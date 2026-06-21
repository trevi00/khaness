#!/usr/bin/env python3
"""subagent_refs validator — every `subagent_type=<name>` must resolve to agents/<name>.md.

## Purpose
After the gsd→kha migration, references to subagents are scattered across
commands/, skills/, get-shit-done/workflows/, and various READMEs. A typo or
stale reference (e.g. `gsd-researcher` after rename to `kha-researcher`)
causes silent runtime failure when the slash command spawns the agent.

This validator:
1. Builds the canonical agent set from `agents/*.md` (ignoring `_*.md`).
2. Scans all `*.md` under repo root for `subagent_type=<name>` patterns.
3. Reports any name that does NOT have a corresponding `agents/<name>.md`.

## Caller contract
- main() -> None, no args
- reads os.getcwd() == project root
- prints `[PASS]` / `[FAIL]` / `[WARN]` lines to stdout
- never raises; failures via stdout

## Pattern
Matches both styles:
- `subagent_type=kha-executor`
- `subagent_type: "kha-executor"`
- `subagent_type="kha-executor"`

## Whitelist (excluded from scan)
- `.git/**`, `node_modules/**`, `__pycache__/**`
- `state/**` (analysis artifacts, can reference legacy names)
- `.omc/**`, `telemetry/**`
- Files containing prompt-engine docstrings that reference template
  placeholders (`subagent_type=<name>`, `subagent_type=...`) — these are
  recognized by the literal `<name>` / `...` token and skipped.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.logging import log_telemetry  # noqa: E402

_REF_RE = re.compile(
    r"""subagent_type\s*[=:]\s*["']?([a-z][\w-]+)["']?""",
    re.IGNORECASE,
)

_PLACEHOLDER_TOKENS = {"name", "agent", "agent-name", "your-agent"}

# Built-in subagents shipped by the Claude Code runtime (no agents/*.md file).
_BUILTIN_AGENTS = {
    "general-purpose",
    "explore",
    "plan",
    "statusline-setup",
    "claude-code-guide",
}

_EXCLUDE_DIRS = (
    ".git",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    "state",
    ".omc",
    "telemetry",
)


def _collect_agents(root: Path) -> set[str]:
    """Build canonical agent name set from agents/*.md (excluding underscore files)."""
    agents_dir = root / "agents"
    if not agents_dir.is_dir():
        return set()
    return {
        p.stem for p in agents_dir.glob("*.md")
        if not p.stem.startswith("_")
    }


def _should_skip(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    parts = rel.parts
    if not parts:
        return True
    return parts[0] in _EXCLUDE_DIRS


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Return [(lineno, name), ...] of subagent_type references."""
    refs: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return refs
    for i, line in enumerate(text.splitlines(), 1):
        for m in _REF_RE.finditer(line):
            name = m.group(1).lower()
            if name in _PLACEHOLDER_TOKENS:
                continue
            # Trailing hyphen indicates template placeholder (`kha-{agent}`)
            if name.endswith("-"):
                continue
            # Python subscript expression: `subagent_type=payload["subagent_type"]`
            # captures `payload` then `[` follows. Not a literal agent name.
            # Surfaced as false positive on commands/harness-autopilot.md:49
            # (wave 5 baseline).
            end_pos = m.end()
            if end_pos < len(line) and line[end_pos] == "[":
                continue
            refs.append((i, name))
    return refs


def main() -> None:
    root = Path(os.getcwd())
    agents = _collect_agents(root)
    if not agents:
        print("[PASS] agents/ 디렉토리 없음 (skip)")
        return

    md_files = sorted(root.glob("**/*.md"))
    md_files = [p for p in md_files if not _should_skip(p, root)]

    total_refs = 0
    dangling: list[tuple[Path, int, str]] = []

    for path in md_files:
        for lineno, name in _scan_file(path):
            total_refs += 1
            if name in _BUILTIN_AGENTS:
                continue
            if name not in agents:
                dangling.append((path, lineno, name))

    if not dangling:
        print(f"[PASS] subagent_refs: {total_refs}개 참조 모두 agents/*.md와 일치 ({len(agents)}개 agent)")
        return

    for path, lineno, name in dangling[:50]:
        try:
            rel = path.relative_to(root)
        except ValueError:
            rel = path
        print(f"[FAIL] {rel}:{lineno}: subagent_type={name!r} — agents/{name}.md 없음")
        try:
            log_telemetry("subagent-refs-dangling", {
                "path": str(rel), "lineno": lineno, "name": name,
            })
        except Exception:
            pass

    if len(dangling) > 50:
        print(f"[FAIL] ... and {len(dangling) - 50} more dangling references")

    print(f"[FAIL] subagent_refs: {len(dangling)}개 dangling 참조 ({total_refs}개 중)")


if __name__ == "__main__":
    main()
