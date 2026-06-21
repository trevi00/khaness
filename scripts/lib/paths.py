"""Path helpers for Claude Code harness scripts.

Two roots are resolved separately so the harness works both as a `~/.claude`
clone AND as an installed Claude Code plugin:

- CLAUDE_HOME (state root): per-user persistent state — STATE_DIR, TELEMETRY_DIR,
  ATLAS_DIR, memory. Always the user's home (env CLAUDE_HOME → USERPROFILE/.claude
  → ~/.claude), so a plugin keeps its runtime state in the user's home, not in the
  ephemeral plugin cache.
- _CODE_ROOT (code/resource root): the bundled scripts/skills/agents/commands. When
  running as a plugin, Claude Code exports CLAUDE_PLUGIN_ROOT (the install dir), so
  code resolves from there; otherwise it falls back to CLAUDE_HOME (clone mode).

When CLAUDE_PLUGIN_ROOT is unset (clone mode / tests) the two roots coincide, so
behaviour is identical to the pre-plugin layout.
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


def _resolve_code_root() -> Path:
    """Code/resource root: the plugin install dir when running as a plugin,
    else the harness home (clone mode)."""
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        return Path(plugin_root)
    return _resolve_claude_home()


CLAUDE_HOME: Path = _resolve_claude_home()    # state root (per-user, persistent)
_CODE_ROOT: Path = _resolve_code_root()       # code/resource root (plugin or clone)

SCRIPTS_DIR: Path = _CODE_ROOT / "scripts"
SKILLS_DIR: Path = _CODE_ROOT / "skills"
AGENTS_DIR: Path = _CODE_ROOT / "agents"
COMMANDS_DIR: Path = _CODE_ROOT / "commands"
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
