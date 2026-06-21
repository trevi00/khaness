#!/usr/bin/env python3
"""Bulk-add `output_schema: free_text` to agent .md frontmatter (v15.10 A7m).

Per debate-1778946602-jj7vxk implementation note 2, every agent_type must
have a declared output_schema before D2 validator activation. This script
performs a mechanical migration:

  - For every agent .md file under ~/.claude/agents/ that is classified
    MISSING by `cli.output_schema_audit`, inject `output_schema: free_text`
    immediately before the closing `---` of the YAML frontmatter.
  - free_text is the conservative default: it claims "this agent produces
    unstructured prose" so lib.validators.structural.validate() silently
    skips layer 1. Agents that DO emit structured JSON should later be
    upgraded to a real JSON-Schema object via direct edit.

The migration is idempotent:
  - If `output_schema:` already exists in frontmatter, no change.
  - PRESENT_XML agents keep their XML block — the audit treats them as
    covered in non-strict mode, but the strict-mode coverage check
    requires migration to frontmatter form. Pass `--include-xml` to also
    add the free_text key to PRESENT_XML agents (recommended for strict-
    mode unblock).

Usage:
    python -m cli.output_schema_migrate --dry-run     # preview
    python -m cli.output_schema_migrate                # apply (MISSING only)
    python -m cli.output_schema_migrate --include-xml  # apply to PRESENT_XML too

Exit codes:
    0  success — files updated (or dry-run printed)
    1  no candidates found / no changes needed
    2  argparse error
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.paths import AGENTS_DIR  # noqa: E402
from cli.output_schema_audit import audit, classify_agent  # noqa: E402


def _migrate_file(path: Path, *, dry_run: bool) -> bool:
    """Insert `output_schema: free_text` before closing frontmatter ---.

    Returns True iff the file was changed (or would be changed in dry-run).
    Returns False if the file has no frontmatter (cannot migrate safely).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    if not text.startswith("---"):
        return False
    parts = text.split("---", 2)
    if len(parts) < 3:
        return False
    # parts: ['', '<frontmatter>', '<body>']
    frontmatter = parts[1]
    body = parts[2]
    # Skip if already present (defensive — audit may have caught a different form)
    for line in frontmatter.splitlines():
        if line.strip().startswith("output_schema:"):
            return False
    # Insert before the closing fence. Frontmatter is delimited as:
    #   ---\n<key: val>\n...---\n
    # We rebuild keeping the trailing newline of the frontmatter block
    # (so the new key sits on its own line with proper newline boundaries).
    fm_stripped = frontmatter.rstrip("\n")
    new_frontmatter = fm_stripped + "\noutput_schema: free_text\n"
    new_text = "---" + new_frontmatter + "---" + body
    if dry_run:
        return True
    path.write_text(new_text, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="output-schema-migrate",
        description="v15.10 A7m bulk-migrate agents to declared output_schema",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would change without writing")
    parser.add_argument("--include-xml", action="store_true",
                        help="also migrate agents currently classified PRESENT_XML")
    parser.add_argument("--agents-dir", default=None,
                        help="override agents directory")
    args = parser.parse_args(argv)

    agents_dir = Path(args.agents_dir) if args.agents_dir else AGENTS_DIR
    report = audit(agents_dir, strict=False)
    candidates: list[str] = list(report["__summary__"]["missing"])
    if args.include_xml:
        candidates.extend(
            name for name, cls in report["agents"].items()
            if cls == "PRESENT_XML"
        )
    candidates = sorted(set(candidates))

    if not candidates:
        print("[OK] nothing to migrate — all agents already declare output_schema")
        return 1

    changed: list[str] = []
    skipped: list[tuple[str, str]] = []
    for name in candidates:
        path = agents_dir / f"{name}.md"
        if _migrate_file(path, dry_run=args.dry_run):
            changed.append(name)
        else:
            reason = "no frontmatter" if not path.exists() or not path.read_text(encoding="utf-8").startswith("---") else "already present"
            skipped.append((name, reason))

    verb = "would change" if args.dry_run else "changed"
    print(f"[OK] {verb} {len(changed)} agent file(s); {len(skipped)} skipped")
    for name in changed:
        print(f"  + {name}")
    for name, reason in skipped:
        print(f"  - {name} ({reason})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
