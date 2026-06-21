#!/usr/bin/env python3
"""Normalize agents/kha-*.md frontmatter — adds `model:` per role-based mapping.

Round 5 W4 P1 finding: 22/24 agents missing `model:` frontmatter, leading to
implicit inheritance from parent context. Explicit model choice gives:
- consistent behavior (no surprise downgrades on /fast or rate-limit cooldown)
- cost predictability
- ability to override per agent in profile (kha-set-model-profile).

Mapping (24 kha-* agents):
- opus    (heavy reasoning, design, research, architecture, verification)
- sonnet  (writers, checkers, mappers, fixers, executors, auditors)
- haiku   (lightweight: indexers, simple updates)

Idempotent. `--check` mode verifies all agents have a `model:` field, exits 1 if any miss.
Default mode is dry-run; pass `--apply` to write.
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

# Role-based model assignment for kha-* agents (24 total)
MODEL_MAP: dict[str, str] = {
    # Heavy reasoning / research / planning / verification
    "kha-advisor-researcher":   "opus",
    "kha-assumptions-analyzer": "opus",
    "kha-debugger":             "opus",
    "kha-phase-researcher":     "opus",
    "kha-planner":              "opus",
    "kha-project-researcher":   "opus",
    "kha-research-synthesizer": "opus",
    "kha-roadmapper":           "opus",
    "kha-security-auditor":     "opus",
    "kha-ui-researcher":        "opus",
    "kha-verifier":             "opus",
    # General-purpose: writers, checkers, mappers, fixers, executors
    "kha-codebase-mapper":      "sonnet",
    "kha-code-fixer":           "sonnet",
    "kha-code-reviewer":        "sonnet",
    "kha-doc-verifier":         "sonnet",
    "kha-doc-writer":           "sonnet",
    "kha-executor":             "sonnet",
    "kha-integration-checker":  "sonnet",
    "kha-nyquist-auditor":      "sonnet",
    "kha-plan-checker":         "sonnet",
    "kha-ui-auditor":           "sonnet",
    "kha-ui-checker":           "sonnet",
    "kha-user-profiler":        "sonnet",
    # Lightweight: indexers, simple updates
    "kha-intel-updater":        "haiku",
}

VALID_MODELS = {"opus", "sonnet", "haiku", "inherit"}

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_MODEL_LINE_RE = re.compile(r"^model:\s*(.*)$", re.MULTILINE)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def normalize_agent(name: str, content: str) -> tuple[str, bool]:
    """Return (new_content, changed)."""
    desired = MODEL_MAP.get(name)
    if desired is None:
        return content, False  # not a kha-* we manage

    m = _FRONTMATTER_RE.match(content)
    if not m:
        return content, False  # no frontmatter — caller handles
    fm_body = m.group(1)
    fm_full = m.group(0)

    existing = _MODEL_LINE_RE.search(fm_body)
    if existing:
        current = existing.group(1).strip()
        if current == desired:
            return content, False  # already correct
        new_fm_body = _MODEL_LINE_RE.sub(f"model: {desired}", fm_body, count=1)
    else:
        # Insert after `tools:` line if present, else after `description:`,
        # else just append before closing.
        anchor_match = re.search(r"^(tools:.*)$", fm_body, re.MULTILINE)
        if anchor_match is None:
            anchor_match = re.search(r"^(description:.*)$", fm_body, re.MULTILINE)
        if anchor_match:
            insert_after = anchor_match.end()
            new_fm_body = (
                fm_body[:insert_after] + f"\nmodel: {desired}" + fm_body[insert_after:]
            )
        else:
            new_fm_body = fm_body.rstrip() + f"\nmodel: {desired}"

    new_fm = "---\n" + new_fm_body + "\n---\n"
    return new_fm + content[m.end():], True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually write (default: dry-run)")
    ap.add_argument("--check", action="store_true",
                    help="verify all kha-* agents have model field; exit 1 if any miss")
    args = ap.parse_args(argv)

    if not AGENTS_DIR.is_dir():
        print(f"[ERR] {AGENTS_DIR} missing", file=sys.stderr)
        return 2

    issues: list[str] = []
    changed_count = 0

    for name, desired in sorted(MODEL_MAP.items()):
        path = AGENTS_DIR / f"{name}.md"
        if not path.is_file():
            issues.append(f"{name}: file missing")
            continue
        content = _read(path)
        new_content, changed = normalize_agent(name, content)
        if args.check:
            m = _FRONTMATTER_RE.match(content)
            if not m:
                issues.append(f"{name}: no frontmatter")
                continue
            mline = _MODEL_LINE_RE.search(m.group(1))
            if not mline:
                issues.append(f"{name}: missing model field (expected {desired})")
            else:
                current = mline.group(1).strip()
                if current not in VALID_MODELS:
                    issues.append(f"{name}: invalid model {current!r}")
                elif current != desired:
                    issues.append(f"{name}: model {current!r} differs from expected {desired!r}")
            continue
        if changed:
            verb = "rewrote" if args.apply else "would rewrite"
            print(f"  {name}.md: {verb} (model: {desired})")
            changed_count += 1
            if args.apply:
                _write(path, new_content)

    if args.check:
        if issues:
            for i in issues:
                print(f"[FAIL] {i}")
            print(f"\n[FAIL] {len(issues)} agent(s) need normalization")
            return 1
        print(f"[PASS] all {len(MODEL_MAP)} kha-* agents have valid model field")
        return 0

    verb = "rewrote" if args.apply else "would rewrite"
    print(f"\n=== {verb} {changed_count}/{len(MODEL_MAP)} agents ===")
    if not args.apply and changed_count:
        print("(dry-run — pass --apply to write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
