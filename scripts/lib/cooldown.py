"""Cooldown helpers — debounce hook outputs by time.

Used by post-tool-reviewer and other hooks to avoid spamming the same
additionalContext on every tool call. A cooldown is represented by a
tiny touch-file in the OS temp dir; mtime is the last-fire timestamp.
"""
from __future__ import annotations

import os
import time


TEMP_DIR: str = os.environ.get("TEMP", os.environ.get("TMPDIR", "/tmp"))


def cooldown_path(name: str) -> str:
    """Path to the cooldown marker file for a named category."""
    safe = name.replace(".", "_").replace("-", "_").replace("/", "_").replace("\\", "_")
    return os.path.join(TEMP_DIR, f".claude_cd_{safe}")


def check_cooldown(cooldown_file: str, cooldown_seconds: float) -> bool:
    """Return True if the cooldown expired; touches the file as a side effect.

    Any IO error defaults to True so a broken temp dir never blocks hooks.
    """
    try:
        if os.path.exists(cooldown_file):
            mtime = os.path.getmtime(cooldown_file)
            if time.time() - mtime < cooldown_seconds:
                return False
        with open(cooldown_file, "w") as f:
            f.write(str(time.time()))
        return True
    except Exception:
        return True


def clear_cooldown(cooldown_file: str) -> None:
    try:
        if os.path.exists(cooldown_file):
            os.remove(cooldown_file)
    except Exception:
        pass
