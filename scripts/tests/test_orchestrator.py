#!/usr/bin/env python3
"""Unit tests for engine/orchestrator.py — resumable super-session.

Per debate-1778161608-713bdc Phase 1 implementation. Verifies:
  - new_session creates dir + events.jsonl + initial event
  - load_session resumes from events replay (root phase restored)
  - load_session returns None for missing sid (B5 cold-start tolerance)
  - load_session raises on corrupt child_sids.json (B5 fail-closed)
  - confirm_resume_or_new returns 'resume' on non-TTY (D4b)
  - update_phase appends phase_update event + writes phase-tree.md
  - link_child writes child_sids.json + child_linked event
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


# Captured at import so main() can restore it after the suite. Tests below
# point CLAUDE_HOME at a temp dir; without restore, a later test module that
# resolves CLAUDE_HOME-derived paths would land in a now-deleted directory.
_ORIG_CLAUDE_HOME = os.environ.get("CLAUDE_HOME")


def _redirect_orchestrator_dir(tmp: Path):
    """Isolate every real-state write a test triggers into tmp:
      - state/orchestrator (super-session events) via lib.paths.STATE_DIR
      - the L1 insight-index (~/.claude/memory/insight-index.jsonl) via CLAUDE_HOME

    evaluate_completion appends one insight per terminal verdict ('complete' /
    'escalate') — it is a declared L1 writer. insight_index resolves its path from
    the CLAUDE_HOME env at call time, NOT from lib.paths, so patching only STATE_DIR
    leaves those synthetic records leaking into the PRODUCTION insight-index
    (observed 2026-06-03: burst of orchestrator records polluting
    memory/insight-index.jsonl from run_units). main() restores CLAUDE_HOME after.
    """
    from engine import orchestrator as O
    from lib import paths as P
    P.STATE_DIR = tmp / "state"
    P.STATE_DIR.mkdir(parents=True, exist_ok=True)
    O.ORCHESTRATOR_DIR = P.STATE_DIR / "orchestrator"
    os.environ["CLAUDE_HOME"] = str(tmp)


def test_new_session_creates_dir_events_and_initial_event():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session

        sess = new_session("ship feature X")
        assert sess.sid.startswith("orch-")
        assert sess.goal == "ship feature X"
        assert sess.events_path.exists()
        assert sess.phase_tree_path.exists()

        events = [json.loads(line) for line in sess.events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(events) == 1
        assert events[0]["type"] == "session_start"
        assert events[0]["payload"]["goal"] == "ship feature X"


def test_load_session_returns_none_for_missing_sid():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import load_session

        assert load_session("orch-nonexistent-000000") is None


def test_load_session_resumes_from_events_replay():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, load_session

        original = new_session("resume goal")
        sid = original.sid

        loaded = load_session(sid)
        assert loaded is not None
        assert loaded.sid == sid
        assert loaded.goal == "resume goal"
        assert loaded.root_phase.id.startswith("root-")


def test_load_session_raises_on_corrupt_child_sids():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, load_session

        sess = new_session("g")
        sess.child_sids_path.write_text("{not valid json", encoding="utf-8")

        try:
            load_session(sess.sid)
        except RuntimeError as e:
            assert "child_sids.json corrupt" in str(e)
            return
        raise AssertionError("expected RuntimeError on corrupt child_sids.json")


def test_confirm_resume_or_new_returns_resume_on_non_tty(monkeypatch=None):
    # Don't import pytest — manual stdin replacement
    import io
    from engine.orchestrator import confirm_resume_or_new

    real_stdin = sys.stdin
    try:
        sys.stdin = io.StringIO("")  # StringIO has isatty() == False
        result = confirm_resume_or_new("orch-test")
        assert result == "resume"
    finally:
        sys.stdin = real_stdin


def test_update_phase_appends_event_and_writes_tree():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, update_phase
        from lib.phase_tree import Phase, Status

        sess = new_session("g")
        new_root = Phase(id="root-x", goal="g", status=Status.IN_PROGRESS,
                         next_action="phase_1_implementation")
        update_phase(sess, new_root)

        events = [json.loads(line) for line in sess.events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert any(e["type"] == "phase_update" for e in events)

        tree_text = sess.phase_tree_path.read_text(encoding="utf-8")
        assert "root-x" in tree_text


def test_link_child_writes_atomic_sidecar_and_event():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, link_child

        sess = new_session("g")
        link_child(sess, phase_id="phase_0_design", child_sid="debate-12345-abc")

        sidecar = json.loads(sess.child_sids_path.read_text(encoding="utf-8"))
        assert sidecar == {"phase_0_design": "debate-12345-abc"}

        events = [json.loads(line) for line in sess.events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert any(e["type"] == "child_linked" and
                   e["payload"]["phase_id"] == "phase_0_design"
                   for e in events)


def test_load_session_missing_session_start_returns_none():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import ORCHESTRATOR_DIR, load_session

        sid = "orch-handcrafted-aaaaaa"
        sess_dir = ORCHESTRATOR_DIR / sid
        sess_dir.mkdir(parents=True)
        # events.jsonl exists but has no session_start
        (sess_dir / "events.jsonl").write_text(
            json.dumps({"ts": "2026-01-01", "type": "noise", "payload": {}}) + "\n",
            encoding="utf-8",
        )
        assert load_session(sid) is None


def test_build_research_dispatch_payload_returns_none_below_threshold():
    """Phase 2 wiring: should_dispatch denies below RESEARCH_DISPATCH_THRESHOLD."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, build_research_dispatch_payload

        sess = new_session("g")
        payload = build_research_dispatch_payload(
            sess, fingerprint="fp1", error_excerpt="err",
            tool_name="Bash", strike_count=1,  # below threshold=2
        )
        assert payload is None


def test_build_research_dispatch_payload_at_threshold_returns_payload_and_logs_event():
    """At/above threshold + quota available -> returns Agent payload + records event."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, build_research_dispatch_payload

        sess = new_session("g")
        payload = build_research_dispatch_payload(
            sess, fingerprint="fp1", error_excerpt="error excerpt",
            tool_name="Bash", strike_count=2,
        )
        assert payload is not None
        assert payload["subagent_type"] == "harness-researcher"
        assert payload["fingerprint"] == "fp1"
        assert payload["sid"] == sess.sid
        assert payload["dispatch_count_for_fingerprint"] == 1

        events = [json.loads(line) for line in sess.events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert any(e["type"] == "research_dispatched" for e in events)


def test_build_research_dispatch_payload_quota_exhausted_returns_none():
    """4th dispatch attempt for same fingerprint blocked (PER_FINGERPRINT_DISPATCH_LIMIT=3)."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, build_research_dispatch_payload

        sess = new_session("g")
        for _ in range(3):
            assert build_research_dispatch_payload(
                sess, fingerprint="fp_hot", error_excerpt="x",
                tool_name="Bash", strike_count=2,
            ) is not None
        # 4th -> blocked
        assert build_research_dispatch_payload(
            sess, fingerprint="fp_hot", error_excerpt="x",
            tool_name="Bash", strike_count=2,
        ) is None
        # Different fingerprint still allowed
        assert build_research_dispatch_payload(
            sess, fingerprint="fp_new", error_excerpt="x",
            tool_name="Bash", strike_count=2,
        ) is not None


# ---------- Goal-completion loop (W21+ autonomous-to-goal) ----------

def test_current_iteration_returns_zero_for_fresh_session():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, current_iteration

        sess = new_session("g")
        assert current_iteration(sess) == 0


def test_bump_iteration_increments_and_appends_event():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import (
            new_session, bump_iteration, current_iteration,
        )

        sess = new_session("g")
        assert bump_iteration(sess) == 1
        assert current_iteration(sess) == 1
        assert bump_iteration(sess) == 2
        assert current_iteration(sess) == 2

        events = [json.loads(line) for line in
                  sess.events_path.read_text(encoding="utf-8").splitlines()
                  if line.strip()]
        iteration_events = [e for e in events if e["type"] == "iteration_started"]
        assert len(iteration_events) == 2
        assert iteration_events[0]["payload"]["iteration"] == 1
        assert iteration_events[1]["payload"]["iteration"] == 2


def test_evaluate_completion_returns_complete_on_full_success():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, evaluate_completion

        sess = new_session("g")
        result = evaluate_completion(
            sess,
            validators_passed=True,
            tests_passed=True,
            blocking_question_count=0,
        )
        assert result == "complete"


def test_evaluate_completion_returns_iterate_on_failure_within_cap():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import (
            new_session, bump_iteration, evaluate_completion,
        )

        sess = new_session("g")
        bump_iteration(sess)  # iteration_count = 1
        result = evaluate_completion(
            sess,
            validators_passed=False,
            tests_passed=True,
            max_iterations=3,
        )
        assert result == "iterate"


def test_evaluate_completion_returns_escalate_at_max_iterations():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import (
            new_session, bump_iteration, evaluate_completion,
        )

        sess = new_session("g")
        for _ in range(3):
            bump_iteration(sess)  # iteration_count = 3
        result = evaluate_completion(
            sess,
            validators_passed=False,
            tests_passed=False,
            max_iterations=3,
        )
        assert result == "escalate"


def test_evaluate_completion_returns_escalate_on_blocking_question():
    """Blocking question short-circuits regardless of pass/fail or iteration count."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, evaluate_completion

        sess = new_session("g")
        # Even with passing validators+tests, a blocking_question forces escalate
        result = evaluate_completion(
            sess,
            validators_passed=True,
            tests_passed=True,
            blocking_question_count=1,
        )
        assert result == "escalate"


# ---- DGE E2 evaluator_verdict integration (debate-1778248254-0b7092) ----

def test_evaluate_completion_e2_approved_with_clean_tests_completes():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, evaluate_completion
        sess = new_session("g")
        result = evaluate_completion(
            sess,
            validators_passed=True, tests_passed=True,
            evaluator_verdict="approved",
        )
        assert result == "complete"


def test_evaluate_completion_e2_approved_with_failing_tests_iterates():
    """E2 'approved' alone is insufficient — objective tests must also pass."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, evaluate_completion
        sess = new_session("g")
        result = evaluate_completion(
            sess,
            validators_passed=False, tests_passed=True,
            evaluator_verdict="approved",
        )
        assert result == "iterate"


def test_evaluate_completion_e2_iterate_does_not_complete():
    """E2 'iterate' verdict blocks 'complete' even when tests pass."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, evaluate_completion
        sess = new_session("g")
        result = evaluate_completion(
            sess,
            validators_passed=True, tests_passed=True,
            evaluator_verdict="iterate",
        )
        assert result == "iterate"


def test_evaluate_completion_e2_escalate_short_circuits():
    """E2 'escalate' verdict forces escalate immediately."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, evaluate_completion
        sess = new_session("g")
        result = evaluate_completion(
            sess,
            validators_passed=True, tests_passed=True,
            evaluator_verdict="escalate",
        )
        assert result == "escalate"


def test_evaluate_completion_e2_none_falls_back_to_legacy_path():
    """evaluator_verdict=None preserves legacy behavior (objective tests only)."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, evaluate_completion
        sess = new_session("g")
        result = evaluate_completion(
            sess,
            validators_passed=True, tests_passed=True,
            evaluator_verdict=None,
        )
        assert result == "complete"


def test_iteration_count_survives_replay_via_load_session():
    """current_iteration is derived from events.jsonl — must persist across
    load_session (no extra sidecar to corrupt)."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import (
            new_session, load_session, bump_iteration, current_iteration,
        )

        original = new_session("g")
        bump_iteration(original)
        bump_iteration(original)
        sid = original.sid

        # Simulate fresh load (replay)
        loaded = load_session(sid)
        assert loaded is not None
        assert current_iteration(loaded) == 2


def test_loop_integration_fail_fail_succeed_pattern():
    """Realistic autopilot loop scenario: 3 iterations, first 2 fail, 3rd succeeds.

    Locks in the contract that:
      - bump_iteration + evaluate_completion compose into a working loop
      - 'iterate' is returned while iteration < max AND failures present
      - 'complete' takes precedence over iteration count once both pass
      - escalate is NOT triggered prematurely
    """
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import (
            new_session, bump_iteration, evaluate_completion,
        )

        sess = new_session("ship feature X")

        # Iteration 1 — validators fail, tests fail
        assert bump_iteration(sess) == 1
        decision = evaluate_completion(
            sess, validators_passed=False, tests_passed=False, max_iterations=3,
        )
        assert decision == "iterate"

        # Iteration 2 — validators pass, tests still fail
        assert bump_iteration(sess) == 2
        decision = evaluate_completion(
            sess, validators_passed=True, tests_passed=False, max_iterations=3,
        )
        assert decision == "iterate"

        # Iteration 3 — both pass
        assert bump_iteration(sess) == 3
        decision = evaluate_completion(
            sess, validators_passed=True, tests_passed=True, max_iterations=3,
        )
        assert decision == "complete"


def test_loop_integration_runaway_caps_at_max_iterations():
    """Realistic worst case: 4 iterations all fail. cap=3 → escalate at 3."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import (
            new_session, bump_iteration, evaluate_completion,
        )

        sess = new_session("g")
        decisions = []
        for _ in range(4):
            bump_iteration(sess)
            decisions.append(evaluate_completion(
                sess, validators_passed=False, tests_passed=False, max_iterations=3,
            ))
        # First 2 iterations: 'iterate'. At iteration 3 cap met → 'escalate'.
        assert decisions[0] == "iterate"
        assert decisions[1] == "iterate"
        assert decisions[2] == "escalate"
        assert decisions[3] == "escalate"  # stays escalated past cap


def test_loop_integration_blocking_question_escalates_immediately():
    """Even on iteration 1 with passing checks, blocking_question forces escalate."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import (
            new_session, bump_iteration, evaluate_completion,
        )

        sess = new_session("g")
        bump_iteration(sess)  # iteration 1
        decision = evaluate_completion(
            sess,
            validators_passed=True,
            tests_passed=True,
            blocking_question_count=2,
            max_iterations=3,
        )
        assert decision == "escalate"


TESTS = [
    test_new_session_creates_dir_events_and_initial_event,
    test_load_session_returns_none_for_missing_sid,
    test_load_session_resumes_from_events_replay,
    test_load_session_raises_on_corrupt_child_sids,
    test_confirm_resume_or_new_returns_resume_on_non_tty,
    test_update_phase_appends_event_and_writes_tree,
    test_link_child_writes_atomic_sidecar_and_event,
    test_load_session_missing_session_start_returns_none,
    test_build_research_dispatch_payload_returns_none_below_threshold,
    test_build_research_dispatch_payload_at_threshold_returns_payload_and_logs_event,
    test_build_research_dispatch_payload_quota_exhausted_returns_none,
    test_current_iteration_returns_zero_for_fresh_session,
    test_bump_iteration_increments_and_appends_event,
    test_evaluate_completion_returns_complete_on_full_success,
    test_evaluate_completion_returns_iterate_on_failure_within_cap,
    test_evaluate_completion_returns_escalate_at_max_iterations,
    test_evaluate_completion_returns_escalate_on_blocking_question,
    test_evaluate_completion_e2_approved_with_clean_tests_completes,
    test_evaluate_completion_e2_approved_with_failing_tests_iterates,
    test_evaluate_completion_e2_iterate_does_not_complete,
    test_evaluate_completion_e2_escalate_short_circuits,
    test_evaluate_completion_e2_none_falls_back_to_legacy_path,
    test_iteration_count_survives_replay_via_load_session,
    test_loop_integration_fail_fail_succeed_pattern,
    test_loop_integration_runaway_caps_at_max_iterations,
    test_loop_integration_blocking_question_escalates_immediately,
]


def test_list_sessions_returns_empty_when_orchestrator_dir_absent():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import list_sessions
        assert list_sessions() == []


def test_list_sessions_returns_session_summary():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import (
            list_sessions, new_session, bump_iteration,
        )
        sess = new_session("ship feature X")
        bump_iteration(sess)
        bump_iteration(sess)

        sessions = list_sessions()
        assert len(sessions) == 1
        s = sessions[0]
        assert s["sid"] == sess.sid
        assert s["iter"] == 2
        assert s["goal"] == "ship feature X"
        assert s["status"] == "in_progress"


def test_list_sessions_skips_dir_without_events_jsonl():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import list_sessions, new_session, ORCHESTRATOR_DIR
        new_session("g1")
        (ORCHESTRATOR_DIR / "stray-no-events").mkdir(parents=True)

        sessions = list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["goal"] == "g1"


def test_list_sessions_sorts_by_started_ts_desc():
    import time as _time
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import list_sessions, new_session
        new_session("first")
        _time.sleep(1)
        new_session("second")

        sessions = list_sessions()
        assert len(sessions) == 2
        assert sessions[0]["goal"] == "second"
        assert sessions[1]["goal"] == "first"


def test_list_sessions_tiebreak_deterministic_on_equal_started_ts():
    """STEP 5 flaky fix: when started_ts ties (rapid sub-sessions sharing one
    second — now_iso is second-resolution), ordering must be deterministic by
    sid desc, never filesystem-iteration order. Monkeypatches now_iso to a fixed
    value (forces the tie) + mint_session_id to known sids so the sid tiebreak is
    the SOLE ordering signal."""
    import engine.orchestrator as orch
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        saved_mint, saved_now = orch.mint_session_id, orch.now_iso
        try:
            orch.now_iso = lambda: "2026-06-04T00:00:00Z"  # identical ts → tie
            minted = iter(["orch-100-aaa111", "orch-100-ccc333", "orch-100-bbb222"])
            orch.mint_session_id = lambda: next(minted)
            orch.new_session("first")    # aaa111
            orch.new_session("second")   # ccc333
            orch.new_session("third")    # bbb222
        finally:
            orch.mint_session_id, orch.now_iso = saved_mint, saved_now
        got = [s["sid"] for s in orch.list_sessions()]
        # all share started_ts → pure sid-desc tiebreak, fully deterministic
        assert got == ["orch-100-ccc333", "orch-100-bbb222", "orch-100-aaa111"], got
        # stable across repeated calls (no filesystem-order dependence)
        assert [s["sid"] for s in orch.list_sessions()] == got


# Append list_sessions tests after their defs (Python parses top-down).
TESTS.extend([
    test_list_sessions_returns_empty_when_orchestrator_dir_absent,
    test_list_sessions_returns_session_summary,
    test_list_sessions_skips_dir_without_events_jsonl,
    test_list_sessions_sorts_by_started_ts_desc,
    test_list_sessions_tiebreak_deterministic_on_equal_started_ts,
])


# ---------- Pane shard aggregation (D6 wave (a) — debate-1778302432-1ce6ea) ----------

def _write_shard(sid_dir: Path, pane_id: str, records: list[dict]) -> Path:
    panes_dir = sid_dir / "panes"
    panes_dir.mkdir(parents=True, exist_ok=True)
    shard = panes_dir / f"{pane_id}.jsonl"
    with shard.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return shard


def test_replay_pane_state_returns_empty_for_missing_sid():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import replay_pane_state
        assert replay_pane_state("orch-nope-000000") == {}


def test_replay_pane_state_reads_shards_only():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, replay_pane_state, ORCHESTRATOR_DIR
        sess = new_session("g")
        sid_dir = ORCHESTRATOR_DIR / sess.sid
        _write_shard(sid_dir, "D1", [
            {"ts": "2026-05-09T00:00:01Z", "type": "pane_started", "pane_id": "D1"},
            {"ts": "2026-05-09T00:00:02Z", "type": "pane_status",
             "pane_id": "D1", "status": "exited", "exit_code": 0},
        ])
        snap = replay_pane_state(sess.sid)
        assert "D1" in snap
        assert snap["D1"]["status"] == "exited"
        assert snap["D1"]["exit_code"] == 0


def test_replay_pane_state_reads_canonical_already_merged():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, replay_pane_state, ORCHESTRATOR_DIR
        from lib.logging import jsonl_append
        sess = new_session("g")
        canonical = (ORCHESTRATOR_DIR / sess.sid) / "events.jsonl"
        jsonl_append(canonical, {
            "type": "pane_started", "sid": sess.sid,
            "payload": {"pane_id": "D3"},
        })
        jsonl_append(canonical, {
            "type": "pane_status", "sid": sess.sid,
            "payload": {"pane_id": "D3", "status": "killed", "exit_code": -1},
        })
        snap = replay_pane_state(sess.sid)
        assert "D3" in snap
        assert snap["D3"]["status"] == "killed"
        assert snap["D3"]["exit_code"] == -1


def test_replay_pane_state_combines_canonical_and_shards_latest_wins():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, replay_pane_state, ORCHESTRATOR_DIR
        sess = new_session("g")
        sid_dir = ORCHESTRATOR_DIR / sess.sid
        canonical = sid_dir / "events.jsonl"
        # Write canonical entry directly with a controlled (older) ts
        # — bypass jsonl_append's auto-stamp so the test is deterministic.
        with canonical.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": "1970-01-01T00:00:00Z",
                "type": "pane_status", "sid": sess.sid,
                "payload": {"pane_id": "D6", "status": "exited", "exit_code": 0},
            }) + "\n")
        # Newer event in shard (lex-greater ts wins)
        _write_shard(sid_dir, "D6", [
            {"ts": "2099-12-31T23:59:59Z", "type": "pane_status",
             "pane_id": "D6", "status": "exited", "exit_code": 99},
        ])
        snap = replay_pane_state(sess.sid)
        assert snap["D6"]["status"] == "exited"
        assert snap["D6"]["exit_code"] == 99


def test_replay_pane_state_tolerates_corrupt_shard_lines():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, replay_pane_state, ORCHESTRATOR_DIR
        sess = new_session("g")
        sid_dir = ORCHESTRATOR_DIR / sess.sid
        panes_dir = sid_dir / "panes"
        panes_dir.mkdir()
        (panes_dir / "D1.jsonl").write_text(
            '{"ts":"a","type":"pane_started","pane_id":"D1"}\n'
            'not-json\n'
            '{"ts":"b","type":"pane_status","pane_id":"D1","status":"exited","exit_code":0}\n',
            encoding="utf-8",
        )
        snap = replay_pane_state(sess.sid)
        assert snap["D1"]["status"] == "exited"


def test_merge_pane_shards_returns_zero_when_no_shards():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, merge_pane_shards
        sess = new_session("g")
        assert merge_pane_shards(sess.sid) == 0


def test_merge_pane_shards_skips_running_pane():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, merge_pane_shards, ORCHESTRATOR_DIR
        sess = new_session("g")
        sid_dir = ORCHESTRATOR_DIR / sess.sid
        shard = _write_shard(sid_dir, "D1", [
            {"ts": "x", "type": "pane_started", "pane_id": "D1"},
            {"ts": "y", "type": "pane_status", "pane_id": "D1", "status": "running"},
        ])
        merged = merge_pane_shards(sess.sid)
        assert merged == 0
        assert shard.exists(), "running shard must NOT be deleted"


def test_merge_pane_shards_merges_exited_pane_and_deletes_shard():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, merge_pane_shards, ORCHESTRATOR_DIR
        sess = new_session("g")
        sid_dir = ORCHESTRATOR_DIR / sess.sid
        canonical = sid_dir / "events.jsonl"
        before = canonical.read_text(encoding="utf-8").count("\n")
        shard = _write_shard(sid_dir, "D3", [
            {"ts": "x", "type": "pane_started", "pane_id": "D3"},
            {"ts": "y", "type": "pane_status", "pane_id": "D3",
             "status": "exited", "exit_code": 0},
        ])
        merged = merge_pane_shards(sess.sid)
        assert merged == 1
        assert not shard.exists(), "exited shard MUST be deleted"
        after = canonical.read_text(encoding="utf-8").count("\n")
        assert after == before + 2  # 2 records appended


def test_merge_pane_shards_killed_status_is_terminal():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, merge_pane_shards, ORCHESTRATOR_DIR
        sess = new_session("g")
        sid_dir = ORCHESTRATOR_DIR / sess.sid
        _write_shard(sid_dir, "D1", [
            {"ts": "x", "type": "pane_status", "pane_id": "D1",
             "status": "killed", "exit_code": -9},
        ])
        assert merge_pane_shards(sess.sid) == 1


def test_merge_pane_shards_failed_status_is_terminal():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, merge_pane_shards, ORCHESTRATOR_DIR
        sess = new_session("g")
        sid_dir = ORCHESTRATOR_DIR / sess.sid
        _write_shard(sid_dir, "D1", [
            {"ts": "x", "type": "pane_status", "pane_id": "D1",
             "status": "failed", "exit_code": 2},
        ])
        assert merge_pane_shards(sess.sid) == 1


def test_merge_pane_shards_mixed_running_and_exited():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, merge_pane_shards, ORCHESTRATOR_DIR
        sess = new_session("g")
        sid_dir = ORCHESTRATOR_DIR / sess.sid
        running = _write_shard(sid_dir, "D1", [
            {"ts": "x", "type": "pane_status", "pane_id": "D1", "status": "running"},
        ])
        exited = _write_shard(sid_dir, "D3", [
            {"ts": "x", "type": "pane_status", "pane_id": "D3",
             "status": "exited", "exit_code": 0},
        ])
        merged = merge_pane_shards(sess.sid)
        assert merged == 1
        assert running.exists()
        assert not exited.exists()


def test_merge_pane_shards_idempotent_after_full_merge():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, merge_pane_shards, ORCHESTRATOR_DIR
        sess = new_session("g")
        sid_dir = ORCHESTRATOR_DIR / sess.sid
        _write_shard(sid_dir, "D1", [
            {"ts": "x", "type": "pane_status", "pane_id": "D1",
             "status": "exited", "exit_code": 0},
        ])
        first = merge_pane_shards(sess.sid)
        second = merge_pane_shards(sess.sid)
        assert first == 1
        assert second == 0


def test_merge_pane_shards_appends_with_proper_canonical_shape():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, merge_pane_shards, ORCHESTRATOR_DIR
        sess = new_session("g")
        sid_dir = ORCHESTRATOR_DIR / sess.sid
        _write_shard(sid_dir, "D6", [
            {"ts": "x", "type": "pane_started", "pane_id": "D6",
             "worktree_path": "/wt"},
            {"ts": "y", "type": "pane_status", "pane_id": "D6",
             "status": "exited", "exit_code": 0},
        ])
        merge_pane_shards(sess.sid)
        canonical = sid_dir / "events.jsonl"
        events = [
            json.loads(line)
            for line in canonical.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        pane_events = [e for e in events if e.get("type") in ("pane_started", "pane_status")]
        assert len(pane_events) == 2
        for e in pane_events:
            assert e["sid"] == sess.sid
            assert "payload" in e
            assert e["payload"]["pane_id"] == "D6"


def test_merge_pane_shards_empty_shard_unlinked():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, merge_pane_shards, ORCHESTRATOR_DIR
        sess = new_session("g")
        sid_dir = ORCHESTRATOR_DIR / sess.sid
        panes_dir = sid_dir / "panes"
        panes_dir.mkdir()
        empty = panes_dir / "D1.jsonl"
        empty.write_text("", encoding="utf-8")
        merge_pane_shards(sess.sid)
        assert not empty.exists()


def test_merge_pane_shards_post_merge_replay_state_preserved():
    """Round-trip: shard → merge → replay_pane_state still sees the pane."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import (
            new_session, merge_pane_shards, replay_pane_state, ORCHESTRATOR_DIR,
        )
        sess = new_session("g")
        sid_dir = ORCHESTRATOR_DIR / sess.sid
        _write_shard(sid_dir, "D1", [
            {"ts": "x", "type": "pane_started", "pane_id": "D1"},
            {"ts": "y", "type": "pane_status", "pane_id": "D1",
             "status": "exited", "exit_code": 7},
        ])
        merge_pane_shards(sess.sid)
        snap = replay_pane_state(sess.sid)
        assert snap["D1"]["status"] == "exited"
        assert snap["D1"]["exit_code"] == 7


TESTS.extend([
    test_replay_pane_state_returns_empty_for_missing_sid,
    test_replay_pane_state_reads_shards_only,
    test_replay_pane_state_reads_canonical_already_merged,
    test_replay_pane_state_combines_canonical_and_shards_latest_wins,
    test_replay_pane_state_tolerates_corrupt_shard_lines,
    test_merge_pane_shards_returns_zero_when_no_shards,
    test_merge_pane_shards_skips_running_pane,
    test_merge_pane_shards_merges_exited_pane_and_deletes_shard,
    test_merge_pane_shards_killed_status_is_terminal,
    test_merge_pane_shards_failed_status_is_terminal,
    test_merge_pane_shards_mixed_running_and_exited,
    test_merge_pane_shards_idempotent_after_full_merge,
    test_merge_pane_shards_appends_with_proper_canonical_shape,
    test_merge_pane_shards_empty_shard_unlinked,
    test_merge_pane_shards_post_merge_replay_state_preserved,
])


# ---------- Phase 1 entry helpers (D1+D5 wiring closure) ----------

def test_phase1_onedrive_check_passes_when_safe():
    """When probe returns ok=True, no worktree_probe_failed event is emitted."""
    from unittest import mock
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, phase1_onedrive_check
        sess = new_session("g")
        with mock.patch("lib.autopilot_worktree_probe.is_onedrive_path",
                        return_value=(True, None)):
            ok, reason = phase1_onedrive_check(sess, Path(td))
        assert ok is True
        assert reason is None
        events = sess.events_path.read_text(encoding="utf-8").splitlines()
        types = [json.loads(e).get("type") for e in events if e.strip()]
        assert "worktree_probe_failed" not in types


def test_phase1_onedrive_check_emits_event_on_positive_detection():
    from unittest import mock
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, phase1_onedrive_check
        sess = new_session("g")
        with mock.patch("lib.autopilot_worktree_probe.is_onedrive_path",
                        return_value=(False, "onedrive_path_match")):
            ok, reason = phase1_onedrive_check(sess, Path(td))
        assert ok is False
        assert reason == "onedrive_path_match"
        events = [
            json.loads(line)
            for line in sess.events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        probe_failed = [e for e in events if e.get("type") == "worktree_probe_failed"]
        assert len(probe_failed) == 1
        assert probe_failed[0]["payload"]["reason"] == "onedrive_path_match"
        assert probe_failed[0]["payload"]["repo_root"] == str(Path(td))


def test_phase1_onedrive_check_accepts_str_repo_root():
    from unittest import mock
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, phase1_onedrive_check
        sess = new_session("g")
        with mock.patch("lib.autopilot_worktree_probe.is_onedrive_path",
                        return_value=(True, "skipped_via_env")):
            ok, reason = phase1_onedrive_check(sess, td)
        assert ok is True
        assert reason == "skipped_via_env"


def test_phase1_onedrive_check_handles_none_reason():
    from unittest import mock
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from engine.orchestrator import new_session, phase1_onedrive_check
        sess = new_session("g")
        with mock.patch("lib.autopilot_worktree_probe.is_onedrive_path",
                        return_value=(False, None)):
            ok, reason = phase1_onedrive_check(sess, Path(td))
        assert ok is False
        events = [
            json.loads(line)
            for line in sess.events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        probe_failed = [e for e in events if e.get("type") == "worktree_probe_failed"]
        assert probe_failed[0]["payload"]["reason"] == "unknown"


def test_record_parallel_run_outcome_writes_telemetry():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from lib import paths as P
        from lib import logging as L
        P.TELEMETRY_DIR = Path(td) / "telemetry"
        L.TELEMETRY_DIR = P.TELEMETRY_DIR
        P.TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)

        from engine.orchestrator import new_session, record_parallel_run_outcome
        sess = new_session("g")
        record_parallel_run_outcome(
            sess, status="complete", merge_conflicts=0, pane_failures=0,
        )
        target = P.TELEMETRY_DIR / "autopilot-parallel-runs.jsonl"
        assert target.is_file()
        rec = json.loads(target.read_text(encoding="utf-8").strip())
        assert rec["sid"] == sess.sid
        assert rec["status"] == "complete"


def test_record_parallel_run_outcome_passes_extras():
    with tempfile.TemporaryDirectory() as td:
        _redirect_orchestrator_dir(Path(td))
        from lib import paths as P
        from lib import logging as L
        P.TELEMETRY_DIR = Path(td) / "telemetry"
        L.TELEMETRY_DIR = P.TELEMETRY_DIR
        P.TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)

        from engine.orchestrator import new_session, record_parallel_run_outcome
        sess = new_session("g")
        record_parallel_run_outcome(
            sess, status="escalate", merge_conflicts=1, pane_failures=2,
            failing_decisions=["D1"],
        )
        target = P.TELEMETRY_DIR / "autopilot-parallel-runs.jsonl"
        rec = json.loads(target.read_text(encoding="utf-8").strip())
        assert rec["merge_conflicts"] == 1
        assert rec["pane_failures"] == 2
        assert rec["failing_decisions"] == ["D1"]


TESTS.extend([
    test_phase1_onedrive_check_passes_when_safe,
    test_phase1_onedrive_check_emits_event_on_positive_detection,
    test_phase1_onedrive_check_accepts_str_repo_root,
    test_phase1_onedrive_check_handles_none_reason,
    test_record_parallel_run_outcome_writes_telemetry,
    test_record_parallel_run_outcome_passes_extras,
])


def main() -> int:
    failed = 0
    try:
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
    finally:
        # Restore CLAUDE_HOME mutated by _redirect_orchestrator_dir so other test
        # modules / the runner resolve real paths again (no leak into a deleted tmp).
        if _ORIG_CLAUDE_HOME is None:
            os.environ.pop("CLAUDE_HOME", None)
        else:
            os.environ["CLAUDE_HOME"] = _ORIG_CLAUDE_HOME
    if failed:
        print(f"\n[FAIL] {failed}/{len(TESTS)} tests failed")
        return 1
    print(f"\n[OK] {len(TESTS)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
