"""Path helpers for Claude Code harness scripts.

Resolves CLAUDE_HOME from env var or falls back to ~/.claude.
All harness scripts should import from here instead of hardcoding paths.
"""
from __future__ import annotations

import os
from pathlib import Path


def _resolve_claude_home() -> Path:
    env = os.environ.get("CLAUDE_HOME")
    if env:
        return Path(env)
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        return Path(user_profile) / ".claude"
    return Path.home() / ".claude"


CLAUDE_HOME: Path = _resolve_claude_home()
SCRIPTS_DIR: Path = CLAUDE_HOME / "scripts"
SKILLS_DIR: Path = CLAUDE_HOME / "skills"
AGENTS_DIR: Path = CLAUDE_HOME / "agents"
COMMANDS_DIR: Path = CLAUDE_HOME / "commands"
TELEMETRY_DIR: Path = CLAUDE_HOME / "telemetry"
STATE_DIR: Path = CLAUDE_HOME / "state"
ATLAS_DIR: Path = CLAUDE_HOME / "atlas"

# Subtrees under SCRIPTS_DIR — created in P1~P4 of the refactor.
HOOKS_DIR: Path = SCRIPTS_DIR / "hooks"
HANDLERS_DIR: Path = SCRIPTS_DIR / "handlers"
VALIDATORS_DIR: Path = SCRIPTS_DIR / "validators"
LIB_DIR: Path = SCRIPTS_DIR / "lib"
ENGINE_DIR: Path = SCRIPTS_DIR / "engine"


# Telemetry retention — D4 (harness-perfection debate Gen3+Gen4 converged).
# log_telemetry() in lib/logging.py checks file size after append; if >= this
# threshold it rotates `<file>.jsonl` → `<file>.jsonl.1`. Windows lock failures
# fall through via log_stderr (rotation is best-effort, never breaks append).
TELEMETRY_ROTATE_BYTES: int = 1_048_576  # 1 MiB


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
