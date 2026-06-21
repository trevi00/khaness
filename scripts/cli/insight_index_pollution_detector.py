#!/usr/bin/env python3
"""insight_index_pollution_detector CLI — D1 LOCK (debate-1780268884-1di5gw
gen 4 sha1 78f09503a8894f02cff45ed53a3ea07d26a5fddf).

Subcommands:
  measure
    Read ~/.claude/memory/insight-index.jsonl, emit histogram of inter-event
    Δt grouped by (source_module, event_type) to
      ~/.claude/state/snapshots/<ts>-insight-bucket-histogram.json
    Apply the >0.5%-co-fire rule: if violation_ratio > 0.005, widen bucket to
    500ms OR raise BUCKET_MIN_COUNT to 4 (chosen by smallest single-pivot
    delta). Then touch the ready-flag at FIXED path
      ~/.claude/state/pollution-threshold-validated.flag
    (atlas:58 D17 shape parity; no enable-cron-job token — ad-hoc admin).

  status
    Print whether the ready-flag exists. Exit 0 always.

  detect [--execute]
    Dry-run lists confirmed burst pollution (>=3/250ms cluster AND no live
    projects/<cid> or state/orchestrator/<cid> artifact). With --execute,
    retracts each via lib.insight_index.retract() (append-only, D7) — gated by
    the measure ready-flag (SystemExit 3 if absent); deletes the flag after
    (single-use → forces re-measurement next run).

Usage:
  python -m cli.insight_index_pollution_detector measure
  python -m cli.insight_index_pollution_detector status
  python -m cli.insight_index_pollution_detector detect [--execute]

Exit codes: 0 on success, 1 on internal error, 3 on --execute without ready-flag.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import insight_index_pollution_detector as pd  # noqa: E402


def _cmd_measure(args: argparse.Namespace) -> int:
    entries = pd.load_entries()
    hist = pd.histogram_inter_event_delta(entries)
    ratio = pd.cofire_window_violation_ratio(entries)

    tuned_bucket = pd.BUCKET_MS
    tuned_min = pd.BUCKET_MIN_COUNT
    if ratio > pd.COFIRE_RULE_RATIO:
        # Pick smallest single-pivot adjustment: try raising min first.
        if pd.cofire_window_violation_ratio(
            entries, bucket_ms=pd.BUCKET_MS, bucket_min=pd.BUCKET_MIN_COUNT + 1
        ) <= pd.COFIRE_RULE_RATIO:
            tuned_min = pd.BUCKET_MIN_COUNT + 1
        else:
            tuned_bucket = 500

    snapshots_dir = pd._claude_home() / "state" / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    ts_ms = int(time.time() * 1000)
    hist_path = snapshots_dir / f"{ts_ms}-insight-bucket-histogram.json"
    serializable_hist = {
        f"{sm}::{et}": deltas for (sm, et), deltas in hist.items()
    }
    hist_path.write_text(
        json.dumps({
            "ts_unix_ms": ts_ms,
            "entry_count": len(entries),
            "cofire_window_violation_ratio": ratio,
            "cofire_rule_threshold": pd.COFIRE_RULE_RATIO,
            "tuned_bucket_ms": tuned_bucket,
            "tuned_bucket_min_count": tuned_min,
            "rule_tripped": ratio > pd.COFIRE_RULE_RATIO,
            "inter_event_delta_ms_by_key": serializable_hist,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    pd.write_ready_flag()
    print(f"histogram: {hist_path}")
    print(f"violation_ratio: {ratio:.6f} (threshold {pd.COFIRE_RULE_RATIO})")
    print(f"tuned: bucket_ms={tuned_bucket} bucket_min={tuned_min}")
    print(f"ready-flag: {pd._ready_flag_path()}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    flag = pd._ready_flag_path()
    if pd.ready_flag_exists():
        print(f"ready-flag PRESENT: {flag}")
    else:
        print(f"ready-flag ABSENT: {flag}")
    return 0


def _cmd_detect(args: argparse.Namespace) -> int:
    """D4 detect/retract path. Dry-run by default (prints the plan); with
    --execute, retracts confirmed pollution via lib.insight_index.retract()
    (append-only, D7) but ONLY when the measure ready-flag is present (gate);
    refuses with SystemExit(3) otherwise (distinct from argparse usage exit 2).
    The flag is single-use — deleted after a successful retract pass to force
    re-measurement next time. Detection uses the default 250ms/3 bucket (narrow
    = conservative): a candidate is confirmed iff it is in a >=3/250ms burst AND
    has no live run artifact (projects/<cid>/ or state/orchestrator/<cid>/),
    so real spread-out autopilot runs are never candidates.
    """
    from collections import Counter
    entries = pd.load_entries()
    confirmed = pd.confirm_pollution(pd.cluster_pollution_candidates(entries))
    by_sm = Counter(r.get("source_module", "?") for r in confirmed)
    print(f"index entries: {len(entries)}")
    print(f"confirmed pollution (burst >=3/{pd.BUCKET_MS}ms AND no live fs artifact): {len(confirmed)}")
    print(f"by source_module: {dict(by_sm)}")
    if not args.execute:
        print("sample ids:", [r.get("id") for r in confirmed[:5]])
        print("(dry-run; pass --execute to retract; requires ready-flag from measure)")
        return 0
    if not pd.ready_flag_exists():
        print(
            "ERROR: ready-flag absent — run `measure` first (D4 gate)",
            file=sys.stderr,
        )
        raise SystemExit(3)
    from lib import insight_index as ii
    reason = (
        "pollution-detector: burst-cluster (>=3/250ms) + no live fs artifact "
        "(test_orchestrator L1 insight-index leak, pre-fe4024b isolation fix)"
    )
    retracted = failed = 0
    for rec in confirmed:
        rid = rec.get("id")
        if not isinstance(rid, str) or not rid:
            failed += 1
            continue
        if ii.retract(rid, reason=reason):
            retracted += 1
        else:
            failed += 1
    pd.delete_ready_flag()  # single-use: force re-measure next run
    print(f"retracted {retracted} pollution records ({failed} failed); ready-flag consumed")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="insight_index_pollution_detector",
        description="D1 pollution detector — measure + ready-flag gate",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    p_m = sub.add_parser("measure", help="emit histogram + touch ready-flag")
    p_m.set_defaults(fn=_cmd_measure)
    p_s = sub.add_parser("status", help="check ready-flag")
    p_s.set_defaults(fn=_cmd_status)
    p_d = sub.add_parser(
        "detect", help="detect burst pollution; with --execute retract it (gated by ready-flag)"
    )
    p_d.add_argument(
        "--execute", action="store_true",
        help="retract confirmed pollution (requires ready-flag from `measure`)",
    )
    p_d.set_defaults(fn=_cmd_detect)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
