#!/usr/bin/env python3
"""Smoke tests for cli/harness_health.py — ecosystem dashboard.

Read-only contract: must complete without raising regardless of state.
Empty SKILLS_DIR / missing telemetry → still produces valid dashboard.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cli import harness_health as HH  # noqa: E402


def test_build_dashboard_returns_all_sections():
    d = HH.build_dashboard()
    for key in ("skills", "lint", "debate", "strict_design",
                "telemetry", "tests", "phase_tree", "writeback",
                "audit_log", "operational_metrics"):
        assert key in d


def test_render_text_includes_all_section_headers():
    d = HH.build_dashboard()
    out = HH.render_text(d)
    assert "=== Harness Ecosystem Health ===" in out
    assert "[Skills]" in out
    assert "[Lint]" in out
    assert "[Debate]" in out
    assert "[StrictDesign]" in out
    assert "[Telemetry]" in out
    assert "[Tests]" in out
    assert "[Phase-tree]" in out
    assert "[Writeback]" in out
    assert "[Audit-log]" in out
    assert "[Operational]" in out


def test_section_strict_design_returns_counts():
    s = HH.section_strict_design()
    if "error" in s:
        return
    assert "total" in s
    assert "pending" in s
    assert "acknowledged" in s
    assert s["pending"] <= s["total"]


def test_section_skills_inventory_returns_valid_shape():
    s = HH.section_skills_inventory()
    assert "total_skills" in s
    assert "trees_count" in s
    assert "size_bytes" in s
    assert "by_tree" in s
    assert isinstance(s["total_skills"], int)
    assert isinstance(s["by_tree"], dict)


def test_section_lint_status_handles_no_telemetry_gracefully():
    """Read-only contract: missing telemetry returns informative dict, not raises."""
    s = HH.section_lint_status()
    # Either telemetry_present=True with metrics, or False for empty
    assert "telemetry_present" in s or "error" in s


def test_section_debate_state_returns_counts():
    s = HH.section_debate_state()
    if "error" in s:
        return  # acceptable on environments without state/debates/
    assert "total_sessions" in s
    assert "doubts_logged" in s
    assert "doubts_pending" in s
    assert isinstance(s["total_sessions"], int)


def test_main_exits_zero_in_text_mode():
    rc = HH.main([])
    assert rc == 0


def test_main_exits_zero_in_json_mode(capsys):
    """JSON output must be valid JSON."""
    rc = HH.main(["--json"])
    assert rc == 0
    captured = capsys.readouterr()
    import json as _json
    parsed = _json.loads(captured.out)
    assert "skills" in parsed


# ---------- section_phase_tree (W21+ autonomous closure 3rd surface) ----------

import tempfile  # noqa: E402

from lib.handoff_drift import (  # noqa: E402
    ANCHOR_BEGIN,
    ANCHOR_END,
    render_from_handoff,
)


def _write_handoff_with_tree(path: Path, tree: str) -> None:
    text = (
        "# H\n\n"
        "## Current Phase Block (machine-readable)\n\n"
        "```yaml\n"
        "phase_id: root-x\n"
        "status: in_progress\n"
        "```\n\n"
        f"{ANCHOR_BEGIN}\n```\n{tree}\n```\n{ANCHOR_END}\n"
    )
    path.write_text(text, encoding="utf-8")


def _build_minimal_dashboard(*, phase_tree: dict) -> dict:
    """Minimal dashboard fixture for render_text branch tests."""
    return {
        "skills": {
            "total_skills": 0,
            "trees_count": 0,
            "size_bytes": {"n": 0, "median": 0, "p90": 0, "max": 0},
            "by_tree": {},
        },
        "lint": {"telemetry_present": False},
        "debate": {
            "total_sessions": 0,
            "doubts_logged": 0,
            "doubts_pending": 0,
            "doubts_acknowledged": 0,
            "recent_sessions": [],
        },
        "strict_design": {"total": 0, "pending": 0, "acknowledged": 0},
        "telemetry": {"dir": "/tmp/telemetry", "present": False},
        "tests": {"present": True, "test_files": 0, "files": []},
        "phase_tree": phase_tree,
        "writeback": {"pending_count": 0, "total_count": 0,
                      "by_status": {}, "telemetry": {}},
        "audit_log": {"total_sessions": 0, "total_invocations": 0,
                      "by_agent": {}, "by_origin": {},
                      "hook_failed_count": 0, "recent_invocations": []},
        "operational_metrics": {"metrics": {}, "met_count": 0, "total_count": 0},
    }


def test_section_phase_tree_returns_absent_when_handoff_missing():
    with tempfile.TemporaryDirectory() as td:
        out = HH.section_phase_tree(Path(td) / "HANDOFF.md")
        assert out["present"] is False
        assert "path" in out


def test_section_phase_tree_reports_in_sync():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "HANDOFF.md"
        canon = render_from_handoff(
            "## Current Phase Block (machine-readable)\n\n"
            "```yaml\nphase_id: root-x\nstatus: in_progress\n```\n"
        )
        _write_handoff_with_tree(path, canon)
        out = HH.section_phase_tree(path)
        assert out["present"] is True
        assert out["drift"] is False
        assert "error" not in out


def test_section_phase_tree_detects_drift():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "HANDOFF.md"
        _write_handoff_with_tree(path, "stale-tree-text")
        out = HH.section_phase_tree(path)
        assert out["present"] is True
        assert out["drift"] is True


def test_section_phase_tree_fail_soft_on_malformed_yaml():
    """Malformed yaml MUST NOT raise — section returns error key, drift=None."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "HANDOFF.md"
        path.write_text(
            "## Current Phase Block (machine-readable)\n\n"
            "```yaml\n: : : not yaml\n```\n",
            encoding="utf-8",
        )
        out = HH.section_phase_tree(path)
        assert out["present"] is True
        assert out["drift"] is None
        assert "error" in out


def test_render_text_emits_phase_tree_line_for_in_sync():
    fake = _build_minimal_dashboard(
        phase_tree={"present": True, "drift": False, "path": "/tmp/HANDOFF.md"}
    )
    text = HH.render_text(fake)
    assert "[Phase-tree] in_sync" in text


def test_render_text_emits_phase_tree_line_for_drift():
    fake = _build_minimal_dashboard(
        phase_tree={"present": True, "drift": True, "path": "/tmp/HANDOFF.md"}
    )
    text = HH.render_text(fake)
    assert "[Phase-tree] DRIFT" in text
    assert "handoff_render" in text


def test_render_text_emits_phase_tree_line_for_absent():
    fake = _build_minimal_dashboard(
        phase_tree={"present": False, "path": "/nowhere/HANDOFF.md"}
    )
    text = HH.render_text(fake)
    assert "[Phase-tree]" in text
    assert "absent" in text


# ---------- section_writeback (operator queue health) ----------

def test_section_writeback_returns_zeros_on_empty_state():
    """fail-soft contract: missing state/writeback/ → all-zero shape, no error."""
    s = HH.section_writeback()
    assert s.get("pending_count", -1) >= 0
    assert s.get("total_count", -1) >= 0
    assert isinstance(s.get("by_status"), dict)


def test_section_writeback_aggregates_by_status():
    """Seed proposals with different statuses → by_status reflects counts."""
    import tempfile as _tmp
    with _tmp.TemporaryDirectory() as td:
        from lib import paths as P
        old_state = P.STATE_DIR
        P.STATE_DIR = Path(td) / "state"
        P.STATE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            from lib.writeback_store import (
                ProposalRecord, register_proposal, mark_status,
            )
            register_proposal(ProposalRecord(
                id="p1", fingerprint="f" * 40,
                target_skill_path="skills/_common/a.md",
                sha1_of_diff="0" * 40,
            ))
            register_proposal(ProposalRecord(
                id="p2", fingerprint="g" * 40,
                target_skill_path="skills/_common/b.md",
                sha1_of_diff="0" * 40,
            ))
            mark_status("p2", "rejected")

            s = HH.section_writeback()
            assert s["total_count"] == 2
            assert s["pending_count"] == 1
            assert s["by_status"].get("pending") == 1
            assert s["by_status"].get("rejected") == 1
        finally:
            P.STATE_DIR = old_state


def test_render_text_writeback_branch_empty():
    fake = _build_minimal_dashboard(
        phase_tree={"present": False, "path": "/x"}
    )
    out = HH.render_text(fake)
    assert "[Writeback]" in out
    assert "queue empty" in out


def test_render_text_writeback_branch_with_pending():
    fake = _build_minimal_dashboard(
        phase_tree={"present": False, "path": "/x"}
    )
    fake["writeback"] = {
        "pending_count": 2, "total_count": 3,
        "by_status": {"pending": 2, "rejected": 1},
        "telemetry": {"writeback_split_rejected_total": 1},
    }
    out = HH.render_text(fake)
    assert "[Writeback] pending=2" in out
    assert "rejected=1" in out
    assert "writeback_split_rejected_total=1" in out
    assert "writeback_inspect" in out


# ---------- section_audit_log (subagent invocation grep target) ----------

def test_section_audit_log_returns_zeros_on_empty_state():
    """No state/subagent_invocations/ → all-zero shape, no error."""
    s = HH.section_audit_log()
    assert s.get("total_sessions", -1) >= 0
    assert s.get("total_invocations", -1) >= 0
    assert isinstance(s.get("by_agent"), dict)
    assert isinstance(s.get("recent_invocations"), list)


def test_section_audit_log_aggregates_records():
    """Seed records → totals + by_agent + recent_invocations populate."""
    import tempfile as _tmp
    with _tmp.TemporaryDirectory() as td:
        from lib import paths as P
        old_state = P.STATE_DIR
        old_hh_state = HH.STATE_DIR
        P.STATE_DIR = Path(td) / "state"
        HH.STATE_DIR = P.STATE_DIR  # harness_health captured at import
        P.STATE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            from lib import subagent_invocation_log as M
            M.STATE_DIR = P.STATE_DIR
            from lib.subagent_invocation_log import record_invocation
            record_invocation("debate-h-001", "harness-critic", ["WebFetch"])
            record_invocation("debate-h-001", "harness-architect", ["WebFetch"])
            record_invocation("orch-h-002", "harness-evaluator", ["Read"])

            s = HH.section_audit_log()
            assert s["total_sessions"] == 2
            assert s["total_invocations"] == 3
            assert s["by_agent"].get("harness-critic") == 1
            assert s["by_agent"].get("harness-architect") == 1
            assert s["by_agent"].get("harness-evaluator") == 1
            assert len(s["recent_invocations"]) == 3
        finally:
            P.STATE_DIR = old_state
            HH.STATE_DIR = old_hh_state


def test_render_text_audit_log_branch_empty():
    fake = _build_minimal_dashboard(
        phase_tree={"present": False, "path": "/x"}
    )
    out = HH.render_text(fake)
    assert "[Audit-log]" in out
    assert "no subagent invocations" in out


def test_render_text_audit_log_branch_with_data():
    fake = _build_minimal_dashboard(
        phase_tree={"present": False, "path": "/x"}
    )
    fake["audit_log"] = {
        "total_sessions": 3,
        "total_invocations": 12,
        "by_agent": {"harness-critic": 5, "harness-planner": 4, "harness-architect": 3},
        "by_origin": {},
        "hook_failed_count": 0,
        "recent_invocations": [
            {"ts": "2026-05-10T12:34:56Z", "sid": "debate-x-001",
             "agent": "harness-critic", "role": "critic"},
        ],
    }
    out = HH.render_text(fake)
    assert "[Audit-log] sessions=3" in out
    assert "invocations=12" in out
    assert "harness-critic=5" in out
    assert "debate-x-001" in out
    # search_by_agent hint in footer
    assert "search_by_agent" in out


def test_section_audit_log_aggregates_by_origin():
    """E2 closure 2026-05-10: by_origin breakdown reflects record origins."""
    import tempfile as _tmp
    with _tmp.TemporaryDirectory() as td:
        from lib import paths as P
        old_state = P.STATE_DIR
        old_hh_state = HH.STATE_DIR
        P.STATE_DIR = Path(td) / "state"
        HH.STATE_DIR = P.STATE_DIR
        P.STATE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            from lib import subagent_invocation_log as M
            M.STATE_DIR = P.STATE_DIR
            from lib.subagent_invocation_log import (
                record_invocation, ORIGIN_HOOK, ORIGIN_DIRECTIVE,
            )
            record_invocation("d-1", "harness-x", ["Read"], extra={"origin": ORIGIN_HOOK})
            record_invocation("d-1", "harness-x", ["Read"], extra={"origin": ORIGIN_HOOK})
            record_invocation("d-2", "harness-y", ["Read"], extra={"origin": ORIGIN_DIRECTIVE})
            record_invocation("d-3", "harness-z", ["Read"])  # untagged

            s = HH.section_audit_log()
            assert s["by_origin"]["hook"] == 2
            assert s["by_origin"]["directive"] == 1
            assert s["by_origin"]["_untagged"] == 1
        finally:
            P.STATE_DIR = old_state
            HH.STATE_DIR = old_hh_state


def test_render_text_audit_log_shows_by_origin():
    fake = _build_minimal_dashboard(
        phase_tree={"present": False, "path": "/x"}
    )
    fake["audit_log"] = {
        "total_sessions": 2,
        "total_invocations": 6,
        "by_agent": {"harness-critic": 3, "harness-planner": 3},
        "by_origin": {"hook": 4, "directive": 2},
        "hook_failed_count": 0,
        "recent_invocations": [],
    }
    out = HH.render_text(fake)
    assert "by_origin:" in out
    assert "hook=4" in out
    assert "directive=2" in out


def test_section_audit_log_surfaces_hook_failed_count():
    """E3 closure 2026-05-10: telemetry/audit-log-hook-failed.jsonl entry
    count surfaces in the section dict regardless of invocations dir state."""
    import json as _json
    import tempfile as _tmp
    with _tmp.TemporaryDirectory() as td:
        tmp_path = Path(td)
        from lib import paths as P
        old_state = P.STATE_DIR
        old_tel = P.TELEMETRY_DIR
        old_hh_state = HH.STATE_DIR
        old_hh_tel = HH.TELEMETRY_DIR
        P.STATE_DIR = tmp_path / "state"
        P.TELEMETRY_DIR = tmp_path / "telemetry"
        HH.STATE_DIR = P.STATE_DIR
        HH.TELEMETRY_DIR = P.TELEMETRY_DIR
        P.STATE_DIR.mkdir(parents=True, exist_ok=True)
        P.TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
        try:
            # Seed 3 hook-failure records
            with (P.TELEMETRY_DIR / "audit-log-hook-failed.jsonl").open(
                "w", encoding="utf-8"
            ) as f:
                for i in range(3):
                    f.write(_json.dumps({
                        "ts": "2026-05-10T00:00:0" + str(i) + "Z",
                        "agent": "harness-x",
                    }) + "\n")
            s = HH.section_audit_log()
            assert s["hook_failed_count"] == 3
        finally:
            P.STATE_DIR = old_state
            P.TELEMETRY_DIR = old_tel
            HH.STATE_DIR = old_hh_state
            HH.TELEMETRY_DIR = old_hh_tel


def test_render_text_audit_log_attention_when_hook_failed():
    """When hook_failed_count > 0, render an ATTENTION line — silent
    regression of the hook itself becomes operator-visible."""
    fake = _build_minimal_dashboard(
        phase_tree={"present": False, "path": "/x"}
    )
    fake["audit_log"] = {
        "total_sessions": 1,
        "total_invocations": 5,
        "by_agent": {"harness-critic": 5},
        "by_origin": {"hook": 5},
        "hook_failed_count": 7,
        "recent_invocations": [],
    }
    out = HH.render_text(fake)
    assert "hook_failed=7" in out
    assert "ATTENTION" in out


def test_section_operational_metrics_returns_5_keys():
    """5 sub_phase metrics with current/target/met flag."""
    s = HH.section_operational_metrics()
    if "error" in s:
        return  # acceptable on env without state dirs (defensive)
    assert "metrics" in s
    assert "met_count" in s
    assert "total_count" in s
    assert s["total_count"] == 5
    for name, m in s["metrics"].items():
        assert "current" in m
        assert "target" in m
        assert "met" in m


def test_render_text_operational_metrics_shows_progress():
    fake = _build_minimal_dashboard(
        phase_tree={"present": False, "path": "/x"}
    )
    fake["operational_metrics"] = {
        "metrics": {
            "autopilot_runs": {"current": 2, "target": 10, "met": False},
            "allsolution_runs": {"current": 1, "target": 1, "met": True},
        },
        "met_count": 1,
        "total_count": 2,
    }
    out = HH.render_text(fake)
    assert "[Operational] 1/2 targets met" in out
    assert "autopilot_runs" in out
    assert "[x]" in out  # ASCII met marker on allsolution_runs


TESTS = [
    test_build_dashboard_returns_all_sections,
    test_render_text_includes_all_section_headers,
    test_section_skills_inventory_returns_valid_shape,
    test_section_lint_status_handles_no_telemetry_gracefully,
    test_section_debate_state_returns_counts,
    test_section_strict_design_returns_counts,
    test_main_exits_zero_in_text_mode,
    test_section_phase_tree_returns_absent_when_handoff_missing,
    test_section_phase_tree_reports_in_sync,
    test_section_phase_tree_detects_drift,
    test_section_phase_tree_fail_soft_on_malformed_yaml,
    test_render_text_emits_phase_tree_line_for_in_sync,
    test_render_text_emits_phase_tree_line_for_drift,
    test_render_text_emits_phase_tree_line_for_absent,
    test_section_writeback_returns_zeros_on_empty_state,
    test_section_writeback_aggregates_by_status,
    test_render_text_writeback_branch_empty,
    test_render_text_writeback_branch_with_pending,
    test_section_audit_log_returns_zeros_on_empty_state,
    test_section_audit_log_aggregates_records,
    test_render_text_audit_log_branch_empty,
    test_render_text_audit_log_branch_with_data,
    test_section_audit_log_aggregates_by_origin,
    test_render_text_audit_log_shows_by_origin,
    test_section_audit_log_surfaces_hook_failed_count,
    test_render_text_audit_log_attention_when_hook_failed,
    test_section_operational_metrics_returns_5_keys,
    test_render_text_operational_metrics_shows_progress,
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
