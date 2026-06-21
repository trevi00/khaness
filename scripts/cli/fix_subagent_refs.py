#!/usr/bin/env python3
"""Rewrite legacy `subagent_type='gsd-X'` → `subagent_type='kha-X'` in workflow docs.

The kha migration renamed agents/gsd-*.md → agents/kha-*.md but did NOT update
references inside `get-shit-done/workflows/*.md`. Those workflows are loaded
into kha SKILL.md via `@` directives, so a stale `gsd-executor` reference
causes silent runtime failure.

This script:
1. Scans target dirs (default: get-shit-done/, get-shit-done-references/).
2. Finds every `subagent_type` reference to `gsd-<NAME>`.
3. If `agents/kha-<NAME>.md` exists, rewrite to `kha-<NAME>`.
4. Reports which references were rewritten vs left untouched (no kha equivalent).

Idempotent: re-running on already-rewritten files is a no-op.
Default mode is dry-run; pass `--apply` to write.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULT_DIRS = (
    "get-shit-done",
)

# Match `subagent_type` then `=` or `:`, optional whitespace/quotes, then capture
# `gsd-<name>`. Preserves the surrounding quote style on rewrite.
_REF_RE = re.compile(
    r"""(subagent_type\s*[=:]\s*["']?)gsd-([a-z][\w-]*)(["']?)""",
    re.IGNORECASE,
)


def _kha_agents() -> set[str]:
    agents_dir = REPO_ROOT / "agents"
    return {p.stem for p in agents_dir.glob("kha-*.md")}


def _rewrite_text(text: str, kha_agents: set[str]) -> tuple[str, int, list[str]]:
    """Return (new_text, replaced_count, untouched_names)."""
    replaced = 0
    untouched: list[str] = []

    def _sub(m: re.Match) -> str:
        nonlocal replaced
        prefix, name, suffix = m.group(1), m.group(2), m.group(3)
        kha_name = f"kha-{name}"
        if kha_name in kha_agents:
            replaced += 1
            return f"{prefix}{kha_name}{suffix}"
        untouched.append(f"gsd-{name}")
        return m.group(0)

    new_text = _REF_RE.sub(_sub, text)
    return new_text, replaced, untouched


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually write (default: dry-run)")
    ap.add_argument("--dirs", nargs="*", default=list(DEFAULT_DIRS),
                    help="dirs to scan, relative to repo root")
    args = ap.parse_args(argv)

    kha_agents = _kha_agents()
    if not kha_agents:
        print("[ERR] no kha-* agents found under agents/", file=sys.stderr)
        return 2

    total_files_changed = 0
    total_refs_replaced = 0
    untouched_summary: dict[str, int] = {}

    for d in args.dirs:
        root = REPO_ROOT / d
        if not root.is_dir():
            print(f"[skip] {d} (not a directory)")
            continue
        for path in sorted(root.glob("**/*.md")):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as e:
                print(f"[err] {path.relative_to(REPO_ROOT)}: {e}")
                continue
            new_text, replaced, untouched = _rewrite_text(text, kha_agents)
            for u in untouched:
                untouched_summary[u] = untouched_summary.get(u, 0) + 1
            if replaced == 0:
                continue
            rel = path.relative_to(REPO_ROOT)
            verb = "rewrote" if args.apply else "would rewrite"
            print(f"  {rel}: {verb} {replaced} ref(s)")
            total_files_changed += 1
            total_refs_replaced += replaced
            if args.apply:
                path.write_text(new_text, encoding="utf-8")

    verb = "rewrote" if args.apply else "would rewrite"
    print(f"\n=== {verb} {total_refs_replaced} ref(s) in {total_files_changed} file(s) ===")
    if untouched_summary:
        print("\nUntouched (no kha-* equivalent):")
        for name, count in sorted(untouched_summary.items(), key=lambda x: -x[1]):
            print(f"  {name}: {count}")
    if not args.apply:
        print("\n(dry-run — pass --apply to write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
