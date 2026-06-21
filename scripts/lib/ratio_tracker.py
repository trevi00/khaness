"""Read:Edit ratio tracker — shared by context-loader (reset per turn) and
post-tool-reviewer (count + warn).

Counter file is a tiny JSON in the OS temp dir. Reset on every user turn
so the warning reflects the CURRENT request, not cumulative session history.
"""
from __future__ import annotations

import os
import time

from .atomic_json import read_json, write_json_atomic


_TEMP = os.environ.get("TEMP", os.environ.get("TMPDIR", "/tmp"))
_RATIO_FILE = os.path.join(_TEMP, ".claude_tool_ratio")
_RATIO_COOLDOWN_FILE = os.path.join(_TEMP, ".claude_ratio_warn_cooldown")

RESEARCH_TOOLS: frozenset[str] = frozenset({"Read", "Grep", "Glob"})
MODIFY_TOOLS: frozenset[str] = frozenset({"Edit", "Write", "MultiEdit"})

WARN_THRESHOLD: float = 3.0
MIN_EDITS: int = 3
RESET_HOURS: int = 4
COOLDOWN_SECONDS: int = 300  # 5 min between surfaced warnings


def load_counts() -> dict[str, int]:
    try:
        if os.path.exists(_RATIO_FILE):
            if time.time() - os.path.getmtime(_RATIO_FILE) > RESET_HOURS * 3600:
                return {"research": 0, "modify": 0}
    except OSError:
        return {"research": 0, "modify": 0}

    data = read_json(_RATIO_FILE, default={})
    return {
        "research": int(data.get("research", 0)),
        "modify": int(data.get("modify", 0)),
    }


def save_counts(data: dict[str, int]) -> None:
    """Atomic write via lib/atomic_json (W24 + W?). Concurrent hooks fire on
    the same turn (UserPromptSubmit + PostToolUse), so non-atomic open("w")
    can show a half-written JSON to the next reader.
    """
    write_json_atomic(_RATIO_FILE, data)


def reset_counts() -> None:
    """Called at the start of every user turn by the UserPromptSubmit hook."""
    save_counts({"research": 0, "modify": 0})
    try:
        if os.path.exists(_RATIO_COOLDOWN_FILE):
            os.remove(_RATIO_COOLDOWN_FILE)
    except Exception:
        pass


def record_tool_use(tool_name: str) -> dict[str, int]:
    """Increment the appropriate counter and return the new snapshot."""
    data = load_counts()
    if tool_name in RESEARCH_TOOLS:
        data["research"] += 1
        save_counts(data)
    elif tool_name in MODIFY_TOOLS:
        data["modify"] += 1
        save_counts(data)
    return data


def check_ratio_warning(data: dict[str, int]) -> float | None:
    """Return the current ratio if it should be surfaced as a warning; else None."""
    if data["modify"] < MIN_EDITS:
        return None
    ratio = data["research"] / data["modify"]
    return ratio if ratio < WARN_THRESHOLD else None
