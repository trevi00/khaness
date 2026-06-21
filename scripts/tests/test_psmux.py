#!/usr/bin/env python3
"""Tests for lib/psmux.py — terminal multiplexer wrapper.

Closes vision items #11 (psmux 세션 분리 + 살려두기) and #12 (multi-pane).

Tests are skipped when psmux/pmux/tmux is not installed (fail-soft for
CI environments without a multiplexer). Each test is self-contained and
cleans up its sessions; namespace prefix `harness-test-` reduces collision
with user sessions.

Coverage:
  - which: returns binary path or None
  - new_session/has_session/kill_session round-trip
  - list_sessions includes created session
  - list_panes returns at least one pane id
  - send_keys + capture_pane: round-trip text through a pane
  - ensure_session idempotency (existing → True, no clobber)
  - run_session_with_command: spawns + returns False on existing
  - missing-name fail-soft (empty/None args return False without crash)
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import psmux  # noqa: E402


# Skip flag — set once at module load
_PSMUX_AVAILABLE = psmux.which() is not None


def _unique_session_name(prefix: str = "harness-test") -> str:
    """Random-suffix session name to avoid collisions across parallel test runs."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _safe_kill(name: str) -> None:
    """Best-effort cleanup; ignore failures (test should leave clean state)."""
    try:
        psmux.kill_session(name)
    except Exception:
        pass


# ---------- which / availability ----------

def test_which_returns_path_when_installed():
    if not _PSMUX_AVAILABLE:
        return  # SKIP semantic for env without multiplexer
    path = psmux.which()
    assert path is not None
    assert isinstance(path, str)
    assert len(path) > 0


def test_which_returns_none_concept():
    """Smoke: which() returns either a string or None (never crashes)."""
    result = psmux.which()
    assert result is None or isinstance(result, str)


# ---------- session lifecycle ----------

def test_has_session_returns_false_for_empty_name():
    assert psmux.has_session("") is False


def test_has_session_returns_false_for_nonexistent():
    if not _PSMUX_AVAILABLE:
        return
    assert psmux.has_session("definitely-does-not-exist-zzz-99999") is False


def test_new_session_creates_and_kill_removes():
    if not _PSMUX_AVAILABLE:
        return
    name = _unique_session_name()
    try:
        assert psmux.new_session(name, detached=True) is True
        assert psmux.has_session(name) is True
    finally:
        psmux.kill_session(name)
    assert psmux.has_session(name) is False


def test_new_session_rejects_empty_name():
    assert psmux.new_session("") is False


def test_kill_session_returns_false_for_nonexistent():
    if not _PSMUX_AVAILABLE:
        return
    assert psmux.kill_session("nonexistent-zzz-99999") is False


def test_kill_session_rejects_empty_name():
    assert psmux.kill_session("") is False


def test_list_sessions_includes_created_session():
    if not _PSMUX_AVAILABLE:
        return
    name = _unique_session_name()
    try:
        psmux.new_session(name, detached=True)
        sessions = psmux.list_sessions()
        assert name in sessions, f"created {name} not in {sessions}"
    finally:
        _safe_kill(name)


# ---------- pane operations ----------

def test_list_panes_returns_at_least_one_for_new_session():
    if not _PSMUX_AVAILABLE:
        return
    name = _unique_session_name()
    try:
        psmux.new_session(name, detached=True)
        panes = psmux.list_panes(name)
        assert len(panes) >= 1
        assert all(p.startswith("%") for p in panes)
    finally:
        _safe_kill(name)


def test_list_panes_rejects_empty_target():
    assert psmux.list_panes("") == []


def test_send_keys_rejects_empty_args():
    assert psmux.send_keys("", "text") is False
    assert psmux.send_keys("target", "") is False


def test_send_keys_round_trip_via_capture_pane():
    """Round-trip: send_keys → capture_pane returns the typed text.

    PowerShell on Windows takes 1-3 seconds to reach the interactive prompt
    after psmux session creation. Poll capture_pane until the marker appears
    or a 5-second budget elapses. Failure mode = environment issue, not
    code defect; flagged as deterministic-after-warmup.
    """
    if not _PSMUX_AVAILABLE:
        return
    name = _unique_session_name()
    marker = f"AUTOPILOT-MARKER-{uuid.uuid4().hex[:6]}"
    try:
        psmux.new_session(name, detached=True)
        # Wait for the shell to reach its prompt before sending keys
        deadline_prompt = time.monotonic() + 5.0
        panes: list[str] = []
        while time.monotonic() < deadline_prompt:
            panes = psmux.list_panes(name)
            if panes:
                break
            time.sleep(0.1)
        assert panes, "no panes after new_session within 5s"

        # Additional warmup: send keys only once the shell prompt is visible.
        # Look for typical prompt indicators ('>', 'PS') in the captured output.
        deadline_warmup = time.monotonic() + 5.0
        while time.monotonic() < deadline_warmup:
            buf = psmux.capture_pane(panes[0]) or ""
            if "PS " in buf or buf.rstrip().endswith(">"):
                break
            time.sleep(0.2)

        ok = psmux.send_keys(panes[0], marker, literal=True, send_enter=False)
        assert ok is True

        # Poll until marker appears in pane buffer or 3s budget exhausted
        deadline_marker = time.monotonic() + 3.0
        captured: str | None = None
        while time.monotonic() < deadline_marker:
            captured = psmux.capture_pane(panes[0])
            if captured and marker in captured:
                break
            time.sleep(0.15)
        assert captured is not None
        assert marker in captured, (
            f"marker not in capture (likely shell-startup race on this host): "
            f"tail={(captured or '')[-200:]!r}"
        )
    finally:
        _safe_kill(name)


def test_capture_pane_rejects_empty_target():
    assert psmux.capture_pane("") is None


def test_capture_pane_clamps_max_lines():
    if not _PSMUX_AVAILABLE:
        return
    name = _unique_session_name()
    try:
        psmux.new_session(name, detached=True)
        panes = psmux.list_panes(name)
        cap = psmux.capture_pane(panes[0], max_lines=5)
        assert cap is not None
        assert len(cap.splitlines()) <= 5
    finally:
        _safe_kill(name)


# ---------- high-level helpers ----------

def test_ensure_session_returns_true_when_session_exists():
    if not _PSMUX_AVAILABLE:
        return
    name = _unique_session_name()
    try:
        psmux.new_session(name, detached=True)
        # Pre-existing → ensure_session returns True without clobbering
        assert psmux.ensure_session(name) is True
        assert psmux.has_session(name) is True
    finally:
        _safe_kill(name)


def test_ensure_session_creates_when_absent():
    if not _PSMUX_AVAILABLE:
        return
    name = _unique_session_name()
    try:
        assert psmux.has_session(name) is False
        assert psmux.ensure_session(name) is True
        assert psmux.has_session(name) is True
    finally:
        _safe_kill(name)


def test_run_session_with_command_returns_false_on_existing():
    if not _PSMUX_AVAILABLE:
        return
    name = _unique_session_name()
    try:
        psmux.new_session(name, detached=True)
        # Already exists — run_session_with_command refuses (no clobber)
        assert psmux.run_session_with_command(name, "echo hi") is False
    finally:
        _safe_kill(name)


# ---------- split_window ----------

def test_split_window_creates_second_pane():
    if not _PSMUX_AVAILABLE:
        return
    name = _unique_session_name()
    try:
        psmux.new_session(name, detached=True)
        time.sleep(0.2)
        before = len(psmux.list_panes(name))
        ok = psmux.split_window(name, horizontal=True)
        assert ok is True
        time.sleep(0.2)
        after = len(psmux.list_panes(name))
        assert after == before + 1
    finally:
        _safe_kill(name)


def test_split_window_rejects_empty_target():
    assert psmux.split_window("") is False


TESTS = [
    test_which_returns_path_when_installed,
    test_which_returns_none_concept,
    test_has_session_returns_false_for_empty_name,
    test_has_session_returns_false_for_nonexistent,
    test_new_session_creates_and_kill_removes,
    test_new_session_rejects_empty_name,
    test_kill_session_returns_false_for_nonexistent,
    test_kill_session_rejects_empty_name,
    test_list_sessions_includes_created_session,
    test_list_panes_returns_at_least_one_for_new_session,
    test_list_panes_rejects_empty_target,
    test_send_keys_rejects_empty_args,
    test_send_keys_round_trip_via_capture_pane,
    test_capture_pane_rejects_empty_target,
    test_capture_pane_clamps_max_lines,
    test_ensure_session_returns_true_when_session_exists,
    test_ensure_session_creates_when_absent,
    test_run_session_with_command_returns_false_on_existing,
    test_split_window_creates_second_pane,
    test_split_window_rejects_empty_target,
]


def main() -> int:
    if not _PSMUX_AVAILABLE:
        print("  [SKIP-SUITE] psmux/pmux/tmux not in PATH — multiplexer round-trip tests NOT exercised (run_units tallies this as skipped, not passed)")
        # Run only the non-skipped tests (those that test None/empty paths)
        runnable = [
            test_which_returns_none_concept,
            test_has_session_returns_false_for_empty_name,
            test_new_session_rejects_empty_name,
            test_kill_session_rejects_empty_name,
            test_list_panes_rejects_empty_target,
            test_send_keys_rejects_empty_args,
            test_capture_pane_rejects_empty_target,
            test_split_window_rejects_empty_target,
        ]
    else:
        runnable = TESTS

    failed = 0
    for fn in runnable:
        try:
            fn()
            print(f"  [OK] {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  [ERROR] {fn.__name__}: {type(e).__name__}: {e}")
    if failed:
        print(f"\n[FAIL] {failed}/{len(runnable)} tests failed")
        return 1
    print(f"\n[OK] {len(runnable)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
