#!/usr/bin/env python3
"""skill_telemetry_audit — weight / false-positive audit of skill-match telemetry (M7).

🧵 signal-spend: `handlers/prompt/skill_match.py` LOGS every skill match to
telemetry/skill-match.jsonl (top-5 {name, score, dims} per prompt). `cli.telemetry_report`
already rolls up match FREQUENCY — this CLI spends the richer score+dimension signal on
the question that frequency alone cannot answer: **which skills fire often but WEAKLY**
(coincidental single-signal matches — the documented 승인→example_gateway-example_vendor polysemy class),
and **which scoring dimension drives matches overall** (weight audit).

Per skill it computes: match count, score min/median/max, thin-signal rate (% of matches
scoring < FULL_BODY_MIN_SCORE, i.e. never eligible for full-body injection), and the
dominant matched-dimension category (intent / kw / path / pat). A skill that matches
≥ MIN_SAMPLES times, is thin ≥ FP_THIN_RATE of the time, AND has a median score in the
thin band is flagged a **false-positive candidate** — its keyword/intent surface is too
broad and should be narrowed (a skill-frontmatter mutation, which stays operator-gated;
this audit only SURFACES candidates, it never edits a skill).

Read-only. Empty telemetry → graceful empty report (exit 0). Mirrors cli.telemetry_report
style (--json, --since N[smhd]).

Usage:
    python -m cli.skill_telemetry_audit                 # text report
    python -m cli.skill_telemetry_audit --json          # machine-readable
    python -m cli.skill_telemetry_audit --since 7d      # last 7 days only
    python -m cli.skill_telemetry_audit --min-samples 5 # raise the judging floor
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
# M2a: thin-fire classification constants + predicate are single-sourced in
# lib.thin_skill_advisor so the passive audit (here) and the prompt-time advisory
# can never drift. THIN_SCORE_CEILING mirrors skill_match.py FULL_BODY_MIN_SCORE=3:
# a match scoring <= 2 is never eligible for full-body injection (thin signal).
from lib.thin_skill_advisor import (  # noqa: E402
    THIN_SCORE_CEILING, MIN_SAMPLES, FP_THIN_RATE,
)

SKILL_MATCH = "skill-match"

_DIM_CATEGORIES = ("intent", "path", "kw", "pat")  # display order (by scoring weight)


def _parse_since_arg(arg: str) -> float:
    """'24h' / '7d' / '60m' / '300s' → seconds. Raises ValueError on bad unit."""
    if not arg:
        raise ValueError("empty")
    unit = arg[-1].lower()
    value = float(arg[:-1])
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if unit not in mult:
        raise ValueError(f"unknown unit {unit!r} — use s/m/h/d")
    return value * mult[unit]


def _ts_to_epoch(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        return time.mktime(time.strptime(ts.rstrip("Z"), "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return None


def _dim_category(dim: str) -> str:
    """'intent:API' -> 'intent'; 'kw:test' -> 'kw'; unknown -> 'unknown'."""
    if not isinstance(dim, str) or ":" not in dim:
        return "unknown"
    cat = dim.split(":", 1)[0]
    return cat if cat in _DIM_CATEGORIES else "unknown"


def audit(events: list[dict], *, min_samples: int = MIN_SAMPLES) -> dict[str, Any]:
    """Aggregate skill-match telemetry into a per-skill weight/FP report.

    Returns {invocations, skills: {name: {...}}, false_positive_candidates: [...],
    dim_weight: {category: count}} — pure, no I/O.
    """
    scores: dict[str, list[int]] = {}
    dim_counts: dict[str, Counter] = {}
    overall_dim: Counter = Counter()

    for ev in events:
        for entry in ev.get("top") or []:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            score = entry.get("score")
            if not isinstance(name, str) or not isinstance(score, int):
                continue
            scores.setdefault(name, []).append(score)
            dc = dim_counts.setdefault(name, Counter())
            for d in entry.get("dims") or []:
                cat = _dim_category(d)
                dc[cat] += 1
                overall_dim[cat] += 1

    skills: dict[str, Any] = {}
    fp_candidates: list[dict[str, Any]] = []
    for name, sc in scores.items():
        sc_sorted = sorted(sc)
        count = len(sc_sorted)
        median = statistics.median(sc_sorted)
        thin = sum(1 for s in sc_sorted if s <= THIN_SCORE_CEILING)
        thin_rate = thin / count
        dc = dim_counts.get(name, Counter())
        dominant_dim = dc.most_common(1)[0][0] if dc else None
        rec = {
            "count": count,
            "score_min": sc_sorted[0],
            "score_median": median,
            "score_max": sc_sorted[-1],
            "thin_rate": round(thin_rate, 3),
            "dominant_dim": dominant_dim,
            "dim_breakdown": dict(dc),
        }
        skills[name] = rec
        # Constants single-sourced from lib.thin_skill_advisor (no drift with the
        # prompt-time advisor); the CLI keeps its own --min-samples override as the
        # count floor in place of the default MIN_SAMPLES.
        if count >= min_samples and thin_rate >= FP_THIN_RATE and median <= THIN_SCORE_CEILING:
            fp_candidates.append({
                "name": name,
                "count": count,
                "thin_rate": round(thin_rate, 3),
                "score_median": median,
                "dominant_dim": dominant_dim,
                "reason": (
                    f"fires {count}x but {round(thin_rate * 100)}% are thin (score<={THIN_SCORE_CEILING}, "
                    f"never full-body); median {median}. Narrow the "
                    f"{dominant_dim or 'matching'} surface."
                ),
            })

    fp_candidates.sort(key=lambda c: (-c["count"], c["name"]))
    return {
        "invocations": len(events),
        "skills": skills,
        "false_positive_candidates": fp_candidates,
        "dim_weight": dict(overall_dim),
    }


def render_text(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"=== skill telemetry audit ({report['invocations']} invocations) ===\n")
    skills = report["skills"]
    if not skills:
        lines.append("(no skill-match telemetry — run some prompts to populate)")
        return "\n".join(lines)

    lines.append("--- per-skill score profile (by match count) ---")
    lines.append(f"  {'skill':<34} {'n':>4} {'min':>4} {'med':>4} {'max':>4} {'thin%':>6} dom-dim")
    for name, r in sorted(skills.items(), key=lambda kv: (-kv[1]["count"], kv[0])):
        lines.append(
            f"  {name:<34} {r['count']:>4} {r['score_min']:>4} "
            f"{r['score_median']:>4} {r['score_max']:>4} "
            f"{round(r['thin_rate'] * 100):>5}% {r['dominant_dim'] or '-'}"
        )
    lines.append("")

    lines.append("--- dimension weight (what drives matches overall) ---")
    dw = report["dim_weight"]
    if dw:
        total = sum(dw.values()) or 1  # falsy-zero-ok: intentional div-by-zero guard (denominator below)
        for cat in _DIM_CATEGORIES + ("unknown",):
            if cat in dw:
                lines.append(f"  {cat:<10} {dw[cat]:>6} ({round(100 * dw[cat] / total)}%)")
    else:
        lines.append("  (no dim data — telemetry predates M7 dims enrichment)")
    lines.append("")

    fps = report["false_positive_candidates"]
    lines.append(f"--- false-positive candidates ({len(fps)}) ---")
    if fps:
        for c in fps:
            lines.append(f"  ⚠ {c['name']}: {c['reason']}")
    else:
        lines.append("  (none — no skill fires often-yet-thin above threshold)")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.skill_telemetry_audit",
        description="Weight / false-positive audit of skill-match telemetry (M7).",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable JSON")
    parser.add_argument("--since", type=str, default="",
                        help="filter to events newer than N (e.g. '7d', '24h', '60m')")
    parser.add_argument("--min-samples", type=int, default=MIN_SAMPLES,
                        help=f"min matches before judging a skill (default {MIN_SAMPLES})")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    events = list(iter_events(SKILL_MATCH))
    if args.since:
        try:
            cutoff = time.time() - _parse_since_arg(args.since)
        except ValueError as e:
            sys.stderr.write(f"[error] invalid --since: {e}\n")
            return 2
        events = [e for e in events
                  if (_ts_to_epoch(e.get("ts")) is None or _ts_to_epoch(e.get("ts")) >= cutoff)]

    report = audit(events, min_samples=args.min_samples)
    if args.json:
        sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(render_text(report) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
