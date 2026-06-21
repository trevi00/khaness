#!/usr/bin/env python3
"""telemetry_report — aggregate state/telemetry/*.jsonl into a single summary.

Round 7 Phase B.2 (debate-1777614013 follow-on observability work). Reads
all known telemetry categories via lib.telemetry_read and prints:

- hook-latency: p50 / p95 / max per name (ms)
- skill-match: top-N most-matched skills + match frequency
- debate-triggers: strict_design ratio + top phases/cwds
- validator violations rollup (git_flow, hashline, mutation_safety,
  private_content_leak, skill_frontmatter, subagent_refs)
- learner-candidates / mode-triggers / shim-hits: counts only
- test-coverage-gaps: file count + most-stale entry

evaluator accuracy mode (v15.38, autopilot Phase 3.5 land):
- reads state/evaluator/*/axis_scores.jsonl via lib.axis_scores_log
- verdict 분포 (approved/iterate/escalate %) + axis 1-5 평균 +
  completeness 비율 + fallback_reason 분포 + ensemble split 비율

Usage:
    python -m cli.telemetry_report                       # full report
    python -m cli.telemetry_report --json                # machine-readable
    python -m cli.telemetry_report --since=24h           # filter by recency
    python -m cli.telemetry_report --evaluator-accuracy  # v15.38 stats

Read-only — does not mutate state. Safe to run anytime.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.telemetry_read import iter_events  # noqa: E402


# Categories aggregated. Order = display order.
HOOK_LATENCY = "hook-latency"
SKILL_MATCH = "skill-match"
DEBATE_TRIGGERS = "debate-triggers"

VALIDATOR_CATEGORIES = (
    ("git_flow violations", "git-flow-violations"),
    ("hashline violations", "hashline-violations"),
    ("mutation_safety gaps", "mutation-safety-gaps"),
    ("private_content leaks", "private-content-leak"),
    ("skill_frontmatter gaps", "skill-frontmatter-gaps"),
    ("subagent_refs dangling", "subagent-refs-dangling"),
    ("test_coverage gaps", "test-coverage-gaps"),
)

OPAQUE_COUNTS = (
    ("learner candidates", "learner-candidates"),
    ("mode triggers", "mode-triggers"),
    ("shim hits", "shim-hits"),
)


def _ts_to_epoch(ts: str | None) -> float | None:
    """Parse '2026-05-01T06:15:35Z' → epoch seconds. None on failure."""
    if not ts:
        return None
    try:
        return time.mktime(time.strptime(ts.rstrip("Z"), "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return None


def _filter_since(events: list[dict], since_seconds: float | None) -> list[dict]:
    if since_seconds is None:
        return events
    cutoff = time.time() - since_seconds
    out: list[dict] = []
    for ev in events:
        epoch = _ts_to_epoch(ev.get("ts"))
        if epoch is None or epoch >= cutoff:
            out.append(ev)
    return out


def _parse_since_arg(arg: str) -> float:
    """'24h' / '7d' / '60m' / '300s' → seconds."""
    if not arg:
        raise ValueError("empty")
    unit = arg[-1].lower()
    value = float(arg[:-1])
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if unit not in multipliers:
        raise ValueError(f"unknown unit {unit!r} — use s/m/h/d")
    return value * multipliers[unit]


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = int(len(sorted_values) * pct / 100)
    idx = min(idx, len(sorted_values) - 1)
    return sorted_values[idx]


def report_hook_latency(events: list[dict]) -> dict[str, Any]:
    """Group hook-latency by name → p50/p95/max (ms) + status counts."""
    by_name: dict[str, list[float]] = {}
    error_counts: dict[str, int] = {}
    for ev in events:
        name = ev.get("name") or "unknown"
        dur = ev.get("duration_ms")
        if isinstance(dur, (int, float)):
            by_name.setdefault(name, []).append(float(dur))
        if ev.get("status") == "error":
            error_counts[name] = error_counts.get(name, 0) + 1

    summary: dict[str, Any] = {}
    for name, durations in sorted(by_name.items()):
        durations.sort()
        summary[name] = {
            "n": len(durations),
            "p50_ms": round(_percentile(durations, 50), 1),
            "p95_ms": round(_percentile(durations, 95), 1),
            "max_ms": round(durations[-1], 1) if durations else 0.0,
            "errors": error_counts.get(name, 0),
        }
    return summary


def report_skill_match(events: list[dict], top_n: int = 10) -> dict[str, Any]:
    """Roll up skill-match events: total invocations, top-N skills by frequency."""
    total = len(events)
    skill_counter: Counter[str] = Counter()
    truncated = 0
    phases_counter: Counter[str] = Counter()
    for ev in events:
        for entry in ev.get("top") or []:
            name = entry.get("name") if isinstance(entry, dict) else None
            if name:
                skill_counter[name] += 1
        if ev.get("truncated"):
            truncated += 1
        for phase in ev.get("phases") or []:
            phases_counter[phase] += 1
    return {
        "invocations": total,
        "truncated_pct": round(100.0 * truncated / total, 1) if total else 0.0,
        "top_skills": skill_counter.most_common(top_n),
        "top_phases": phases_counter.most_common(5),
    }


def report_debate_triggers(events: list[dict]) -> dict[str, Any]:
    total = len(events)
    strict = sum(1 for e in events if e.get("strict_design") is True)
    phase_counter: Counter[str] = Counter()
    cwd_counter: Counter[str] = Counter()
    for ev in events:
        phase = ev.get("phase")
        if phase:
            phase_counter[phase] += 1
        cwd = ev.get("cwd")
        if cwd:
            cwd_counter[cwd] += 1
    return {
        "total_prompts": total,
        "strict_design_count": strict,
        "strict_design_pct": round(100.0 * strict / total, 1) if total else 0.0,
        "top_phases": phase_counter.most_common(5),
        "top_cwds": cwd_counter.most_common(5),
    }


def report_validators(since_seconds: float | None) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for label, category in VALIDATOR_CATEGORIES:
        events = _filter_since(list(iter_events(category)), since_seconds)
        out.append((label, len(events)))
    return out


def report_opaque(since_seconds: float | None) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for label, category in OPAQUE_COUNTS:
        events = _filter_since(list(iter_events(category)), since_seconds)
        out.append((label, len(events)))
    return out


def render_text(report: dict[str, Any]) -> str:
    lines: list[str] = []
    window = report.get("window", "all-time")
    lines.append(f"=== telemetry_report (window={window}) ===\n")

    # Hook latency
    lines.append("--- hook-latency (ms) ---")
    hl = report["hook_latency"]
    if hl:
        lines.append(f"  {'name':<30} {'n':>6} {'p50':>8} {'p95':>8} {'max':>8} {'err':>5}")
        for name, stats in hl.items():
            lines.append(
                f"  {name:<30} {stats['n']:>6} "
                f"{stats['p50_ms']:>8.1f} {stats['p95_ms']:>8.1f} "
                f"{stats['max_ms']:>8.1f} {stats['errors']:>5}"
            )
    else:
        lines.append("  (no events)")
    lines.append("")

    # Skill match
    lines.append("--- skill-match ---")
    sm = report["skill_match"]
    lines.append(f"  invocations: {sm['invocations']}")
    lines.append(f"  truncated:   {sm['truncated_pct']}%")
    if sm["top_skills"]:
        lines.append(f"  top {len(sm['top_skills'])} matched skills:")
        for name, count in sm["top_skills"]:
            lines.append(f"    {count:>4}x {name}")
    if sm["top_phases"]:
        lines.append(f"  top phases: {', '.join(f'{p}={c}' for p, c in sm['top_phases'])}")
    lines.append("")

    # Debate triggers
    lines.append("--- debate-triggers ---")
    dt = report["debate_triggers"]
    lines.append(f"  total prompts:     {dt['total_prompts']}")
    lines.append(f"  strict_design:     {dt['strict_design_count']} ({dt['strict_design_pct']}%)")
    if dt["top_phases"]:
        lines.append(f"  top phases:        {', '.join(f'{p}={c}' for p, c in dt['top_phases'])}")
    lines.append("")

    # Validators
    lines.append("--- validator violations (rollup) ---")
    for label, count in report["validators"]:
        lines.append(f"  {label:<30} {count:>6}")
    lines.append("")

    # Opaque counts
    lines.append("--- other categories (counts only) ---")
    for label, count in report["opaque_counts"]:
        lines.append(f"  {label:<30} {count:>6}")

    return "\n".join(lines)


def report_evaluator_accuracy(since_seconds: float | None) -> dict[str, Any]:
    """Aggregate state/evaluator/*/axis_scores.jsonl across all sids.

    Returns dict with: total_events, sids_count, verdict_dist + pct,
    axis_means (1-5 per axis), completeness_rate %, fallback_rate %,
    fallback_reasons Counter, split_rate % (ensemble).

    Empty state/evaluator/ → all-zero dict (autopilot Phase 3.5 not yet
    exercised).
    """
    from lib.paths import STATE_DIR
    from lib.axis_scores_log import read_axis_events

    base = STATE_DIR / "evaluator"
    cutoff = (time.time() - since_seconds) if since_seconds is not None else None

    verdict_counter: Counter[str] = Counter()
    axis_sums: dict[str, float] = {}
    axis_counts: dict[str, int] = {}
    completeness_true = 0
    fallback_count = 0
    fallback_reasons: Counter[str] = Counter()
    split_true = 0
    total_events = 0
    sids: list[str] = []

    if base.exists():
        for sid_dir in base.iterdir():
            if not sid_dir.is_dir():
                continue
            events = read_axis_events(sid_dir.name)
            if not events:
                continue
            sids.append(sid_dir.name)
            for ev in events:
                if cutoff is not None:
                    ts = ev.get("ts")
                    if isinstance(ts, (int, float)) and ts < cutoff:
                        continue
                total_events += 1
                verdict = ev.get("verdict")
                if verdict in ("approved", "iterate", "escalate"):
                    verdict_counter[verdict] += 1
                axes = ev.get("axis_scores")
                if isinstance(axes, dict):
                    for k, v in axes.items():
                        if (isinstance(k, str) and
                                isinstance(v, (int, float)) and
                                not isinstance(v, bool)):
                            axis_sums[k] = axis_sums.get(k, 0.0) + float(v)
                            axis_counts[k] = axis_counts.get(k, 0) + 1
                if ev.get("completeness") is True:
                    completeness_true += 1
                fb = ev.get("fallback_reason")
                if fb:
                    fallback_count += 1
                    # Strip ":evaluator_id[:detail]" suffix for category key
                    reason_key = str(fb).split(":", 1)[0]
                    fallback_reasons[reason_key] += 1
                if ev.get("split") is True:
                    split_true += 1

    axis_means = {
        k: round(axis_sums[k] / axis_counts[k], 2)
        for k in sorted(axis_sums)
        if axis_counts.get(k, 0) > 0
    }

    def _pct(n: int) -> float:
        return round(100.0 * n / total_events, 1) if total_events else 0.0

    return {
        "window": (
            f"last-{int(since_seconds)}s" if since_seconds is not None else "all-time"
        ),
        "total_events": total_events,
        "sids_count": len(sids),
        "verdict_dist": dict(verdict_counter),
        "verdict_pct": {k: _pct(v) for k, v in verdict_counter.items()},
        "axis_means": axis_means,
        "completeness_rate_pct": _pct(completeness_true),
        "fallback_rate_pct": _pct(fallback_count),
        "fallback_reasons": dict(fallback_reasons),
        "split_rate_pct": _pct(split_true),
    }


def render_evaluator_accuracy_text(report: dict[str, Any]) -> str:
    lines: list[str] = []
    window = report.get("window", "all-time")
    lines.append(f"=== evaluator accuracy (window={window}) ===\n")
    lines.append(f"  total events:    {report['total_events']}")
    lines.append(f"  sessions (sids): {report['sids_count']}")
    lines.append("")
    if report["total_events"] == 0:
        lines.append("  (no events — autopilot Phase 3.5 not yet exercised; "
                     "run `/harness-autopilot <goal>` 1+ to populate)")
        return "\n".join(lines)
    lines.append("--- verdict distribution ---")
    for verdict in ("approved", "iterate", "escalate"):
        count = report["verdict_dist"].get(verdict, 0)
        pct = report["verdict_pct"].get(verdict, 0.0)
        lines.append(f"  {verdict:<10} {count:>5} ({pct:>5.1f}%)")
    lines.append("")
    if report["axis_means"]:
        lines.append("--- axis 1-5 means ---")
        for k, v in report["axis_means"].items():
            lines.append(f"  {k:<15} {v:>5.2f}")
        lines.append("")
    lines.append(f"--- completeness rate: {report['completeness_rate_pct']}% ---")
    lines.append(f"--- fallback rate:     {report['fallback_rate_pct']}% ---")
    if report["fallback_reasons"]:
        lines.append("    reasons:")
        for r, c in sorted(report["fallback_reasons"].items(),
                           key=lambda x: -x[1]):
            lines.append(f"      {c:>4}x {r}")
    lines.append(f"--- ensemble split rate: {report['split_rate_pct']}% ---")
    return "\n".join(lines)


def build_report(since_seconds: float | None) -> dict[str, Any]:
    return {
        "window": (
            f"last-{int(since_seconds)}s" if since_seconds is not None else "all-time"
        ),
        "hook_latency": report_hook_latency(
            _filter_since(list(iter_events(HOOK_LATENCY)), since_seconds)
        ),
        "skill_match": report_skill_match(
            _filter_since(list(iter_events(SKILL_MATCH)), since_seconds)
        ),
        "debate_triggers": report_debate_triggers(
            _filter_since(list(iter_events(DEBATE_TRIGGERS)), since_seconds)
        ),
        "validators": report_validators(since_seconds),
        "opaque_counts": report_opaque(since_seconds),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--json", action="store_true",
        help="emit machine-readable JSON instead of text",
    )
    parser.add_argument(
        "--since", type=str, default="",
        help="filter to events newer than N (e.g. '24h', '7d', '60m', '300s')",
    )
    parser.add_argument(
        "--evaluator-accuracy", action="store_true",
        help="(v15.38) emit evaluator-dispatch accuracy stats from "
             "state/evaluator/*/axis_scores.jsonl instead of full report",
    )
    args = parser.parse_args()

    since_seconds: float | None = None
    if args.since:
        try:
            since_seconds = _parse_since_arg(args.since)
        except ValueError as e:
            print(f"[error] invalid --since value: {e}", file=sys.stderr)
            return 2

    if args.evaluator_accuracy:
        eval_report = report_evaluator_accuracy(since_seconds)
        if args.json:
            print(json.dumps(eval_report, ensure_ascii=False, indent=2))
        else:
            print(render_evaluator_accuracy_text(eval_report))
        return 0

    report = build_report(since_seconds)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
