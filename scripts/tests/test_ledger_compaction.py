#!/usr/bin/env python3
"""Tests for lib.ledger_compaction (M29) — pure operator-ledger compaction logic.
Auto-discovered by run_units.py via main()->int.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.ledger_compaction import compaction_plan, redundancy_ratio  # noqa: E402


def _rec(task_hash, ts, **kw):
    r = {"task_hash": task_hash, "ts": ts}
    r.update(kw)
    return r


def test_keeps_latest_per_task_hash():
    recs = [_rec("A", "2026-01-01T00:00:00Z"), _rec("A", "2026-01-02T00:00:00Z"),
            _rec("B", "2026-01-01T00:00:00Z")]
    plan = compaction_plan(recs)
    kept_ts = {r["ts"] for r in plan.kept if r["task_hash"] == "A"}
    assert kept_ts == {"2026-01-02T00:00:00Z"}        # only the latest A
    assert plan.reclaimed == 1                          # the older A superseded
    assert len(plan.kept) == 2 and plan.total == 3


def test_human_override_never_superseded():
    recs = [_rec("A", "2026-01-01T00:00:00Z"),
            _rec("A", "2026-01-02T00:00:00Z", human_override={"action": "force_close"}),
            _rec("A", "2026-01-03T00:00:00Z")]
    plan = compaction_plan(recs)
    # the override row is kept regardless; the latest non-override A is kept; the
    # first A is superseded. Override is NOT counted in the task_hash latest race.
    overrides = [r for r in plan.kept if r.get("human_override")]
    assert len(overrides) == 1
    assert any(r["ts"] == "2026-01-03T00:00:00Z" for r in plan.kept)  # latest non-override kept


def test_task_hash_less_always_kept():
    recs = [_rec(None, "2026-01-01T00:00:00Z"), _rec("", "2026-01-02T00:00:00Z"),
            _rec("A", "2026-01-01T00:00:00Z"), _rec("A", "2026-01-02T00:00:00Z")]
    plan = compaction_plan(recs)
    assert plan.reclaimed == 1  # only the older A; the two task_hash-less rows kept
    assert len(plan.kept) == 3


def test_idempotent_recompaction():
    recs = [_rec("A", "t1"), _rec("A", "t2"), _rec("B", "t1")]
    plan1 = compaction_plan(recs)
    plan2 = compaction_plan(list(plan1.kept))
    assert plan2.reclaimed == 0 and len(plan2.kept) == len(plan1.kept)


def test_redundancy_ratio():
    recs = [_rec("A", "t1"), _rec("A", "t2"), _rec("A", "t3"), _rec("B", "t1")]
    # 4 records, kept = latest A + B = 2, superseded = 2 → ratio 0.5
    assert abs(redundancy_ratio(recs) - 0.5) < 1e-9
    assert redundancy_ratio([]) == 0.0
    assert redundancy_ratio([_rec("A", "t1"), _rec("B", "t1")]) == 0.0  # no dupes


def test_non_dict_rows_preserved():
    recs = [_rec("A", "t1"), _rec("A", "t2"), "not-a-dict"]  # type: ignore[list-item]
    plan = compaction_plan(recs)  # type: ignore[arg-type]
    assert "not-a-dict" in plan.kept  # foreign rows never dropped
    assert plan.reclaimed == 1


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
