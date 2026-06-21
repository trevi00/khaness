#!/usr/bin/env python3
"""Tests for lib/graduation_audit.py — the read-only graduation audit-trail reader (M13).

The producer (lib/graduation.py::_append_history) writes graduate/demote/
circuit_breaker_demote records to state/graduation-history.jsonl. These tests
redirect graduation.STATE_DIR to a temp dir (same isolation pattern as
test_session_init.py), drive real flips through the producer, and assert the
reader aggregates them correctly. Fail-soft / forward-looking (empty trail) is
explicitly covered.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _seed_real_flips(td: Path):
    """Use the PRODUCER (graduation.py) to write a realistic trail, so the reader
    is tested against the exact schema graduation emits — not a hand-mocked one."""
    from lib import graduation as g
    g.STATE_DIR = td  # lazy path funcs read this at call time
    # graduate doc_code_drift: needs ready-flag first
    st = g.load_state()
    g._entry(st, "doc_code_drift")["ready"] = True
    g.save_state(st)
    g.graduate("doc_code_drift", token=g.TOKEN_GRADUATE)            # action=graduate
    g.demote("doc_code_drift", token=g.TOKEN_DEMOTE)                # action=demote
    # a second validator graduated once
    st = g.load_state()
    g._entry(st, "self_model_drift")["ready"] = True
    g.save_state(st)
    g.graduate("self_model_drift", token=g.TOKEN_GRADUATE)          # action=graduate


def test_empty_trail_is_forward_looking():
    """No history file → empty read + zero-filled summary (today's live state)."""
    from lib import graduation as g
    from lib import graduation_audit as ga
    saved = g.STATE_DIR
    with tempfile.TemporaryDirectory() as td:
        g.STATE_DIR = Path(td)
        try:
            assert ga.read_history() == []
            s = ga.summary_report()
            assert s["total_records"] == 0
            # zero-filled known buckets present even with no data
            assert s["by_action"] == {"graduate": 0, "demote": 0, "circuit_breaker_demote": 0}
            assert s["validators"] == {}
        finally:
            g.STATE_DIR = saved


def test_read_history_roundtrips_producer_records():
    from lib import graduation as g
    from lib import graduation_audit as ga
    saved = g.STATE_DIR
    with tempfile.TemporaryDirectory() as td:
        g.STATE_DIR = Path(td)
        try:
            _seed_real_flips(Path(td))
            recs = ga.read_history()
            actions = [r.get("action") for r in recs]
            assert actions == ["graduate", "demote", "graduate"], actions
            assert all(isinstance(r, dict) and "ts" in r for r in recs)
        finally:
            g.STATE_DIR = saved


def test_summary_report_aggregates_by_action_and_validator():
    from lib import graduation as g
    from lib import graduation_audit as ga
    saved = g.STATE_DIR
    with tempfile.TemporaryDirectory() as td:
        g.STATE_DIR = Path(td)
        try:
            _seed_real_flips(Path(td))
            s = ga.summary_report()
            assert s["total_records"] == 3
            assert s["by_action"]["graduate"] == 2
            assert s["by_action"]["demote"] == 1
            assert s["by_action"]["circuit_breaker_demote"] == 0
            # doc_code_drift: graduate then demote → last is demote
            doc = s["validators"]["doc_code_drift"]
            assert doc["total"] == 2
            assert doc["actions"] == {"graduate": 1, "demote": 1}
            assert doc["last_action"] == "demote"
            assert doc["last_token"] == g.TOKEN_DEMOTE
            # self_model_drift: single graduate
            smd = s["validators"]["self_model_drift"]
            assert smd["total"] == 1 and smd["last_action"] == "graduate"
        finally:
            g.STATE_DIR = saved


def test_history_for_validator_filters():
    from lib import graduation as g
    from lib import graduation_audit as ga
    saved = g.STATE_DIR
    with tempfile.TemporaryDirectory() as td:
        g.STATE_DIR = Path(td)
        try:
            _seed_real_flips(Path(td))
            doc = ga.history_for_validator("doc_code_drift")
            assert [r["action"] for r in doc] == ["graduate", "demote"]
            assert all(r["validator"] == "doc_code_drift" for r in doc)
            assert ga.history_for_validator("nonexistent") == []
        finally:
            g.STATE_DIR = saved


def test_limit_tails_records():
    from lib import graduation as g
    from lib import graduation_audit as ga
    saved = g.STATE_DIR
    with tempfile.TemporaryDirectory() as td:
        g.STATE_DIR = Path(td)
        try:
            _seed_real_flips(Path(td))
            assert len(ga.read_history(limit=1)) == 1
            # last record overall is the self_model_drift graduate
            assert ga.read_history(limit=1)[0]["validator"] == "self_model_drift"
            assert len(ga.read_history(limit=0)) == 0
            assert len(ga.read_history(limit=99)) == 3  # over-cap returns all
        finally:
            g.STATE_DIR = saved


def test_garbled_lines_skipped_failsoft():
    from lib import graduation as g
    from lib import graduation_audit as ga
    saved = g.STATE_DIR
    with tempfile.TemporaryDirectory() as td:
        g.STATE_DIR = Path(td)
        try:
            _seed_real_flips(Path(td))
            # corrupt the file: inject a garbled line + a non-object JSON line
            hp = ga._history_path()
            with hp.open("a", encoding="utf-8") as f:
                f.write("this is not json\n")
                f.write("[1, 2, 3]\n")     # valid json but not an object
                f.write("\n")              # blank
            recs = ga.read_history()
            # still exactly the 3 real object records; garbage skipped, no raise
            assert len(recs) == 3
            assert [r["action"] for r in recs] == ["graduate", "demote", "graduate"]
        finally:
            g.STATE_DIR = saved


def test_cli_history_subcommand_runs_clean():
    """The CLI `history` path is wired and never raises on empty or populated trail."""
    from lib import graduation as g
    from cli import graduate_validator as cli
    saved = g.STATE_DIR
    with tempfile.TemporaryDirectory() as td:
        g.STATE_DIR = Path(td)
        try:
            assert cli.main(["history"]) == 0           # empty trail
            _seed_real_flips(Path(td))
            assert cli.main(["history"]) == 0           # populated
            assert cli.main(["history", "doc_code_drift"]) == 0
            assert cli.main(["history", "doc_code_drift", "5"]) == 0
            assert cli.main(["history", "x", "y"]) == 2  # too many positionals
        finally:
            g.STATE_DIR = saved


def main() -> int:
    tests = [
        test_empty_trail_is_forward_looking,
        test_read_history_roundtrips_producer_records,
        test_summary_report_aggregates_by_action_and_validator,
        test_history_for_validator_filters,
        test_limit_tails_records,
        test_garbled_lines_skipped_failsoft,
        test_cli_history_subcommand_runs_clean,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            import traceback
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failed += 1
    if failed == 0:
        print(f"[OK] {len(tests)} tests passed")
        return 0
    print(f"[FAIL] {failed}/{len(tests)} tests failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
