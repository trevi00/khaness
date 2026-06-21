#!/usr/bin/env python3
"""Tests for the M29 cron jobs (ledger compaction / pollution / brain push).

Covers the security-critical enable-cron-job token gate on every run_* script, the
check_* flag emission/quiet logic, run_ledger_compaction archive+rewrite+idempotency,
and the brain divergence summation. Auto-discovered by run_units.py via main()->int.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


# ---- token gate (security-critical) — all three run_* scripts ----

def _assert_token_behaviour(mod):
    # absent / wrong token -> raise
    for bad in ({}, {"HARNESS_MUTATION_TOKEN": ""}, {"HARNESS_MUTATION_TOKEN": "enable-skill"}):
        with mock.patch.dict("os.environ", bad, clear=False):
            # ensure the var is exactly the bad value (clear any inherited real token)
            import os
            os.environ.pop("HARNESS_MUTATION_TOKEN", None)
            os.environ.update(bad)
            try:
                mod._assert_token()
            except mod.TokenMissingError:
                pass
            else:
                raise AssertionError(f"{mod.__name__}: expected refusal for {bad!r}")
    # exact token -> passes
    with mock.patch.dict("os.environ", {"HARNESS_MUTATION_TOKEN": "enable-cron-job"}, clear=False):
        mod._assert_token()  # must not raise


def test_token_gate_ledger():
    import cron.run_ledger_compaction as m
    _assert_token_behaviour(m)


def test_token_gate_pollution():
    import cron.run_pollution_cleanup as m
    _assert_token_behaviour(m)


def test_token_gate_brain():
    import cron.run_brain_push as m
    _assert_token_behaviour(m)


def test_run_scripts_main_refuses_without_token_exit1():
    import os
    for modname in ("cron.run_ledger_compaction", "cron.run_pollution_cleanup", "cron.run_brain_push"):
        m = __import__(modname, fromlist=["main"])
        with mock.patch.dict("os.environ", {}, clear=False):
            os.environ.pop("HARNESS_MUTATION_TOKEN", None)
            assert m.main() == 1, f"{modname}.main() should exit 1 without token"


# ---- ledger compaction check + run (temp state) ----

def _make_redundant_ledger(root: Path):
    """60 records: 40 share task_hash 'DUP' (39 superseded) + 20 unique → fires."""
    proj = root / "proj01"
    proj.mkdir(parents=True, exist_ok=True)
    ledger = proj / "kha-executor.jsonl"
    recs = [{"task_hash": "DUP", "ts": f"2026-01-01T00:00:{i:02d}Z", "success": True} for i in range(40)]
    recs += [{"task_hash": f"U{i}", "ts": "2026-01-01T00:01:00Z", "success": True} for i in range(20)]
    ledger.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    return ledger


def test_check_ledger_fires_and_emits_flag():
    import cron.check_ledger_compaction as m
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "operator-ledger"
        _make_redundant_ledger(root)
        flag = Path(td) / "ledger-ready.flag"
        check = Path(td) / "ledger-check.json"
        with mock.patch.object(m, "LEDGER_ROOT", root), \
             mock.patch.object(m, "FLAG_PATH", flag), \
             mock.patch.object(m, "CHECK_STATE_PATH", check):
            state = m.evaluate()
        assert state["fired"] is True and flag.exists()
        assert state["candidates"] and state["candidates"][0]["record_count"] == 60


def test_check_ledger_quiet_on_tiny_ledger():
    import cron.check_ledger_compaction as m
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "operator-ledger"
        proj = root / "proj01"
        proj.mkdir(parents=True)
        (proj / "a.jsonl").write_text(
            "\n".join(json.dumps({"task_hash": "A", "ts": str(i)}) for i in range(5)) + "\n",
            encoding="utf-8")
        flag = Path(td) / "f.flag"
        with mock.patch.object(m, "LEDGER_ROOT", root), \
             mock.patch.object(m, "FLAG_PATH", flag), \
             mock.patch.object(m, "CHECK_STATE_PATH", Path(td) / "c.json"):
            state = m.evaluate()
        assert state["fired"] is False and not flag.exists()


def test_run_ledger_compacts_archives_and_is_idempotent():
    import cron.run_ledger_compaction as m
    import cron.check_ledger_compaction as chk
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "operator-ledger"
        ledger = _make_redundant_ledger(root)
        # patch the SINGLE source of truth (check module) — run references chk.LEDGER_ROOT
        with mock.patch.object(chk, "LEDGER_ROOT", root):
            summary1 = m.compact_all(ts_ms=111)
        # 39 superseded archived, ledger rewritten to 21 kept (1 DUP + 20 unique)
        assert summary1["total_reclaimed"] == 39
        kept = [json.loads(x) for x in ledger.read_text(encoding="utf-8").splitlines() if x.strip()]
        assert len(kept) == 21
        archive = ledger.with_name(f"{ledger.name}.compacted.111")
        assert archive.exists()
        arch_recs = [x for x in archive.read_text(encoding="utf-8").splitlines() if x.strip()]
        assert len(arch_recs) == 39  # superseded preserved, never deleted
        # idempotent: second pass reclaims 0
        with mock.patch.object(chk, "LEDGER_ROOT", root):
            summary2 = m.compact_all(ts_ms=222)
        assert summary2["total_reclaimed"] == 0


def test_run_ledger_idle_with_token_no_flag_exit0():
    import os
    import cron.run_ledger_compaction as m
    with tempfile.TemporaryDirectory() as td:
        flag = Path(td) / "absent.flag"
        with mock.patch.object(m, "FLAG_PATH", flag), \
             mock.patch.dict("os.environ", {"HARNESS_MUTATION_TOKEN": "enable-cron-job"}, clear=False):
            os.environ["HARNESS_MUTATION_TOKEN"] = "enable-cron-job"
            assert m.main() == 0  # token present, flag absent -> idle exit 0


# ---- brain push divergence summation ----

def test_brain_divergence_sums_live_not_in_brain():
    import cron.check_brain_push as m
    status = {
        "l1": {"insight-index.jsonl": {"live": 10, "brain": 7, "live_not_in_brain": 3},
               "insight-index-retractions.jsonl": {"live": 2, "brain": 2, "live_not_in_brain": 0}},
        "l2": {"global-facts.jsonl": {"live": 5, "brain": 4, "live_not_in_brain": 1}},
        "graduation": {"live_validators": 3},
    }
    assert m._total_divergence(status) == 4


def test_check_brain_push_fires_on_divergence():
    import cron.check_brain_push as m
    with tempfile.TemporaryDirectory() as td:
        flag = Path(td) / "brain.flag"
        fake_status = {"l1": {"insight-index.jsonl": {"live": 9, "brain": 8, "live_not_in_brain": 1}}, "l2": {}}
        with mock.patch.object(m, "FLAG_PATH", flag), \
             mock.patch.object(m, "CHECK_STATE_PATH", Path(td) / "c.json"), \
             mock.patch("lib.brain_store.status", return_value=fake_status):
            state = m.evaluate()
        assert state["fired"] is True and state["live_not_in_brain_total"] == 1 and flag.exists()


# ---- pollution check (mocked detector) ----

def test_check_pollution_fires_on_confirmed():
    import cron.check_pollution as m
    with tempfile.TemporaryDirectory() as td:
        flag = Path(td) / "poll.flag"
        confirmed = [{"id": "x1", "source_module": "engine.orchestrator"},
                     {"id": "x2", "source_module": "engine.orchestrator"}]
        with mock.patch.object(m, "FLAG_PATH", flag), \
             mock.patch.object(m, "CHECK_STATE_PATH", Path(td) / "c.json"), \
             mock.patch.object(m.pd, "load_entries", return_value=[{"a": 1}]), \
             mock.patch.object(m.pd, "cluster_pollution_candidates", return_value=[]), \
             mock.patch.object(m.pd, "confirm_pollution", return_value=confirmed):
            state = m.evaluate()
        assert state["fired"] is True and state["confirmed_pollution"] == 2 and flag.exists()


def test_pollution_cleanup_delegates_to_sanctioned_cli():
    """run_pollution_cleanup.cleanup() must NOT import lib.insight_index — it
    subprocess-delegates to the whitelisted cli.insight_index_pollution_detector."""
    import cron.run_pollution_cleanup as m

    class _R:
        def __init__(self, rc, out="", err=""):
            self.returncode, self.stdout, self.stderr = rc, out, err

    # success: measure rc=0 then detect --execute rc=0 -> returns summary
    with mock.patch("subprocess.run", side_effect=[_R(0, "ok"), _R(0, "[done] retracted 5 pollution records")]):
        res = m.cleanup()
    assert res["execute_rc"] == 0 and "retracted 5" in res["summary"]

    # failure: detect --execute rc=1 -> raises (caller must NOT ack)
    with mock.patch("subprocess.run", side_effect=[_R(0, "ok"), _R(1, "", "boom")]):
        try:
            m.cleanup()
        except RuntimeError:
            pass
        else:
            raise AssertionError("cleanup() must raise on non-zero detect rc")


def test_run_pollution_no_direct_insight_index_import():
    """Static guard: the cron consumer must not have a `from lib import insight_index`
    line (that would re-trip the importer whitelist)."""
    src = (_SCRIPTS / "cron" / "run_pollution_cleanup.py").read_text(encoding="utf-8")
    assert "import insight_index" not in src or "pollution_detector" in src
    # specifically the bare lib.insight_index import must be gone
    assert "from lib import insight_index\n" not in src
    assert "from lib import insight_index as ii" not in src


def main() -> int:
    failed = 0
    n = 0
    for name, obj in list(globals().items()):
        if not name.startswith("test_"):
            continue
        n += 1
        try:
            obj()
            print(f"  [OK] {name}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [ERR] {name}: {e!r}")
    if failed:
        print(f"\n{failed}/{n} failed")
        return 1
    print(f"\n[OK] {n} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
