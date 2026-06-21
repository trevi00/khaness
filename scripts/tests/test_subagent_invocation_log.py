#!/usr/bin/env python3
"""Tests for lib/subagent_invocation_log.py — audit trail for subagent dispatches.

Closes the OS-isolation residual via detection-side reinforcement: every
invocation written here can be retrospectively grepped for forensics, even
if claude-code's platform-level isolation is not OS-enforced.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _redirect_state_dir(tmp: Path) -> None:
    """Mutate the module-local STATE_DIR symbol so writes go to tmp."""
    from lib import paths as P
    from lib import subagent_invocation_log as M
    P.STATE_DIR = tmp
    # The module captured STATE_DIR at import — re-bind explicitly.
    M.STATE_DIR = tmp
    tmp.mkdir(parents=True, exist_ok=True)


def test_record_invocation_writes_jsonl_record():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import record_invocation, session_log_path
        path = record_invocation(
            "debate-1778500000-abc123",
            "harness-critic",
            ["Read", "Grep", "WebFetch"],
        )
        assert path == session_log_path("debate-1778500000-abc123")
        assert path.exists()
        line = path.read_text(encoding="utf-8").strip()
        rec = json.loads(line)
        assert rec["sid"] == "debate-1778500000-abc123"
        assert rec["agent"] == "harness-critic"
        assert rec["tools"] == ["Grep", "Read", "WebFetch"]  # sorted
        assert "ts" in rec  # injected by jsonl_append


def test_record_invocation_appends_in_order():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import record_invocation, list_invocations
        record_invocation("debate-test-001", "harness-planner", ["Read"], generation=1)
        record_invocation("debate-test-001", "harness-critic", ["Read", "WebFetch"], generation=1)
        record_invocation("debate-test-001", "harness-architect", ["Read", "WebFetch"], generation=1)
        records = list_invocations("debate-test-001")
        assert len(records) == 3
        assert [r["agent"] for r in records] == [
            "harness-planner", "harness-critic", "harness-architect",
        ]


def test_record_invocation_optional_fields():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import record_invocation, list_invocations
        record_invocation(
            "debate-opt-001", "harness-critic", ["WebFetch"],
            generation=2, role="critic", extra={"caller": "autopilot-phase-0"},
        )
        rec = list_invocations("debate-opt-001")[0]
        assert rec["generation"] == 2
        assert rec["role"] == "critic"
        assert rec["extra"] == {"caller": "autopilot-phase-0"}


def test_record_invocation_handles_empty_tools():
    """An agent with no frontmatter tools field should still be recordable."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import record_invocation, list_invocations
        record_invocation("debate-empty-tools", "harness-x", [])
        rec = list_invocations("debate-empty-tools")[0]
        assert rec["tools"] == []


def test_record_invocation_dedupes_and_sorts_tools():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import record_invocation, list_invocations
        record_invocation(
            "debate-dedupe", "harness-x",
            ["WebFetch", "Read", "WebFetch", "  Grep  ", ""],
        )
        rec = list_invocations("debate-dedupe")[0]
        assert rec["tools"] == ["Grep", "Read", "WebFetch"]


def test_invalid_sid_rejected():
    from lib.subagent_invocation_log import record_invocation
    for bad in ("../escape", "a/b", "a\\b", "", "with space", "with$dollar"):
        try:
            record_invocation(bad, "harness-x", ["Read"])
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError on sid={bad!r}")


def test_invalid_agent_name_rejected():
    from lib.subagent_invocation_log import record_invocation
    for bad in ("../escape", "a/b", "a\\b", ""):
        try:
            record_invocation("debate-test-001", bad, ["Read"])
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError on agent={bad!r}")


def test_list_invocations_missing_sid_returns_empty():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import list_invocations
        assert list_invocations("debate-never-recorded") == []


def test_list_invocations_skips_corrupt_lines():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import (
            record_invocation, list_invocations, session_log_path,
        )
        record_invocation("debate-corrupt", "harness-x", ["Read"])
        path = session_log_path("debate-corrupt")
        with path.open("a", encoding="utf-8") as f:
            f.write("not-json-at-all\n")
            f.write('{"agent": "harness-y", "tools": []}\n')
        records = list_invocations("debate-corrupt")
        assert len(records) == 2  # corrupt skipped, two valid kept
        assert records[0]["agent"] == "harness-x"
        assert records[1]["agent"] == "harness-y"


def test_search_by_agent_finds_across_sids():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import record_invocation, search_by_agent
        record_invocation("debate-001", "harness-critic", ["WebFetch"])
        record_invocation("debate-002", "harness-planner", ["WebFetch"])
        record_invocation("debate-002", "harness-critic", ["WebFetch"])
        record_invocation("orch-003", "harness-evaluator", ["Read"])
        critic_invocations = search_by_agent("harness-critic")
        assert len(critic_invocations) == 2
        assert all(r["agent"] == "harness-critic" for r in critic_invocations)
        # Sids appear in alphabetical order: debate-001, debate-002
        assert [r["sid"] for r in critic_invocations] == ["debate-001", "debate-002"]


def test_search_by_agent_filters_by_timestamp():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import record_invocation, search_by_agent
        record_invocation("debate-time-001", "harness-critic", ["WebFetch"])
        # Past cutoff
        past = search_by_agent("harness-critic", since_ts="2099-01-01T00:00:00Z")
        assert past == []
        # Future cutoff (record's ts > 2000)
        future = search_by_agent("harness-critic", since_ts="2000-01-01T00:00:00Z")
        assert len(future) == 1


def test_search_by_agent_until_ts_excludes_future_records():
    """until_ts is exclusive upper bound — records at-or-after it are skipped."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import record_invocation, search_by_agent
        record_invocation("debate-until-001", "harness-critic", ["WebFetch"])
        # Past upper bound — record's ts > 2000-01-01 → excluded
        old_only = search_by_agent("harness-critic", until_ts="2000-01-01T00:00:00Z")
        assert old_only == []
        # Future upper bound — record falls within window → included
        all_recent = search_by_agent("harness-critic", until_ts="2099-01-01T00:00:00Z")
        assert len(all_recent) == 1


def test_search_by_agent_window_both_bounds():
    """since_ts <= ts < until_ts — half-open window with both ends."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import record_invocation, search_by_agent
        record_invocation("debate-window-001", "harness-critic", ["WebFetch"])
        # Window covering 2026 era (the record's ts is now → 2026)
        wide = search_by_agent(
            "harness-critic",
            since_ts="2000-01-01T00:00:00Z",
            until_ts="2099-01-01T00:00:00Z",
        )
        assert len(wide) == 1


def test_search_by_agent_empty_window_returns_empty():
    """since_ts >= until_ts → no record can match → []."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import record_invocation, search_by_agent
        record_invocation("debate-empty-window", "harness-critic", ["WebFetch"])
        # since == until (degenerate)
        result = search_by_agent(
            "harness-critic",
            since_ts="2026-01-01T00:00:00Z",
            until_ts="2026-01-01T00:00:00Z",
        )
        assert result == []
        # since > until (inverted)
        result_inv = search_by_agent(
            "harness-critic",
            since_ts="2099-01-01T00:00:00Z",
            until_ts="2000-01-01T00:00:00Z",
        )
        assert result_inv == []


def test_search_by_agent_empty_when_no_records():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import search_by_agent
        assert search_by_agent("harness-critic") == []


def test_list_sessions_returns_empty_when_no_dir():
    """Pre-first-invocation install — no dir yet, empty list, no exception."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import list_sessions
        assert list_sessions() == []


def test_list_sessions_returns_recorded_sids_sorted():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import record_invocation, list_sessions
        # Insert in non-sorted order to verify output is sorted
        record_invocation("orch-2", "harness-x", ["Read"])
        record_invocation("debate-1", "harness-y", ["Read"])
        record_invocation("ralph-3", "harness-z", ["Read"])
        sids = list_sessions()
        assert sids == ["debate-1", "orch-2", "ralph-3"]


def test_list_sessions_excludes_unlinked_files():
    """GC-removed sids do not appear (only file presence counts)."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import (
            record_invocation, list_sessions, session_log_path,
        )
        record_invocation("debate-keep", "harness-x", ["Read"])
        record_invocation("debate-purge", "harness-y", ["Read"])
        # Simulate GC removal of one
        session_log_path("debate-purge").unlink()
        assert list_sessions() == ["debate-keep"]


def test_origin_constants_exposed():
    """E8 closure 2026-05-10: origin string literals centralized."""
    from lib.subagent_invocation_log import (
        ORIGIN_HOOK, ORIGIN_DIRECTIVE, ORIGIN_MANUAL, ORIGIN_VALUES,
    )
    assert ORIGIN_HOOK == "hook"
    assert ORIGIN_DIRECTIVE == "directive"
    assert ORIGIN_MANUAL == "manual"
    assert ORIGIN_VALUES == frozenset({"hook", "directive", "manual"})


def test_record_invocation_accepts_tools_none():
    """E12 closure: tools=None is normalized to [] (hook fallback path)."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import record_invocation, list_invocations
        record_invocation("debate-none", "harness-x", None)
        rec = list_invocations("debate-none")[0]
        assert rec["tools"] == []


def test_record_invocation_accepts_valid_origin():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import (
            record_invocation, list_invocations, ORIGIN_HOOK,
            ORIGIN_DIRECTIVE, ORIGIN_MANUAL,
        )
        for origin in (ORIGIN_HOOK, ORIGIN_DIRECTIVE, ORIGIN_MANUAL):
            sid = f"debate-origin-{origin}"
            record_invocation(sid, "harness-x", ["Read"], extra={"origin": origin})
            rec = list_invocations(sid)[0]
            assert rec["extra"]["origin"] == origin


def test_record_invocation_rejects_invalid_origin():
    """E8 closure: typo in origin must surface as ValueError, not silent."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import record_invocation
        for bad in ("hookk", "directve", "HOOK", "user", ""):
            try:
                record_invocation(
                    "debate-origin-bad", "harness-x", ["Read"],
                    extra={"origin": bad},
                )
            except ValueError:
                continue
            raise AssertionError(f"expected ValueError on origin={bad!r}")


def test_search_by_agent_filters_by_origin():
    """E5 closure 2026-05-10: origin filter pulls only that surface's records."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import (
            record_invocation, search_by_agent,
            ORIGIN_HOOK, ORIGIN_DIRECTIVE,
        )
        record_invocation("debate-1", "harness-critic", ["WebFetch"],
                          extra={"origin": ORIGIN_HOOK})
        record_invocation("debate-1", "harness-critic", ["WebFetch"],
                          extra={"origin": ORIGIN_DIRECTIVE})
        record_invocation("debate-1", "harness-critic", ["WebFetch"])  # untagged
        hook_only = search_by_agent("harness-critic", origin=ORIGIN_HOOK)
        directive_only = search_by_agent("harness-critic", origin=ORIGIN_DIRECTIVE)
        all_recs = search_by_agent("harness-critic")  # no filter
        assert len(hook_only) == 1
        assert len(directive_only) == 1
        assert len(all_recs) == 3
        assert hook_only[0]["extra"]["origin"] == "hook"
        assert directive_only[0]["extra"]["origin"] == "directive"


def test_search_by_agent_invalid_origin_filter_raises():
    from lib.subagent_invocation_log import search_by_agent
    try:
        search_by_agent("harness-critic", origin="bogus")
    except ValueError:
        return
    raise AssertionError("expected ValueError on bogus origin filter")


def test_sids_in_window_returns_sorted_unique():
    """E6 closure 2026-05-10."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import (
            record_invocation, sids_in_window,
        )
        record_invocation("orch-z", "harness-x", ["Read"])
        record_invocation("debate-a", "harness-y", ["Read"])
        record_invocation("orch-z", "harness-x", ["Read"])  # dedup test
        sids = sids_in_window()
        assert sids == ["debate-a", "orch-z"]


def test_sids_in_window_filters_by_window():
    """Wide window includes; pre-cutoff window excludes."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import (
            record_invocation, sids_in_window,
        )
        record_invocation("debate-w", "harness-x", ["Read"])
        wide = sids_in_window(since_ts="2000-01-01T00:00:00Z",
                              until_ts="2099-01-01T00:00:00Z")
        assert wide == ["debate-w"]
        old_only = sids_in_window(until_ts="2000-01-01T00:00:00Z")
        assert old_only == []


def test_sids_in_window_empty_when_inverted_window():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import (
            record_invocation, sids_in_window,
        )
        record_invocation("debate-x", "harness-x", ["Read"])
        result = sids_in_window(
            since_ts="2099-01-01T00:00:00Z",
            until_ts="2000-01-01T00:00:00Z",
        )
        assert result == []


def test_sids_in_window_returns_empty_when_dir_missing():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import sids_in_window
        assert sids_in_window() == []


def test_session_log_path_uses_state_dir():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import session_log_path
        path = session_log_path("debate-path-test")
        assert path == Path(td) / "subagent_invocations" / "debate-path-test.jsonl"


def test_gc_old_logs_removes_stale_files():
    """Files older than retention_days must be unlinked."""
    import os
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import (
            record_invocation, gc_old_logs, session_log_path,
        )
        record_invocation("debate-old-001", "harness-x", ["Read"])
        path = session_log_path("debate-old-001")
        # Backdate by 31 days
        old_ts = path.stat().st_mtime - (31 * 86400)
        os.utime(path, (old_ts, old_ts))

        removed = gc_old_logs(retention_days=30)
        assert removed == 1
        assert not path.exists()


def test_gc_old_logs_keeps_fresh_files():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import (
            record_invocation, gc_old_logs, session_log_path,
        )
        record_invocation("debate-fresh-001", "harness-x", ["Read"])
        path = session_log_path("debate-fresh-001")
        # Default mtime ≈ now → should NOT be reclaimed
        removed = gc_old_logs(retention_days=30)
        assert removed == 0
        assert path.exists()


def test_gc_old_logs_zero_retention_short_circuits():
    """retention_days<=0 returns 0 immediately with no scan."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import (
            record_invocation, gc_old_logs,
        )
        record_invocation("debate-zero-001", "harness-x", ["Read"])
        assert gc_old_logs(retention_days=0) == 0
        assert gc_old_logs(retention_days=-1) == 0


def test_gc_old_logs_returns_zero_when_dir_missing():
    """No subagent_invocations/ dir yet — defensive zero, no exception."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import gc_old_logs
        # Don't record anything; dir doesn't exist
        assert gc_old_logs(retention_days=30) == 0


def test_gc_old_logs_uses_explicit_now_for_determinism():
    """Passing now=<float> overrides time.time() — test fixture friendly."""
    import os
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.subagent_invocation_log import (
            record_invocation, gc_old_logs, session_log_path,
        )
        record_invocation("debate-now-001", "harness-x", ["Read"])
        path = session_log_path("debate-now-001")
        # File mtime is "now". Pass a now value 31 days in the future →
        # the file becomes stale.
        future_now = path.stat().st_mtime + (31 * 86400)
        removed = gc_old_logs(now=future_now, retention_days=30)
        assert removed == 1


TESTS = [
    test_record_invocation_writes_jsonl_record,
    test_record_invocation_appends_in_order,
    test_record_invocation_optional_fields,
    test_record_invocation_handles_empty_tools,
    test_record_invocation_dedupes_and_sorts_tools,
    test_invalid_sid_rejected,
    test_invalid_agent_name_rejected,
    test_list_invocations_missing_sid_returns_empty,
    test_list_invocations_skips_corrupt_lines,
    test_search_by_agent_finds_across_sids,
    test_search_by_agent_filters_by_timestamp,
    test_search_by_agent_until_ts_excludes_future_records,
    test_search_by_agent_window_both_bounds,
    test_search_by_agent_empty_window_returns_empty,
    test_search_by_agent_empty_when_no_records,
    test_list_sessions_returns_empty_when_no_dir,
    test_list_sessions_returns_recorded_sids_sorted,
    test_list_sessions_excludes_unlinked_files,
    test_origin_constants_exposed,
    test_record_invocation_accepts_tools_none,
    test_record_invocation_accepts_valid_origin,
    test_record_invocation_rejects_invalid_origin,
    test_search_by_agent_filters_by_origin,
    test_search_by_agent_invalid_origin_filter_raises,
    test_sids_in_window_returns_sorted_unique,
    test_sids_in_window_filters_by_window,
    test_sids_in_window_empty_when_inverted_window,
    test_sids_in_window_returns_empty_when_dir_missing,
    test_session_log_path_uses_state_dir,
    test_gc_old_logs_removes_stale_files,
    test_gc_old_logs_keeps_fresh_files,
    test_gc_old_logs_zero_retention_short_circuits,
    test_gc_old_logs_returns_zero_when_dir_missing,
    test_gc_old_logs_uses_explicit_now_for_determinism,
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
