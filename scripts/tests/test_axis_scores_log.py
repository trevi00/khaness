#!/usr/bin/env python3
"""Unit tests for lib/axis_scores_log.py — D6 axis variance event log."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _redirect_state_dir(tmp: Path):
    from lib import paths as P
    P.STATE_DIR = tmp / "state"
    P.STATE_DIR.mkdir(parents=True, exist_ok=True)


# ---- log_axis_event ----

def test_schema_version_constant():
    from lib.axis_scores_log import SCHEMA_VERSION
    assert SCHEMA_VERSION == "1"


def test_log_axis_event_writes_jsonl_line():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.axis_scores_log import log_axis_event, log_dir
        ok = log_axis_event("orch-test-aaa", {
            "phase": "phase_4",
            "axis": "응집",
            "score": 5,
            "verdict": "approved",
            "model_used": "gpt-5.5",
        })
        assert ok is True
        line = (log_dir("orch-test-aaa") / "axis_scores.jsonl").read_text(encoding="utf-8").strip()
        rec = json.loads(line)
        assert rec["axis"] == "응집"
        assert rec["score"] == 5
        assert rec["schema_version"] == "1"  # auto-injected
        assert "ts" in rec  # auto-injected


def test_log_axis_event_preserves_caller_schema_version():
    """Caller may set their own schema_version (forward-compat); not overwritten."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.axis_scores_log import log_axis_event, log_dir
        log_axis_event("sid-x", {"axis": "결합", "schema_version": "2"})
        line = (log_dir("sid-x") / "axis_scores.jsonl").read_text(encoding="utf-8").strip()
        rec = json.loads(line)
        assert rec["schema_version"] == "2"


def test_log_axis_event_rejects_oversize_line():
    """PIPE_BUF cap reused (4096 bytes)."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.axis_scores_log import log_axis_event
        big = log_axis_event("sid-big", {"axis": "x", "blob": "y" * 5000})
        assert big is False


def test_log_axis_event_rejects_non_dict():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.axis_scores_log import log_axis_event
        try:
            log_axis_event("sid", "not-a-dict")  # type: ignore[arg-type]
        except ValueError:
            return
        raise AssertionError("expected ValueError on non-dict event")


def test_log_axis_event_rejects_empty_sid():
    from lib.axis_scores_log import log_axis_event
    try:
        log_axis_event("", {"axis": "x"})
    except ValueError:
        return
    raise AssertionError("expected ValueError on empty sid")


def test_log_axis_event_appends_multiple_events():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.axis_scores_log import log_axis_event, read_axis_events
        for i in range(3):
            log_axis_event("sid-multi", {"axis": "응집", "score": i + 3})
        events = read_axis_events("sid-multi")
        assert len(events) == 3
        scores = [e["score"] for e in events]
        assert scores == [3, 4, 5]


# ---- read_axis_events ----

def test_read_axis_events_returns_empty_when_no_log():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.axis_scores_log import read_axis_events
        assert read_axis_events("missing") == []


def test_read_axis_events_skips_lines_missing_schema_version():
    """Required field per D6 condition C6."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.axis_scores_log import log_dir, read_axis_events
        d = log_dir("sid-mixed")
        path = d / "axis_scores.jsonl"
        path.write_text(
            json.dumps({"axis": "응집", "score": 5}) + "\n"  # NO schema_version
            + json.dumps({"axis": "결합", "score": 4, "schema_version": "1"}) + "\n",
            encoding="utf-8",
        )
        events = read_axis_events("sid-mixed")
        assert len(events) == 1
        assert events[0]["axis"] == "결합"


def test_read_axis_events_skips_malformed_json():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.axis_scores_log import log_axis_event, read_axis_events, log_dir
        log_axis_event("sid-corrupt", {"axis": "응집"})
        # Append corrupt line
        with open(log_dir("sid-corrupt") / "axis_scores.jsonl", "a",
                  encoding="utf-8") as f:
            f.write("not_json {{{\n")
        events = read_axis_events("sid-corrupt")
        # Original valid event preserved, corrupt skipped
        assert len(events) == 1


# ---- log_verdict_event / has_cross_target_marker (cross-target write side) ----

def test_log_verdict_event_marks_first_cross_target():
    """First genuine LLM verdict on a generator artifact gets the marker."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.axis_scores_log import log_verdict_event, read_axis_events
        ok = log_verdict_event("orch-ct-1", {
            "event": "evaluator_verdict", "verdict": "approved",
            "completeness": True, "phase_id": "phase_3.5",
        })
        assert ok is True
        events = read_axis_events("orch-ct-1")
        assert len(events) == 1
        assert events[0]["cross_target_first_invocation"] is True


def test_log_verdict_event_second_record_not_marked():
    """Re-evaluation within PER_PHASE_EVAL_LIMIT must NOT re-count."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.axis_scores_log import log_verdict_event, read_axis_events
        log_verdict_event("orch-ct-2", {"event": "evaluator_verdict", "verdict": "approved"})
        log_verdict_event("orch-ct-2", {"event": "evaluator_verdict", "verdict": "iterate"})
        events = read_axis_events("orch-ct-2")
        assert len(events) == 2
        marked = [e for e in events if e.get("cross_target_first_invocation") is True]
        assert len(marked) == 1  # exactly the first


def test_log_verdict_event_fallback_not_marked():
    """cross_target=False (legacy fallback, no real LLM E2) → never marked."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.axis_scores_log import log_verdict_event, read_axis_events
        log_verdict_event(
            "orch-ct-3",
            {"event": "evaluator_verdict", "verdict": "iterate", "fallback_reason": "subagent_timeout"},
            cross_target=False,
        )
        events = read_axis_events("orch-ct-3")
        assert len(events) == 1
        assert "cross_target_first_invocation" not in events[0]


def test_log_verdict_event_marks_after_only_fallbacks():
    """A real LLM verdict after prior fallbacks still earns the first marker."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.axis_scores_log import (
            log_verdict_event, has_cross_target_marker, read_axis_events,
        )
        log_verdict_event("orch-ct-4", {"event": "evaluator_verdict", "verdict": "iterate"},
                          cross_target=False)
        assert has_cross_target_marker("orch-ct-4") is False
        log_verdict_event("orch-ct-4", {"event": "evaluator_verdict", "verdict": "approved"})
        assert has_cross_target_marker("orch-ct-4") is True
        events = read_axis_events("orch-ct-4")
        marked = [e for e in events if e.get("cross_target_first_invocation") is True]
        assert len(marked) == 1


def test_has_cross_target_marker_empty_log():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.axis_scores_log import has_cross_target_marker
        assert has_cross_target_marker("orch-ct-missing") is False


def test_log_verdict_event_rejects_non_dict():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.axis_scores_log import log_verdict_event
        try:
            log_verdict_event("sid", "nope")  # type: ignore[arg-type]
        except ValueError:
            return
        raise AssertionError("expected ValueError on non-dict event")


# ---- gc_old_axis_scores ----

def test_gc_removes_old_session_dir():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.axis_scores_log import (
            log_axis_event, gc_old_axis_scores, log_dir, DEFAULT_RETENTION_DAYS,
        )
        log_axis_event("sid-old", {"axis": "응집"})
        # Backdate jsonl mtime past retention
        jsonl = log_dir("sid-old") / "axis_scores.jsonl"
        past = time.time() - (DEFAULT_RETENTION_DAYS + 1) * 86400
        os.utime(jsonl, (past, past))

        removed = gc_old_axis_scores()
        assert removed == 1
        assert not log_dir.__wrapped__ if False else True  # noqa
        from lib.paths import STATE_DIR
        assert not (STATE_DIR / "evaluator" / "sid-old").exists()


def test_gc_keeps_fresh_session_dir():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.axis_scores_log import (
            log_axis_event, gc_old_axis_scores, log_dir,
        )
        log_axis_event("sid-fresh", {"axis": "결합"})
        removed = gc_old_axis_scores()
        assert removed == 0
        assert (log_dir("sid-fresh") / "axis_scores.jsonl").exists()


def test_gc_returns_zero_when_evaluator_dir_missing():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.axis_scores_log import gc_old_axis_scores
        # state/evaluator/ doesn't exist yet
        assert gc_old_axis_scores() == 0


def test_gc_zero_retention_returns_zero():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.axis_scores_log import log_axis_event, gc_old_axis_scores
        log_axis_event("sid-x", {"axis": "응집"})
        # retention=0 means disabled
        assert gc_old_axis_scores(retention_days=0) == 0


def test_session_init_axis_log_gc_helper_removes_old_dir():
    """SessionStart hook wiring: _evaluator_axis_log_gc() prunes old session dirs."""
    import os as _os
    import time as _time
    import tempfile as _tmp
    with _tmp.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.axis_scores_log import (
            log_axis_event, log_dir, DEFAULT_RETENTION_DAYS,
        )
        from handlers.session.init import _evaluator_axis_log_gc
        log_axis_event("orch-old-axis", {"axis": "응집"})
        jsonl = log_dir("orch-old-axis") / "axis_scores.jsonl"
        past = _time.time() - (DEFAULT_RETENTION_DAYS + 1) * 86400
        _os.utime(jsonl, (past, past))

        _evaluator_axis_log_gc()

        from lib.paths import STATE_DIR
        assert not (STATE_DIR / "evaluator" / "orch-old-axis").exists()


TESTS = [
    test_schema_version_constant,
    test_log_axis_event_writes_jsonl_line,
    test_log_axis_event_preserves_caller_schema_version,
    test_log_axis_event_rejects_oversize_line,
    test_log_axis_event_rejects_non_dict,
    test_log_axis_event_rejects_empty_sid,
    test_log_axis_event_appends_multiple_events,
    test_read_axis_events_returns_empty_when_no_log,
    test_read_axis_events_skips_lines_missing_schema_version,
    test_read_axis_events_skips_malformed_json,
    test_log_verdict_event_marks_first_cross_target,
    test_log_verdict_event_second_record_not_marked,
    test_log_verdict_event_fallback_not_marked,
    test_log_verdict_event_marks_after_only_fallbacks,
    test_has_cross_target_marker_empty_log,
    test_log_verdict_event_rejects_non_dict,
    test_gc_removes_old_session_dir,
    test_gc_keeps_fresh_session_dir,
    test_gc_returns_zero_when_evaluator_dir_missing,
    test_gc_zero_retention_returns_zero,
    test_session_init_axis_log_gc_helper_removes_old_dir,
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
