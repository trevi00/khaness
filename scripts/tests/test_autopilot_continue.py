#!/usr/bin/env python3
"""Unit + subprocess tests for handlers/stop/autopilot_continue.py.

Per debate-1778224899-c24de4 (D1''/D2''/D3'' converged).

Coverage:
  - parse_autopilot_tag: 4 taxonomy branches (ok / json_error / empty_body / tag_miss)
  - parser regex addenda: case-insensitive, quote-tolerant, whitespace-tolerant
  - subprocess gate: silent when no autopilot active, fires when active
  - retry counter increment on tag_miss + json_error
  - terminal: goal_reached marks status=done
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


_HOOK_PATH = _SCRIPTS / "handlers" / "stop" / "autopilot_continue.py"


def _redirect_state_dir(tmp: Path):
    from lib import paths as P
    P.STATE_DIR = tmp / "state"
    P.STATE_DIR.mkdir(parents=True, exist_ok=True)
    # Engine orchestrator binds ORCHESTRATOR_DIR at module load (line 50:
    # `ORCHESTRATOR_DIR = STATE_DIR / "orchestrator"`). Reassigning P.STATE_DIR
    # alone leaves orchestrator pointing at the real STATE_DIR. Redirect here
    # too so shared-sid integration tests can create real orchestrator
    # sessions in the tmp dir.
    try:
        from engine import orchestrator as O
        O.ORCHESTRATOR_DIR = P.STATE_DIR / "orchestrator"
    except ImportError:
        pass


# ---------- parse_autopilot_tag (D1'' addenda regex) ----------

def test_parse_returns_none_when_no_tag():
    from handlers.stop.autopilot_continue import parse_autopilot_tag
    assert parse_autopilot_tag("just a regular response") is None
    assert parse_autopilot_tag("") is None
    assert parse_autopilot_tag(None) is None


def test_parse_recognizes_execute_with_body():
    from handlers.stop.autopilot_continue import parse_autopilot_tag
    res = parse_autopilot_tag(
        "<autopilot mode='execute'>{\"goal_reached\": true}</autopilot>"
    )
    assert res is not None
    assert res["kind"] == "ok"
    assert res["mode"] == "execute"
    assert res["body"] == {"goal_reached": True}


def test_parse_recognizes_advisory_mode():
    from handlers.stop.autopilot_continue import parse_autopilot_tag
    res = parse_autopilot_tag(
        '<autopilot mode="advisory">{"hint":"continue"}</autopilot>'
    )
    assert res is not None
    assert res["mode"] == "advisory"


def test_parse_case_insensitive_tag_and_mode():
    from handlers.stop.autopilot_continue import parse_autopilot_tag
    res = parse_autopilot_tag(
        '<Autopilot Mode="Execute">{"x":1}</autopilot>'
    )
    assert res is not None
    assert res["kind"] == "ok"
    assert res["mode"] == "execute"  # lowercased per addendum


def test_parse_unquoted_mode_attribute():
    from handlers.stop.autopilot_continue import parse_autopilot_tag
    res = parse_autopilot_tag(
        '<autopilot mode=execute>{"x":1}</autopilot>'
    )
    assert res is not None
    assert res["mode"] == "execute"


def test_parse_whitespace_tolerant():
    from handlers.stop.autopilot_continue import parse_autopilot_tag
    res = parse_autopilot_tag(
        "<autopilot   mode = 'execute'>{\"x\":1}</autopilot>"
    )
    assert res is not None
    assert res["mode"] == "execute"


def test_parse_empty_body_kind():
    from handlers.stop.autopilot_continue import parse_autopilot_tag
    res = parse_autopilot_tag(
        "<autopilot mode='execute'>   </autopilot>"
    )
    assert res is not None
    assert res["kind"] == "empty_body"


def test_parse_json_error_kind():
    from handlers.stop.autopilot_continue import parse_autopilot_tag
    res = parse_autopilot_tag(
        "<autopilot mode='execute'>{malformed</autopilot>"
    )
    assert res is not None
    assert res["kind"] == "json_error"
    assert "raw" in res


def test_parse_non_dict_body_treated_as_json_error():
    from handlers.stop.autopilot_continue import parse_autopilot_tag
    res = parse_autopilot_tag(
        "<autopilot mode='execute'>[1,2,3]</autopilot>"
    )
    assert res is not None
    assert res["kind"] == "json_error"


def test_parse_iteration_result_alternative_shape():
    """Body MAY come inside <iteration-result>...</iteration-result> instead."""
    from handlers.stop.autopilot_continue import parse_autopilot_tag
    res = parse_autopilot_tag(
        "<autopilot mode='execute'></autopilot>\n"
        '<iteration-result>{"validators_passed":true,"tests_passed":true}</iteration-result>'
    )
    assert res is not None
    # The autopilot tag itself is empty_body (priority match), so the iteration-result
    # block is not consulted — caller uses body=None and looks elsewhere if needed.
    # Verify behavior: empty_body wins when autopilot tag has no inner content.
    assert res["kind"] == "empty_body"


# ---------- subprocess gate ----------

def _run_hook(stdin_payload: dict, *, env_extra: dict | None = None) -> tuple[int, str]:
    """Run autopilot_continue.py as subprocess. Returns (rc, stdout)."""
    import os as _os
    env = dict(_os.environ)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=json.dumps(stdin_payload),
        capture_output=True,
        text=True,
        timeout=10,
        encoding="utf-8",
        env=env,
    )
    return proc.returncode, proc.stdout


def test_hook_silent_when_no_autopilot_active():
    """No state file → no active session → exit 0 silent."""
    with tempfile.TemporaryDirectory() as td:
        # Subprocess won't see the in-process redirect; it uses its own paths
        # module. Without ANY autopilot state files at the real STATE_DIR
        # for this test cwd, list_active_sids returns []. We use a fresh
        # tmp cwd to ensure no leftover state files affect this.
        rc, out = _run_hook({
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "Plain response with no autopilot context.",
            "session_id": "claude-session-x",
            "cwd": td,  # Brand-new tmp dir, no autopilot state binding to cwd
        })
        assert rc == 0
        # NOTE: subprocess sees REAL state/autopilot/. If real state has active
        # sessions, hook may fire. So this test confirms only the hook didn't
        # crash; deeper test moves to in-process test_autopilot_continue_main_*.


def test_hook_silent_for_subagent():
    """agent_id present → subagent stop, skip."""
    with tempfile.TemporaryDirectory() as td:
        rc, out = _run_hook({
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "subagent message",
            "agent_id": "subagent-x",
            "session_id": "claude-session-x",
            "cwd": td,
        })
        assert rc == 0
        assert out.strip() == ""


def test_hook_silent_for_recursion():
    """stop_hook_active=true → already in stop hook, skip."""
    with tempfile.TemporaryDirectory() as td:
        rc, out = _run_hook({
            "hook_event_name": "Stop",
            "stop_hook_active": True,
            "last_assistant_message": "recursion guard",
            "session_id": "claude-session-x",
            "cwd": td,
        })
        assert rc == 0
        assert out.strip() == ""


def test_hook_silent_for_non_stop_event():
    """Non-Stop event names should be skipped."""
    with tempfile.TemporaryDirectory() as td:
        rc, out = _run_hook({
            "hook_event_name": "PostToolUse",
            "last_assistant_message": "wrong event",
            "session_id": "claude-session-x",
            "cwd": td,
        })
        assert rc == 0
        assert out.strip() == ""


# ---------- in-process state-machine logic ----------

def test_main_advance_iter_on_valid_tag(monkeypatch=None):
    """When state is active + model emits valid <autopilot mode='execute'>{...}</autopilot>,
    advance_iter is called and state is updated. Tested in-process by patching
    sys.stdin and capturing stdout."""
    import io
    import os
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.autopilot_state import (
            new_state, write_state, read_state,
        )
        from handlers.stop import autopilot_continue as ac

        sid = "orch-test-aaa"
        sess = new_state(sid, "test goal")
        write_state(sess)

        payload = {
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": (
                "<autopilot mode='execute'>"
                '{"validators_passed":true,"tests_passed":true,"summary":"done"}'
                "</autopilot>"
            ),
            "session_id": "claude-x",
            "cwd": os.getcwd(),
        }

        real_stdin, real_stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = io.StringIO(json.dumps(payload))
            sys.stdout = io.StringIO()
            try:
                ac.main()
            except SystemExit:
                pass
            captured = sys.stdout.getvalue()
        finally:
            sys.stdin = real_stdin
            sys.stdout = real_stdout

        # State should have advanced
        loaded = read_state(sid)
        assert loaded is not None
        assert loaded.iter == 1
        # Tag was valid, no counters incremented
        assert loaded.tag_miss_count == 0
        assert loaded.json_error_count == 0
        # Output should include the next directive (decision=block)
        assert "decision" in captured
        assert "block" in captured


def test_main_increments_tag_miss_count_on_missing_tag():
    import io
    import os
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.autopilot_state import new_state, write_state, read_state
        from handlers.stop import autopilot_continue as ac

        sid = "orch-tagmiss-bbb"
        write_state(new_state(sid, "g"))

        payload = {
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "Just a plain response with no autopilot tag.",
            "session_id": "claude-x",
            "cwd": os.getcwd(),
        }

        real_stdin, real_stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = io.StringIO(json.dumps(payload))
            sys.stdout = io.StringIO()
            try:
                ac.main()
            except SystemExit:
                pass
        finally:
            sys.stdin = real_stdin
            sys.stdout = real_stdout

        loaded = read_state(sid)
        assert loaded is not None
        assert loaded.tag_miss_count == 1
        assert loaded.iter == 0  # not advanced — model didn't comply


def test_main_marks_done_on_goal_reached():
    """Ground-truth gate: goal_reached=true marks done ONLY when validators/tests
    pass AND no blocking questions. Mirrors engine.orchestrator.evaluate_completion
    semantics inline (no sid cross-reference to orchestrator namespace)."""
    import io
    import os
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.autopilot_state import new_state, write_state, read_state
        from handlers.stop import autopilot_continue as ac

        sid = "orch-done-ccc"
        write_state(new_state(sid, "g"))

        payload = {
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": (
                "<autopilot mode='execute'>"
                '{"goal_reached": true, "validators_passed": true, '
                '"tests_passed": true, "blocking_question_count": 0}'
                "</autopilot>"
            ),
            "session_id": "claude-x",
            "cwd": os.getcwd(),
        }

        real_stdin, real_stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = io.StringIO(json.dumps(payload))
            sys.stdout = io.StringIO()
            try:
                ac.main()
            except SystemExit:
                pass
        finally:
            sys.stdin = real_stdin
            sys.stdout = real_stdout

        loaded = read_state(sid)
        assert loaded is not None
        assert loaded.status == "done"


def test_main_blocks_false_positive_goal_reached():
    """When goal_reached=true is self-reported but validators_passed=false, the
    hook MUST NOT mark done — instead advance to next iteration. Guards against
    hallucinated termination."""
    import io
    import os
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.autopilot_state import new_state, write_state, read_state
        from handlers.stop import autopilot_continue as ac

        sid = "orch-false-pos-ddd"
        write_state(new_state(sid, "g"))

        payload = {
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": (
                "<autopilot mode='execute'>"
                '{"goal_reached": true, "validators_passed": false, '
                '"tests_passed": true, "blocking_question_count": 0}'
                "</autopilot>"
            ),
            "session_id": "claude-x",
            "cwd": os.getcwd(),
        }

        real_stdin, real_stdout = sys.stdin, sys.stdout
        captured_stdout = io.StringIO()
        try:
            sys.stdin = io.StringIO(json.dumps(payload))
            sys.stdout = captured_stdout
            try:
                ac.main()
            except SystemExit:
                pass
        finally:
            sys.stdin = real_stdin
            sys.stdout = real_stdout

        loaded = read_state(sid)
        assert loaded is not None
        assert loaded.status != "done", (
            f"false-positive goal_reached must not terminate, got status={loaded.status}"
        )
        assert loaded.iter >= 1, f"expected advance_iter, got iter={loaded.iter}"
        out = captured_stdout.getvalue()
        assert '"decision": "block"' in out, f"expected block emit, got: {out!r}"


def _drive_shared_sid_hook(td_path, *, write_verdict=None, bump=True):
    """Helper: mint a shared orchestrator+autopilot sid, optionally bump an
    iteration and write an E2 verdict to axis_scores.jsonl, then drive the
    Stop hook with a Tier-1-passing goal_reached payload. Returns the loaded
    autopilot state.

    write_verdict: None | (verdict_str, ts_offset_from_floor) — writes one
    evaluator_verdict axis event at floor+offset (negative offset = stale).
    """
    import io
    import os
    _redirect_state_dir(Path(td_path))
    from lib.autopilot_state import new_state, write_state, read_state
    from engine.orchestrator import new_session, bump_iteration
    from lib.completion_gate import iteration_started_ts
    from lib.axis_scores_log import log_axis_event
    from handlers.stop import autopilot_continue as ac

    sess = new_session("integration goal")
    sid = sess.sid
    write_state(new_state(sid, "integration goal"))
    if bump:
        bump_iteration(sess)  # writes iteration_started → freshness floor

    if write_verdict is not None:
        verdict_str, ts_offset = write_verdict
        floor = iteration_started_ts(sid) or 0.0
        ok = log_axis_event(sid, {
            "event": "evaluator_verdict", "verdict": verdict_str,
            "phase_id": "phase_3.5", "ts": floor + ts_offset,
        })
        assert ok, "log_axis_event should succeed"

    payload = {
        "hook_event_name": "Stop",
        "stop_hook_active": False,
        "last_assistant_message": (
            "<autopilot mode='execute'>"
            '{"goal_reached": true, "validators_passed": true, '
            '"tests_passed": true, "blocking_question_count": 0}'
            "</autopilot>"
        ),
        "session_id": "claude-x",
        "cwd": os.getcwd(),
    }
    real_stdin, real_stdout = sys.stdin, sys.stdout
    try:
        sys.stdin = io.StringIO(json.dumps(payload))
        sys.stdout = io.StringIO()
        try:
            ac.main()
        except SystemExit:
            pass
    finally:
        sys.stdin = real_stdin
        sys.stdout = real_stdout
    return read_state(sid)


def test_shared_sid_blocks_complete_without_fresh_e2_verdict():
    """E2 PLATFORM ENFORCEMENT (debate-1780564679-8mgxsd): on the shared-sid
    path, Tier-1 validators+tests passing is NOT sufficient to complete — with
    NO fresh E2 evaluator verdict in axis_scores.jsonl the hook MUST fail
    closed (require_evaluator=True → 'iterate'), NOT mark done. This is the
    silent-skip gap (completion_gate line-83 None path) the design closes."""
    with tempfile.TemporaryDirectory() as td:
        loaded = _drive_shared_sid_hook(td, write_verdict=None)
        assert loaded is not None
        assert loaded.status != "done", (
            f"E2 not run → must NOT complete on Tier-1 alone, got {loaded.status}"
        )
        assert loaded.iter >= 1, f"expected advance_iter, got iter={loaded.iter}"


def test_shared_sid_completes_with_fresh_approved_verdict():
    """Happy path: a FRESH (ts >= iteration_started) E2 'approved' verdict in
    axis_scores.jsonl + Tier-1 pass → done."""
    with tempfile.TemporaryDirectory() as td:
        loaded = _drive_shared_sid_hook(td, write_verdict=("approved", 1.0))
        assert loaded is not None
        assert loaded.status == "done", (
            f"fresh approved E2 verdict + Tier-1 pass must complete, got {loaded.status}"
        )


def test_shared_sid_stale_approved_does_not_complete():
    """A STALE (ts < iteration_started) prior-iteration 'approved' MUST be
    filtered by the freshness floor → fail-closed → NOT done. Guards the
    stale-verdict-completes-changed-iteration vector (B3/B4)."""
    with tempfile.TemporaryDirectory() as td:
        loaded = _drive_shared_sid_hook(td, write_verdict=("approved", -5.0))
        assert loaded is not None
        assert loaded.status != "done", (
            f"stale approved must NOT complete a fresh iteration, got {loaded.status}"
        )


def test_shared_sid_fresh_escalate_terminates_not_iterates():
    """A fresh E2 'escalate' verdict must SURFACE as terminal (status='failed'
    → can_continue False), NOT be folded into advance_iter (which would loop to
    the autopilot hard cap, burying the operator-decision signal).
    debate-1780564679-8mgxsd E2-review finding #2."""
    with tempfile.TemporaryDirectory() as td:
        loaded = _drive_shared_sid_hook(td, write_verdict=("escalate", 1.0))
        assert loaded is not None
        assert loaded.status == "failed", (
            f"fresh escalate verdict must terminate (failed), got {loaded.status}"
        )
        assert not loaded.can_continue(), "escalate-terminal must stop the loop"


def test_module_import_safe_under_capture_stdin():
    """E2-review finding #3 (debate-1780564679-8mgxsd): the module-level stream
    reconfigure must be import-SAFE. Reloading the hook with a capture stdin
    (StringIO / pytest DontReadFromInput — no .reconfigure) must NOT raise
    AttributeError, else every module importing this hook fails collection."""
    import io
    import importlib
    real_stdin, real_stdout = sys.stdin, sys.stdout
    try:
        sys.stdin = io.StringIO("{}")
        sys.stdout = io.StringIO()
        assert not hasattr(sys.stdin, "reconfigure")
        import handlers.stop.autopilot_continue as ac
        importlib.reload(ac)  # re-runs module-level reconfigure under capture
    finally:
        sys.stdin, sys.stdout = real_stdin, real_stdout
        # Restore the module to its canonical (real-stream) load for siblings.
        import handlers.stop.autopilot_continue as ac2
        importlib.reload(ac2)


def test_shared_sid_helper_exception_fails_closed():
    """E2-review finding #1 hardening (debate-1780564679-8mgxsd): if a
    freshness helper raises AFTER the shared-sid path is confirmed, the Stop
    hook MUST fail CLOSED (verdict='iterate' → NOT done), NEVER degrade OPEN to
    the Tier-1 inline gate (which would silently re-open the E2 skip gap)."""
    import io
    import os
    from unittest import mock
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.autopilot_state import new_state, write_state, read_state
        from engine.orchestrator import new_session, bump_iteration
        from handlers.stop import autopilot_continue as ac
        import lib.completion_gate as cg

        sess = new_session("g")
        sid = sess.sid
        write_state(new_state(sid, "g"))
        bump_iteration(sess)  # iter_count not None → shared-sid confirmed

        def _boom(*a, **k):
            raise RuntimeError("simulated freshness-helper failure")

        payload = {
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": (
                "<autopilot mode='execute'>"
                '{"goal_reached": true, "validators_passed": true, '
                '"tests_passed": true, "blocking_question_count": 0}'
                "</autopilot>"
            ),
            "session_id": "claude-x",
            "cwd": os.getcwd(),
        }
        real_stdin, real_stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = io.StringIO(json.dumps(payload))
            sys.stdout = io.StringIO()
            # Patch the helper the hook re-imports inside its try block.
            with mock.patch.object(cg, "latest_fresh_evaluator_verdict", _boom):
                try:
                    ac.main()
                except SystemExit:
                    pass
        finally:
            sys.stdin = real_stdin
            sys.stdout = real_stdout

        loaded = read_state(sid)
        assert loaded is not None
        assert loaded.status != "done", (
            f"shared-sid helper exception must fail CLOSED, got {loaded.status}"
        )


TESTS = [
    test_parse_returns_none_when_no_tag,
    test_parse_recognizes_execute_with_body,
    test_parse_recognizes_advisory_mode,
    test_parse_case_insensitive_tag_and_mode,
    test_parse_unquoted_mode_attribute,
    test_parse_whitespace_tolerant,
    test_parse_empty_body_kind,
    test_parse_json_error_kind,
    test_parse_non_dict_body_treated_as_json_error,
    test_parse_iteration_result_alternative_shape,
    test_hook_silent_when_no_autopilot_active,
    test_hook_silent_for_subagent,
    test_hook_silent_for_recursion,
    test_hook_silent_for_non_stop_event,
    test_main_advance_iter_on_valid_tag,
    test_main_increments_tag_miss_count_on_missing_tag,
    test_main_marks_done_on_goal_reached,
    test_main_blocks_false_positive_goal_reached,
    test_shared_sid_blocks_complete_without_fresh_e2_verdict,
    test_shared_sid_completes_with_fresh_approved_verdict,
    test_shared_sid_stale_approved_does_not_complete,
    test_shared_sid_fresh_escalate_terminates_not_iterates,
    test_shared_sid_helper_exception_fails_closed,
    test_module_import_safe_under_capture_stdin,
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
