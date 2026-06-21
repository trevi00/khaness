#!/usr/bin/env python3
"""Add `expects_paths` capability declaration to agents/kha-*.md frontmatter.

Round 5 W4 P1: 22/24 kha-* agents reference `.planning/*` and/or
`$HOME/.claude/get-shit-done/*` paths in their prompt body. These are
INTENTIONAL workflow contracts (kha command runtime guarantees these dirs
exist), not bugs. But the dependency is invisible to anyone reading the
frontmatter.

This CLI scans each agent body for path conventions and writes them as a
declared `expects_paths:` list in frontmatter, making the contract explicit.

Idempotent. Default mode is dry-run; pass `--apply` to write. `--check`
exits 1 if any agent's declared list differs from the body scan.

## Detected paths

- `.planning/`  → GSD/kha workflow context
- `$HOME/.claude/get-shit-done/`  → legacy CLI tool registry
- `.planning/<phase>/`  → per-phase scratch (rolled up to `.planning/`)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AGENTS_DIR = REPO_ROOT / "agents"

# Path detection patterns — matched against agent BODY (after frontmatter).
PATH_DETECTORS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\.planning/"), ".planning/"),
    (re.compile(r"\$HOME/\.claude/get-shit-done/|\$\{HOME\}/\.claude/get-shit-done/|~/\.claude/get-shit-done/"),
     "$HOME/.claude/get-shit-done/"),
]

_FRONTMATTER_RE = re.compile(r"^(---\n)(.*?)(\n---\n)", re.DOTALL)
_EXPECTS_LINE_RE = re.compile(
    r"^expects_paths:\s*(?:\[(.*?)\]|\n((?:\s*-\s*.+\n)+))",
    re.MULTILINE,
)


def detect_expected_paths(body: str) -> list[str]:
    """Scan agent body for known path conventions, return sorted unique list."""
    found: set[str] = set()
    for pattern, label in PATH_DETECTORS:
        if pattern.search(body):
            found.add(label)
    return sorted(found)


def _format_paths(paths: list[str]) -> str:
    """Format as YAML inline list."""
    if not paths:
        return "[]"
    quoted = [f'"{p}"' for p in paths]
    return "[" + ", ".join(quoted) + "]"


def _strip_existing_expects(fm: str) -> str:
    """Remove any existing `expects_paths:` line/block from frontmatter."""
    return _EXPECTS_LINE_RE.sub("", fm).rstrip("\n")


def normalize_agent(content: str) -> tuple[str, list[str], bool]:
    """Add/update expects_paths field. Returns (new_content, paths, changed)."""
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return content, [], False

    fm_open, fm_body, fm_close = m.group(1), m.group(2), m.group(3)
    body = content[m.end():]

    paths = detect_expected_paths(body)
    if not paths:
        # No paths detected — make sure we don't leave a stale expects_paths.
        cleaned_fm = _strip_existing_expects(fm_body)
        if cleaned_fm == fm_body:
            return content, [], False
        new_content = fm_open + cleaned_fm + "\n" + fm_close + body
        return new_content, [], True

    expected_line = f"expects_paths: {_format_paths(paths)}"

    existing = _EXPECTS_LINE_RE.search(fm_body)
    if existing:
        # Replace
        new_fm = _EXPECTS_LINE_RE.sub(expected_line, fm_body, count=1)
        if new_fm == fm_body:
            return content, paths, False
        return fm_open + new_fm + fm_close + body, paths, True

    # Insert before closing fence — anchor after `model:` line if present, else
    # after `tools:`, else append.
    insert_anchors = [r"^(model:.*)$", r"^(tools:.*)$", r"^(description:.*)$"]
    insert_after_match = None
    for pat in insert_anchors:
        m2 = re.search(pat, fm_body, re.MULTILINE)
        if m2:
            insert_after_match = m2
            break

    if insert_after_match:
        idx = insert_after_match.end()
        new_fm = fm_body[:idx] + "\n" + expected_line + fm_body[idx:]
    else:
        new_fm = fm_body.rstrip() + "\n" + expected_line

    return fm_open + new_fm + fm_close + body, paths, True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if any agent's expects_paths is stale")
    args = ap.parse_args(argv)

    if not AGENTS_DIR.is_dir():
        print(f"[ERR] {AGENTS_DIR} missing", file=sys.stderr)
        return 2

    issues: list[str] = []
    changed_count = 0
    total = 0

    for path in sorted(AGENTS_DIR.glob("kha-*.md")):
        total += 1
        content = path.read_text(encoding="utf-8")
        new_content, paths, changed = normalize_agent(content)

        if args.check:
            if changed:
                issues.append(f"{path.stem}: expects_paths stale ({paths})")
            continue

        if changed:
            verb = "rewrote" if args.apply else "would rewrite"
            print(f"  {path.stem}.md: {verb} expects_paths={paths}")
            changed_count += 1
            if args.apply:
                path.write_text(new_content, encoding="utf-8")

    if args.check:
        if issues:
            for i in issues:
                print(f"[FAIL] {i}")
            print(f"\n[FAIL] {len(issues)}/{total} agents need expects_paths normalization")
            return 1
        print(f"[PASS] all {total} kha-* agents have current expects_paths")
        return 0

    verb = "rewrote" if args.apply else "would rewrite"
    print(f"\n=== {verb} {changed_count}/{total} agents ===")
    if not args.apply and changed_count:
        print("(dry-run — pass --apply to write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
