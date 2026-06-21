#!/usr/bin/env python3
"""Unit tests for the insight_index_pollution_detector CLI `detect` path.

Covers the D4 detect/--execute consumer added 2026-06-03:
  - dry-run reports confirmed pollution without mutating
  - --execute without the measure ready-flag refuses (SystemExit 3)
  - --execute with the flag retracts burst pollution, PRESERVES records with a
    live fs artifact (real runs), and consumes the flag

Isolation: CLAUDE_HOME is pointed at a temp dir (insight_index + the detector
resolve all paths from it at call time), so this never touches the real index.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_ORIG_CLAUDE_HOME = os.environ.get("CLAUDE_HOME")


def _rec(id_: str, ts_ms: int, cid: str, sm: str = "engine.orchestrator") -> dict:
    return {
        "id": id_, "schema_version": "1", "ts_unix_ms": ts_ms,
        "event_type": "completion", "summary": "x", "correlation_id": cid,
        "source_module": sm, "axis": "completion", "tags": [], "body_ref": None,
    }


def _write_index(home: Path, records: list[dict]) -> None:
    idx = home / "memory" / "insight-index.jsonl"
    idx.parent.mkdir(parents=True, exist_ok=True)
    idx.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def test_detect_execute_retracts_pollution_preserves_real_and_gates_on_flag():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        os.environ["CLAUDE_HOME"] = str(home)
        try:
            from cli import insight_index_pollution_detector as cli_pd
            from lib import insight_index_pollution_detector as pd
            from lib import insight_index as ii

            base = 1700000000000  # aligned so base..base+20 share one 250ms bucket
            polluted = [_rec(f"p{i}", base + i * 10, f"orch-x-{i}") for i in range(3)]
            real_cid = "orch-real-1"
            (home / "state" / "orchestrator" / real_cid).mkdir(parents=True)
            real = _rec("real1", base + 5, real_cid)  # bursty BUT has a live artifact
            _write_index(home, polluted + [real])

            # dry-run: confirms 3 polluted, mutates nothing
            assert cli_pd._cmd_detect(SimpleNamespace(execute=False)) == 0
            assert len(pd.confirm_pollution(
                pd.cluster_pollution_candidates(pd.load_entries()))) == 3

            # --execute without ready-flag → SystemExit(3)
            raised = False
            try:
                cli_pd._cmd_detect(SimpleNamespace(execute=True))
            except SystemExit as e:
                raised = True
                assert e.code == 3
            assert raised, "execute without flag must SystemExit(3)"

            # measure sets the flag; execute retracts pollution, preserves real
            pd.write_ready_flag()
            assert cli_pd._cmd_detect(SimpleNamespace(execute=True)) == 0
            active_ids = {r["id"] for r in ii.query(limit=10000)}
            assert "real1" in active_ids, "record with live fs artifact must survive"
            assert active_ids.isdisjoint({"p0", "p1", "p2"}), "burst pollution must retract"
            assert not pd.ready_flag_exists(), "flag is single-use (consumed)"
        finally:
            if _ORIG_CLAUDE_HOME is None:
                os.environ.pop("CLAUDE_HOME", None)
            else:
                os.environ["CLAUDE_HOME"] = _ORIG_CLAUDE_HOME


def test_load_entries_retraction_aware_idempotent():
    """M29 gap fix (2026-06-17): after retraction, load_entries excludes the
    retracted ids by default, so a second confirm pass returns 0 (idempotent) and
    check_pollution self-quiets. include_retracted=True restores the raw view."""
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        os.environ["CLAUDE_HOME"] = str(home)
        try:
            from cli import insight_index_pollution_detector as cli_pd
            from lib import insight_index_pollution_detector as pd

            base = 1700000000000
            polluted = [_rec(f"p{i}", base + i * 10, f"orch-x-{i}") for i in range(3)]
            _write_index(home, polluted)

            # before retraction: 3 confirmed
            assert len(pd.confirm_pollution(
                pd.cluster_pollution_candidates(pd.load_entries()))) == 3
            # retract them
            pd.write_ready_flag()
            assert cli_pd._cmd_detect(SimpleNamespace(execute=True)) == 0
            # AFTER retraction: load_entries excludes them → 0 confirmed (idempotent)
            assert pd.load_entries() == []
            assert len(pd.confirm_pollution(
                pd.cluster_pollution_candidates(pd.load_entries()))) == 0
            # raw view still sees the physical lines
            assert len(pd.load_entries(include_retracted=True)) == 3
        finally:
            if _ORIG_CLAUDE_HOME is None:
                os.environ.pop("CLAUDE_HOME", None)
            else:
                os.environ["CLAUDE_HOME"] = _ORIG_CLAUDE_HOME


def main() -> int:
    tests = [
        test_detect_execute_retracts_pollution_preserves_real_and_gates_on_flag,
        test_load_entries_retraction_aware_idempotent,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
    if failed:
        print(f"[FAIL] {failed}/{len(tests)} failed")
        return 1
    print(f"[OK] {len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
