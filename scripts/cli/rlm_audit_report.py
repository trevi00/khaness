#!/usr/bin/env python3
"""rlm_audit_report — reader for state/evaluator/<sid>/rlm_audit.jsonl.

Wave 11 S4 closure (자가개선 silo S4 closure per A1-A6 분석,
interview-1779253986-8554c71f seed). Wave 10 landed `lib/providers/rlm_codex.py`
with `_emit_audit_row()` writer but ZERO reader — A4 data flow report flagged
as dead-end surface. This CLI closes the loop: aggregate rlm_audit.jsonl rows
into depth/child_count/branch/elapsed distributions for verification that
rlm_codex actually performs recursive context decomposition (not flat fallback
in production).

## rlm_audit.jsonl row schema (from lib/providers/rlm_codex.py:_emit_audit_row)

  {
    "ts": "<ISO timestamp>",
    "depth": int,
    "prompt_sha1": "<40-char hex>",
    "prompt_len_chars": int,
    "child_call_count": int,
    "branch": "recursive" | "flat_base_case",
    "model": "<resolved id>",
    "parent_sha1": "<40-char hex> | null",
    "elapsed_seconds": float | null,
    "reason": "depth_cap" | "short_prompt" | "decomposition_failed"   (optional)
  }

## Output (aggregated across all sessions)

  - total rows
  - depth distribution: {depth=0: N, depth=1: N, depth=2: N, ...}
  - branch ratio: recursive=N (%) / flat_base_case=N (%)
  - child_call_count distribution (per recursive parent row)
  - elapsed_seconds: min / median / p95 / max
  - reason distribution (flat_base_case rows)
  - top 3 models used

## Filters

  --since <ISO date>     — rows whose ts >= date (YYYY-MM-DD)
  --sid <session_id>     — restrict to one session
  --format {table,json}  — table (default) or json

## Empty-state behavior

Wave 10 land 후 사용자가 RlmCodexProvider 를 ensemble pool 에 inject 하지
않았다면 line count 0 — graceful empty output (exit 0). 이 reader 의 신설은
"infrastructure 준비 완료, 실 데이터 운용 시 활용 가능" 상태 만들기.

## Usage

  python -m cli.rlm_audit_report                          # full report
  python -m cli.rlm_audit_report --sid orch-12345-abc     # single session
  python -m cli.rlm_audit_report --since 2026-05-20       # recent only
  python -m cli.rlm_audit_report --format json            # machine output

## Cross-references

  - lib/providers/rlm_codex.py:_emit_audit_row — writer authority
  - HANDOFF wave 11 S4 (interview-1779253986-8554c71f seed)
  - A4 data flow report: dead-end surface closure (writer ✓, reader 0 → reader ✓)
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.paths import STATE_DIR  # noqa: E402


AUDIT_FILENAME: str = "rlm_audit.jsonl"
"""Per-session audit file under state/evaluator/<sid>/."""

TOP_MODELS_N: int = 3


@dataclass
class AuditAggregate:
    """Aggregated audit metrics across N sessions."""
    total_rows: int = 0
    depth_dist: Counter = field(default_factory=Counter)
    branch_dist: Counter = field(default_factory=Counter)
    child_count_dist: Counter = field(default_factory=Counter)
    elapsed_values: list[float] = field(default_factory=list)
    reason_dist: Counter = field(default_factory=Counter)
    model_dist: Counter = field(default_factory=Counter)
    sid_dist: Counter = field(default_factory=Counter)

    def to_dict(self) -> dict[str, Any]:
        elapsed_stats: dict[str, float | None] = {
            "min": None, "median": None, "p95": None, "max": None,
        }
        if self.elapsed_values:
            sorted_vals = sorted(self.elapsed_values)
            elapsed_stats = {
                "min": round(sorted_vals[0], 4),
                "median": round(statistics.median(sorted_vals), 4),
                "p95": round(
                    sorted_vals[int(0.95 * len(sorted_vals))]
                    if len(sorted_vals) > 1 else sorted_vals[0], 4,
                ),
                "max": round(sorted_vals[-1], 4),
            }
        return {
            "total_rows": self.total_rows,
            "depth_distribution": dict(sorted(self.depth_dist.items())),
            "branch_distribution": dict(self.branch_dist),
            "child_count_distribution": dict(sorted(self.child_count_dist.items())),
            "elapsed_seconds": elapsed_stats,
            "reason_distribution": dict(self.reason_dist),
            "top_models": dict(self.model_dist.most_common(TOP_MODELS_N)),
            "session_distribution": dict(self.sid_dist),
        }


def _iter_rows(audit_path: Path) -> list[dict]:
    """Read one rlm_audit.jsonl. Per-line JSONDecodeError tolerant."""
    rows: list[dict] = []
    try:
        with audit_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        rows.append(row)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return rows


def aggregate(
    evaluator_dir: Path,
    *,
    since: str | None = None,
    sid_filter: str | None = None,
) -> AuditAggregate:
    """Walk state/evaluator/*/rlm_audit.jsonl, return aggregated counters."""
    agg = AuditAggregate()
    if not evaluator_dir.is_dir():
        return agg

    for entry in sorted(evaluator_dir.iterdir()):
        if not entry.is_dir():
            continue
        if sid_filter and entry.name != sid_filter:
            continue
        audit_path = entry / AUDIT_FILENAME
        if not audit_path.exists():
            continue
        rows = _iter_rows(audit_path)
        for row in rows:
            ts = row.get("ts")
            if since and isinstance(ts, str) and ts < since:
                continue
            agg.total_rows += 1
            agg.sid_dist[entry.name] += 1

            depth = row.get("depth")
            if isinstance(depth, int):
                agg.depth_dist[depth] += 1

            branch = row.get("branch")
            if isinstance(branch, str):
                agg.branch_dist[branch] += 1

            child_count = row.get("child_call_count")
            if isinstance(child_count, int):
                agg.child_count_dist[child_count] += 1

            elapsed = row.get("elapsed_seconds")
            if isinstance(elapsed, (int, float)):
                agg.elapsed_values.append(float(elapsed))

            reason = row.get("reason")
            if isinstance(reason, str):
                agg.reason_dist[reason] += 1

            model = row.get("model")
            if isinstance(model, str):
                agg.model_dist[model] += 1

    return agg


def _format_table(agg: AuditAggregate) -> str:
    """Human-readable summary."""
    if agg.total_rows == 0:
        return (
            "=== rlm_audit_report (0 rows) ===\n"
            "\n"
            "No rlm_audit.jsonl data found. RlmCodexProvider has not been\n"
            "invoked yet (wave 10 land 후 operator 가 evaluator_specs 에\n"
            "RlmCodexProvider 미주입 상태). Reader infrastructure ready;\n"
            "활용은 operator decision 후 자연 누적.\n"
        )

    lines: list[str] = []
    lines.append(f"=== rlm_audit_report ({agg.total_rows} rows) ===")
    lines.append("")

    lines.append("Depth distribution:")
    for depth, count in sorted(agg.depth_dist.items()):
        pct = 100.0 * count / agg.total_rows
        lines.append(f"  depth={depth}: {count} ({pct:.1f}%)")
    lines.append("")

    lines.append("Branch breakdown:")
    for branch, count in agg.branch_dist.most_common():
        pct = 100.0 * count / agg.total_rows
        lines.append(f"  {branch}: {count} ({pct:.1f}%)")
    lines.append("")

    if agg.child_count_dist:
        lines.append("Child call count distribution (per recursive parent):")
        for cc, count in sorted(agg.child_count_dist.items()):
            lines.append(f"  child_count={cc}: {count}")
        lines.append("")

    if agg.elapsed_values:
        sorted_vals = sorted(agg.elapsed_values)
        lines.append("Elapsed seconds:")
        lines.append(f"  min:    {sorted_vals[0]:.4f}")
        lines.append(f"  median: {statistics.median(sorted_vals):.4f}")
        if len(sorted_vals) > 1:
            p95 = sorted_vals[int(0.95 * len(sorted_vals))]
        else:
            p95 = sorted_vals[0]
        lines.append(f"  p95:    {p95:.4f}")
        lines.append(f"  max:    {sorted_vals[-1]:.4f}")
        lines.append("")

    if agg.reason_dist:
        lines.append("Flat fallback reasons:")
        for reason, count in agg.reason_dist.most_common():
            lines.append(f"  {reason}: {count}")
        lines.append("")

    if agg.model_dist:
        lines.append(f"Top {TOP_MODELS_N} models:")
        for model, count in agg.model_dist.most_common(TOP_MODELS_N):
            pct = 100.0 * count / agg.total_rows
            lines.append(f"  {model}: {count} ({pct:.1f}%)")
        lines.append("")

    lines.append(f"Sessions contributing: {len(agg.sid_dist)}")
    return "\n".join(lines) + "\n"


def _format_json(agg: AuditAggregate) -> str:
    return json.dumps(agg.to_dict(), indent=2, ensure_ascii=False) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.rlm_audit_report",
        description="Aggregate rlm_audit.jsonl across state/evaluator/<sid>/",
    )
    parser.add_argument(
        "--since", default=None,
        help="ISO timestamp prefix (e.g., 2026-05-20) — rows with ts >= since",
    )
    parser.add_argument(
        "--sid", default=None,
        help="restrict to one session id (state/evaluator/<sid>/)",
    )
    parser.add_argument(
        "--format", default="table",
        choices=["table", "json"],
        help="output format (default: table)",
    )
    parser.add_argument(
        "--evaluator-dir", default=None,
        help="override evaluator dir (default: STATE_DIR/evaluator)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    evaluator_dir = (
        Path(args.evaluator_dir) if args.evaluator_dir
        else STATE_DIR / "evaluator"
    )

    agg = aggregate(evaluator_dir, since=args.since, sid_filter=args.sid)

    if args.format == "json":
        sys.stdout.write(_format_json(agg))
    else:
        sys.stdout.write(_format_table(agg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
