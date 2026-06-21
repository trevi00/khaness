#!/usr/bin/env python3
"""Tests for lib.calibration.proposer + cli.calibration_review (v15.12).

Coverage:
  - analyze_ledger: 빈 ledger / 누적 record / malformed line tolerance
  - AgentStats: failure_rate / success_rate 계산
  - R1 (insufficient sample): sample < min_sample → 제안 없음
  - R2 (invoke→skip 자원 절약): 조건 충족 시 제안, DEFAULT_INVOKE는 자동 제외
  - R3 (skip→invoke 검출 강화): 조건 충족 시 제안
  - R4 (fabrication-heavy):
      * current=skip + fab>=50% + R3 임계 미만 → invoke 격상 제안
      * current=invoke + fab>=50% → semantic-layer note (suggested=None)
  - CLI: text/json 출력, exit 0 (제안 유무 무관)
"""
from __future__ import annotations

import json
import sys
import tempfile
from io import StringIO
from contextlib import redirect_stdout
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.calibration.proposer import (  # noqa: E402
    AgentStats,
    INVOKE_THRESHOLD_FAILURE_RATE,
    MIN_SAMPLE_SIZE,
    SKIP_THRESHOLD_FAILURE_RATE,
    analyze_ledger,
    propose_critic_policy_changes,
)
from lib import critic_policy as CP  # noqa: E402
from cli.calibration_review import main as cli_main  # noqa: E402


def _redirect_policy_path(tmp: Path) -> Path:
    p = tmp / "critic-policy.yaml"
    CP.POLICY_PATH = p
    return p


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _project_ledger_path(root: Path, project: str, agent: str) -> Path:
    from lib.operator_ledger import project_id_for
    return root / project_id_for(project) / f"{agent}.jsonl"


# ---- AgentStats ----

def test_failure_rate_zero_sample():
    s = AgentStats("x", 0, 0, 0)
    assert s.failure_rate == 0.0
    assert s.success_rate == 1.0


def test_failure_rate_basic():
    s = AgentStats("x", 10, 8, 2)
    assert s.failure_rate == 0.2
    assert s.success_rate == 0.8


# ---- analyze_ledger ----

def test_analyze_empty_ledger_returns_zero_stats():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        stats = analyze_ledger("C:/proj", "researcher", ledger_root=root)
        assert stats.sample_size == 0
        assert stats.failure_count == 0


def test_analyze_accumulates_records():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        records = [
            {"agent_type": "researcher", "success": True, "failure_modes": []},
            {"agent_type": "researcher", "success": True, "failure_modes": []},
            {"agent_type": "researcher", "success": False,
             "failure_modes": ["schema_violation"]},
        ]
        _write_jsonl(_project_ledger_path(root, "C:/proj", "researcher"), records)
        stats = analyze_ledger("C:/proj", "researcher", ledger_root=root)
        assert stats.sample_size == 3
        assert stats.success_count == 2
        assert stats.failure_count == 1
        assert stats.failure_mode_counts == {"schema_violation": 1}


def test_analyze_skips_malformed_lines():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        path = _project_ledger_path(root, "C:/proj", "researcher")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            f.write('{"agent_type": "researcher", "success": true, "failure_modes": []}\n')
            f.write('garbage not json\n')
            f.write('{"agent_type": "researcher", "success": false, "failure_modes": ["tool_misuse"]}\n')
        stats = analyze_ledger("C:/proj", "researcher", ledger_root=root)
        assert stats.sample_size == 2  # malformed skipped


# ---- R1: insufficient sample ----

def test_r1_below_min_sample_returns_no_proposals():
    with tempfile.TemporaryDirectory() as td:
        _redirect_policy_path(Path(td))
        root = Path(td) / "ledger"
        records = [{"agent_type": "Explore", "success": True, "failure_modes": []}] * 5
        _write_jsonl(_project_ledger_path(root, "C:/proj", "Explore"), records)
        proposals = propose_critic_policy_changes(
            "C:/proj", min_sample=MIN_SAMPLE_SIZE, ledger_root=root,
        )
        assert proposals == []


# ---- R2: invoke→skip ----

def test_r2_invoke_to_skip_proposed_for_low_failure_rate():
    """custom agent (not in DEFAULT_INVOKE) + low failure rate + currently invoke."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_policy_path(Path(td))
        root = Path(td) / "ledger"
        agent = "custom-low-fail-agent"  # not in DEFAULT_INVOKE / DEFAULT_SKIP → default invoke
        records = [{"agent_type": agent, "success": True, "failure_modes": []}] * 20
        _write_jsonl(_project_ledger_path(root, "C:/proj", agent), records)
        proposals = propose_critic_policy_changes("C:/proj", ledger_root=root)
        matching = [p for p in proposals if p.agent_type == agent]
        assert len(matching) == 1
        p = matching[0]
        assert p.current == "invoke"
        assert p.suggested == "skip"
        assert "configure-critic-policy" in p.rationale


def test_r2_skips_judgment_class_agents():
    """harness-planner is in DEFAULT_INVOKE — never auto-propose skip."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_policy_path(Path(td))
        root = Path(td) / "ledger"
        records = [{"agent_type": "harness-planner", "success": True,
                    "failure_modes": []}] * 30
        _write_jsonl(_project_ledger_path(root, "C:/proj", "harness-planner"), records)
        proposals = propose_critic_policy_changes("C:/proj", ledger_root=root)
        assert [p for p in proposals if p.agent_type == "harness-planner"] == []


# ---- R3: skip→invoke ----

def test_r3_skip_to_invoke_when_high_failure_rate():
    with tempfile.TemporaryDirectory() as td:
        _redirect_policy_path(Path(td))
        root = Path(td) / "ledger"
        # Explore is in DEFAULT_SKIP → current=skip
        records = (
            [{"agent_type": "Explore", "success": False,
              "failure_modes": ["schema_violation"]}] * 5
            + [{"agent_type": "Explore", "success": True, "failure_modes": []}] * 15
        )  # 5/20 = 25% failure
        _write_jsonl(_project_ledger_path(root, "C:/proj", "Explore"), records)
        proposals = propose_critic_policy_changes("C:/proj", ledger_root=root)
        matching = [p for p in proposals if p.agent_type == "Explore"]
        assert len(matching) == 1
        p = matching[0]
        assert p.current == "skip"
        assert p.suggested == "invoke"
        assert "apply-user-preference" in p.rationale
        assert "안전 방향" in p.rationale


# ---- R4: fabrication-heavy ----

def test_r4_fabrication_heavy_below_r3_threshold_still_proposes_invoke():
    """fab >= 50% of failures, even if total failure_rate < R3 threshold."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_policy_path(Path(td))
        root = Path(td) / "ledger"
        # Explore: 2 fabrications + 18 success = 10% failure (< R3 20%)
        # but fab is 100% of failures → R4 fires
        records = (
            [{"agent_type": "Explore", "success": False,
              "failure_modes": ["evidence_fabrication"]}] * 2
            + [{"agent_type": "Explore", "success": True, "failure_modes": []}] * 18
        )
        _write_jsonl(_project_ledger_path(root, "C:/proj", "Explore"), records)
        proposals = propose_critic_policy_changes("C:/proj", ledger_root=root)
        matching = [p for p in proposals if p.agent_type == "Explore"]
        assert len(matching) == 1
        p = matching[0]
        assert p.current == "skip"
        assert p.suggested == "invoke"
        assert "fabrication" in p.rationale.lower()
        assert "apply-user-preference" in p.rationale


def test_r4_fabrication_heavy_when_invoke_emits_semantic_note():
    """current=invoke but fab still happening → suggested=None + note."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_policy_path(Path(td))
        root = Path(td) / "ledger"
        agent = "harness-planner"  # DEFAULT_INVOKE
        records = (
            [{"agent_type": agent, "success": False,
              "failure_modes": ["evidence_fabrication"]}] * 5
            + [{"agent_type": agent, "success": True, "failure_modes": []}] * 15
        )  # 5/20 = 25% (above R3 threshold)
        _write_jsonl(_project_ledger_path(root, "C:/proj", agent), records)
        proposals = propose_critic_policy_changes("C:/proj", ledger_root=root)
        matching = [p for p in proposals if p.agent_type == agent]
        # R3 condition (skip→invoke) won't apply because current=invoke. R4 falls into else branch.
        assert len(matching) == 1
        p = matching[0]
        assert p.current == "invoke"
        assert p.suggested is None
        assert p.note is not None
        assert "fabrication" in p.note.lower()


# ---- CLI ----

def test_cli_no_proposals_returns_zero_and_prints_info():
    with tempfile.TemporaryDirectory() as td:
        _redirect_policy_path(Path(td))
        out = StringIO()
        with redirect_stdout(out):
            rc = cli_main(["--project-root", td])
        assert rc == 0
        assert "변경 제안 없음" in out.getvalue() or "proposals=0" in out.getvalue()


def test_cli_json_output_is_valid():
    with tempfile.TemporaryDirectory() as td:
        _redirect_policy_path(Path(td))
        out = StringIO()
        with redirect_stdout(out):
            rc = cli_main(["--project-root", td, "--json"])
        assert rc == 0
        parsed = json.loads(out.getvalue())
        assert "proposals" in parsed
        assert parsed["proposal_count"] == 0


def test_cli_critic_proposal_includes_apply_command():
    """v15.18: 각 actionable proposal에 copy-paste CLI 명령 포함."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_policy_path(Path(td))
        root = Path(td) / "ledger"
        # Explore (DEFAULT_SKIP) + high failure → R3 fires → skip→invoke
        records = (
            [{"agent_type": "Explore", "success": False,
              "failure_modes": ["schema_violation"]}] * 5
            + [{"agent_type": "Explore", "success": True, "failure_modes": []}] * 15
        )
        _write_jsonl(_project_ledger_path(root, "C:/proj", "Explore"), records)
        # Trigger via JSON output to inspect apply_command field
        from lib.calibration import propose_critic_policy_changes
        proposals = propose_critic_policy_changes("C:/proj", ledger_root=root)
        assert len(proposals) >= 1
        from cli.calibration_review import _critic_apply_command
        cmd = _critic_apply_command(proposals[0])
        assert cmd is not None
        assert "cli.critic_policy_override" in cmd
        assert "--agent Explore" in cmd
        assert "--decision invoke" in cmd
        assert "apply-user-preference" in cmd  # skip→invoke = safe token


def test_cli_advisory_only_proposal_has_no_apply_command():
    """suggested=None (advisory) → apply_command=None."""
    from lib.calibration.proposer import Proposal, AgentStats
    from cli.calibration_review import _critic_apply_command
    advisory = Proposal(
        agent_type="x",
        current="invoke",
        suggested=None,
        evidence=AgentStats("x", 20, 10, 10),
        rationale="advisory",
        note="info",
    )
    assert _critic_apply_command(advisory) is None


TESTS = [
    test_failure_rate_zero_sample,
    test_failure_rate_basic,
    test_analyze_empty_ledger_returns_zero_stats,
    test_analyze_accumulates_records,
    test_analyze_skips_malformed_lines,
    test_r1_below_min_sample_returns_no_proposals,
    test_r2_invoke_to_skip_proposed_for_low_failure_rate,
    test_r2_skips_judgment_class_agents,
    test_r3_skip_to_invoke_when_high_failure_rate,
    test_r4_fabrication_heavy_below_r3_threshold_still_proposes_invoke,
    test_r4_fabrication_heavy_when_invoke_emits_semantic_note,
    test_cli_no_proposals_returns_zero_and_prints_info,
    test_cli_json_output_is_valid,
    test_cli_critic_proposal_includes_apply_command,
    test_cli_advisory_only_proposal_has_no_apply_command,
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
