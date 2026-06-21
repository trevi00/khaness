#!/usr/bin/env python3
"""Skill description trigger accuracy evaluator.

Given a target skill path and a set of (should_trigger, should_not_trigger)
queries, computes recall/precision/F1 and a per-query breakdown showing
how the target competes against other skills in the same phase.

Use case: validating a new skill's frontmatter (keywords/intent/min_score)
before merging. Mirrors the manual process used during qa-boundary.md
addition (debate-1777963974-4e8915, 2026-05-05) where queries were tuned
through 5→3→2 min_score iterations.

Usage:
    python -m cli.skill_trigger_eval <skill.md> --queries <file.json>
    python -m cli.skill_trigger_eval <skill.md> --queries <file.json> --json
    python -m cli.skill_trigger_eval <skill.md> --queries <file.json> --candidates _common

Exit codes:
    0  recall ≥ 0.6 AND precision == 1.0
    1  precision < 1.0 (false-positive on near-miss — frontmatter too aggressive)
    2  recall < 0.6 (under-triggering — frontmatter too narrow)

Origin: revfactory/harness P0 candidate #3, deferred for first standalone
implementation. Snapshot reference: see migration-progress.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.frontmatter import parse_frontmatter  # noqa: E402
from lib.paths import SKILLS_DIR  # noqa: E402
from lib.skill_score import score_skill  # noqa: E402


# Quality thresholds — exit-code mapping.
RECALL_FLOOR: float = 0.60
PRECISION_FLOOR: float = 1.0  # zero false-positive tolerated on near-miss


def discover_candidates(target_path: Path, scope: str | None) -> list[Path]:
    """Find skill .md files to score the target against.

    scope=None    → all skills under SKILLS_DIR
    scope='tree'  → same first-level tree as target (e.g. _common)
    scope='<name>'→ only skills under SKILLS_DIR/<name>/
    """
    if scope is None:
        roots = [SKILLS_DIR]
    elif scope == "tree":
        rel = target_path.resolve().relative_to(SKILLS_DIR.resolve())
        roots = [SKILLS_DIR / rel.parts[0]]
    else:
        roots = [SKILLS_DIR / scope]

    out: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for md in root.rglob("*.md"):
            name = md.name.lower()
            if name in ("readme.md", "changelog.md", "todo.md"):
                continue
            if md.name.startswith("_template"):
                continue
            if md.resolve() == target_path.resolve():
                continue
            out.append(md)
    return out


def score_one(skill_path: Path, prompt: str) -> tuple[bool, int, list[str]]:
    """Score a single skill against a prompt. Empty meta → score 0."""
    res = parse_frontmatter(skill_path)
    meta = res[0] if res else {}
    return score_skill(meta, prompt.lower(), set(), {})


def run_eval(
    target: Path,
    queries: dict[str, list[str]],
    *,
    candidates_scope: str | None = None,
) -> dict[str, Any]:
    """Run the eval. Returns structured result dict."""
    target_name = target.stem
    competitors = discover_candidates(target, candidates_scope)

    def winner_of(prompt: str) -> tuple[str, int]:
        """Highest-scoring skill (target included). Score 0 → no winner."""
        scores: list[tuple[str, int]] = []
        _, ts, _ = score_one(target, prompt)
        scores.append((target_name, ts))
        for c in competitors:
            _, cs, _ = score_one(c, prompt)
            scores.append((c.stem, cs))
        scores.sort(key=lambda x: -x[1])
        if scores[0][1] == 0:
            return ("(none)", 0)
        return scores[0]

    should_trigger = queries.get("should_trigger", [])
    should_not_trigger = queries.get("should_not_trigger", [])

    trigger_results: list[dict] = []
    for q in should_trigger:
        winner, w_score = winner_of(q)
        target_match, target_score, _ = score_one(target, q)
        trigger_results.append({
            "query": q,
            "winner": winner,
            "winner_score": w_score,
            "target_score": target_score,
            "target_matched": target_match,
            # Pass = target matched (≥ min_score) AND is winner.
            "passes": target_match and winner == target_name,
        })

    near_miss_results: list[dict] = []
    for q in should_not_trigger:
        winner, w_score = winner_of(q)
        target_match, target_score, _ = score_one(target, q)
        near_miss_results.append({
            "query": q,
            "winner": winner,
            "winner_score": w_score,
            "target_score": target_score,
            "target_matched": target_match,
            # Pass = target did NOT match (below min_score) — even if it
            # ties at 0 with others, the matcher would not activate it.
            "passes": not target_match,
        })

    recall_pass = sum(1 for r in trigger_results if r["passes"])
    precision_pass = sum(1 for r in near_miss_results if r["passes"])
    recall = recall_pass / len(trigger_results) if trigger_results else 0.0
    precision = precision_pass / len(near_miss_results) if near_miss_results else 1.0
    f1 = (2 * recall * precision / (recall + precision)) if (recall + precision) else 0.0

    # Suggested min_score: lowest target_score among successful triggers.
    successful_target_scores = [r["target_score"] for r in trigger_results if r["passes"]]
    suggested_min_score = min(successful_target_scores) if successful_target_scores else None

    return {
        "target": str(target),
        "target_name": target_name,
        "candidates_count": len(competitors),
        "recall": round(recall, 3),
        "precision": round(precision, 3),
        "f1": round(f1, 3),
        "should_trigger": trigger_results,
        "should_not_trigger": near_miss_results,
        "suggested_min_score": suggested_min_score,
        "verdict": _verdict(recall, precision),
    }


def _verdict(recall: float, precision: float) -> str:
    if precision < PRECISION_FLOOR:
        return "FAIL_PRECISION"
    if recall < RECALL_FLOOR:
        return "FAIL_RECALL"
    return "PASS"


def render_text(result: dict[str, Any]) -> str:
    lines = []
    lines.append(f"=== Trigger Eval — {result['target_name']} ===")
    lines.append(f"target: {result['target']}")
    lines.append(f"candidates: {result['candidates_count']} other skills")
    lines.append("")
    lines.append(
        f"recall={result['recall']:.0%} ({sum(1 for r in result['should_trigger'] if r['passes'])}/{len(result['should_trigger'])}) "
        f"precision={result['precision']:.0%} ({sum(1 for r in result['should_not_trigger'] if r['passes'])}/{len(result['should_not_trigger'])}) "
        f"f1={result['f1']:.2f}"
    )
    lines.append(f"verdict: {result['verdict']}")
    if result["suggested_min_score"] is not None:
        lines.append(f"suggested min_score: {result['suggested_min_score']}")
    lines.append("")

    lines.append("should_trigger:")
    for r in result["should_trigger"]:
        mark = "OK" if r["passes"] else "MISS"
        lines.append(
            f"  [{mark:4s}] target={r['target_score']:2d}  winner={r['winner']}({r['winner_score']})  | {r['query'][:60]}"
        )
    lines.append("")
    lines.append("should_not_trigger:")
    for r in result["should_not_trigger"]:
        mark = "OK" if r["passes"] else "FP"
        lines.append(
            f"  [{mark:4s}] target={r['target_score']:2d}  winner={r['winner']}({r['winner_score']})  | {r['query'][:60]}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="skill_trigger_eval")
    parser.add_argument("skill", help="Target skill .md path")
    parser.add_argument("--queries", required=True,
                        help="JSON file with {should_trigger:[...], should_not_trigger:[...]}")
    parser.add_argument("--candidates", default=None,
                        help="Scope: omit=all, 'tree'=same tree, '<name>'=specific tree")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")

    target = Path(args.skill).resolve()
    if not target.exists():
        print(f"error: target not found: {target}", file=sys.stderr)
        return 2

    try:
        queries = json.loads(Path(args.queries).read_text(encoding="utf-8"))
    except Exception as e:
        print(f"error: cannot read queries: {e}", file=sys.stderr)
        return 2

    result = run_eval(target, queries, candidates_scope=args.candidates)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(render_text(result))

    if result["verdict"] == "FAIL_PRECISION":
        return 1
    if result["verdict"] == "FAIL_RECALL":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
