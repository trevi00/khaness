#!/usr/bin/env python3
"""Parse codex team-1777510773 worker outputs and apply contract fills to kha SKILL.md files.

Each worker emits per-skill blocks of the form:

    === kha-<name> ===

    ## Output
    ...
    ## Failure behavior
    ...
    ## Gate summary
    ...
    ## Retry / Resume   (only when long-running)
    ...

This script extracts those blocks and replaces the `<!-- TODO -->` stub
sections in each kha SKILL.md with the worker's contract content.

Idempotent — only replaces sections that still contain `<!-- TODO -->`.
Already-filled sections are left untouched.
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

TEAM_DIR = Path.home() / ".omc" / "team" / "team-1777510773"

# Sections to replace (by exact `## <header>`)
SECTIONS = ("Output", "Failure behavior", "Gate summary", "Retry / Resume")

# Per-skill block start
SKILL_BLOCK_RE = re.compile(r"^===\s*(kha-[\w-]+)\s*===\s*$", re.MULTILINE)
# Section header inside a block
SECTION_HEADER_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def parse_worker_output(text: str) -> dict[str, dict[str, str]]:
    """Return {skill_name: {section_name: content}} from worker stdout."""
    out: dict[str, dict[str, str]] = {}
    matches = list(SKILL_BLOCK_RE.finditer(text))
    for i, m in enumerate(matches):
        skill = m.group(1)
        block_start = m.end()
        block_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[block_start:block_end]
        sections = parse_sections(block)
        if sections:
            out[skill] = sections
    return out


def parse_sections(block: str) -> dict[str, str]:
    """Split a skill block into {section_name: content}.

    Handles two worker formats:
    A) Heading-style:  `## Output\n<multi-line content>\n## Failure behavior\n...`
    B) Inline-style:   `Output: <one-line>\nFailure: <one-line>\nGate: ...\nRetry: ...`

    Returns canonical SECTIONS keys (`Output`, `Failure behavior`, `Gate summary`,
    `Retry / Resume`) regardless of source variant.
    """
    out: dict[str, str] = {}

    # Variant A — heading style
    headers = list(SECTION_HEADER_RE.finditer(block))
    for i, m in enumerate(headers):
        name = m.group(1).strip()
        if name not in SECTIONS:
            continue
        content_start = m.end()
        content_end = headers[i + 1].start() if i + 1 < len(headers) else len(block)
        rest = block[content_start:content_end].strip()
        if rest:
            out[name] = rest

    # Variant B — inline style (one line per section). Only fill what A didn't.
    inline_map = {
        "Output": r"^Output:\s*(.+)$",
        "Failure behavior": r"^Failure:\s*(.+)$",
        "Gate summary": r"^Gate:\s*(.+)$",
        "Retry / Resume": r"^Retry:\s*(.+)$",
    }
    for canonical, pattern in inline_map.items():
        if canonical in out:
            continue
        m = re.search(pattern, block, re.MULTILINE)
        if m:
            content = m.group(1).strip()
            if not content.startswith("- "):
                content = "- " + content
            out[canonical] = content

    # Variant C — header-without-## (`Output\n- bullet1\n- bullet2\n\nFailure\n...`)
    variant_c_map = {
        "Output": "Output",
        "Failure behavior": "Failure",
        "Gate summary": "Gate",
        "Retry / Resume": "Retry",
    }
    headers_c = list(re.finditer(r"^(Output|Failure|Gate|Retry)\s*$",
                                  block, re.MULTILINE))
    for i, m in enumerate(headers_c):
        label = m.group(1)
        canonical = next((k for k, v in variant_c_map.items() if v == label), None)
        if canonical is None or canonical in out:
            continue
        body_start = m.end()
        body_end = headers_c[i + 1].start() if i + 1 < len(headers_c) else len(block)
        body = block[body_start:body_end].strip()
        if body:
            out[canonical] = body

    return out


def find_skill_md(skill: str) -> Path | None:
    p = SKILLS_DIR / skill / "SKILL.md"
    return p if p.is_file() else None


def replace_stub_section(content: str, section_name: str, new_body: str) -> tuple[str, bool]:
    """Replace `## <section_name>` block with new_body if it currently contains <!-- TODO -->."""
    # Find the section header + everything until next header or EOF
    pattern = re.compile(
        rf"(##\s+{re.escape(section_name)}\s*\n)((?:.|\n)*?)(?=\n##\s+|\Z)",
        re.MULTILINE,
    )
    m = pattern.search(content)
    if not m:
        return content, False
    header, body = m.group(1), m.group(2)
    if "<!-- TODO" not in body:
        return content, False  # already filled
    # Compose new section text
    new_section = header + "\n" + new_body.strip() + "\n"
    new_content = content[: m.start()] + new_section + content[m.end():]
    return new_content, True


def apply_skill(skill: str, fills: dict[str, str], dry_run: bool) -> tuple[int, list[str]]:
    """Return (sections_replaced, notes)."""
    path = find_skill_md(skill)
    if path is None:
        return 0, [f"{skill}: SKILL.md not found"]
    content = path.read_text(encoding="utf-8")
    original = content
    replaced = 0
    notes: list[str] = []
    for sec_name in SECTIONS:
        if sec_name not in fills:
            continue
        new_content, changed = replace_stub_section(content, sec_name, fills[sec_name])
        if changed:
            content = new_content
            replaced += 1
        else:
            notes.append(f"{skill}: '{sec_name}' already filled (skipped)")
    if not dry_run and content != original:
        path.write_text(content, encoding="utf-8")
    return replaced, notes


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Apply kha SKILL.md substantive fills from worker outputs")
    ap.add_argument("--apply", action="store_true", help="actually write (default: dry-run)")
    ap.add_argument("--worker", type=int, choices=[1, 2, 3, 4],
                    help="apply only one worker (default: all 4)")
    args = ap.parse_args(argv)

    workers = [args.worker] if args.worker else [1, 2, 3, 4]
    total_skills = 0
    total_sections = 0
    failures: list[str] = []
    skipped_notes: list[str] = []

    for w in workers:
        out_path = TEAM_DIR / f"worker-{w}.out"
        if not out_path.is_file():
            failures.append(f"worker-{w}: output file missing")
            continue
        text = out_path.read_text(encoding="utf-8", errors="replace")
        skill_fills = parse_worker_output(text)
        print(f"\n--- worker-{w}: {len(skill_fills)} skills parsed ---")
        for skill, fills in sorted(skill_fills.items()):
            replaced, notes = apply_skill(skill, fills, dry_run=not args.apply)
            if replaced > 0:
                print(f"  {skill}: {replaced} sections {'replaced' if args.apply else 'would replace'}")
                total_skills += 1
                total_sections += replaced
            skipped_notes.extend(notes)

    print(f"\n=== summary: {total_skills} skills, {total_sections} sections "
          f"{'replaced' if args.apply else 'would replace'} ===")
    if skipped_notes:
        print(f"  skipped (already filled): {len(skipped_notes)}")
    if failures:
        print("  failures:")
        for f in failures:
            print(f"    - {f}")
        return 1
    if not args.apply:
        print("(dry-run — pass --apply to write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
