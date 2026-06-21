#!/usr/bin/env python3
"""project_branch_guard.py — PreToolUse hook (generalized from example_app_branch_guard).

Project-specific branch allowlist for Write/Edit/MultiEdit. Reads guard rules
from `~/.claude/state/branch-guard-config.json`:

```json
{
  "guards": [
    {"path": "C:/path/to/project", "allowed_branch": "feature/X", "tool_filter": ["Write","Edit","MultiEdit"]}
  ]
}
```

When user attempts a Write/Edit on a path matching `path` (prefix match) and the
git branch in that path is NOT `allowed_branch`, deny with structured PreToolUse
hook output. Otherwise no-op (sys.exit 0).

Config file missing → no-op (clean install). Multiple guards supported (one per
project). Each guard runs `git -C <path> branch --show-current` with 3s timeout.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

CONFIG_PATH = Path.home() / ".claude" / "state" / "branch-guard-config.json"


def _load_config() -> list[dict]:
    if not CONFIG_PATH.is_file():
        return []
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return data.get("guards", []) or []
    except Exception:
        return []


def _normalize(path: str) -> str:
    return (path or "").replace("\\", "/").lower()


def _path_matches(file_path: str, guard_path: str) -> bool:
    return _normalize(file_path).startswith(_normalize(guard_path))


def _current_branch(repo_path: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "branch", "--show-current"],
            capture_output=True, text=True, timeout=3,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _emit_deny(reason: str) -> None:
    output = {
        "decision": "block",
        "reason": reason,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
    }
    print(json.dumps(output, ensure_ascii=False))


def main() -> None:
    try:
        input_data = json.load(sys.stdin)
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})
        file_path = tool_input.get("file_path", "")

        if not file_path:
            sys.exit(0)

        guards = _load_config()
        if not guards:
            sys.exit(0)

        for g in guards:
            guard_path = g.get("path", "")
            allowed = g.get("allowed_branch", "")
            tools = g.get("tool_filter") or ["Write", "Edit", "MultiEdit"]

            if not guard_path or not allowed:
                continue
            if tool_name not in tools:
                continue
            if not _path_matches(file_path, guard_path):
                continue

            branch = _current_branch(guard_path)
            if branch == allowed:
                sys.exit(0)

            _emit_deny(
                f"[project-branch-guard] {guard_path} 폴더는 "
                f"'{allowed}' 브랜치에서만 수정 가능합니다. "
                f"현재 브랜치: '{branch or '(detached/unknown)'}'. "
                f"브랜치 전환 후 다시 시도하세요."
            )
            return

    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
