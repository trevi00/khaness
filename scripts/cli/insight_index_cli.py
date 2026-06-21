#!/usr/bin/env python3
"""insight_index_cli — operator surface for L1 Insight Index (S2 R3).

debate-1779267594-edb2a2 LOCK D6_reader_count=3 (R3 = this CLI).

Subcommands:
  list [--tail N] [--event-type T] [--correlation-id C] [--axis A] [--tag X]
       [--json]
  retract <entry_id> --reason "<text>"
  retract-polluted [--execute] [--reason TEXT]
      D4 LOCK (debate-1780268884-1di5gw gen 4 sha1
      78f09503a8894f02cff45ed53a3ea07d26a5fddf). --dry-run default ON,
      --execute required to mutate. Before any retract() call: writes
      retract-plan.json + shutil.copy2 backup of insight-index.jsonl AND
      insight-index-retractions.jsonl into state/snapshots/. Refuses
      --execute without ready-flag at state/pollution-threshold-validated.flag
      via raise SystemExit(3). On success, deletes the ready-flag (single-use).

Usage:
  python -m cli.insight_index_cli list --tail 20
  python -m cli.insight_index_cli list --event-type wonder --json
  python -m cli.insight_index_cli retract wonder-1700000000000-abc123 \
      --reason "superseded by later analysis"
  python -m cli.insight_index_cli retract-polluted              # dry-run
  python -m cli.insight_index_cli retract-polluted --execute    # mutates

Exit code: 0 on success, 1 on error, 3 on ready-flag refusal (D4 policy).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

# Windows cp949 console can't encode em-dash / arrows that appear in insight
# summaries; reconfigure to utf-8 (codebase pattern, fail-soft) so `list` never
# crashes on a non-ASCII summary field.
for _s in (sys.stdout, sys.stderr):
    _r = getattr(_s, "reconfigure", None)
    if _r:
        try:
            _r(encoding="utf-8")
        except Exception:
            pass

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import insight_index  # noqa: E402
from lib import insight_index_pollution_detector as _pd  # noqa: E402


def _cmd_list(args: argparse.Namespace) -> int:
    entries = insight_index.query(
        event_type=args.event_type,
        correlation_id=args.correlation_id,
        axis=args.axis,
        tag=args.tag,
        include_retracted=args.include_retracted,
        limit=args.tail if args.tail and args.tail > 0 else None,
    )
    if args.json:
        json.dump(entries, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    if not entries:
        print("(no entries)")
        return 0
    for rec in entries:
        ts = rec.get("ts_unix_ms", 0)
        print(
            f"[{rec.get('id', '?')}] {rec.get('event_type', '?')} "
            f"corr={rec.get('correlation_id', '?')} "
            f"axis={rec.get('axis') or '-'} "
            f"ts_ms={ts}"
        )
        print(f"    {rec.get('summary', '')}")
        tags = rec.get("tags") or []
        if tags:
            print(f"    tags: {', '.join(tags)}")
    print(f"\n({len(entries)} entries)")
    return 0


def _cmd_retract(args: argparse.Namespace) -> int:
    if not args.entry_id:
        print("error: entry_id required", file=sys.stderr)
        return 1
    if not args.reason:
        print("error: --reason required", file=sys.stderr)
        return 1
    ok = insight_index.retract(args.entry_id, reason=args.reason)
    if ok:
        print(f"retracted: {args.entry_id}")
        return 0
    print(f"failed to write retraction for {args.entry_id}", file=sys.stderr)
    return 1


def _build_retract_plan() -> tuple[list[dict], int, int]:
    """Run the D1 pollution detector and return (confirmed_entries, candidate_buckets, total_entries)."""
    entries = _pd.load_entries()
    candidates = _pd.cluster_pollution_candidates(
        entries, bucket_ms=_pd.BUCKET_MS, bucket_min=_pd.BUCKET_MIN_COUNT,
    )
    already_retracted = insight_index._retracted_ids()
    confirmed = [
        rec for rec in _pd.confirm_pollution(candidates)
        if rec.get("id") not in already_retracted
    ]
    return confirmed, len(candidates), len(entries)


def _cmd_retract_polluted(args: argparse.Namespace) -> int:
    reason = args.reason or "test_fixture_pollution"
    confirmed, candidate_buckets, total = _build_retract_plan()

    if not confirmed:
        print(f"(no pollution confirmed: total_entries={total} "
              f"candidate_buckets={candidate_buckets})")
        return 0

    if not args.execute:
        print(f"DRY-RUN: would retract {len(confirmed)} entries "
              f"(candidate_buckets={candidate_buckets} total_entries={total})")
        for rec in confirmed[:10]:
            print(f"  - {rec.get('id')} ts={rec.get('ts_unix_ms')} "
                  f"corr={rec.get('correlation_id')} "
                  f"src={rec.get('source_module')}")
        if len(confirmed) > 10:
            print(f"  ... and {len(confirmed) - 10} more")
        print("\nRe-run with --execute to apply (requires ready-flag).")
        return 0

    # --execute path: enforce ready-flag gate (D1 LOCK)
    if not _pd.ready_flag_exists():
        sys.stderr.write(
            "refusing to execute: ready-flag missing at "
            f"{_pd._ready_flag_path()}\n"
            "Run 'python -m cli.insight_index_pollution_detector measure' first "
            "to validate threshold.\n"
        )
        raise SystemExit(3)

    # Pre-execution snapshot + retract plan persistence
    snapshots_dir = _pd._claude_home() / "state" / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    ts_ms = int(time.time() * 1000)

    index_path = _pd._index_path()
    retractions_path = _pd._claude_home() / "memory" / "insight-index-retractions.jsonl"
    src_sha1 = ""
    if index_path.exists():
        src_sha1 = hashlib.sha1(index_path.read_bytes()).hexdigest()
        shutil.copy2(index_path, snapshots_dir / f"{ts_ms}-insight-index.jsonl.bak")
    if retractions_path.exists():
        shutil.copy2(
            retractions_path,
            snapshots_dir / f"{ts_ms}-insight-index-retractions.jsonl.bak",
        )

    plan = {
        "ts_unix_ms": ts_ms,
        "target_ids": [rec.get("id") for rec in confirmed],
        "reason": reason,
        "bucket_ms": _pd.BUCKET_MS,
        "bucket_min": _pd.BUCKET_MIN_COUNT,
        "source_snapshot_sha1": src_sha1,
    }
    plan_path = snapshots_dir / f"{ts_ms}-retract-plan.json"
    plan_path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    retracted = 0
    failed = 0
    for rec in confirmed:
        eid = rec.get("id")
        if not isinstance(eid, str) or not eid:
            failed += 1
            continue
        if insight_index.retract(eid, reason=reason):
            retracted += 1
        else:
            failed += 1

    # Single-use ready-flag (delete after successful run)
    if retracted and not failed:
        _pd.delete_ready_flag()

    print(f"retract-plan: {plan_path}")
    print(f"retracted: {retracted}  failed: {failed}  total_plan: {len(confirmed)}")
    return 0 if failed == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="insight_index_cli",
        description="Operator surface for the L1 Insight Index",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list entries (most recent last)")
    p_list.add_argument("--tail", type=int, default=20, help="show last N entries")
    p_list.add_argument("--event-type", default=None)
    p_list.add_argument("--correlation-id", default=None)
    p_list.add_argument("--axis", default=None)
    p_list.add_argument("--tag", default=None)
    p_list.add_argument("--include-retracted", action="store_true")
    p_list.add_argument("--json", action="store_true", help="emit JSON to stdout")
    p_list.set_defaults(fn=_cmd_list)

    p_retract = sub.add_parser("retract", help="append a retraction record")
    p_retract.add_argument("entry_id")
    p_retract.add_argument("--reason", required=True)
    p_retract.set_defaults(fn=_cmd_retract)

    p_rp = sub.add_parser(
        "retract-polluted",
        help="bulk retract D1-confirmed pollution (dry-run default)",
    )
    p_rp.add_argument(
        "--execute", action="store_true",
        help="actually mutate (requires ready-flag from `pollution_detector measure`)",
    )
    p_rp.add_argument(
        "--reason", default="test_fixture_pollution",
        help="retraction reason (default: test_fixture_pollution)",
    )
    p_rp.set_defaults(fn=_cmd_retract_polluted)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
