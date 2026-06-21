#!/usr/bin/env python3
"""handoff_drift_gate.py — PreToolUse hook (W21+ autonomous closure 5th surface).

Fires on Bash tool calls where the command is `git commit` (or variants).
Checks the cwd's HANDOFF.md anchored phase-tree block against the yaml-rendered
tree. On drift, emits a NON-BLOCKING advisory via additionalContext.

Why pre-commit and not just rely on the 4 existing surfaces (PostToolUse Edit,
SessionStart, harness_health, validators registry):
  - PostToolUse fires when HANDOFF is being edited; user may dismiss it.
  - SessionStart catches drift carried into a new session.
  - harness_health runs only when invoked manually.
  - validators registry runs only on regression command.
  None catch the "user committed the drift" moment specifically. This gate
  is the last chance to surface drift before it goes upstream.

NON-BLOCKING by design: blocking commits would frustrate the development loop
when drift is transient (mid-edit). The advisory fires; user decides.

Input schema (PreToolUse):
  {tool_name: "Bash", tool_input: {command: "..."}, cwd: "...", ...}

Output (drift detected):
  {hookSpecificOutput: {hookEventName: "PreToolUse",
                        additionalContext: "<phase-tree-drift>...</phase-tree-drift>"}}

Output (no drift / non-git-commit / no HANDOFF / parse error): exit 0 silent.

Fail-open per CLAUDE.md hook discipline: any exception returns silent exit 0.
The gate must NEVER block a commit due to its own bug.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


# Match `git commit`, `git -C <path> commit`, etc. Excludes `git commit-tree`
# (plumbing, not user-level commit) and `git committers` (alias variations).
_GIT_COMMIT_RE = re.compile(
    r"\bgit\b(?:\s+-[A-Za-z]\s+\S+)*\s+commit(?:\s|$)(?!-tree\b)",
)


def is_git_commit_command(command: str) -> bool:
    """True if the Bash command invokes `git commit` (excluding plumbing).

    Matches:
      git commit
      git commit -m "msg"
      git -C /path commit -m "msg"
      git -c user.name=x commit ...
    Excludes:
      git commit-tree ...    (low-level plumbing)
      git config commit.X    (config, not commit)
    """
    if not isinstance(command, str):
        return False
    return bool(_GIT_COMMIT_RE.search(command))


def _emit_advisory(advisory: str) -> None:
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": advisory,
        }
    }
    print(json.dumps(output, ensure_ascii=False))


def main() -> None:
    try:
        input_data = json.load(sys.stdin)
        tool_name = input_data.get("tool_name", "")
        if tool_name != "Bash":
            sys.exit(0)

        command = input_data.get("tool_input", {}).get("command", "")
        if not is_git_commit_command(command):
            sys.exit(0)

        cwd = input_data.get("cwd", "")
        if not cwd:
            sys.exit(0)

        handoff_path = Path(cwd) / "HANDOFF.md"
        if not handoff_path.is_file():
            sys.exit(0)

        try:
            from lib.handoff_drift import emit_drift_advisory
            advisory = emit_drift_advisory(handoff_path)
        except Exception:
            sys.exit(0)

        if not advisory:
            sys.exit(0)

        # Surface but don't block. Replace the <phase-tree-drift> tag wrapper
        # with a commit-specific framing so the operator immediately sees the
        # connection to the upcoming commit.
        commit_advisory = (
            "<phase-tree-drift-precommit>\n"
            "[HANDOFF.md drift detected at commit time]\n"
            "  yaml block과 anchored phase-tree block 불일치 — "
            "이대로 commit하면 drift가 origin에 push됩니다.\n"
            "  fix: `python -m cli.handoff_render <handoff> --in-place` 실행 후 commit\n"
            "  bypass: 의도적이라면 그대로 commit (advisory only, NOT blocking)\n"
            "</phase-tree-drift-precommit>"
        )
        _emit_advisory(commit_advisory)

    except Exception:
        # Hook discipline: never block on internal error
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
