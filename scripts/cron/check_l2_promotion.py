#!/usr/bin/env python3
"""check_l2_promotion — L2 promotion trigger evaluator (S2 PR-cron).

debate-1779267594-edb2a2 LOCK D4_scheduling_trigger:

  Emits state/l2-promotion-ready.flag when ANY of the three clauses holds:
    (a) 30 days since first insight_index entry
    (b) >500 unretracted entries
    (c) p99 query latency > 50ms on 3 consecutive evaluations

Per Mutation table (CLAUDE.md §Mutation 분류):
  - flag *emission* (this script): auto OK
  - flag *consumption / actual L2 promotion execution*: requires
    `enable-cron-job` token gate (L2 (Global Facts) DEFERRED)

State files written:
  ~/.claude/state/l2-promotion-ready.flag   (emitted when any clause fires)
  ~/.claude/state/l2-promotion-check.json   (per-run telemetry: clause hits,
                                             entry count, p99, consecutive
                                             p99 streak)

Run manually:
  python -m cron.check_l2_promotion

Exit code: 0 (always — cron is fail-soft).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import insight_index  # noqa: E402
from lib.paths import STATE_DIR  # noqa: E402


_THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000
_ENTRY_THRESHOLD = 500
_P99_THRESHOLD_MS = 50.0
_P99_CONSECUTIVE_TRIGGER = 3

FLAG_PATH = STATE_DIR / "l2-promotion-ready.flag"
CHECK_STATE_PATH = STATE_DIR / "l2-promotion-check.json"


def _measure_p99_ms(entries: list[dict], samples: int = 10) -> float:
    """Re-execute query() and measure latency. Returns p99 in milliseconds.

    Cheap & dependency-free: filter the same list `samples` times under a
    representative filter. Returns 0.0 when there are no entries.
    """
    if not entries:
        return 0.0
    measurements: list[float] = []
    for _ in range(samples):
        t0 = time.perf_counter()
        # Re-read via the public API so we're measuring the real path.
        insight_index.query(event_type=None, limit=None)
        t1 = time.perf_counter()
        measurements.append((t1 - t0) * 1000.0)
    measurements.sort()
    # p99 of 10 samples = worst (conservative).
    return measurements[-1]


def _load_check_state() -> dict:
    if not CHECK_STATE_PATH.exists():
        return {"p99_consecutive_over": 0}
    try:
        return json.loads(CHECK_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"p99_consecutive_over": 0}


def _save_check_state(state: dict) -> None:
    try:
        CHECK_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CHECK_STATE_PATH.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def evaluate() -> dict:
    """Run one evaluation. Returns the decision record.

    Side effects: writes l2-promotion-check.json; writes l2-promotion-ready.flag
    iff any clause fires.
    """
    entries = insight_index.query(include_retracted=False, limit=None)
    now_ms = int(time.time() * 1000)
    first_ts = entries[0]["ts_unix_ms"] if entries else now_ms
    age_ms = now_ms - first_ts
    entry_count = len(entries)
    p99_ms = _measure_p99_ms(entries)

    prev = _load_check_state()
    prev_streak = int(prev.get("p99_consecutive_over", 0) or 0)
    streak = prev_streak + 1 if p99_ms > _P99_THRESHOLD_MS else 0

    clauses = {
        "age_30d": age_ms >= _THIRTY_DAYS_MS,
        "entries_over_500": entry_count > _ENTRY_THRESHOLD,
        "p99_streak_over_3": streak >= _P99_CONSECUTIVE_TRIGGER,
    }
    fired = any(clauses.values())

    state = {
        "ts_ms": now_ms,
        "entry_count": entry_count,
        "first_entry_ts_ms": first_ts,
        "age_ms": age_ms,
        "p99_ms": p99_ms,
        "p99_consecutive_over": streak,
        "clauses": clauses,
        "fired": fired,
    }
    _save_check_state(state)

    if fired:
        try:
            FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
            FLAG_PATH.write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    return state


def main() -> int:
    state = evaluate()
    if state["fired"]:
        print(
            f"[FIRE] l2-promotion-ready: entries={state['entry_count']} "
            f"age_days={state['age_ms'] / (24*60*60*1000):.1f} "
            f"p99={state['p99_ms']:.2f}ms streak={state['p99_consecutive_over']} "
            f"clauses={state['clauses']}"
        )
    else:
        print(
            f"[QUIET] l2-promotion: entries={state['entry_count']} "
            f"age_days={state['age_ms'] / (24*60*60*1000):.1f} "
            f"p99={state['p99_ms']:.2f}ms streak={state['p99_consecutive_over']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
