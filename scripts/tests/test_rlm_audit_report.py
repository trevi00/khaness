#!/usr/bin/env python3
"""Tests for cli.rlm_audit_report — wave 10 dead-end surface reader.

Wave 11 S4 closure (interview-1779253986-8554c71f seed, success criterion 4).
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


def _audit_row(
    depth: int,
    branch: str,
    *,
    ts: str = "2026-05-20T00:00:00Z",
    prompt_sha1: str = "a" * 40,
    prompt_len_chars: int = 100,
    child_call_count: int = 0,
    model: str = "codex-default",
    parent_sha1: str | None = None,
    elapsed_seconds: float = 0.5,
    reason: str | None = None,
) -> dict:
    """Build one rlm_audit.jsonl row."""
    row = {
        "ts": ts,
        "depth": depth,
        "prompt_sha1": prompt_sha1,
        "prompt_len_chars": prompt_len_chars,
        "child_call_count": child_call_count,
        "branch": branch,
        "model": model,
        "parent_sha1": parent_sha1,
        "elapsed_seconds": elapsed_seconds,
    }
    if reason is not None:
        row["reason"] = reason
    return row


def _write_audit(session_dir: Path, rows: list[dict]) -> Path:
    """Write rlm_audit.jsonl in a session directory."""
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / "rlm_audit.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


# ============================================================================
# Test cases
# ============================================================================


def test_empty_evaluator_dir_returns_empty_aggregate():
    """Missing evaluator dir → AuditAggregate(total_rows=0)."""
    from cli.rlm_audit_report import aggregate
    with tempfile.TemporaryDirectory() as td:
        agg = aggregate(Path(td) / "nonexistent")
        assert agg.total_rows == 0
        assert agg.depth_dist == {} or len(agg.depth_dist) == 0


def test_session_without_audit_file_skipped():
    """Session dir exists but no rlm_audit.jsonl → skip cleanly."""
    from cli.rlm_audit_report import aggregate
    with tempfile.TemporaryDirectory() as td:
        ev = Path(td) / "evaluator"
        ev.mkdir()
        (ev / "orch-empty").mkdir()
        agg = aggregate(ev)
        assert agg.total_rows == 0


def test_single_session_aggregates_depth_and_branch():
    """Single session with mixed rows → depth + branch + elapsed populated."""
    from cli.rlm_audit_report import aggregate
    with tempfile.TemporaryDirectory() as td:
        ev = Path(td) / "evaluator"
        ev.mkdir()
        _write_audit(ev / "orch-001", [
            _audit_row(depth=0, branch="recursive", child_call_count=3,
                       elapsed_seconds=1.5),
            _audit_row(depth=1, branch="flat_base_case",
                       reason="depth_cap", elapsed_seconds=0.3),
            _audit_row(depth=1, branch="flat_base_case",
                       reason="short_prompt", elapsed_seconds=0.2),
        ])
        agg = aggregate(ev)
        assert agg.total_rows == 3
        assert agg.depth_dist[0] == 1
        assert agg.depth_dist[1] == 2
        assert agg.branch_dist["recursive"] == 1
        assert agg.branch_dist["flat_base_case"] == 2
        assert agg.child_count_dist[3] == 1
        assert agg.child_count_dist[0] == 2
        assert agg.reason_dist["depth_cap"] == 1
        assert agg.reason_dist["short_prompt"] == 1
        assert len(agg.elapsed_values) == 3


def test_multi_session_aggregates_across_dirs():
    """Multi-session rows summed across sid_dist."""
    from cli.rlm_audit_report import aggregate
    with tempfile.TemporaryDirectory() as td:
        ev = Path(td) / "evaluator"
        ev.mkdir()
        _write_audit(ev / "orch-a", [
            _audit_row(depth=0, branch="recursive", elapsed_seconds=1.0),
        ])
        _write_audit(ev / "orch-b", [
            _audit_row(depth=0, branch="flat_base_case",
                       reason="short_prompt", elapsed_seconds=0.5),
            _audit_row(depth=1, branch="flat_base_case",
                       reason="depth_cap", elapsed_seconds=0.2),
        ])
        agg = aggregate(ev)
        assert agg.total_rows == 3
        assert agg.sid_dist["orch-a"] == 1
        assert agg.sid_dist["orch-b"] == 2
        assert len(agg.sid_dist) == 2


def test_since_filter_narrows_by_ts():
    """--since filter excludes rows with ts < since."""
    from cli.rlm_audit_report import aggregate
    with tempfile.TemporaryDirectory() as td:
        ev = Path(td) / "evaluator"
        ev.mkdir()
        _write_audit(ev / "orch-001", [
            _audit_row(depth=0, branch="recursive",
                       ts="2026-04-01T00:00:00Z"),
            _audit_row(depth=0, branch="recursive",
                       ts="2026-05-20T00:00:00Z"),
        ])
        agg = aggregate(ev, since="2026-05-01")
        assert agg.total_rows == 1
        assert agg.depth_dist[0] == 1


def test_sid_filter_restricts_to_single_session():
    """--sid filter narrows to one session_dir name."""
    from cli.rlm_audit_report import aggregate
    with tempfile.TemporaryDirectory() as td:
        ev = Path(td) / "evaluator"
        ev.mkdir()
        _write_audit(ev / "orch-a", [
            _audit_row(depth=0, branch="recursive"),
        ])
        _write_audit(ev / "orch-b", [
            _audit_row(depth=0, branch="flat_base_case", reason="short_prompt"),
            _audit_row(depth=1, branch="flat_base_case", reason="depth_cap"),
        ])
        agg = aggregate(ev, sid_filter="orch-b")
        assert agg.total_rows == 2
        assert agg.sid_dist["orch-b"] == 2
        assert "orch-a" not in agg.sid_dist


def test_format_table_empty_state():
    """--format table with 0 rows produces explanatory empty message."""
    from cli.rlm_audit_report import main
    with tempfile.TemporaryDirectory() as td:
        ev = Path(td) / "evaluator"
        ev.mkdir()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--format", "table", "--evaluator-dir", str(ev)])
        assert rc == 0
        out = buf.getvalue()
        assert "0 rows" in out
        assert "RlmCodexProvider" in out


def test_format_table_populated():
    """--format table with rows includes depth/branch sections."""
    from cli.rlm_audit_report import main
    with tempfile.TemporaryDirectory() as td:
        ev = Path(td) / "evaluator"
        ev.mkdir()
        _write_audit(ev / "orch-001", [
            _audit_row(depth=0, branch="recursive", child_call_count=2,
                       elapsed_seconds=1.5),
            _audit_row(depth=1, branch="flat_base_case",
                       reason="depth_cap", elapsed_seconds=0.3),
        ])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--format", "table", "--evaluator-dir", str(ev)])
        assert rc == 0
        out = buf.getvalue()
        assert "2 rows" in out
        assert "Depth distribution" in out
        assert "Branch breakdown" in out
        assert "recursive" in out
        assert "flat_base_case" in out
        assert "Elapsed seconds" in out
        assert "depth_cap" in out


def test_format_json_valid_structure():
    """--format json produces valid JSON dict with expected keys."""
    from cli.rlm_audit_report import main
    with tempfile.TemporaryDirectory() as td:
        ev = Path(td) / "evaluator"
        ev.mkdir()
        _write_audit(ev / "orch-001", [
            _audit_row(depth=0, branch="recursive", child_call_count=2,
                       elapsed_seconds=1.0),
        ])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--format", "json", "--evaluator-dir", str(ev)])
        assert rc == 0
        decoded = json.loads(buf.getvalue())
        assert decoded["total_rows"] == 1
        assert "depth_distribution" in decoded
        assert "branch_distribution" in decoded
        assert "child_count_distribution" in decoded
        assert "elapsed_seconds" in decoded
        assert decoded["elapsed_seconds"]["min"] is not None
        assert decoded["branch_distribution"]["recursive"] == 1


def test_malformed_rows_silently_skipped():
    """Malformed JSON lines in rlm_audit.jsonl → per-line skip."""
    from cli.rlm_audit_report import aggregate
    with tempfile.TemporaryDirectory() as td:
        ev = Path(td) / "evaluator"
        ev.mkdir()
        session_dir = ev / "orch-broken"
        session_dir.mkdir()
        path = session_dir / "rlm_audit.jsonl"
        # Mix valid + malformed
        path.write_text(
            json.dumps(_audit_row(depth=0, branch="recursive")) + "\n"
            "{not valid json\n"
            + json.dumps(_audit_row(depth=1, branch="flat_base_case",
                                     reason="depth_cap")) + "\n",
            encoding="utf-8",
        )
        agg = aggregate(ev)
        assert agg.total_rows == 2
        assert agg.depth_dist[0] == 1
        assert agg.depth_dist[1] == 1


def test_elapsed_percentile_stats():
    """elapsed_seconds min/median/p95/max calculated correctly."""
    from cli.rlm_audit_report import aggregate
    with tempfile.TemporaryDirectory() as td:
        ev = Path(td) / "evaluator"
        ev.mkdir()
        rows = [
            _audit_row(depth=0, branch="recursive", elapsed_seconds=v)
            for v in [0.1, 0.5, 1.0, 2.0, 10.0]
        ]
        _write_audit(ev / "orch-001", rows)
        agg = aggregate(ev)
        stats = agg.to_dict()["elapsed_seconds"]
        assert stats["min"] == 0.1
        assert stats["max"] == 10.0
        assert stats["median"] == 1.0
        # p95 = index int(0.95 * 5) = 4 → 10.0
        assert stats["p95"] == 10.0


def test_top_models_aggregated():
    """top_models in to_dict() reflects model_dist Counter."""
    from cli.rlm_audit_report import aggregate
    with tempfile.TemporaryDirectory() as td:
        ev = Path(td) / "evaluator"
        ev.mkdir()
        rows = []
        # 3 codex, 2 claude, 1 ollama
        for _ in range(3):
            rows.append(_audit_row(depth=0, branch="recursive",
                                    model="codex-default"))
        for _ in range(2):
            rows.append(_audit_row(depth=0, branch="recursive",
                                    model="claude-sonnet-4-6"))
        rows.append(_audit_row(depth=0, branch="recursive",
                                model="llama3.1:8b"))
        _write_audit(ev / "orch-001", rows)
        agg = aggregate(ev)
        top = agg.to_dict()["top_models"]
        assert top["codex-default"] == 3
        assert top["claude-sonnet-4-6"] == 2
        assert top["llama3.1:8b"] == 1


# ============================================================================
# Runner
# ============================================================================


TESTS = [
    test_empty_evaluator_dir_returns_empty_aggregate,
    test_session_without_audit_file_skipped,
    test_single_session_aggregates_depth_and_branch,
    test_multi_session_aggregates_across_dirs,
    test_since_filter_narrows_by_ts,
    test_sid_filter_restricts_to_single_session,
    test_format_table_empty_state,
    test_format_table_populated,
    test_format_json_valid_structure,
    test_malformed_rows_silently_skipped,
    test_elapsed_percentile_stats,
    test_top_models_aggregated,
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
