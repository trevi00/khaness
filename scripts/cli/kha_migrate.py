#!/usr/bin/env python3
"""kha migration — full gsd-* → kha-* refactor (agents + references + delete).

Three-phase migration tool. Each phase is idempotent and can be run
independently. Default is dry-run; --apply to mutate.

Phase A — agents:
  Rename agents/gsd-X.md → agents/kha-X.md and update the `name:` field
  inside each file's frontmatter. Simple prefix swap (no semantic renames
  in agents — only in skills).

Phase B — references:
  Search-replace `gsd-X` → `kha-Y` across all participating .md files
  (skills/**/*.md, agents/*.md, commands/*.md, HARNESS-GUIDE.md, root
  README*). Substitution map is the union of:
    - 24 agent prefix swaps (gsd-Z → kha-Z for each Z)
    - 68 skill renames from cli.kha_alias.RENAME_MAP
  Ordered longest-first to avoid partial-match collisions.

Phase C — delete legacy:
  Remove skills/gsd-*/ directories. ONLY runs after Phase B has produced
  zero remaining `gsd-*` references in participating files (--check-zero
  enforces this; pass --force to override).

Excluded from rewrite (historical / auto-generated / out-of-tree):
  state/gsd-to-kha-review.md   (the report itself)
  state/debates/**             (event sourcing log, immutable)
  state/inventory.md           (auto-regen)
  changelog.md                 (historical)
  projects/**/memory/**        (user memory, leave for user)
  .omc/**                      (worker outputs)
  scripts/cli/kha_alias.py     (the alias map source)
  scripts/cli/kha_migrate.py   (this file)
  scripts/tests/test_kha_*.py  (tests must keep both names visible)

Usage:
    cd ~/.claude/scripts
    python -m cli.kha_migrate --phase agents                   # dry-run
    python -m cli.kha_migrate --phase agents --apply
    python -m cli.kha_migrate --phase references               # dry-run
    python -m cli.kha_migrate --phase references --apply
    python -m cli.kha_migrate --phase delete                   # dry-run + check-zero
    python -m cli.kha_migrate --phase delete --apply
    python -m cli.kha_migrate --phase all --apply              # A → B → C in sequence

Exit code: 0 on success, 1 on validation/write failure.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cli.kha_alias import RENAME_MAP as SKILL_RENAME_MAP  # noqa: E402
from lib.paths import CLAUDE_HOME, SKILLS_DIR  # noqa: E402


AGENTS_DIR = CLAUDE_HOME / "agents"
COMMANDS_DIR = CLAUDE_HOME / "commands"
HARNESS_GUIDE = CLAUDE_HOME / "HARNESS-GUIDE.md"


# Agents are pure prefix swap (no semantic renames).
AGENT_NAMES = [
    "advisor-researcher", "assumptions-analyzer", "codebase-mapper",
    "code-fixer", "code-reviewer", "debugger", "doc-verifier", "doc-writer",
    "executor", "integration-checker", "intel-updater", "nyquist-auditor",
    "phase-researcher", "plan-checker", "planner", "project-researcher",
    "research-synthesizer", "roadmapper", "security-auditor", "ui-auditor",
    "ui-checker", "ui-researcher", "user-profiler", "verifier",
]


def build_substitution_map() -> dict[str, str]:
    """Union of agent + skill renames. Longest-first ordering for safe replace."""
    sub: dict[str, str] = {}
    for name in AGENT_NAMES:
        sub[f"gsd-{name}"] = f"kha-{name}"
    for gsd, kha in SKILL_RENAME_MAP.items():
        sub[gsd] = kha
    return sub


# Globs for files to rewrite. Excludes are applied via _is_excluded below.
INCLUDE_GLOBS = [
    "skills/**/*.md",
    "agents/*.md",
    "commands/*.md",
    "HARNESS-GUIDE.md",
    "README*.md",
]


def _is_excluded(path: Path) -> bool:
    rel = path.relative_to(CLAUDE_HOME).as_posix()
    excluded_prefixes = (
        "state/gsd-to-kha-review.md",
        "state/debates/",
        "state/inventory.md",
        "changelog.md",
        "projects/",
        ".omc/",
        "scripts/cli/kha_alias.py",
        "scripts/cli/kha_migrate.py",
        "scripts/tests/test_kha_alias.py",
        "scripts/tests/test_kha_migrate.py",
    )
    if any(rel == p or rel.startswith(p) for p in excluded_prefixes):
        return True
    # Filenames ending with _gsd_ pattern that are intentionally historic
    return False


def _gather_targets() -> list[Path]:
    out: list[Path] = []
    seen: set[Path] = set()
    for pat in INCLUDE_GLOBS:
        for p in CLAUDE_HOME.glob(pat):
            if not p.is_file():
                continue
            if p in seen:
                continue
            if _is_excluded(p):
                continue
            seen.add(p)
            out.append(p)
    return sorted(out)


# ---------------------------------------------------------------------------
# Phase A — agents rename
# ---------------------------------------------------------------------------

_NAME_LINE_RE = re.compile(r"^name:\s*[\"']?gsd-([A-Za-z0-9-]+)[\"']?\s*$",
                            re.MULTILINE)


def phase_agents(apply: bool) -> tuple[int, int, list[str]]:
    """Rename agents/gsd-X.md → agents/kha-X.md + frontmatter `name:` swap."""
    if not AGENTS_DIR.is_dir():
        return 0, 0, [f"agents dir missing: {AGENTS_DIR}"]

    renamed = 0
    skipped = 0
    failures: list[str] = []

    for name in AGENT_NAMES:
        gsd_path = AGENTS_DIR / f"gsd-{name}.md"
        kha_path = AGENTS_DIR / f"kha-{name}.md"

        if kha_path.is_file() and not gsd_path.is_file():
            skipped += 1
            continue
        if not gsd_path.is_file():
            failures.append(f"missing source: {gsd_path}")
            continue
        if kha_path.is_file():
            failures.append(f"both exist (manual review): {gsd_path} + {kha_path}")
            continue

        try:
            content = gsd_path.read_text(encoding="utf-8")
        except Exception as e:
            failures.append(f"read error {gsd_path}: {e}")
            continue

        new_content = _NAME_LINE_RE.sub(f"name: kha-{name}", content, count=1)

        if not apply:
            renamed += 1
            continue

        try:
            kha_path.write_text(new_content, encoding="utf-8")
            gsd_path.unlink()
            renamed += 1
        except Exception as e:
            failures.append(f"write/delete error {name}: {e}")
            continue

    return renamed, skipped, failures


# ---------------------------------------------------------------------------
# Phase B — references rewrite
# ---------------------------------------------------------------------------

def _build_replace_regex(sub: dict[str, str]) -> re.Pattern:
    # Order longest first so `gsd-list-phase-assumptions` matches before `gsd-list`.
    keys = sorted(sub.keys(), key=len, reverse=True)
    # Word boundary: gsd-X must not be followed by an identifier char.
    pattern = "(" + "|".join(re.escape(k) for k in keys) + r")(?![A-Za-z0-9_-])"
    return re.compile(pattern)


def phase_references(apply: bool) -> tuple[int, int, list[str], dict[str, int]]:
    sub = build_substitution_map()
    rx = _build_replace_regex(sub)

    files_changed = 0
    files_unchanged = 0
    failures: list[str] = []
    per_file: dict[str, int] = {}

    for path in _gather_targets():
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            failures.append(f"read error {path}: {e}")
            continue

        # Count + apply substitutions in one pass via re.sub callback
        count = 0

        def _sub(m: re.Match) -> str:
            nonlocal count
            count += 1
            return sub[m.group(1)]

        new_content = rx.sub(_sub, content)
        if count == 0:
            files_unchanged += 1
            continue

        per_file[path.relative_to(CLAUDE_HOME).as_posix()] = count

        if not apply:
            files_changed += 1
            continue

        try:
            path.write_text(new_content, encoding="utf-8")
            files_changed += 1
        except Exception as e:
            failures.append(f"write error {path}: {e}")

    return files_changed, files_unchanged, failures, per_file


# ---------------------------------------------------------------------------
# Phase C — delete legacy
# ---------------------------------------------------------------------------

def count_remaining_references() -> int:
    """Count gsd-* references in participating files (post-Phase-B sanity check)."""
    sub = build_substitution_map()
    rx = _build_replace_regex(sub)
    total = 0
    for path in _gather_targets():
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue
        total += len(rx.findall(content))
    return total


def phase_delete(apply: bool, force: bool) -> tuple[int, int, list[str]]:
    """Delete skills/gsd-*/ directories. Refuses when references remain unless --force."""
    failures: list[str] = []

    if not force:
        remaining = count_remaining_references()
        if remaining > 0:
            return 0, 0, [
                f"refusing to delete: {remaining} gsd-* reference(s) still exist "
                "in participating files. Run Phase B (--phase references --apply) "
                "first, or pass --force to override.",
            ]

    deleted = 0
    skipped = 0
    for child in sorted(SKILLS_DIR.iterdir()):
        if not child.is_dir() or not child.name.startswith("gsd-"):
            continue
        if not apply:
            deleted += 1
            continue
        try:
            shutil.rmtree(child)
            deleted += 1
        except Exception as e:
            failures.append(f"delete error {child}: {e}")
    return deleted, skipped, failures


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="gsd → kha migration")
    ap.add_argument("--phase", choices=["agents", "references", "delete", "all"],
                    required=True)
    ap.add_argument("--apply", action="store_true", help="actually mutate (default: dry-run)")
    ap.add_argument("--force", action="store_true",
                    help="(phase=delete) skip the zero-reference check")
    ap.add_argument("--quiet", action="store_true", help="suppress per-file diff list")
    args = ap.parse_args(argv)

    rc = 0
    phases = ["agents", "references", "delete"] if args.phase == "all" else [args.phase]

    for phase in phases:
        print(f"\n=== Phase {phase} ({'apply' if args.apply else 'dry-run'}) ===")
        if phase == "agents":
            renamed, skipped, failures = phase_agents(args.apply)
            print(f"agents renamed={renamed}  skipped={skipped}  failures={len(failures)}")
            for f in failures:
                print(f"  - {f}")
            if failures:
                rc = 1
        elif phase == "references":
            ch, unch, failures, per_file = phase_references(args.apply)
            print(f"files changed={ch}  unchanged={unch}  failures={len(failures)}")
            if not args.quiet:
                for path, n in sorted(per_file.items(), key=lambda kv: -kv[1])[:30]:
                    print(f"  {n:4}× {path}")
            for f in failures:
                print(f"  - {f}")
            if failures:
                rc = 1
        elif phase == "delete":
            deleted, _, failures = phase_delete(args.apply, args.force)
            print(f"directories deleted={deleted}  failures={len(failures)}")
            for f in failures:
                print(f"  - {f}")
            if failures:
                rc = 1

    if not args.apply:
        print("\n(dry-run — pass --apply to mutate)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
