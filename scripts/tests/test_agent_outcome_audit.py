#!/usr/bin/env python3
"""Tests for handlers/post_tool/agent_outcome_audit.py (v15.10 wiring W1).

Subprocess-isolated: each test forks the hook script with CLAUDE_HOME
pointing at a fresh tmpdir so writes can't pollute the real state tree.

Coverage map:
  - Non-Agent tool_name → silent no-op (no ledger write).
  - Agent + free-text response → ledger appends success record.
  - Agent + JSON envelope with missing evidence file_path → ledger records
    failure with failure_modes=['evidence_fabrication'].
  - Agent + JSON envelope passing schema + evidence → ledger record success.
  - critic decision env var threads into the ledger record.
  - Hook is fail-soft: malformed payload doesn't raise.
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

_HOOK = _SCRIPTS / "handlers" / "post_tool" / "agent_outcome_audit.py"


def _invoke_hook(payload, *, claude_home: Path, project_root: Path,
                 env_overrides: dict | None = None,
                 raw_input: str | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["CLAUDE_HOME"] = str(claude_home)
    env["PROJECT_ROOT"] = str(project_root)
    env.pop("ORCH_CRITIC_DECISION", None)
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
        timeout=20,
    )


def _read_ledger(claude_home: Path, project_root: Path, agent_type: str) -> list[dict]:
    """Read the operator-ledger jsonl for given (project_root, agent_type)."""
    # The hook computes project_id off PROJECT_ROOT env, which we sent.
    # Use the same path the lib would compute.
    sys.path.insert(0, str(_SCRIPTS))
    try:
        from lib.operator_ledger import project_id_for
    finally:
        pass
    pid = project_id_for(str(project_root))
    ledger = claude_home / "state" / "operator-ledger" / pid / f"{agent_type}.jsonl"
    if not ledger.exists():
        return []
    out = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def test_non_agent_tool_is_noop():
    with tempfile.TemporaryDirectory() as td:
        ch = Path(td) / "claude"
        pr = Path(td) / "proj"
        ch.mkdir(); pr.mkdir()
        payload = {
            "tool_name": "Read",
            "tool_input": {"file_path": "x"},
            "tool_response": "ok",
            "session_id": "test-sid",
        }
        res = _invoke_hook(payload, claude_home=ch, project_root=pr)
        assert res.returncode == 0, res.stderr
        # No ledger directory should exist
        ledger_dir = ch / "state" / "operator-ledger"
        assert not ledger_dir.exists() or not any(ledger_dir.iterdir())


def test_agent_free_text_response_records_success():
    with tempfile.TemporaryDirectory() as td:
        ch = Path(td) / "claude"
        pr = Path(td) / "proj"
        ch.mkdir(); pr.mkdir()
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "researcher",
                "prompt": "find foo",
            },
            "tool_response": "Found foo at line 42.",
            "session_id": "sid-1",
        }
        res = _invoke_hook(payload, claude_home=ch, project_root=pr)
        assert res.returncode == 0, res.stderr
        records = _read_ledger(ch, pr, "researcher")
        assert len(records) == 1
        rec = records[0]
        assert rec["agent_type"] == "researcher"
        assert rec["success"] is True
        assert rec["failure_modes"] == []
        assert rec["parent_sid"] == "sid-1"
        assert rec["task_hash"]


def test_agent_envelope_missing_evidence_file_records_fabrication():
    with tempfile.TemporaryDirectory() as td:
        ch = Path(td) / "claude"
        pr = Path(td) / "proj"
        ch.mkdir(); pr.mkdir()
        envelope = {
            "summary": "did the thing",
            "evidence": [
                {"file_path": str(pr / "no-such-file.txt")},
            ],
        }
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "researcher",
                "prompt": "do the thing",
            },
            "tool_response": json.dumps(envelope),
            "session_id": "sid-fab",
        }
        res = _invoke_hook(payload, claude_home=ch, project_root=pr)
        assert res.returncode == 0, res.stderr
        records = _read_ledger(ch, pr, "researcher")
        assert len(records) == 1
        rec = records[0]
        assert rec["success"] is False
        assert "evidence_fabrication" in rec["failure_modes"]
        # Breaker state should be recorded
        assert rec["breaker_state_after"] in ("closed", "open")


def test_agent_envelope_clean_records_success_with_evidence_paths():
    with tempfile.TemporaryDirectory() as td:
        ch = Path(td) / "claude"
        pr = Path(td) / "proj"
        ch.mkdir(); pr.mkdir()
        marker = pr / "marker.txt"
        marker.write_text("ok", encoding="utf-8")
        envelope = {
            "summary": "did the thing",
            "evidence": [{"file_path": str(marker)}],
        }
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "researcher",
                "prompt": "do the thing",
            },
            "tool_response": json.dumps(envelope),
            "session_id": "sid-clean",
        }
        res = _invoke_hook(payload, claude_home=ch, project_root=pr)
        assert res.returncode == 0, res.stderr
        records = _read_ledger(ch, pr, "researcher")
        assert len(records) == 1
        rec = records[0]
        assert rec["success"] is True
        assert rec["evidence_paths"] == [str(marker)]


def test_critic_decision_threads_into_ledger():
    with tempfile.TemporaryDirectory() as td:
        ch = Path(td) / "claude"
        pr = Path(td) / "proj"
        ch.mkdir(); pr.mkdir()
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "harness-planner",
                "prompt": "design X",
            },
            "tool_response": "design content",
            "session_id": "sid-critic",
        }
        res = _invoke_hook(
            payload, claude_home=ch, project_root=pr,
            env_overrides={"ORCH_CRITIC_DECISION": "invoke"},
        )
        assert res.returncode == 0, res.stderr
        records = _read_ledger(ch, pr, "harness-planner")
        assert len(records) == 1
        assert records[0]["critic_invoked"] is True


def test_malformed_payload_is_fail_soft():
    with tempfile.TemporaryDirectory() as td:
        ch = Path(td) / "claude"
        pr = Path(td) / "proj"
        ch.mkdir(); pr.mkdir()
        # Send raw garbage stdin
        res = _invoke_hook({}, claude_home=ch, project_root=pr,
                           raw_input="not-json-at-all")
        assert res.returncode == 0, res.stderr


def test_plagiarized_summary_records_cross_ref_verdict_in_verified_by():
    """v15.21 wiring: summary가 prompt token과 100% overlap → verified_by에
    cross_ref strong tier 반영."""
    with tempfile.TemporaryDirectory() as td:
        ch = Path(td) / "claude"
        pr = Path(td) / "proj"
        ch.mkdir(); pr.mkdir()
        marker = pr / "m.txt"
        marker.write_text("alpha beta gamma delta epsilon", encoding="utf-8")
        envelope = {
            "summary": "alpha beta gamma delta epsilon",
            "evidence": [{"file_path": str(marker)}],
        }
        # prompt에 동일 token 5+ 추가 (plagiarized scenario)
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "researcher",
                "prompt": "alpha beta gamma delta epsilon zeta eta theta iota",
            },
            "tool_response": json.dumps(envelope),
            "session_id": "sid-plag",
        }
        res = _invoke_hook(payload, claude_home=ch, project_root=pr)
        assert res.returncode == 0, res.stderr
        records = _read_ledger(ch, pr, "researcher")
        assert len(records) == 1
        # cross_ref STRONG_PLAGIARIZED → "_plagiarized_strong"
        assert "plagiarized" in records[0]["verified_by"]


def test_budget_record_persists_across_invocations():
    """v15.20+v15.21 wiring: 두 번 dispatch 후 state/budgets/<sid>.json 누적."""
    import tempfile as _tf
    with _tf.TemporaryDirectory() as td:
        ch = Path(td) / "claude"
        pr = Path(td) / "proj"
        ch.mkdir(); pr.mkdir()
        payload = {
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "researcher", "prompt": "x"},
            "tool_response": "hello world",  # 11 chars
            "session_id": "sid-budget-test",
        }
        _invoke_hook(payload, claude_home=ch, project_root=pr)
        payload["tool_response"] = "again"  # 5 chars
        _invoke_hook(payload, claude_home=ch, project_root=pr)
        budget_file = ch / "state" / "budgets" / "sid-budget-test.json"
        assert budget_file.exists()
        rec = json.loads(budget_file.read_text(encoding="utf-8"))
        assert rec["total_chars"] == 11 + 5
        assert rec["invocation_count"] == 2


TESTS = [
    test_non_agent_tool_is_noop,
    test_agent_free_text_response_records_success,
    test_agent_envelope_missing_evidence_file_records_fabrication,
    test_agent_envelope_clean_records_success_with_evidence_paths,
    test_critic_decision_threads_into_ledger,
    test_malformed_payload_is_fail_soft,
    test_plagiarized_summary_records_cross_ref_verdict_in_verified_by,
    test_budget_record_persists_across_invocations,
    # heartbeat test appended after definition via TESTS.append
]


def test_heartbeat_recorded_per_dispatch():
    """v15.23 wiring: 매 Agent dispatch 후 heartbeat 파일 생성/갱신."""
    import tempfile as _tf
    with _tf.TemporaryDirectory() as td:
        ch = Path(td) / "claude"
        pr = Path(td) / "proj"
        ch.mkdir(); pr.mkdir()
        payload = {
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "researcher", "prompt": "x"},
            "tool_response": "result",
            "session_id": "sid-heartbeat-wire",
        }
        _invoke_hook(payload, claude_home=ch, project_root=pr)
        hb_file = ch / "state" / "heartbeats" / "sid-heartbeat-wire.json"
        assert hb_file.exists()
        rec = json.loads(hb_file.read_text(encoding="utf-8"))
        assert rec["agent_type"] == "researcher"
        assert rec["count"] == 1
        _invoke_hook(payload, claude_home=ch, project_root=pr)
        rec2 = json.loads(hb_file.read_text(encoding="utf-8"))
        assert rec2["count"] == 2


TESTS.append(test_heartbeat_recorded_per_dispatch)


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
