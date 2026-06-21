#!/usr/bin/env python3
"""Tests for cli.debate_aggregate — cross-session debate events.jsonl reader.

Wave 11 S3 closure (interview-1779253986-8554c71f seed, success criterion 3).
≥6 test cases per seed.md spec — empty/single/multi-session, filters, formats.

Auto-discovered by tests/run_units.py via top-level main() -> int.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _write_events(session_dir: Path, events: list[dict]) -> Path:
    """Write events.jsonl in a session directory."""
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / "events.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return path


def _proposal(gen: int, topic: str, ts: str = "2026-05-20T00:00:00Z") -> dict:
    return {
        "ts": ts, "gen": gen, "type": "proposal", "actor": "harness-planner",
        "payload": {"topic_restatement": topic},
        "hash": "abc123",
    }


def _verdict(
    gen: int, verdict: str,
    accepted: list[str] | None = None,
    snapshot: str = "deadbeef" * 5,
    early_cap: bool = False,
    ts: str = "2026-05-20T00:01:00Z",
) -> dict:
    payload = {
        "verdict": verdict,
        "accepted_decisions": accepted or [],
        "ontology_sha1": snapshot,
    }
    if early_cap:
        payload["early_hard_cap_recommendation"] = True
    return {
        "ts": ts, "gen": gen, "type": "verdict", "actor": "harness-architect",
        "payload": payload, "hash": "def456",
    }


# ============================================================================
# Test cases
# ============================================================================


def test_empty_debates_dir_returns_empty():
    """Missing debates dir → empty list (graceful, no crash)."""
    from cli.debate_aggregate import aggregate
    with tempfile.TemporaryDirectory() as td:
        result = aggregate(Path(td) / "nonexistent")
        assert result == [], f"expected [], got {result}"


def test_empty_subdir_returns_empty():
    """debates/ exists but no session subdirs → empty list."""
    from cli.debate_aggregate import aggregate
    with tempfile.TemporaryDirectory() as td:
        debates = Path(td) / "debates"
        debates.mkdir()
        result = aggregate(debates)
        assert result == []


def test_single_session_basic_summary():
    """One session with proposal + verdict → summary populated correctly."""
    from cli.debate_aggregate import aggregate
    with tempfile.TemporaryDirectory() as td:
        debates = Path(td) / "debates"
        debates.mkdir()
        _write_events(debates / "debate-test-001", [
            _proposal(gen=1, topic="RLM_gate Path 2 implementation"),
            _verdict(gen=3, verdict="approved", accepted=["D1", "D2"],
                     snapshot="c75bfaf40398abc123"),
        ])
        result = aggregate(debates)
        assert len(result) == 1
        s = result[0]
        assert s.sid == "debate-test-001"
        assert s.topic == "RLM_gate Path 2 implementation"
        assert s.gen_count == 3
        assert s.terminal_verdict == "approved"
        assert s.accepted_decisions == ("D1", "D2")
        assert s.snapshot_hash == "c75bfaf40398abc123"


def test_multi_session_sorted_by_sid():
    """Multiple sessions returned in sorted sid order."""
    from cli.debate_aggregate import aggregate
    with tempfile.TemporaryDirectory() as td:
        debates = Path(td) / "debates"
        debates.mkdir()
        _write_events(debates / "debate-zzz", [_proposal(1, "topic-z"),
                                                 _verdict(1, "approved")])
        _write_events(debates / "debate-aaa", [_proposal(1, "topic-a"),
                                                 _verdict(1, "rejected")])
        _write_events(debates / "debate-mmm", [_proposal(1, "topic-m"),
                                                 _verdict(1, "conditional")])
        result = aggregate(debates)
        assert [r.sid for r in result] == [
            "debate-aaa", "debate-mmm", "debate-zzz",
        ]


def test_topic_filter_case_insensitive_substring():
    """--topic filter matches case-insensitive substring."""
    from cli.debate_aggregate import aggregate
    with tempfile.TemporaryDirectory() as td:
        debates = Path(td) / "debates"
        debates.mkdir()
        _write_events(debates / "debate-001", [
            _proposal(1, "RLM_gate Path 2 implementation"),
            _verdict(1, "approved"),
        ])
        _write_events(debates / "debate-002", [
            _proposal(1, "ambiguity score rebalance"),
            _verdict(1, "approved"),
        ])
        # Case insensitive
        result = aggregate(debates, topic_filter="rlm_gate")
        assert len(result) == 1
        assert result[0].sid == "debate-001"
        # Different topic
        result = aggregate(debates, topic_filter="AMBIGUITY")
        assert len(result) == 1
        assert result[0].sid == "debate-002"
        # No match
        result = aggregate(debates, topic_filter="nonexistent")
        assert result == []


def test_verdict_filter():
    """--verdict filter narrows to terminal_verdict == value."""
    from cli.debate_aggregate import aggregate
    with tempfile.TemporaryDirectory() as td:
        debates = Path(td) / "debates"
        debates.mkdir()
        _write_events(debates / "debate-a", [_proposal(1, "t1"),
                                              _verdict(1, "approved")])
        _write_events(debates / "debate-b", [_proposal(1, "t2"),
                                              _verdict(1, "rejected")])
        _write_events(debates / "debate-c", [_proposal(1, "t3"),
                                              _verdict(1, "conditional")])
        approved = aggregate(debates, verdict_filter="approved")
        assert [r.sid for r in approved] == ["debate-a"]
        rejected = aggregate(debates, verdict_filter="rejected")
        assert [r.sid for r in rejected] == ["debate-b"]


def test_since_filter():
    """--since filter narrows by first_ts >= date."""
    from cli.debate_aggregate import aggregate
    with tempfile.TemporaryDirectory() as td:
        debates = Path(td) / "debates"
        debates.mkdir()
        _write_events(debates / "debate-old", [
            _proposal(1, "old topic", ts="2026-04-01T00:00:00Z"),
            _verdict(1, "approved", ts="2026-04-01T00:01:00Z"),
        ])
        _write_events(debates / "debate-new", [
            _proposal(1, "new topic", ts="2026-05-20T00:00:00Z"),
            _verdict(1, "approved", ts="2026-05-20T00:01:00Z"),
        ])
        result = aggregate(debates, since="2026-05-01")
        assert [r.sid for r in result] == ["debate-new"]


def test_format_json_output():
    """--format json produces valid JSON list with all fields."""
    from cli.debate_aggregate import main
    with tempfile.TemporaryDirectory() as td:
        debates = Path(td) / "debates"
        debates.mkdir()
        _write_events(debates / "debate-001", [
            _proposal(1, "test"), _verdict(2, "approved",
                                            accepted=["D1"], snapshot="abc123"),
        ])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--format", "json", "--debates-dir", str(debates)])
        assert rc == 0
        out = buf.getvalue()
        decoded = json.loads(out)
        assert isinstance(decoded, list)
        assert len(decoded) == 1
        assert decoded[0]["sid"] == "debate-001"
        assert decoded[0]["terminal_verdict"] == "approved"
        assert decoded[0]["accepted_decisions"] == ["D1"]
        assert decoded[0]["gen_count"] == 2


def test_format_table_output_header():
    """--format table (default) produces header + footer."""
    from cli.debate_aggregate import main
    with tempfile.TemporaryDirectory() as td:
        debates = Path(td) / "debates"
        debates.mkdir()
        _write_events(debates / "debate-001", [
            _proposal(1, "test topic"), _verdict(1, "approved"),
        ])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--format", "table", "--debates-dir", str(debates)])
        assert rc == 0
        out = buf.getvalue()
        assert "debate aggregate (1 sessions)" in out
        assert "debate-001" in out
        assert "approved" in out
        assert "verdict distribution" in out


def test_malformed_events_silently_skipped():
    """Malformed JSON lines in events.jsonl → skipped, scan continues."""
    from cli.debate_aggregate import aggregate
    with tempfile.TemporaryDirectory() as td:
        debates = Path(td) / "debates"
        debates.mkdir()
        session_dir = debates / "debate-broken"
        session_dir.mkdir()
        path = session_dir / "events.jsonl"
        # Mix valid + malformed lines
        path.write_text(
            json.dumps(_proposal(1, "valid topic")) + "\n"
            "{not valid json}\n"
            + json.dumps(_verdict(1, "approved")) + "\n",
            encoding="utf-8",
        )
        result = aggregate(debates)
        # Should still return one summary (malformed line skipped)
        assert len(result) == 1
        assert result[0].topic == "valid topic"
        assert result[0].terminal_verdict == "approved"


def test_early_hard_cap_marker():
    """early_hard_cap_recommendation in verdict payload sets flag."""
    from cli.debate_aggregate import aggregate
    with tempfile.TemporaryDirectory() as td:
        debates = Path(td) / "debates"
        debates.mkdir()
        _write_events(debates / "debate-stagnated", [
            _proposal(1, "stagnated debate"),
            _verdict(3, "conditional", early_cap=True),
        ])
        result = aggregate(debates)
        assert len(result) == 1
        assert result[0].early_hard_cap is True


def test_session_without_verdict_still_returned():
    """In-progress session (proposal only, no verdict) still returned."""
    from cli.debate_aggregate import aggregate
    with tempfile.TemporaryDirectory() as td:
        debates = Path(td) / "debates"
        debates.mkdir()
        _write_events(debates / "debate-inprogress", [
            _proposal(1, "in-progress topic"),
        ])
        result = aggregate(debates)
        assert len(result) == 1
        assert result[0].terminal_verdict is None
        assert result[0].snapshot_hash is None
        assert result[0].accepted_decisions == ()


def test_topic_field_fallback():
    """Proposal payload `topic` (orchestrator-persisted, M1) read when topic_restatement absent."""
    from cli.debate_aggregate import aggregate
    with tempfile.TemporaryDirectory() as td:
        debates = Path(td) / "debates"
        debates.mkdir()
        _write_events(debates / "debate-topicfield", [
            {"ts": "2026-06-01T00:00:00Z", "gen": 1, "type": "proposal",
             "actor": "harness-planner",
             "payload": {"topic": "wire researcher dispatch"}, "hash": "h"},
            _verdict(1, "approved", accepted=["D1"]),
        ])
        result = aggregate(debates)
        assert len(result) == 1
        assert result[0].topic == "wire researcher dispatch"


def test_render_planner_context_empty():
    """No summaries → empty string so callers can include it unconditionally."""
    from cli.debate_aggregate import render_planner_context
    assert render_planner_context([]) == ""


def test_render_planner_context_splits_rejected_and_accepted():
    """Block separates REJECTED/STALLED from ACCEPTED and carries the no-veto advisory."""
    from cli.debate_aggregate import aggregate, render_planner_context
    with tempfile.TemporaryDirectory() as td:
        debates = Path(td) / "debates"
        debates.mkdir()
        _write_events(debates / "debate-rej", [
            _proposal(1, "competing parallel tree"), _verdict(2, "rejected"),
        ])
        _write_events(debates / "debate-cap", [
            _proposal(1, "stalled oscillation"),
            _verdict(4, "conditional", early_cap=True),
        ])
        _write_events(debates / "debate-acc", [
            _proposal(1, "dual storage layout"),
            _verdict(2, "approved", accepted=["mirror under atlas", "global brain"]),
        ])
        block = render_planner_context(aggregate(debates))
        assert block.startswith("<prior_debates>")
        assert block.rstrip().endswith("</prior_debates>")
        assert "not a veto" in block.lower()
        assert "REJECTED / STALLED" in block
        assert "competing parallel tree" in block
        assert "early_hard_cap" in block        # conditional+cap tagged as stalled
        assert "ACCEPTED" in block
        assert "dual storage layout" in block
        assert "mirror under atlas" in block


def test_format_planner_context_cli():
    """--format planner-context emits the <prior_debates> block via main()."""
    from cli.debate_aggregate import main
    with tempfile.TemporaryDirectory() as td:
        debates = Path(td) / "debates"
        debates.mkdir()
        _write_events(debates / "debate-x", [
            _proposal(1, "some topic"), _verdict(1, "approved", accepted=["D1"]),
        ])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--format", "planner-context", "--debates-dir", str(debates)])
        assert rc == 0
        out = buf.getvalue()
        assert "<prior_debates>" in out
        assert "some topic" in out


def test_early_hard_cap_from_convergence_event():
    """M14 (D3): a convergence{status:early_hard_cap} event sets early_hard_cap=True.

    EventStore is append-only so the verdict event can't be patched; the
    deterministic cli.debate_stagnation_check writes the signal as its own
    convergence/recommendation events, which _summarize_session must read.
    """
    from cli.debate_aggregate import aggregate
    with tempfile.TemporaryDirectory() as td:
        debates = Path(td) / "debates"
        debates.mkdir()
        _write_events(debates / "debate-eh-conv", [
            _proposal(1, "stagnated debate"),
            _verdict(2, "rejected"),
            {"ts": "2026-06-16T00:02:00Z", "gen": 2, "type": "convergence",
             "actor": "debate_stagnation_check",
             "payload": {"status": "early_hard_cap", "gen": 2, "terminal": True},
             "hash": "h"},
        ])
        result = aggregate(debates)
        assert len(result) == 1
        assert result[0].early_hard_cap is True


def test_early_hard_cap_from_recommendation_event():
    """M14 (D3): an early_hard_cap_recommendation{recommend:True} event also sets it."""
    from cli.debate_aggregate import aggregate
    with tempfile.TemporaryDirectory() as td:
        debates = Path(td) / "debates"
        debates.mkdir()
        _write_events(debates / "debate-eh-rec", [
            _proposal(1, "stagnated debate"),
            {"ts": "2026-06-16T00:01:30Z", "gen": 2, "type": "early_hard_cap_recommendation",
             "actor": "debate_stagnation_check",
             "payload": {"recommend": True, "reasons": ["oscillation"]}, "hash": "h"},
            _verdict(2, "rejected"),
        ])
        result = aggregate(debates)
        assert result[0].early_hard_cap is True
        # a recommend=False recommendation must NOT set it
        _write_events(debates / "debate-eh-rec-false", [
            _proposal(1, "healthy debate"),
            {"ts": "2026-06-16T00:01:30Z", "gen": 2, "type": "early_hard_cap_recommendation",
             "actor": "debate_stagnation_check",
             "payload": {"recommend": False, "reasons": []}, "hash": "h"},
            _verdict(2, "conditional"),
        ])
        false_summary = [r for r in aggregate(debates) if r.sid == "debate-eh-rec-false"][0]
        assert false_summary.early_hard_cap is False


# ============================================================================
# M8 — cross-session blocker-axis advisory
# ============================================================================


def _critique(gen: int, axes: list[str], ts: str = "2026-05-20T00:00:30Z") -> dict:
    return {
        "ts": ts, "gen": gen, "type": "critique", "actor": "harness-critic",
        "payload": {"blockers": [{"axis": a, "severity": "high"} for a in axes]},
        "hash": "c0ffee",
    }


def _critique_full(gen: int, blockers: list[dict], ts: str = "2026-05-20T00:00:30Z") -> dict:
    """M30: critique event carrying full blocker dicts (custom severity/claim/target)."""
    return {
        "ts": ts, "gen": gen, "type": "critique", "actor": "harness-critic",
        "payload": {"blockers": blockers},
        "hash": "c0ffee",
    }


def test_blocker_axes_extracted_from_critique():
    import cli.debate_aggregate as da
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_events(root / "debate-1", [
            _proposal(1, "x"), _critique(1, ["assumption", "failure"]),
            _critique(2, ["assumption"]), _verdict(2, "approved"),
        ])
        summ = da.aggregate(root)
        assert len(summ) == 1
        # int-count form contributes no axes; list-of-dicts contributes axis values
        assert summ[0].blocker_axes == ("assumption", "failure", "assumption")
        assert summ[0].stalled is False  # approved


def test_blocker_advisory_empty_below_threshold():
    import cli.debate_aggregate as da
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # Only 2 sessions with axis data (< BLOCKER_ADVISORY_MIN_SESSIONS=3) -> ""
        _write_events(root / "d1", [_proposal(1, "a"), _critique(1, ["failure"]), _verdict(1, "approved")])
        _write_events(root / "d2", [_proposal(1, "b"), _critique(1, ["assumption"]), _verdict(1, "approved")])
        assert da.render_blocker_advisory(da.aggregate(root)) == ""


def test_blocker_advisory_ranks_dominant_axis_with_tip():
    import cli.debate_aggregate as da
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # 3 sessions; 'failure' dominates (4 vs assumption 1)
        _write_events(root / "d1", [_proposal(1, "a"), _critique(1, ["failure", "failure"]), _verdict(1, "approved")])
        _write_events(root / "d2", [_proposal(1, "b"), _critique(1, ["failure"]), _verdict(1, "approved")])
        _write_events(root / "d3", [_proposal(1, "c"), _critique(1, ["failure", "assumption"]), _verdict(1, "approved")])
        adv = da.render_blocker_advisory(da.aggregate(root))
        assert "<recurring_blockers>" in adv and "across 3 prior debates" in adv
        assert "DOMINANT = failure" in adv
        assert "enumerate failure modes" in adv  # the tip
        # failure ranked above assumption
        assert adv.index("- failure") < adv.index("- assumption")


def test_blocker_advisory_highlights_stalled():
    import cli.debate_aggregate as da
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_events(root / "d1", [_proposal(1, "a"), _critique(1, ["failure"]), _verdict(1, "approved")])
        _write_events(root / "d2", [_proposal(1, "b"), _critique(1, ["assumption"]), _verdict(1, "approved")])
        # a stalled (conditional) session with axis data
        _write_events(root / "d3", [_proposal(1, "c"), _critique(1, ["simplification"]), _verdict(1, "conditional")])
        adv = da.render_blocker_advisory(da.aggregate(root))
        assert "1 STALLED" in adv and "simplification(1)" in adv


def test_format_blocker_advisory_cli():
    import cli.debate_aggregate as da
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for i, ax in enumerate(["failure", "failure", "assumption"]):
            _write_events(root / f"d{i}", [_proposal(1, "t"), _critique(1, [ax]), _verdict(1, "approved")])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = da.main(["--debates-dir", str(root), "--format", "blocker-advisory"])
        assert rc == 0
        assert "<recurring_blockers>" in buf.getvalue()


# ---- M30: severity-calibration + criticism-diversity ----

def test_severity_calibration_surfaces_only_triage_changing():
    import cli.debate_aggregate as da
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        blockers = [
            {"axis": "failure", "claim": "embedder no provider binding", "severity": "blocker", "target_decision": "D2"},
            {"axis": "assumption", "claim": "citation misattributed", "severity": "high", "target_decision": "D3"},
            {"axis": "failure", "claim": "no observable detector", "target_decision": "D1"},  # missing severity -> UNSPEC
        ]
        _write_events(root / "d1", [_proposal(1, "t"), _critique_full(1, blockers), _verdict(1, "approved")])
        out = da.render_severity_calibration(da.aggregate(root))
        assert "<severity_calibration>" in out
        # 'blocker' raw normalizes to HIGH (triage-changing) -> surfaced
        assert "raw='blocker' -> HIGH" in out
        # missing severity -> UNSPEC (untriageable) -> surfaced
        assert "-> UNSPEC" in out
        # raw 'high' already == canonical HIGH -> SUPPRESSED (no triage change)
        assert "raw='high'" not in out


def test_severity_calibration_empty_when_all_identity():
    import cli.debate_aggregate as da
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        blockers = [
            {"axis": "failure", "claim": "x", "severity": "high"},
            {"axis": "failure", "claim": "y", "severity": "low"},
        ]
        _write_events(root / "d1", [_proposal(1, "t"), _critique_full(1, blockers), _verdict(1, "approved")])
        # every raw token == its canonical bucket -> nothing to surface -> ""
        assert da.render_severity_calibration(da.aggregate(root)) == ""


def test_criticism_diversity_unspec_fires_above_threshold():
    import cli.debate_aggregate as da
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # 3 blocker-bearing sessions; 1-of-3 blockers UNSPEC = 33% >= 0.20 -> fires
        for i in range(3):
            blockers = [
                {"axis": "failure", "claim": f"alpha{i} unique here", "severity": "high"},
                {"axis": "assumption", "claim": f"beta{i} other thing"},  # UNSPEC
                {"axis": "failure", "claim": f"gamma{i} third item", "severity": "med"},
            ]
            _write_events(root / f"d{i}", [_proposal(1, "t"), _critique_full(1, blockers), _verdict(1, "approved")])
        out = da.render_criticism_diversity(da.aggregate(root))
        assert "<criticism_diversity>" in out
        assert "overlap_rate:" in out and "HIGH-rate" in out
        assert "UNSPEC_UNCALIBRATED" in out


def test_criticism_diversity_unspec_silent_below_threshold():
    import cli.debate_aggregate as da
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # all blockers carry a recognizable severity -> unspec_rate 0% -> no UNSPEC line
        for i in range(3):
            blockers = [
                {"axis": "failure", "claim": f"alpha{i} unique here", "severity": "high"},
                {"axis": "assumption", "claim": f"beta{i} other thing", "severity": "medium"},
            ]
            _write_events(root / f"d{i}", [_proposal(1, "t"), _critique_full(1, blockers), _verdict(1, "approved")])
        out = da.render_criticism_diversity(da.aggregate(root))
        assert "<criticism_diversity>" in out         # measurement still reports
        assert "UNSPEC_UNCALIBRATED" not in out        # predicate silent below 0.20


def test_criticism_diversity_empty_below_min_sessions():
    import cli.debate_aggregate as da
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for i in range(2):  # only 2 blocker-bearing sessions < MIN(3)
            _write_events(root / f"d{i}", [_proposal(1, "t"),
                          _critique_full(1, [{"axis": "failure", "claim": "x", "severity": "high"}]),
                          _verdict(1, "approved")])
        assert da.render_criticism_diversity(da.aggregate(root)) == ""


def test_criticism_diversity_trailing_window_turns_unspec_off():
    """Load-bearing (gen-2 Critic's slow-dead-guard fix): an OLD high-UNSPEC session
    falling OUTSIDE the trailing window must let the windowed unspec_rate drop below
    threshold and turn UNSPEC_UNCALIBRATED OFF."""
    import cli.debate_aggregate as da
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # 1 OLD session full of UNSPEC blockers
        old = [{"axis": "failure", "claim": f"legacy{i} unspec blocker"} for i in range(5)]
        _write_events(root / "old", [_proposal(1, "t", ts="2020-01-01T00:00:00Z"),
                      _critique_full(1, old, ts="2020-01-01T00:00:30Z"),
                      _verdict(1, "approved", ts="2020-01-01T00:01:00Z")])
        # 3 RECENT clean-severity sessions
        for i in range(3):
            clean = [{"axis": "failure", "claim": f"clean{i} item {j}", "severity": "high"} for j in range(3)]
            _write_events(root / f"new{i}", [_proposal(1, "t", ts=f"2026-06-1{i}T00:00:00Z"),
                          _critique_full(1, clean, ts=f"2026-06-1{i}T00:00:30Z"),
                          _verdict(1, "approved", ts=f"2026-06-1{i}T00:01:00Z")])
        summaries = da.aggregate(root)
        # all-time (window large enough to include old) -> UNSPEC fires
        wide = da.render_criticism_diversity(summaries, window=20)
        assert "UNSPEC_UNCALIBRATED" in wide
        # trailing window of 3 excludes the old session -> UNSPEC OFF
        narrow = da.render_criticism_diversity(summaries, window=3)
        assert "<criticism_diversity>" in narrow and "UNSPEC_UNCALIBRATED" not in narrow


def test_format_severity_calibration_and_diversity_cli():
    import cli.debate_aggregate as da
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for i in range(3):
            blockers = [
                {"axis": "failure", "claim": f"alpha{i} unique", "severity": "blocker"},
                {"axis": "assumption", "claim": f"beta{i} thing"},  # UNSPEC
            ]
            _write_events(root / f"d{i}", [_proposal(1, "t"), _critique_full(1, blockers), _verdict(1, "approved")])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = da.main(["--debates-dir", str(root), "--format", "criticism-diversity"])
        assert rc == 0 and "<criticism_diversity>" in buf.getvalue()
        # severity-calibration scoped to one session via --session-id
        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            rc2 = da.main(["--debates-dir", str(root), "--format", "severity-calibration",
                           "--session-id", "d0"])
        assert rc2 == 0 and "<severity_calibration>" in buf2.getvalue()


# ---- M31: research-provenance (discover-vs-confirm / IKD proxy) ----

def _proposal_cited(gen: int, citations: list, ts: str = "2026-05-20T00:00:00Z") -> dict:
    ev = _proposal(gen, "t", ts)
    ev["payload"]["research_citations"] = citations
    return ev


def test_research_provenance_flags_confirm_only_not_internal():
    import cli.debate_aggregate as da
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # 8+ proposals: mostly internal (no citations), 1 discovered, 1 confirm_only
        for i in range(8):
            _write_events(root / f"int{i}", [_proposal(1, "internal design"), _verdict(1, "approved")])
        _write_events(root / "disc", [_proposal_cited(1, [{"url": "https://serde.rs/x", "load_bearing_for": "D1"}]),
                                      _verdict(1, "approved")])
        _write_events(root / "conf", [_proposal_cited(1, [{"source": "scripts/lib/foo.py"}]),
                                      _verdict(1, "approved")])
        out = da.render_research_provenance(da.aggregate(root))
        assert "<research_provenance>" in out
        # internal-only is framed as expected, NOT flagged
        assert "internal_only" in out and "expected for internal harness design" in out
        # the narrow live flag fires and names the confirm-only session
        assert "CONFIRM_ONLY" in out and "conf" in out
        # discovered counted
        assert "citation_grounded: 1" in out


def test_research_provenance_empty_below_min_proposals():
    import cli.debate_aggregate as da
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for i in range(3):  # < RESEARCH_PROVENANCE_MIN_PROPOSALS (8)
            _write_events(root / f"d{i}", [_proposal(1, "t"), _verdict(1, "approved")])
        assert da.render_research_provenance(da.aggregate(root)) == ""


def test_research_provenance_silent_when_no_confirm_only():
    import cli.debate_aggregate as da
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for i in range(8):
            _write_events(root / f"d{i}", [_proposal(1, "internal"), _verdict(1, "approved")])
        out = da.render_research_provenance(da.aggregate(root))
        assert "<research_provenance>" in out          # still reports the measurement
        assert "CONFIRM_ONLY" not in out                # no confirm-only proposals -> flag silent


def test_format_research_provenance_cli_and_malformed_citations():
    import cli.debate_aggregate as da
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for i in range(8):
            _write_events(root / f"d{i}", [_proposal(1, "t"), _verdict(1, "approved")])
        # a proposal with a malformed int research_citations must not crash aggregation
        _write_events(root / "bad", [_proposal_cited(1, []), _verdict(1, "approved")])
        bad_ev = _proposal(1, "t")
        bad_ev["payload"]["research_citations"] = 5  # malformed (live-data shape)
        _write_events(root / "bad2", [bad_ev, _verdict(1, "approved")])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = da.main(["--debates-dir", str(root), "--format", "research-provenance"])
        assert rc == 0 and "<research_provenance>" in buf.getvalue()


# ============================================================================
# Runner
# ============================================================================


TESTS = [
    test_empty_debates_dir_returns_empty,
    test_empty_subdir_returns_empty,
    test_single_session_basic_summary,
    test_multi_session_sorted_by_sid,
    test_topic_filter_case_insensitive_substring,
    test_verdict_filter,
    test_since_filter,
    test_format_json_output,
    test_format_table_output_header,
    test_malformed_events_silently_skipped,
    test_early_hard_cap_marker,
    test_session_without_verdict_still_returned,
    test_topic_field_fallback,
    test_render_planner_context_empty,
    test_render_planner_context_splits_rejected_and_accepted,
    test_format_planner_context_cli,
    test_early_hard_cap_from_convergence_event,
    test_early_hard_cap_from_recommendation_event,
    test_blocker_axes_extracted_from_critique,
    test_blocker_advisory_empty_below_threshold,
    test_blocker_advisory_ranks_dominant_axis_with_tip,
    test_blocker_advisory_highlights_stalled,
    test_format_blocker_advisory_cli,
    test_severity_calibration_surfaces_only_triage_changing,
    test_severity_calibration_empty_when_all_identity,
    test_criticism_diversity_unspec_fires_above_threshold,
    test_criticism_diversity_unspec_silent_below_threshold,
    test_criticism_diversity_empty_below_min_sessions,
    test_criticism_diversity_trailing_window_turns_unspec_off,
    test_format_severity_calibration_and_diversity_cli,
    test_research_provenance_flags_confirm_only_not_internal,
    test_research_provenance_empty_below_min_proposals,
    test_research_provenance_silent_when_no_confirm_only,
    test_format_research_provenance_cli_and_malformed_citations,
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
