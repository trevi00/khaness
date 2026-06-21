#!/usr/bin/env python3
"""Unit + handler-wiring tests for lib/prompt_origin.py — shared system-reinvocation gate.

Locks the STEP 3 generalization (self-verifying-harness): the classifier
extracted from debate_trigger is now the single source of truth, and
mode_detector + skill_match are wired to it so a harness re-invocation
(<task-notification> …) never produces a content-derived advisory/injection.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.prompt_origin import (  # noqa: E402
    SYSTEM_REINVOCATION_PREFIXES,
    is_system_reinvocation,
)

_TASK_NOTIF = "<task-notification>"


# === core classifier ===

def test_leading_marker_is_system():
    assert is_system_reinvocation(f"{_TASK_NOTIF} <task-id>abc</task-id> done")
    assert is_system_reinvocation(f"   \n  {_TASK_NOTIF} whitespace-tolerant")


def test_empty_or_user_prompt_not_system():
    assert not is_system_reinvocation("")
    assert not is_system_reinvocation("   \n   ")
    assert not is_system_reinvocation("아키텍처 리팩토링 구조 설계 어떻게 하지")


def test_mid_text_mention_not_system():
    # a genuine user prompt that merely MENTIONS the marker mid-text is user intent
    assert not is_system_reinvocation(f"explain the {_TASK_NOTIF} schema please")


def test_prefixes_is_single_source_tuple():
    assert isinstance(SYSTEM_REINVOCATION_PREFIXES, tuple)
    assert _TASK_NOTIF in SYSTEM_REINVOCATION_PREFIXES


# === debate_trigger re-export compatibility (its call site + existing tests rely on it) ===

def test_debate_trigger_reexports_shared_gate():
    from handlers.prompt import debate_trigger as dt
    assert dt._is_system_reinvocation(f"{_TASK_NOTIF} x")
    assert not dt._is_system_reinvocation("normal user prompt")
    # same object identity → genuinely the shared function, not a divergent copy
    assert dt._is_system_reinvocation is is_system_reinvocation
    assert dt._SYSTEM_REINVOCATION_PREFIXES is SYSTEM_REINVOCATION_PREFIXES


# === handler harness helpers ===

def _run_main_capture(module, prompt, cwd=""):
    """Feed a hook payload via stdin, run module.main(), capture (exit_code, stdout)."""
    payload = json.dumps({"prompt": prompt, "cwd": cwd})
    saved_stdin = sys.stdin
    sys.stdin = io.StringIO(payload)
    buf = io.StringIO()
    code = 0
    try:
        with redirect_stdout(buf):
            try:
                module.main()
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 0
    finally:
        sys.stdin = saved_stdin
    return code, buf.getvalue()


class _TelemetryIsolation:
    """Redirect lib.logging.TELEMETRY_DIR to a temp dir so handler telemetry
    writes never touch production state (the systemic gap STEP 4 generalizes)."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self._saved = None

    def __enter__(self):
        from lib import logging as L
        self._saved = L.TELEMETRY_DIR
        L.TELEMETRY_DIR = self.tmp / "telemetry"
        return self

    def __exit__(self, *exc):
        from lib import logging as L
        L.TELEMETRY_DIR = self._saved
        return False


# === mode_detector gate (real end-to-end on a live handler) ===

def test_mode_detector_gates_system_prompt():
    from handlers.prompt import mode_detector as md
    with tempfile.TemporaryDirectory() as td:
        with _TelemetryIsolation(Path(td)):
            # user prompt carrying mode keywords → suggestion IS emitted
            code_u, out_u = _run_main_capture(md, "ultrathink and ouroboros please")
            assert code_u == 0
            assert "<mode-trigger-suggestion>" in out_u
            # identical keywords but as a system re-invocation → gated, no emission
            code_s, out_s = _run_main_capture(
                md, f"{_TASK_NOTIF} ultrathink ouroboros deepsearch"
            )
            assert code_s == 0
            assert out_s.strip() == ""


# === skill_match gate (hermetic: prove the skills scan is short-circuited) ===

def test_skill_match_gate_skips_scan_on_system():
    from handlers.prompt import skill_match as sm
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / ".claude" / "skills").mkdir(parents=True)
        called: list = []

        def _recorder(skills_dir, active_paths=None):
            called.append(skills_dir)
            return []

        saved = {
            "collect": sm.collect_skill_files,
            "pipeline": sm.detect_pipeline_skills,
            "tech": sm.load_tech_stack,
            "ptype": sm.detect_project_type,
            "USERPROFILE": os.environ.get("USERPROFILE"),
        }
        sm.collect_skill_files = _recorder
        sm.detect_pipeline_skills = lambda cwd: ([], None, None)
        sm.load_tech_stack = lambda cwd: None
        sm.detect_project_type = lambda cwd: set()
        os.environ["USERPROFILE"] = str(tmp)
        try:
            with _TelemetryIsolation(tmp):
                # system re-invocation → gate exits BEFORE the skills scan
                called.clear()
                code_s, out_s = _run_main_capture(
                    sm, f"{_TASK_NOTIF} pat:: pat:in advanced type patterns"
                )
                assert code_s == 0
                assert out_s.strip() == ""
                assert called == [], "scan must be short-circuited for system prompts"
                # user prompt → the scan IS reached (recorder invoked once)
                called.clear()
                _run_main_capture(sm, "advanced type patterns please")
                assert len(called) == 1, "user prompts must reach the skills scan"
        finally:
            sm.collect_skill_files = saved["collect"]
            sm.detect_pipeline_skills = saved["pipeline"]
            sm.load_tech_stack = saved["tech"]
            sm.detect_project_type = saved["ptype"]
            if saved["USERPROFILE"] is None:
                os.environ.pop("USERPROFILE", None)
            else:
                os.environ["USERPROFILE"] = saved["USERPROFILE"]


def main() -> int:
    tests = [
        test_leading_marker_is_system,
        test_empty_or_user_prompt_not_system,
        test_mid_text_mention_not_system,
        test_prefixes_is_single_source_tuple,
        test_debate_trigger_reexports_shared_gate,
        test_mode_detector_gates_system_prompt,
        test_skill_match_gate_skips_scan_on_system,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            import traceback
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failed += 1
    if failed == 0:
        print(f"[OK] {len(tests)} tests passed")
        return 0
    print(f"[FAIL] {failed}/{len(tests)} tests failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
