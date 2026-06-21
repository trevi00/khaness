#!/usr/bin/env python3
"""check_pollution — L1 insight-index pollution trigger (M29, auto-OK).

Schedules the existing READ-ONLY burst-pollution detector
(lib.insight_index_pollution_detector) and emits state/pollution-cleanup-ready.flag
when confirmed pollution is found. Mirrors cron/check_l2_promotion.py: read-only flag
emission, no token, fail-soft exit 0.

What the detector already provides (debate-1780268884-1di5gw): a bucket-burst
(>=3 entries / 250ms) whose correlation_id has NO live run artifact
(projects/<cid>/ or state/orchestrator/<cid>/) is confirmed pollution. Today that
detector is "ad-hoc admin" (manually run). This wraps it as a SCHEDULED detector +
surfaces the signal; the actual retraction (the mutation) stays `enable-cron-job`
gated in cron/run_pollution_cleanup.py.

State files written:
  ~/.claude/state/pollution-cleanup-ready.flag   (when confirmed pollution > 0)
  ~/.claude/state/pollution-cleanup-check.json    (per-run telemetry)

Run manually:  python -m cron.check_pollution
Exit code: 0 (always — cron is fail-soft).
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import insight_index_pollution_detector as pd  # noqa: E402
from lib.paths import STATE_DIR  # noqa: E402

FLAG_PATH: Path = STATE_DIR / "pollution-cleanup-ready.flag"
CHECK_STATE_PATH: Path = STATE_DIR / "pollution-cleanup-check.json"


def evaluate() -> dict:
    """Run read-only detection. Writes check.json; writes the flag iff confirmed > 0."""
    entries = pd.load_entries()
    confirmed = pd.confirm_pollution(pd.cluster_pollution_candidates(entries))
    by_sm = Counter(r.get("source_module", "?") for r in confirmed)
    now_ms = int(time.time() * 1000)
    fired = len(confirmed) > 0
    state = {
        "ts_ms": now_ms,
        "index_entries": len(entries),
        "confirmed_pollution": len(confirmed),
        "by_source_module": dict(by_sm),
        "sample_ids": [r.get("id") for r in confirmed[:5]],
        "bucket_ms": pd.BUCKET_MS,
        "bucket_min_count": pd.BUCKET_MIN_COUNT,
        "fired": fired,
    }
    try:
        CHECK_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CHECK_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    if fired:
        try:
            FLAG_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
    return state


def main() -> int:
    state = evaluate()
    if state["fired"]:
        print(f"[FIRE] pollution-cleanup: {state['confirmed_pollution']} confirmed burst-pollution "
              f"records (of {state['index_entries']} entries) by_module={state['by_source_module']}")
    else:
        print(f"[QUIET] pollution: no confirmed pollution (index entries={state['index_entries']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
