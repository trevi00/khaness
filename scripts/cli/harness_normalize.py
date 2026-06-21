#!/usr/bin/env python3
"""harness-* command normalizer — round-3 P0 mechanical step.

Analog of cli/kha_normalize.py for `commands/harness-*.md`. Applies the
template from `state/harness-commands-review-round3.md` to all 16 harness
commands:

1. Frontmatter extension — adds `category`, `mutates`, `long-running`,
   `external-deps` fields (idempotent — only writes when value missing or
   wrong).
2. Standard section headers — appends stub sections at end of body when
   missing: Output, Failure behavior, Gate summary, plus Retry / Resume
   for long-running commands and Boundary with other commands for all.

Categories used (broader than kha because harness sits at a different layer):
    design, run, remediate, review, report, debug, clarify, build, project,
    meta, external-ai

`external-deps` field is harness-specific — codex/claude/gemini/psmux CLI
dependencies need automatic preflight detection.

Usage:
    cd ~/.claude/scripts
    python -m cli.harness_normalize                 # dry-run
    python -m cli.harness_normalize --apply         # write
    python -m cli.harness_normalize --check         # exit 1 if drift
    python -m cli.harness_normalize --report-only   # classification table
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.paths import CLAUDE_HOME  # noqa: E402
from lib.frontmatter_norm import (  # noqa: E402
    ensure_field as _ensure_field,
    has_section as _has_section,
)

COMMANDS_DIR = CLAUDE_HOME / "commands"


# 16-command authoritative classification — round-3 worker-4 + cross-worker synthesis.
HARNESS_COMMANDS: dict[str, dict] = {
    "harness-debate":           {"category": "design",     "mutates": "yes", "long-running": "yes", "external-deps": "none"},
    "harness-autopilot":        {"category": "run",        "mutates": "yes", "long-running": "yes", "external-deps": "none"},
    "harness-ralph":            {"category": "remediate",  "mutates": "yes", "long-running": "yes", "external-deps": "none"},
    "harness-ultrawork":        {"category": "run",        "mutates": "yes", "long-running": "yes", "external-deps": "none"},
    "harness-audit":            {"category": "review",     "mutates": "no",  "long-running": "yes", "external-deps": "none"},
    "harness-optimize":         {"category": "review",     "mutates": "no",  "long-running": "no",  "external-deps": "none"},
    "harness-diagnose":         {"category": "debug",      "mutates": "no",  "long-running": "no",  "external-deps": "none"},
    "harness-extend":           {"category": "build",      "mutates": "yes", "long-running": "yes", "external-deps": "git"},
    "harness-team":             {"category": "external-ai","mutates": "yes", "long-running": "yes", "external-deps": "claude-cli, codex-cli, psmux"},
    "harness-ask":              {"category": "external-ai","mutates": "yes", "long-running": "no",  "external-deps": "claude-cli, codex-cli"},
    "harness-interview":        {"category": "clarify",    "mutates": "yes", "long-running": "yes", "external-deps": "none"},
    "harness-trigger-summary":  {"category": "report",     "mutates": "no",  "long-running": "no",  "external-deps": "python-cli"},
    "harness-pinit":            {"category": "project",    "mutates": "yes", "long-running": "no",  "external-deps": "python-cli"},
    "harness-reverse-prd":      {"category": "design",     "mutates": "yes", "long-running": "yes", "external-deps": "git, python-cli"},
    "harness-skill":            {"category": "meta",       "mutates": "yes", "long-running": "no",  "external-deps": "git"},
    "harness":                  {"category": "meta",       "mutates": "no",  "long-running": "no",  "external-deps": "none"},
}


# ---------------------------------------------------------------------------
# Frontmatter editing
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^(---\s*\n)(.*?)(\n---\s*\n)(.*)$", re.DOTALL)


def normalize_frontmatter(content: str, name: str) -> str:
    meta = HARNESS_COMMANDS[name]
    m = _FRONTMATTER_RE.match(content)
    if not m:
        body_lines = [
            "---",
            f"name: {name}",
            f"category: {meta['category']}",
            f"mutates: {meta['mutates']}",
            f"long-running: {meta['long-running']}",
            f"external-deps: {meta['external-deps']}",
            "---",
        ]
        return "\n".join(body_lines) + "\n" + content
    fm_open, fm_body, fm_close, body = m.group(1), m.group(2), m.group(3), m.group(4)
    for key in ("category", "mutates", "long-running", "external-deps"):
        fm_body = _ensure_field(fm_body, key, meta[key])
    return f"{fm_open}{fm_body}{fm_close}{body}"


# ---------------------------------------------------------------------------
# Section stubs
# ---------------------------------------------------------------------------

_OUTPUT_STUB = """\
## Output

<!-- TODO: list concrete artifacts and status indicators -->
- artifact: `<path>` — <description>
- status: `<terminal status — converged | aborted | hard_cap | partial | etc.>`
"""

_FAILURE_STUB = """\
## Failure behavior

<!-- TODO: per-failure recovery contracts -->
- preflight failure: <action — typically no writes, return blocking reason>
- execution failure: <action — preserve recovery handles, surface resume instruction>
- partial success: <action — what stays, what rolls back>
- external CLI missing: <action — install hint or graceful degradation>
"""

_GATE_STUB = """\
## Gate summary

<!-- TODO: fill in real preflight + success criteria -->
- preflight: <required state / inputs before execution>
- success criteria: <how completion is determined>
- abort triggers: <conditions that hard-stop the command>
"""

_RETRY_STUB = """\
## Retry / Resume

<!-- TODO: long-running command — define checkpoint + resume contract -->
- checkpoint: `<file or session-id path>`
- resume command: `<command-line>`
- idempotent: <yes/no — explain>
- stall detection: <heartbeat or progress-monotonic gate>
"""

_BOUNDARY_STUB = """\
## Boundary with other commands

<!-- TODO: clarify what THIS command does that adjacent ones don't -->
- vs `<adjacent command>`: <key difference in trigger / output / scope>
"""


def append_missing_sections(content: str, name: str) -> str:
    meta = HARNESS_COMMANDS[name]
    long_running = meta["long-running"] == "yes"
    additions: list[str] = []
    if not _has_section(content, "Output"):
        additions.append(_OUTPUT_STUB)
    if not _has_section(content, "Failure behavior"):
        additions.append(_FAILURE_STUB)
    if not _has_section(content, "Gate summary"):
        additions.append(_GATE_STUB)
    if long_running and not _has_section(content, "Retry / Resume"):
        additions.append(_RETRY_STUB)
    if not _has_section(content, "Boundary with other commands"):
        additions.append(_BOUNDARY_STUB)

    if not additions:
        return content
    return content.rstrip() + "\n\n" + "\n".join(additions).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def normalize_one(path: Path, name: str) -> tuple[bool, str]:
    original = path.read_text(encoding="utf-8")
    step1 = normalize_frontmatter(original, name)
    step2 = append_missing_sections(step1, name)
    return (step2 != original), step2


def collect_commands() -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for name in sorted(HARNESS_COMMANDS):
        p = COMMANDS_DIR / f"{name}.md"
        if p.is_file():
            out.append((name, p))
    return out


def check() -> tuple[bool, list[str]]:
    issues: list[str] = []
    for name, path in collect_commands():
        meta = HARNESS_COMMANDS[name]
        content = path.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(content)
        if not m:
            issues.append(f"{name}: no frontmatter")
            continue
        fm_body = m.group(2)
        for key, expected in meta.items():
            if not re.search(rf"^{re.escape(key)}\s*:\s*{re.escape(expected)}\s*$",
                              fm_body, re.MULTILINE):
                issues.append(f"{name}: frontmatter missing/wrong {key}={expected}")
        for sec in ("Output", "Failure behavior", "Gate summary",
                    "Boundary with other commands"):
            if not _has_section(content, sec):
                issues.append(f"{name}: missing section ## {sec}")
        if meta["long-running"] == "yes" and not _has_section(content, "Retry / Resume"):
            issues.append(f"{name}: long-running but missing ## Retry / Resume")
    return (not issues), issues


def report() -> str:
    L = []
    L.append(f"{'command':28} {'category':12} {'mut':4} {'lr':4} external-deps")
    L.append("-" * 80)
    for name, meta in sorted(HARNESS_COMMANDS.items()):
        L.append(f"{name:28} {meta['category']:12} "
                 f"{meta['mutates']:4} {meta['long-running']:4} {meta['external-deps']}")
    L.append("")
    L.append(f"Total: {len(HARNESS_COMMANDS)} commands")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Normalize harness-* commands")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args(argv)

    if args.report_only:
        print(report())
        return 0

    if args.check:
        ok, issues = check()
        if ok:
            print(f"[PASS] all {len(HARNESS_COMMANDS)} harness commands normalized")
            return 0
        print(f"[FAIL] {len(issues)} issue(s):")
        for i in issues:
            print(f"  - {i}")
        return 1

    cmds = collect_commands()
    if not cmds:
        print("[FAIL] no harness commands found", file=sys.stderr)
        return 1

    changed = unchanged = 0
    for name, path in cmds:
        is_changed, new_content = normalize_one(path, name)
        if is_changed:
            if args.apply:
                path.write_text(new_content, encoding="utf-8")
            changed += 1
        else:
            unchanged += 1
    print(f"[OK] {'applied' if args.apply else 'would apply'}: changed={changed}  unchanged={unchanged}  total={len(cmds)}")
    if not args.apply:
        print("(dry-run — pass --apply to write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
