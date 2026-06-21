#!/usr/bin/env python3
"""Tests for lib.agent_depth + lib.budget + handlers/pre_tool/agent_depth_guard (v15.20 B).

Coverage:
  agent_depth:
    - current_depth: env unset → 0, set int → that value, invalid → 0
    - next_depth: +1
    - would_exceed_cap: depth=2 → false (next=3 ≤ 3), depth=3 → true (next=4 > 3)
  budget:
    - record_invocation: 누적 chars + count + last_ts
    - get_total_chars / get_invocation_count: read accuracy
    - exceeded: cap 비교
    - reset: file unlink
    - sid path-traversal guard
  agent_depth_guard hook:
    - Non-Agent → silent
    - Agent + within cap → silent
    - Agent + exceeds cap → deny + reason
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import agent_depth as AD  # noqa: E402
from lib import budget as BG  # noqa: E402

_HOOK = _SCRIPTS / "handlers" / "pre_tool" / "agent_depth_guard.py"


# ---- agent_depth ----

def test_current_depth_unset_is_zero():
    os.environ.pop("ORCH_DEPTH", None)
    assert AD.current_depth() == 0


def test_current_depth_invalid_is_zero():
    os.environ["ORCH_DEPTH"] = "abc"
    try:
        assert AD.current_depth() == 0
    finally:
        os.environ.pop("ORCH_DEPTH", None)


def test_current_depth_negative_clamped_to_zero():
    os.environ["ORCH_DEPTH"] = "-5"
    try:
        assert AD.current_depth() == 0
    finally:
        os.environ.pop("ORCH_DEPTH", None)


def test_would_exceed_cap_at_boundaries():
    for d, exceed in [(0, False), (1, False), (2, False), (3, True), (4, True)]:
        os.environ["ORCH_DEPTH"] = str(d)
        try:
            assert AD.would_exceed_cap() is exceed, f"depth={d}"
        finally:
            os.environ.pop("ORCH_DEPTH", None)


def test_next_depth_is_plus_one():
    os.environ["ORCH_DEPTH"] = "2"
    try:
        assert AD.next_depth() == 3
    finally:
        os.environ.pop("ORCH_DEPTH", None)


# ---- budget ----

def test_record_and_read_round_trip():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        BG.record_invocation("sid-1", "hello world", base_dir=base)
        BG.record_invocation("sid-1", "again", base_dir=base)
        assert BG.get_total_chars("sid-1", base_dir=base) == len("hello world") + len("again")
        assert BG.get_invocation_count("sid-1", base_dir=base) == 2


def test_record_nonstring_is_zero_chars():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        BG.record_invocation("sid-2", None, base_dir=base)
        assert BG.get_total_chars("sid-2", base_dir=base) == 0
        assert BG.get_invocation_count("sid-2", base_dir=base) == 1


def test_exceeded_with_cap():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        BG.record_invocation("sid-3", "x" * 100, base_dir=base)
        assert BG.exceeded("sid-3", cap=50, base_dir=base) is True
        assert BG.exceeded("sid-3", cap=200, base_dir=base) is False


def test_reset_removes_state():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        BG.record_invocation("sid-4", "abc", base_dir=base)
        assert BG.get_total_chars("sid-4", base_dir=base) == 3
        BG.reset("sid-4", base_dir=base)
        assert BG.get_total_chars("sid-4", base_dir=base) == 0


def test_sid_path_traversal_guard_rejects_only_unsafe_chars():
    """The sid guard SANITIZES (keeps only [alnum._-]) — it does NOT raise on a
    traversal-shaped sid; instead the unsafe chars are stripped so the file stays inside
    base. It raises ValueError only when the sid has ZERO safe chars. (M26: hardened from a
    `try/except: pass` that could not fail and mis-documented the behavior as ValueError.)"""
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        # "../escape": '/' stripped → lands at budgets/..escape.json INSIDE base, no traversal.
        BG.record_invocation("../escape", "x", base_dir=base)
        written = [p for p in base.rglob("*.json") if p.is_file()]
        assert written, "sanitized sid must still write a budget file"
        for p in written:
            assert base.resolve() in p.resolve().parents, f"sanitized file escaped base: {p}"
        assert not any(
            "escape" in c.name.lower()
            for c in base.parent.iterdir() if c.resolve() != base.resolve()
        ), "no file may escape the base dir via traversal"
        # A sid with ZERO safe chars IS the actual ValueError condition.
        raised = False
        try:
            BG.record_invocation("/<>:|", "x", base_dir=base)
        except ValueError:
            raised = True
        assert raised, "sid with no safe chars must raise ValueError"
        # A normal sid passes.
        BG.record_invocation("debate-1234-abc", "x", base_dir=base)


def test_unknown_sid_returns_zero():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        assert BG.get_total_chars("never-recorded", base_dir=base) == 0
        assert BG.get_invocation_count("never-recorded", base_dir=base) == 0


# ---- depth guard hook (subprocess) ----

def _invoke_depth_guard(payload, env_overrides=None, raw_input=None):
    env = os.environ.copy()
    env.pop("ORCH_DEPTH", None)
    if env_overrides:
        env.update(env_overrides)
    input_text = raw_input if raw_input is not None else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=15,
    )


def test_hook_non_agent_is_silent():
    res = _invoke_depth_guard({"tool_name": "Read", "tool_input": {"file_path": "x"}})
    assert res.returncode == 0
    assert res.stdout == ""


def test_hook_within_cap_is_silent():
    """depth=2 → next=3 ≤ cap(3) → silent pass."""
    res = _invoke_depth_guard(
        {"tool_name": "Agent", "tool_input": {"subagent_type": "x", "prompt": "p"}},
        env_overrides={"ORCH_DEPTH": "2"},
    )
    assert res.returncode == 0
    assert res.stdout == ""


def test_hook_exceeds_cap_returns_deny():
    """depth=3 → next=4 > cap(3) → deny."""
    res = _invoke_depth_guard(
        {"tool_name": "Agent", "tool_input": {"subagent_type": "x", "prompt": "p"}},
        env_overrides={"ORCH_DEPTH": "3"},
    )
    assert res.returncode == 0
    parsed = json.loads(res.stdout)
    decision = parsed["hookSpecificOutput"]["permissionDecision"]
    assert decision == "deny"
    reason = parsed["hookSpecificOutput"]["permissionDecisionReason"]
    assert "depth cap" in reason or "depth" in reason


def test_hook_fail_soft_on_malformed_payload():
    res = _invoke_depth_guard({}, raw_input="not-json")
    assert res.returncode == 0
    assert res.stdout == ""


TESTS = [
    test_current_depth_unset_is_zero,
    test_current_depth_invalid_is_zero,
    test_current_depth_negative_clamped_to_zero,
    test_would_exceed_cap_at_boundaries,
    test_next_depth_is_plus_one,
    test_record_and_read_round_trip,
    test_record_nonstring_is_zero_chars,
    test_exceeded_with_cap,
    test_reset_removes_state,
    test_sid_path_traversal_guard_rejects_only_unsafe_chars,
    test_unknown_sid_returns_zero,
    test_hook_non_agent_is_silent,
    test_hook_within_cap_is_silent,
    test_hook_exceeds_cap_returns_deny,
    test_hook_fail_soft_on_malformed_payload,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
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
        print(f"\n[FAIL] {failed}/{len(TESTS)} tests failed")
        return 1
    print(f"\n[OK] {len(TESTS)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
