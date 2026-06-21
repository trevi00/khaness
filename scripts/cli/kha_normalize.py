#!/usr/bin/env python3
"""kha SKILL.md normalizer — round-2 P0 mechanical step.

Applies the normalization template from `state/kha-skill-patches-round2.md`
to all 68 kha-* SKILL.md files:

1. Frontmatter extension — adds `category`, `mutates`, `long-running` fields
   to YAML frontmatter (idempotent — only writes when value missing or wrong).
   - category: one of audit / review / verify / validate / remediate / capture
     / triage / run / lifecycle / plan / phase-mutation / status / workflow / meta
   - mutates: yes if the skill writes .planning/ artifacts, commits, or
     deletes/archives anything; no for read-only inspection.
   - long-running: yes for multi-step orchestration or external CLI invocation
     that can take >1 minute; no for inline single-step work.

2. Standard section headers — appends stub sections at end of body when
   missing (header detected by exact `## Output`, `## Failure behavior`,
   `## Gate summary`, `## Retry / Resume` match):
   - All skills: Output, Failure behavior, Gate summary
   - long-running=yes only: Retry / Resume

   Stubs include `<!-- TODO -->` markers so subsequent passes can find and
   fill them in. Existing sections are NEVER modified.

The CATEGORY map is the canonical taxonomy from the round-2 report and
derives mutates/long-running from per-category defaults plus per-skill
overrides for edge cases (e.g. kha-debug is remediate but has heavy
diagnose-only behavior).

Usage:
    cd ~/.claude/scripts
    python -m cli.kha_normalize                  # dry-run report
    python -m cli.kha_normalize --apply          # write changes
    python -m cli.kha_normalize --check          # exit 1 if any kha skill missing fields
    python -m cli.kha_normalize --report-only    # show classification table

Exit code: 0 success; 1 on validation/write failure or --check drift.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.paths import SKILLS_DIR  # noqa: E402
from lib.frontmatter_norm import (  # noqa: E402
    ensure_field as _ensure_frontmatter_field,
    has_section as _has_section,
)


# ---------------------------------------------------------------------------
# Taxonomy — every kha-* skill mapped to (category, mutates, long_running)
# Derived from state/kha-skill-patches-round2.md verb taxonomy + mutation/runtime heuristics.
# ---------------------------------------------------------------------------

# Defaults per category. Per-skill overrides below.
_CATEGORY_DEFAULTS: dict[str, tuple[bool, bool]] = {
    # category:           (mutates, long_running)
    "lifecycle":          (True,  True),
    "plan":               (True,  True),
    "phase-mutation":     (True,  False),
    "run":                (True,  True),
    "status":             (False, False),
    "capture":            (True,  False),
    "triage":             (True,  False),
    "audit":              (False, True),
    "review":             (False, True),
    "verify":             (False, True),
    "validate":           (True,  True),
    "remediate":          (True,  True),
    "workflow":           (True,  False),
    "meta":               (True,  False),
}

# Authoritative classification — 68 kha skills.
SKILL_CATEGORY: dict[str, str] = {
    # lifecycle
    "kha-new-project":              "lifecycle",
    "kha-new-milestone":            "lifecycle",
    "kha-new-workspace":            "lifecycle",
    "kha-complete-milestone":       "lifecycle",
    "kha-pause-work":               "lifecycle",
    "kha-resume-work":              "lifecycle",
    # plan / research
    "kha-plan-phase":               "plan",
    "kha-research-phase":           "plan",
    "kha-clarify-phase":            "plan",
    "kha-plan-gap-phases":          "plan",
    "kha-explore-idea":             "plan",
    # phase mutation
    "kha-add-phase":                "phase-mutation",
    "kha-insert-phase":             "phase-mutation",
    "kha-remove-phase":             "phase-mutation",
    "kha-generate-tests":           "phase-mutation",
    # run / execute
    "kha-execute-phase":            "run",
    "kha-run-trivial":              "run",
    "kha-run-adhoc":                "run",
    "kha-run-milestone":            "run",
    "kha-dispatch":                 "run",
    # status / navigation
    "kha-status":                   "status",
    "kha-advance":                  "status",
    "kha-phase-assumptions":        "status",
    # capture
    "kha-capture-note":             "capture",
    "kha-capture-todo":             "capture",
    "kha-capture-seed":             "capture",
    "kha-capture-backlog":          "capture",
    # triage
    "kha-triage-todos":             "triage",
    "kha-triage-backlog":           "triage",
    # audit
    "kha-audit-milestone":          "audit",
    "kha-audit-uat-backlog":        "audit",
    "kha-audit-planning-health":    "audit",
    "kha-forensics":                "audit",
    # review
    "kha-review-code":              "review",
    "kha-review-ui":                "review",
    "kha-review-plan-peer":         "review",
    # verify
    "kha-verify-uat":               "verify",
    # validate
    "kha-verify-security-phase":    "validate",
    "kha-validate-nyquist-phase":   "validate",
    "kha-spec-ui-phase":            "validate",
    "kha-analyze-dependencies":     "validate",
    # remediate
    "kha-remediate-code-review":    "remediate",
    "kha-remediate-audit-findings": "remediate",
    "kha-debug":                    "remediate",
    "kha-archive-completed-phases": "remediate",
    # workflow (git/branch/PR)
    "kha-context-thread":           "workflow",
    "kha-prepare-pr-branch":        "workflow",
    "kha-submit-pr":                "workflow",
    "kha-revert-work":              "workflow",
    "kha-reapply-local-patches":    "workflow",
    "kha-import-plan":              "workflow",
    # meta
    "kha-settings":                 "meta",
    "kha-set-model-profile":        "meta",
    "kha-self-update":              "meta",
    "kha-user-profile":             "meta",
    "kha-intel-index":              "meta",
    "kha-map-codebase":             "meta",
    "kha-scan-codebase":            "meta",
    "kha-milestone-summary":        "meta",
    "kha-sync-docs":                "meta",
    "kha-session-report":           "meta",
    "kha-project-stats":            "meta",
    "kha-help":                     "meta",
    "kha-join-discord":             "meta",
    "kha-milestone-manager":        "meta",
    "kha-list-workspaces":          "meta",
    "kha-remove-workspace":         "meta",
    "kha-workstream-manager":       "meta",
}

# Per-skill overrides for (mutates, long_running) — only when default is wrong.
_OVERRIDES: dict[str, tuple[bool, bool]] = {
    # status: kha-advance is mutating (commits .planning state)
    "kha-advance":                  (True, False),
    # workflow: most are mutating, but submit-pr/revert/reapply are long-running too
    "kha-submit-pr":                (True, True),
    "kha-revert-work":              (True, True),
    "kha-reapply-local-patches":    (True, True),
    "kha-context-thread":           (True, False),
    "kha-import-plan":              (True, True),
    # meta: read-only ones
    "kha-help":                     (False, False),
    "kha-list-workspaces":          (False, False),
    "kha-project-stats":            (False, False),
    "kha-session-report":           (False, False),
    "kha-milestone-summary":        (False, True),
    "kha-join-discord":             (False, False),
    "kha-scan-codebase":            (False, True),
    "kha-map-codebase":             (False, True),
    # phase-mutation that's actually long-running
    "kha-generate-tests":           (True, True),
    # Round-4 reclassification (codex workers identified these as short-running):
    "kha-dispatch":                 (True, False),   # routes to mutating sub-commands
    "kha-explore-idea":             (True, False),   # interactive but quick
    "kha-pause-work":               (True, False),   # state save (quick)
    "kha-resume-work":              (True, False),   # state restore (quick)
    "kha-run-trivial":              (True, False),   # inline single step
    # Round 7 D.1 P11 — audit/repair mode split: repair mutates, default audit is read-only
    "kha-audit-planning-health":    (True, True),
}


def classify(skill_name: str) -> tuple[str, bool, bool]:
    """Return (category, mutates, long_running) for a kha skill."""
    cat = SKILL_CATEGORY.get(skill_name, "meta")
    if skill_name in _OVERRIDES:
        mutates, long_running = _OVERRIDES[skill_name]
    else:
        mutates, long_running = _CATEGORY_DEFAULTS[cat]
    return cat, mutates, long_running


# ---------------------------------------------------------------------------
# Frontmatter editing
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^(---\s*\n)(.*?)(\n---\s*\n)(.*)$", re.DOTALL)


def normalize_frontmatter(content: str, skill_name: str) -> str:
    cat, mutates, long_running = classify(skill_name)
    m = _FRONTMATTER_RE.match(content)
    if not m:
        # Synthesize minimal frontmatter
        return (
            f"---\nname: {skill_name}\n"
            f"category: {cat}\n"
            f"mutates: {'yes' if mutates else 'no'}\n"
            f"long-running: {'yes' if long_running else 'no'}\n"
            f"---\n{content}"
        )
    fm_open, fm_body, fm_close, body = m.group(1), m.group(2), m.group(3), m.group(4)
    fm_body = _ensure_frontmatter_field(fm_body, "category", cat)
    fm_body = _ensure_frontmatter_field(fm_body, "mutates", "yes" if mutates else "no")
    fm_body = _ensure_frontmatter_field(fm_body, "long-running", "yes" if long_running else "no")
    return f"{fm_open}{fm_body}{fm_close}{body}"


# ---------------------------------------------------------------------------
# Standard section stubs
# ---------------------------------------------------------------------------

_OUTPUT_STUB = """\
## Output

<!-- TODO: fill in actual outputs (artifact paths, status indicators) -->
- artifact: `<path>` — <description>
- status: `<success/failure indicator>`
"""

_FAILURE_STUB = """\
## Failure behavior

<!-- TODO: per-failure recovery contracts -->
- preflight failure: <action — typically no writes, surface blocking reason>
- execution failure: <action — preserve recovery handles, print resume instruction>
- partial success: <action — what stays, what gets rolled back>
"""

_GATE_STUB = """\
## Gate summary

<!-- TODO: fill in real preflight + success criteria -->
- preflight: <required state / inputs before execution>
- success criteria: <how completion is determined>
"""

_RETRY_STUB = """\
## Retry / Resume

<!-- TODO: long-running skill — define checkpoint + resume contract -->
- checkpoint: `<file path>`
- resume command: `<command-line>`
- idempotent: <yes/no — explain>
"""


def append_missing_sections(content: str, skill_name: str) -> str:
    _, _, long_running = classify(skill_name)
    additions: list[str] = []
    if not _has_section(content, "Output"):
        additions.append(_OUTPUT_STUB)
    if not _has_section(content, "Failure behavior"):
        additions.append(_FAILURE_STUB)
    if not _has_section(content, "Gate summary"):
        additions.append(_GATE_STUB)
    if long_running and not _has_section(content, "Retry / Resume"):
        additions.append(_RETRY_STUB)

    if not additions:
        return content
    suffix = "\n\n" + "\n".join(additions).rstrip() + "\n"
    return content.rstrip() + suffix


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def normalize_one(path: Path, skill_name: str) -> tuple[bool, str]:
    """Return (changed, new_content)."""
    original = path.read_text(encoding="utf-8")
    step1 = normalize_frontmatter(original, skill_name)
    step2 = append_missing_sections(step1, skill_name)
    return (step2 != original), step2


def collect_kha_skills() -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for d in sorted(SKILLS_DIR.iterdir()):
        if not d.is_dir() or not d.name.startswith("kha-"):
            continue
        skill = d / "SKILL.md"
        if not skill.is_file():
            continue
        out.append((d.name, skill))
    return out


def check() -> tuple[bool, list[str]]:
    """Verify every kha-* skill has the required frontmatter + sections."""
    issues: list[str] = []
    for name, path in collect_kha_skills():
        cat, mutates, long_running = classify(name)
        content = path.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(content)
        if not m:
            issues.append(f"{name}: no frontmatter")
            continue
        fm_body = m.group(2)
        for key, expected in [
            ("category", cat),
            ("mutates", "yes" if mutates else "no"),
            ("long-running", "yes" if long_running else "no"),
        ]:
            if not re.search(rf"^{re.escape(key)}\s*:\s*{re.escape(expected)}\s*$",
                              fm_body, re.MULTILINE):
                issues.append(f"{name}: frontmatter missing/wrong {key}={expected}")
        for sec in ("Output", "Failure behavior", "Gate summary"):
            if not _has_section(content, sec):
                issues.append(f"{name}: missing section ## {sec}")
        if long_running and not _has_section(content, "Retry / Resume"):
            issues.append(f"{name}: long-running but missing ## Retry / Resume")
    return (not issues), issues


def report_classification() -> str:
    L = []
    by_category: dict[str, list[tuple[str, bool, bool]]] = {}
    for name in sorted(SKILL_CATEGORY):
        cat, mut, lr = classify(name)
        by_category.setdefault(cat, []).append((name, mut, lr))
    L.append(f"{'category':16} {'skill':40} mut  lr")
    L.append("-" * 70)
    for cat in sorted(by_category):
        for name, mut, lr in by_category[cat]:
            L.append(f"{cat:16} {name:40} {('yes' if mut else 'no'):3}  {('yes' if lr else 'no'):3}")
    L.append("")
    L.append(f"Total: {len(SKILL_CATEGORY)} skills across {len(by_category)} categories")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Normalize kha-* SKILL.md (frontmatter + standard sections)")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    ap.add_argument("--check", action="store_true", help="verify all kha skills already normalized")
    ap.add_argument("--report-only", action="store_true", help="print classification table only")
    args = ap.parse_args(argv)

    if args.report_only:
        print(report_classification())
        return 0

    if args.check:
        ok, issues = check()
        if ok:
            print(f"[PASS] all {len(SKILL_CATEGORY)} kha skills normalized")
            return 0
        print(f"[FAIL] {len(issues)} issue(s):")
        for i in issues:
            print(f"  - {i}")
        return 1

    skills = collect_kha_skills()
    if not skills:
        print("[FAIL] no kha-* skills found", file=sys.stderr)
        return 1

    changed = 0
    unchanged = 0
    for name, path in skills:
        is_changed, new_content = normalize_one(path, name)
        if is_changed:
            if args.apply:
                path.write_text(new_content, encoding="utf-8")
            changed += 1
        else:
            unchanged += 1

    print(f"[OK] {'applied' if args.apply else 'would apply'}: changed={changed}  unchanged={unchanged}  total={len(skills)}")
    if not args.apply:
        print("(dry-run — pass --apply to write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
