#!/usr/bin/env python3
"""kha alias generator — 68 gsd-* skills → kha-* aliases.

For each (gsd_name, kha_name) pair in RENAME_MAP, this tool:
  1. Reads `~/.claude/skills/<gsd_name>/SKILL.md`
  2. Copies the body to `~/.claude/skills/<kha_name>/SKILL.md`
  3. Updates frontmatter `name:` field from gsd_name → kha_name
  4. Prepends a small "kha alias" advisory to the description
  5. (Optional) Adds a deprecation banner to the gsd source

The mapping is the canonical output of the team-1777420051 review and lives
in `state/gsd-to-kha-review.md` — kept here as a Python literal so the
script is self-contained.

Usage:
    cd ~/.claude/scripts
    python -m cli.kha_alias                  # dry-run, show what would change
    python -m cli.kha_alias --apply          # actually create kha-* dirs
    python -m cli.kha_alias --apply --deprecate-source   # also add deprecation banner to gsd-*
    python -m cli.kha_alias --check          # verify all kha-* exist + frontmatter matches map
    python -m cli.kha_alias --report         # print summary table

Exit code: 0 on success; 1 on validation or write failure.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.paths import SKILLS_DIR  # noqa: E402


# ---------------------------------------------------------------------------
# Rename map — derived from state/gsd-to-kha-review.md
# ---------------------------------------------------------------------------

# 24 simple prefix-swap (name was already accurate)
SIMPLE_SWAP = [
    "new-project", "new-milestone", "new-workspace", "complete-milestone",
    "plan-phase", "execute-phase", "research-phase",
    "add-phase", "insert-phase", "remove-phase",
    "resume-work", "pause-work",
    "debug", "forensics", "audit-milestone", "analyze-dependencies",
    "milestone-summary", "session-report", "help", "join-discord",
    "list-workspaces", "remove-workspace", "map-codebase", "settings",
]

# 44 semantic renames (gsd_name → kha_name)
SEMANTIC = {
    "discuss-phase":         "clarify-phase",
    "list-phase-assumptions": "phase-assumptions",
    "progress":              "status",
    "next":                  "advance",
    "autonomous":            "run-milestone",
    "add-backlog":           "capture-backlog",
    "add-todo":              "capture-todo",
    "add-tests":             "generate-tests",
    "check-todos":           "triage-todos",
    "note":                  "capture-note",
    "plant-seed":            "capture-seed",
    "explore":               "explore-idea",
    "do":                    "dispatch",
    "review-backlog":        "triage-backlog",
    "import":                "import-plan",
    "fast":                  "run-trivial",
    "quick":                 "run-adhoc",
    "thread":                "context-thread",
    "pr-branch":             "prepare-pr-branch",
    "ship":                  "submit-pr",
    "undo":                  "revert-work",
    "reapply-patches":       "reapply-local-patches",
    "code-review":           "review-code",
    "code-review-fix":       "remediate-code-review",
    "audit-fix":             "remediate-audit-findings",
    "audit-uat":             "audit-uat-backlog",
    "secure-phase":          "verify-security-phase",
    "validate-phase":        "validate-nyquist-phase",
    "verify-work":           "verify-uat",
    "ui-phase":              "spec-ui-phase",
    "ui-review":             "review-ui",
    "review":                "review-plan-peer",
    "plan-milestone-gaps":   "plan-gap-phases",
    "cleanup":               "archive-completed-phases",
    "health":                "audit-planning-health",
    "set-profile":           "set-model-profile",
    "update":                "self-update",
    "profile-user":          "user-profile",
    "intel":                 "intel-index",
    "scan":                  "scan-codebase",
    "docs-update":           "sync-docs",
    "stats":                 "project-stats",
    "manager":               "milestone-manager",
    "workstreams":           "workstream-manager",
}


def build_rename_map() -> dict[str, str]:
    out = {f"gsd-{n}": f"kha-{n}" for n in SIMPLE_SWAP}
    for gsd_suffix, kha_suffix in SEMANTIC.items():
        out[f"gsd-{gsd_suffix}"] = f"kha-{kha_suffix}"
    return out


RENAME_MAP = build_rename_map()


# ---------------------------------------------------------------------------
# Frontmatter editing
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
_NAME_LINE_RE = re.compile(r"^name:\s*[\"']?([\w-]+)[\"']?\s*$", re.MULTILINE)


def rewrite_frontmatter(content: str, new_name: str, original_name: str) -> str:
    """Replace `name:` field in YAML frontmatter; preserve everything else."""
    m = _FRONTMATTER_RE.match(content)
    if not m:
        # No frontmatter — synthesize one
        return f"---\nname: {new_name}\n---\n{content}"
    fm, body = m.group(1), m.group(2)
    new_fm = _NAME_LINE_RE.sub(f"name: {new_name}", fm)
    if new_fm == fm:
        # name field absent — prepend it
        new_fm = f"name: {new_name}\n{fm}"
    # Add an alias note in description if present
    if "description:" in new_fm and original_name != new_name:
        # No-op for now — leave description unchanged so the kha skill reads
        # exactly as the gsd one did. We may add a "(kha alias of gsd-X)"
        # note in a later pass once we confirm Claude Code's skill listing
        # behavior with multiple identical descriptions.
        pass
    return f"---\n{new_fm}\n---\n{body}"


_DEPRECATION_BANNER = """\
> [!warning]
> **DEPRECATED** — this skill has been renamed to `/{new_name}`.
> The old `/{old_name}` alias remains for 90 days for backward compatibility
> and will be removed on/after {removal_date}. Update your scripts and
> documentation to use `/{new_name}`.

"""


def add_deprecation_banner(content: str, old_name: str, new_name: str,
                            removal_date: str) -> str:
    """Insert a deprecation banner immediately after the frontmatter."""
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return _DEPRECATION_BANNER.format(
            old_name=old_name, new_name=new_name, removal_date=removal_date
        ) + content
    fm, body = m.group(1), m.group(2)
    banner = _DEPRECATION_BANNER.format(
        old_name=old_name, new_name=new_name, removal_date=removal_date
    )
    if "DEPRECATED" in body[:300]:
        return content  # already deprecated, idempotent
    return f"---\n{fm}\n---\n{banner}{body}"


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def plan_actions() -> list[dict]:
    """Build a per-pair action list. No filesystem mutation."""
    actions = []
    for gsd, kha in RENAME_MAP.items():
        gsd_dir = SKILLS_DIR / gsd
        kha_dir = SKILLS_DIR / kha
        gsd_skill = gsd_dir / "SKILL.md"
        kha_skill = kha_dir / "SKILL.md"

        action = {
            "gsd": gsd, "kha": kha,
            "gsd_dir_exists": gsd_dir.is_dir(),
            "kha_dir_exists": kha_dir.is_dir(),
            "gsd_skill_exists": gsd_skill.is_file(),
            "kha_skill_exists": kha_skill.is_file(),
            "rename_kind": "swap" if gsd[4:] == kha[4:] else "semantic",
        }
        actions.append(action)
    return actions


def apply_actions(deprecate_source: bool, removal_date: str) -> tuple[int, int, list[str]]:
    """Create kha-* dirs + SKILL.md from gsd-* sources. Optionally add deprecation banner."""
    created = 0
    skipped = 0
    failures: list[str] = []

    for gsd, kha in RENAME_MAP.items():
        gsd_skill = SKILLS_DIR / gsd / "SKILL.md"
        kha_dir = SKILLS_DIR / kha
        kha_skill = kha_dir / "SKILL.md"

        if not gsd_skill.is_file():
            failures.append(f"missing source: {gsd_skill}")
            continue

        try:
            content = gsd_skill.read_text(encoding="utf-8")
        except Exception as e:
            failures.append(f"read error {gsd}: {e}")
            continue

        # Generate kha SKILL.md
        new_content = rewrite_frontmatter(content, new_name=kha, original_name=gsd)

        # Idempotency check — if kha exists with same content, skip
        if kha_skill.is_file():
            try:
                existing = kha_skill.read_text(encoding="utf-8")
                if existing == new_content:
                    skipped += 1
                    continue
            except Exception:
                pass

        kha_dir.mkdir(parents=True, exist_ok=True)
        try:
            kha_skill.write_text(new_content, encoding="utf-8")
            created += 1
        except Exception as e:
            failures.append(f"write error {kha}: {e}")
            continue

        # Deprecation banner on source
        if deprecate_source:
            try:
                src_content = gsd_skill.read_text(encoding="utf-8")
                deprecated = add_deprecation_banner(
                    src_content, old_name=gsd, new_name=kha,
                    removal_date=removal_date,
                )
                if deprecated != src_content:
                    gsd_skill.write_text(deprecated, encoding="utf-8")
            except Exception as e:
                failures.append(f"deprecate error {gsd}: {e}")

    return created, skipped, failures


def check() -> tuple[bool, list[str]]:
    """Verify each kha-* dir exists with the correct frontmatter name."""
    errors: list[str] = []
    for gsd, kha in RENAME_MAP.items():
        kha_skill = SKILLS_DIR / kha / "SKILL.md"
        if not kha_skill.is_file():
            errors.append(f"missing: {kha_skill}")
            continue
        try:
            content = kha_skill.read_text(encoding="utf-8")
        except Exception as e:
            errors.append(f"read error {kha}: {e}")
            continue
        m = _NAME_LINE_RE.search(content)
        if not m or m.group(1) != kha:
            errors.append(
                f"frontmatter name mismatch in {kha}: "
                f"got {m.group(1) if m else 'none'!r}, expected {kha!r}"
            )
    return (not errors), errors


def report() -> str:
    actions = plan_actions()
    L = []
    L.append(f"Total renames: {len(RENAME_MAP)} (simple={len(SIMPLE_SWAP)}, semantic={len(SEMANTIC)})")
    L.append("")
    L.append(f"{'Status':14} {'gsd':32} → {'kha':32}")
    L.append("-" * 88)
    counts = {"NEW": 0, "EXISTS": 0, "MISSING_SRC": 0}
    for a in actions:
        if not a["gsd_skill_exists"]:
            status = "MISSING_SRC"
        elif a["kha_skill_exists"]:
            status = "EXISTS"
        else:
            status = "NEW"
        counts[status] += 1
        L.append(f"{status:14} {a['gsd']:32} → {a['kha']:32}")
    L.append("-" * 88)
    L.append(f"NEW={counts['NEW']}  EXISTS={counts['EXISTS']}  MISSING_SRC={counts['MISSING_SRC']}")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Generate kha-* aliases for gsd-* skills")
    ap.add_argument("--apply", action="store_true", help="actually write kha-* dirs (default: dry-run)")
    ap.add_argument("--deprecate-source", action="store_true",
                    help="also add deprecation banner to gsd-* SKILL.md")
    ap.add_argument("--removal-date", default="2026-07-29",
                    help="deprecation removal target date (banner text only)")
    ap.add_argument("--check", action="store_true", help="verify all kha-* exist with correct frontmatter")
    ap.add_argument("--report", action="store_true", help="print summary table")
    args = ap.parse_args(argv)

    if args.check:
        ok, errs = check()
        if ok:
            print(f"[PASS] all {len(RENAME_MAP)} kha-* aliases present + frontmatter consistent")
            return 0
        print(f"[FAIL] {len(errs)} issues:")
        for e in errs:
            print(f"  - {e}")
        return 1

    if args.report or not args.apply:
        print(report())
        if not args.apply:
            print("\n(dry-run — pass --apply to create kha-* directories)")
        if not args.apply:
            return 0

    created, skipped, failures = apply_actions(
        deprecate_source=args.deprecate_source,
        removal_date=args.removal_date,
    )
    print(f"\n[OK] created={created}  skipped={skipped}  failures={len(failures)}")
    if failures:
        for f in failures:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
