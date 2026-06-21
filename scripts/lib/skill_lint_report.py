#!/usr/bin/env python3
"""Skill lint baseline analyzer — on-demand telemetry reader.

Reads ~/.claude/telemetry/skill_lint.jsonl (collected silently by the
PostToolUse hook) and produces a per-tree shape distribution + threshold
candidate metrics for R002~R004 P1 decisions.

Boundary:
- Does NOT emit advisory text (telemetry_only_no_advisory invariant).
- Does NOT modify any files. Read-only analysis.
- Pure on-demand utility — separate from the always-on telemetry sink.

Usage:
    cd ~/.claude/scripts
    python -m cli.skill_lint_report                  # full report
    python -m cli.skill_lint_report --tree _common   # filter to one tree
    python -m cli.skill_lint_report --p1-check       # P1 entry criteria evaluation
    python -m cli.skill_lint_report --json           # machine-readable
    python -m cli.skill_lint_report --lint           # R002 enforcement (exit 1 on violation)
    python -m cli.skill_lint_report --lint --warn-only        # report violations, always exit 0
    python -m cli.skill_lint_report --lint --r002-threshold N # override default 30000 bytes

References:
    debate-1777963974-4e8915 — P1 entry redefined per-tree
    debate-1777968334-6b381e — advisory_channel_contract (R002 enforcement, snapshot 603933922d9c)
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.paths import TELEMETRY_DIR, SKILLS_DIR  # noqa: E402

JSONL_PATH = TELEMETRY_DIR / "skill_lint.jsonl"

# Per-tree dominance threshold — a tree is "consistent" when ≥80% of its
# files share the same shape. Drift below 80% suggests partial migration.
TREE_DOMINANCE_THRESHOLD = 0.80

# R002 (file size) enforcement — debate 603933922d9c gen 2 approved.
# Module constant is the SoT; --r002-threshold flag overrides per-run.
# Env var override is intentionally rejected (YAGNI).
R002_DEFAULT_BYTES: int = 30_000

# Path-based grandfather list — explicit code-PR registration only
# (no HTML sentinel mutation of skill files). Each entry is an
# acknowledged R002 violation with a documented split-cost > split-benefit
# trade-off. Forcing function preserved for FUTURE files: any new skill
# .md exceeding R002_DEFAULT_BYTES in a non-drift tree without a matching
# entry here will be reported by lint() with exit-code 1.
#
# Reference: debate 603933922d9c gen 1 outlier_analysis classified each
# of these as "정당하지만 비대 — split candidate, cross-ref cost high".
# TODO(backlog): split into <domain>-<aspect>.md when a contributor has
# the bandwidth for the cross-ref rewiring; remove from this set then.
GRANDFATHERED_PATHS: frozenset[str] = frozenset({
    "_common/security.md",     # ~32_920 bytes — 6 domains (auth/Spring/API/sandbox/frontend/DB)
    "java/example_app/backend.md",  # ~34_815 bytes — 4+ domains (API/ORM/Redis/Kafka/MyBatis)
    # OD4 land 2026-05-18 (allsolution-1779083706-305700 skill-lint-candidates.md):
    "_common/abstraction-first.md",
    #   ~78_429 bytes — V1~V20 catalog (50kb dominant) + lifecycle protocol (Stage 1-5)
    #   + 적용 빈도 매트릭스 + Gotchas. Option B (per-variant split) blocked on
    #   skill loader sub-directory compat verification + V20 nested split need.
    #   Cross-file evidence chain with pattern-auto-detector.md V19/V20 detector
    #   paths (Evidence: impl-105/impl-147/impl-148 chains) — split would
    #   duplicate evidence blocks across files. Sunset trigger: when contributor
    #   bandwidth allows skill loader sub-dir compat verification + V20 sub-split
    #   into catalog-v1-v10-data-state.md + catalog-v11-v19-events-design.md +
    #   catalog-v20-data-shape-narrowing.md, remove from this set.
    "_common/pattern-auto-detector.md",
    #   ~51_285 bytes — V19 detector path (~6kb) + V20 detector path with
    #   sub-variations (~22kb) dominate. Mutually cites abstraction-first.md
    #   V19/V20 entries (Evidence: blocks). Same cross-file rewiring cost as
    #   abstraction-first.md. Sunset trigger: paired split with abstraction-
    #   first.md per Option B contributor bandwidth.
})

# R003 (description quality) reactivation trigger — redesigned at
# debate-1777970195-6b152b (snapshot 42b4a343e390 gen 3).
#
# Design principle: fire_on_change_only. Triggers must measure DELTA
# against a captured baseline so a stable codebase never re-fires.
#
#     reactivate_r003 = (
#         baseline_violators_r002 >= 5            # change-sensitive (current count)
#         OR file_size_stats['p90'] >= 200_000    # bytes — monotonic size growth
#         OR (short_description_ratio_conv_trees - 0.0070) >= 0.05
#                  # +5pp drift vs baseline 0.0070 (1/142 conv_trees)
#                  # denom = shape ∈ {has_upstream_schema, harness_extended}
#                  # +5pp matches R002 sensitivity class — wider band because
#                  # description edits are lower-frequency than file growth
#     )
#
# REMOVED at gen 3: `any tree dominance < 0.60` — flutter (0.44) is a
# stable steady state, not migration drift. Clause was conflating static
# schema diversity with quality regression and produced permanent FIRE.
#
# Baseline freeze protocol (D10): BASELINE_SHORT_DESCRIPTION_RATIO_CONV
# and BASELINE_SNAPSHOT_REF are immutable between debates. New baseline
# values may be issued ONLY by a new R003 debate.

BASELINE_SHORT_DESCRIPTION_RATIO_CONV: float = 0.0070
BASELINE_SNAPSHOT_REF: str = "debate-1777970195-6b152b"
SHORT_DESCRIPTION_THRESHOLD_CHARS: int = 40
R003_DRIFT_THRESHOLD_PP: float = 0.05  # +5 percentage points


def load_records() -> list[dict[str, Any]]:
    if not JSONL_PATH.exists():
        return []
    records = []
    with JSONL_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _tree_of(path: str) -> str:
    norm = path.replace("\\", "/")
    marker = "/skills/"
    idx = norm.rfind(marker)
    if idx < 0:
        return "(unknown)"
    rest = norm[idx + len(marker):]
    parts = rest.split("/")
    return parts[0] if parts else "(unknown)"


def latest_per_path(records: list[dict], skip_missing: bool = True) -> dict[str, dict]:
    """Each path is observed multiple times; keep the most recent.

    skip_missing drops records whose path no longer exists on disk (test temp
    files, deleted/renamed skills) so the baseline reflects current state only.
    """
    latest: dict[str, dict] = {}
    for r in records:
        p = r.get("path", "")
        if not p:
            continue
        if skip_missing and not Path(p).exists():
            continue
        prev = latest.get(p)
        if prev is None or r.get("ts", "") >= prev.get("ts", ""):
            latest[p] = r
    return latest


def shape_distribution(records: dict[str, dict]) -> dict[str, int]:
    dist: dict[str, int] = defaultdict(int)
    for r in records.values():
        dist[r.get("shape", "unknown")] += 1
    return dict(dist)


def per_tree_distribution(records: dict[str, dict]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in records.values():
        tree = _tree_of(r.get("path", ""))
        out[tree][r.get("shape", "unknown")] += 1
    return {t: dict(d) for t, d in out.items()}


def tree_dominance(per_tree: dict[str, dict[str, int]]) -> dict[str, dict]:
    """For each tree, compute dominant shape and dominance ratio."""
    out: dict[str, dict] = {}
    for tree, shapes in per_tree.items():
        n = sum(shapes.values())
        if n == 0:
            continue
        dom_shape, dom_count = max(shapes.items(), key=lambda x: x[1])
        out[tree] = {
            "n": n,
            "dominant": dom_shape,
            "dominance_ratio": dom_count / n,
            "is_consistent": dom_count / n >= TREE_DOMINANCE_THRESHOLD,
            "shapes": shapes,
        }
    return out


def file_size_stats(records: dict[str, dict]) -> dict[str, Any]:
    sizes = [r.get("file_size_bytes", 0) for r in records.values() if r.get("file_size_bytes")]
    if not sizes:
        return {"n": 0}
    sizes.sort()
    return {
        "n": len(sizes),
        "median": statistics.median(sizes),
        "mean": int(statistics.mean(sizes)),
        "p90": sizes[int(len(sizes) * 0.9)],
        "p99": sizes[int(len(sizes) * 0.99)] if len(sizes) > 100 else sizes[-1],
        "max": sizes[-1],
    }


def evaluate_p1_entry(per_tree: dict[str, dict[str, int]]) -> dict[str, Any]:
    """P1 entry redefined: every tree is internally consistent (≥80% dominant).

    Original criteria (harness_extended≥70% AND mixed=0%) was _common-specific
    and proved unworkable globally (kha-* is 100% upstream, typescript 100%
    harness — they SHOULD be different).
    """
    dom = tree_dominance(per_tree)
    inconsistent = {t: d for t, d in dom.items() if not d["is_consistent"]}
    return {
        "criteria": f"every tree dominance ≥ {TREE_DOMINANCE_THRESHOLD * 100:.0f}%",
        "trees_total": len(dom),
        "trees_consistent": sum(1 for d in dom.values() if d["is_consistent"]),
        "trees_inconsistent": list(inconsistent.keys()),
        "ready_for_advisory_channel": not inconsistent,
        "details": dom,
    }


def render_text(report: dict[str, Any]) -> str:
    lines = []
    if report["records_total"] == 0:
        return "No telemetry data — emit records first by editing skill .md files."

    lines.append(f"=== Skill Lint Baseline Report ===")
    lines.append(f"telemetry: {JSONL_PATH}")
    lines.append(f"distinct skill files: {report['files_distinct']}")
    lines.append("")

    lines.append("Overall shape distribution:")
    overall = report["overall_distribution"]
    total = sum(overall.values())
    for shape, n in sorted(overall.items(), key=lambda x: -x[1]):
        pct = n / total * 100 if total else 0
        bar = "#" * int(pct / 3)
        lines.append(f"  {shape:25s} {n:4d} ({pct:5.1f}%) {bar}")
    lines.append("")

    lines.append("Per-tree dominance:")
    for tree, d in sorted(report["tree_dominance"].items()):
        marker = "OK " if d["is_consistent"] else "DRIFT"
        ratio = d["dominance_ratio"] * 100
        lines.append(
            f"  [{marker}] {tree:25s} n={d['n']:3d} dominant={d['dominant']:20s} "
            f"({ratio:5.1f}%)"
        )
    lines.append("")

    p1 = report["p1_entry"]
    lines.append("P1 entry criteria:")
    lines.append(f"  rule: {p1['criteria']}")
    lines.append(f"  consistent trees: {p1['trees_consistent']}/{p1['trees_total']}")
    if p1["trees_inconsistent"]:
        lines.append(f"  drift trees: {', '.join(p1['trees_inconsistent'])}")
    lines.append(f"  ready for advisory channel: {p1['ready_for_advisory_channel']}")
    lines.append("")

    sz = report["file_size_stats"]
    if sz["n"]:
        lines.append("File size (bytes) distribution — R002 threshold candidate:")
        lines.append(
            f"  n={sz['n']} median={sz['median']} mean={sz['mean']} "
            f"p90={sz['p90']} p99={sz['p99']} max={sz['max']}"
        )

    return "\n".join(lines)


def build_report(tree_filter: str | None = None) -> dict[str, Any]:
    records = load_records()
    latest = latest_per_path(records)
    if tree_filter:
        latest = {p: r for p, r in latest.items() if _tree_of(r.get("path", "")) == tree_filter}
    per_tree = per_tree_distribution(latest)
    return {
        "records_total": len(records),
        "files_distinct": len(latest),
        "overall_distribution": shape_distribution(latest),
        "tree_dominance": tree_dominance(per_tree),
        "p1_entry": evaluate_p1_entry(per_tree),
        "file_size_stats": file_size_stats(latest),
    }


def _is_conv_tree_shape(shape: str) -> bool:
    """Trees with description convention. D6' denominator predicate."""
    return shape in ("has_upstream_schema", "harness_extended")


def _short_description_ratio_conv_trees(latest: dict[str, dict] | None) -> tuple[float, int, int]:
    """Compute current short-description ratio over conv_trees only.

    Definition matches baseline: short = description length < SHORT_DESCRIPTION_THRESHOLD_CHARS.
    Re-parses frontmatter on demand because telemetry_schema (locked) only
    carries description_present bool, not length. Locked invariant preserved.
    Returns (ratio, short_count, conv_tree_count). Empty conv_trees → (0.0, 0, 0).
    """
    if not latest:
        return (0.0, 0, 0)
    # Local import to keep top-level imports stable across the file.
    from lib.frontmatter import parse_frontmatter
    short = 0
    conv = 0
    for path, r in latest.items():
        if not _is_conv_tree_shape(r.get("shape", "")):
            continue
        conv += 1
        if not r.get("description_present", False):
            short += 1
            continue
        # Description present per telemetry — measure length to match baseline.
        # If file is missing/unreadable, trust the telemetry bool (not-short).
        try:
            res = parse_frontmatter(path)
            if res is None:
                continue  # file gone; trust telemetry, don't count as short
            meta = res[0]
            desc = meta.get("description", "").strip()
            if len(desc) < SHORT_DESCRIPTION_THRESHOLD_CHARS:
                short += 1
        except Exception:
            # Fail-open: cannot measure → treat as not-short (no false-fire).
            pass
    ratio = short / conv if conv else 0.0
    return (ratio, short, conv)


def evaluate_r003_trigger(
    report: dict[str, Any],
    *,
    latest: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """Programmatic evaluation of the R003 reactivation trigger.

    Implements snapshot 42b4a343e390 (gen 3): three change-sensitive clauses,
    no static-state clauses. fire_on_change_only principle.

    Pure function — does NOT mutate state, NOT emit advisory.
    """
    file_size_p90 = report.get("file_size_stats", {}).get("p90", 0) or 0
    r002_count = report.get("r002_violations_count", 0)
    short_ratio, short_count, conv_count = _short_description_ratio_conv_trees(latest)
    drift = short_ratio - BASELINE_SHORT_DESCRIPTION_RATIO_CONV

    clauses = {
        "r002_violations_ge_5": r002_count >= 5,
        "p90_size_ge_200kb_bytes": file_size_p90 >= 200_000,
        "short_desc_drift_ge_5pp_over_baseline": drift >= R003_DRIFT_THRESHOLD_PP,
    }
    fired = any(clauses.values())
    return {
        "fired": fired,
        "clauses": clauses,
        "metrics": {
            "r002_violations_count": r002_count,
            "file_size_p90_bytes": file_size_p90,
            "short_desc_ratio_current": round(short_ratio, 4),
            "short_desc_ratio_baseline": BASELINE_SHORT_DESCRIPTION_RATIO_CONV,
            "short_desc_drift_pp": round(drift * 100, 2),
            "short_count": short_count,
            "conv_tree_count": conv_count,
        },
        "baseline_ref": BASELINE_SNAPSHOT_REF,
    }


def lint(
    latest: dict[str, dict],
    *,
    threshold_bytes: int = R002_DEFAULT_BYTES,
    exempt_trees: set[str] | None = None,
    grandfathered: frozenset[str] = GRANDFATHERED_PATHS,
) -> list[dict[str, Any]]:
    """R002 violations only. Pure function over latest_per_path output.

    Skips paths whose tree is in exempt_trees (opt-in caller-provided) or
    whose relative path under skills/ is in grandfathered. Returns one dict
    per violation; empty list = clean.

    Default exempt_trees=None → empty set (uniform R002 application).
    Overturning of drift_tree_policy=exempt from snapshot 603933922d9c:
    audit (2026-05-05) showed drift trees are stable mixes with intentional
    pure-harness convention, NOT pending migration. Auto-exemption was
    solving a non-problem and silenced legitimate violations. _exempt_trees
    helper retained for opt-in callers but no longer auto-applied.
    """
    if exempt_trees is None:
        exempt_trees = set()
    skills_root_str = str(SKILLS_DIR).replace("\\", "/").rstrip("/")
    violations: list[dict[str, Any]] = []
    for path, rec in latest.items():
        size = rec.get("file_size_bytes") or 0
        if size < threshold_bytes:
            continue
        tree = _tree_of(path)
        if tree in exempt_trees:
            continue
        norm = path.replace("\\", "/")
        rel = norm[len(skills_root_str) + 1:] if norm.startswith(skills_root_str + "/") else norm
        if rel in grandfathered:
            continue
        violations.append({
            "rule": "R002",
            "path": path,
            "rel_path": rel,
            "tree": tree,
            "file_size_bytes": size,
            "threshold_bytes": threshold_bytes,
        })
    return violations


def render_lint(
    violations: list[dict[str, Any]],
    threshold_bytes: int,
    *,
    deferred: list[dict[str, Any]] | None = None,
    trigger: dict[str, Any] | None = None,
) -> str:
    out = [f"=== Skill Lint (R002 ≤ {threshold_bytes:,} bytes) ==="]
    if not violations:
        out.append("No active violations.")
    else:
        out.append(f"Active violations: {len(violations)}")
        out.append("")
        for v in sorted(violations, key=lambda x: -x["file_size_bytes"]):
            over = v["file_size_bytes"] - v["threshold_bytes"]
            out.append(
                f"  R002 {v['rel_path']:50s}  {v['file_size_bytes']:6,}b  "
                f"(+{over:5,}b over {v['threshold_bytes']:,})"
            )
        out.append("")
        out.append("Remediation options:")
        out.append("  1. Split the file along its dominant axis (multi-domain → per-domain).")
        out.append("  2. Add the rel_path to GRANDFATHERED_PATHS in cli/skill_lint_report.py")
        out.append("     with a code-PR justification (no silent waiver).")

    if deferred:
        out.append("")
        out.append(f"=== Time-bomb (drift-exempt — fires when tree reaches 80% dominance) ===")
        out.append(f"Deferred violations: {len(deferred)}")
        for v in sorted(deferred, key=lambda x: -x["file_size_bytes"]):
            out.append(
                f"  WOULD-R002 {v['rel_path']:46s}  {v['file_size_bytes']:6,}b  "
                f"(tree {v['tree']} now @ {v['tree_dominance_now']:.0%})"
            )

    if trigger:
        out.append("")
        out.append("=== R003 reactivation trigger ===")
        status = "FIRED" if trigger["fired"] else "not fired"
        out.append(f"Status: {status}")
        for clause, hit in trigger["clauses"].items():
            mark = "[X]" if hit else "[ ]"
            out.append(f"  {mark} {clause}")
        m = trigger["metrics"]
        out.append(
            f"  metrics: r002_count={m['r002_violations_count']} "
            f"p90={m['file_size_p90_bytes']:,}b "
            f"short_desc_drift={m['short_desc_drift_pp']}pp "
            f"(current={m['short_desc_ratio_current']:.4f} vs baseline={m['short_desc_ratio_baseline']:.4f})"
        )
        out.append(f"  baseline_ref: {trigger.get('baseline_ref', 'n/a')}")
        if trigger["fired"]:
            out.append("  → open a new debate to decide R003 threshold + scope")
            out.append("    (reference snapshot 603933922d9c)")

    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="skill_lint_report")
    parser.add_argument("--tree", help="Filter to one tree (e.g. _common)")
    parser.add_argument("--p1-check", action="store_true", help="Exit 0 if P1-ready, 1 otherwise")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    parser.add_argument("--lint", action="store_true",
                        help="R002 enforcement: report violations, exit 1 if any (unless --warn-only)")
    parser.add_argument("--r002-threshold", type=int, default=R002_DEFAULT_BYTES,
                        help=f"Override R002 byte threshold (default {R002_DEFAULT_BYTES})")
    parser.add_argument("--warn-only", action="store_true",
                        help="With --lint, always exit 0; useful for first-sprint rollout")
    args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")

    if args.lint:
        records = load_records()
        latest = latest_per_path(records)
        if args.tree:
            latest = {p: r for p, r in latest.items()
                      if _tree_of(r.get("path", "")) == args.tree}
        # Uniform R002 application — drift_tree_policy=exempt overturned
        # 2026-05-05 per audit. would_violate_if_undrifted retained as
        # opt-in helper for callers passing exempt_trees explicitly.
        violations = lint(latest, threshold_bytes=args.r002_threshold)
        trigger = evaluate_r003_trigger(
            {"file_size_stats": file_size_stats(latest),
             "r002_violations_count": len(violations)},
            latest=latest,
        )

        if args.json:
            print(json.dumps({
                "violations": violations,
                "r003_trigger": trigger,
                "threshold_bytes": args.r002_threshold,
            }, ensure_ascii=False, indent=2, default=str))
        else:
            print(render_lint(violations, args.r002_threshold,
                              trigger=trigger))

        if args.warn_only:
            return 0
        return 1 if violations else 0

    report = build_report(tree_filter=args.tree)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print(render_text(report))

    if args.p1_check:
        return 0 if report["p1_entry"]["ready_for_advisory_channel"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
