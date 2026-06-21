"""Hook I/O helpers — read stdin JSON, write stdout JSON.

All hooks should use these instead of re-implementing json.load(sys.stdin).
Guarantees UTF-8 on Windows (Korean Windows defaults to cp949 otherwise).

Output schema per hook event (from Claude Code source inspection):

    UserPromptSubmit  → hookSpecificOutput wrapping
    PreToolUse        → hookSpecificOutput wrapping (+ optional top-level decision)
    PostToolUse       → hookSpecificOutput wrapping
    SessionStart      → hookSpecificOutput wrapping
    Stop              → top-level fields only (decision/reason/continue/stopReason)

`additional_context()` handles the first four. Stop uses `stop_decision()`.
"""
from __future__ import annotations

import json
import sys
from typing import Any, Literal


WrappedEvent = Literal[
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "SessionStart",
]


def _configure_utf8() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8")
            except Exception:
                pass


_configure_utf8()


def read_hook_input() -> dict[str, Any]:
    """Read a Claude Code hook JSON payload from stdin.

    Returns {} on empty or malformed input so hooks can fail silently.
    """
    try:
        raw = sys.stdin.read()
    except Exception:
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def write_hook_output(payload: dict[str, Any]) -> None:
    """Emit a hook response as a single JSON line on stdout.

    Empty payload is treated as no-op (Claude Code accepts silent exit).
    """
    if not payload:
        return
    print(json.dumps(payload, ensure_ascii=False))


def additional_context(text: str, hook_event_name: WrappedEvent) -> dict[str, Any]:
    """Build an additionalContext hook response wrapped in hookSpecificOutput.

    Valid for UserPromptSubmit, PreToolUse, PostToolUse, SessionStart.
    NOT for Stop — use stop_decision() instead.
    """
    return {
        "hookSpecificOutput": {
            "hookEventName": hook_event_name,
            "additionalContext": text,
        }
    }


def stop_decision(
    reason: str,
    *,
    block: bool = True,
    continue_: bool = True,
    stop_reason: str | None = None,
) -> dict[str, Any]:
    """Build a Stop hook response using top-level fields only.

    The Stop hook schema does NOT accept hookSpecificOutput — only top-level
    decision/reason/continue/stopReason. When block=True, the reason is
    surfaced to the model as a blockingError so it retries.
    """
    out: dict[str, Any] = {}
    if block:
        out["decision"] = "block"
        out["reason"] = reason
    if not continue_:
        out["continue"] = False
        if stop_reason:
            out["stopReason"] = stop_reason
    return out


def pre_tool_deny(reason: str) -> dict[str, Any]:
    """Build a PreToolUse deny response (both top-level and hookSpecificOutput).

    Claude Code honors either channel, but sending both is the convention
    used by the existing pre-tool-guard.py hook.
    """
    return {
        "decision": "block",
        "reason": reason,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
    }


def pre_tool_updated_input(
    updated_input: dict[str, Any],
    note: str,
) -> dict[str, Any]:
    """Build a PreToolUse response that mutates the tool input before execution."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": updated_input,
            "additionalContext": note,
        }
    }
