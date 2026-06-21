#!/usr/bin/env python3
"""response_guard.py - Stop hook

Analyzes the assistant's last_assistant_message at turn end for quality issues.
Unlike PostToolUse hooks (which only see code edits), this hook sees the full
conversational response — catching lazy text patterns, premature stops, and
evasive language.

Stop hook input schema:
{
  "hook_event_name": "Stop",
  "stop_hook_active": bool,
  "last_assistant_message": str | null,
  "session_id": str,
  "transcript_path": str,
  "cwd": str,
  "agent_id": str | null
}

Output (top-level fields only — Stop has no hookSpecificOutput in schema):
  Block:  {"decision": "block", "reason": "..."} — creates blockingError → model retries
  Warn:   {"decision": "block", "reason": "..."} — same mechanism, softer language
  Halt:   {"continue": false, "stopReason": "..."} — prevents continuation entirely

NOTE: systemMessage is NOT consumed by stopHooks.ts (only result.message and
result.blockingError are checked). So ALL feedback must go through decision:"block".
"""

import sys
import json
import os
import re  # noqa: F401 — kept for backward compat (some downstream imports)
import time
from pathlib import Path

# Fix Windows encoding
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

# Refactor (debate-1778224899-c24de4 D3''): pure analyzer extracted into
# response_guard_core so handlers/stop/autopilot_continue.py can import it
# without the CLI module-level side effects (this very `sys.stdin/stdout
# .reconfigure` block + COOLDOWN_FILE env-read below).
_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from handlers.stop.response_guard_core import (  # noqa: E402
    MIN_MESSAGE_LENGTH,
    RESPONSE_PATTERNS,
    analyze_response,
    format_finding_lines,
    strip_quoted_content,
)

# Re-export for any external callers that import these from this module path.
__all__ = [
    "MIN_MESSAGE_LENGTH",
    "RESPONSE_PATTERNS",
    "analyze_response",
    "format_finding_lines",
    "strip_quoted_content",
]


COOLDOWN_FILE = os.path.join(
    os.environ.get("TEMP", os.environ.get("TMPDIR", "/tmp")),
    ".claude_stop_response_cooldown",
)
COOLDOWN_SECONDS = 90  # Longer cooldown than PostToolUse — this is turn-level

# Context Budget Tiers (GSD 흡수)
# PEAK (0-30%): 전체 운용, 본문 읽기, 다중 에이전트
# GOOD (30-50%): 정상, frontmatter 선호
# DEGRADING (50-70%): 절약, 최소 인라인
# POOR (70%+): 비상, 즉시 체크포인트
CONTEXT_BUDGET_WARNING = "컨텍스트가 많이 차있습니다. 핸드오프를 작성하고 새 대화에서 이어가세요."

# Patterns + analyzer moved to response_guard_core (debate D3''). This module
# now keeps only the CLI shell: cooldown, main entry, and the I/O wrapping.
# RESPONSE_PATTERNS / MIN_MESSAGE_LENGTH / strip_quoted_content /
# analyze_response are re-exported via the import above for backward compat.


def check_cooldown():
    """Check if enough time has passed since last warning."""
    try:
        if os.path.exists(COOLDOWN_FILE):
            mtime = os.path.getmtime(COOLDOWN_FILE)
            if time.time() - mtime < COOLDOWN_SECONDS:
                return False
        with open(COOLDOWN_FILE, "w") as f:
            f.write(str(time.time()))
        return True
    except Exception:
        return True


def main():
    try:
        input_data = json.load(sys.stdin)

        # Skip subagent stops (separate hook event)
        hook_event = input_data.get("hook_event_name", "")
        if hook_event not in ("Stop", ""):
            sys.exit(0)

        # Skip if already in a stop hook (prevent recursion)
        if input_data.get("stop_hook_active", False):
            sys.exit(0)

        # Skip subagent hooks
        if input_data.get("agent_id"):
            sys.exit(0)

        message = input_data.get("last_assistant_message")
        if not message:
            sys.exit(0)

        # Defer to autopilot_continue.py when an active autopilot session exists
        # for this cwd. This is the D3'' single-hook-merge invariant: only ONE
        # Stop hook emits decision=block per Stop event. autopilot_continue
        # runs analyze_response() itself via response_guard_core, so findings
        # are NOT lost — they are bundled into the autopilot reason text.
        try:
            from lib.autopilot_state import list_active_sids
            if list_active_sids(cwd_filter=input_data.get("cwd", "")):
                sys.exit(0)
        except Exception:
            pass  # fail-open: if state lookup fails, fall through to normal flow

        findings, has_blocking = analyze_response(message)

        if not findings:
            sys.exit(0)

        if not check_cooldown():
            sys.exit(0)

        finding_lines = []
        for category, msg, severity in findings[:5]:
            icon = "🚫" if severity == "block" else "⚠️"
            finding_lines.append(f"  {icon} [{category}] {msg}")

        finding_text = "\n".join(finding_lines)

        if has_blocking:
            # Block: force the model to retry via top-level decision field
            # blockingError → createUserMessage → injected into query loop → model retries
            output = {
                "decision": "block",
                "reason": (
                    "[응답 품질 차단] 다음 문제로 응답이 차단되었습니다:\n"
                    f"{finding_text}\n"
                    "→ 작업을 완료하고 다시 응답하세요."
                ),
            }
        else:
            # Warn: also use decision:"block" because Stop hooks silently drop
            # systemMessage (stopHooks.ts only checks result.message and
            # result.blockingError, NOT result.systemMessage).
            # blockingError gets injected as a user message the model sees.
            output = {
                "decision": "block",
                "reason": (
                    "[응답 품질 경고] 다음 패턴이 감지되었습니다:\n"
                    f"{finding_text}\n"
                    "→ 다음 응답에서 이 패턴을 피하세요. (경고이므로 기존 작업은 유지됩니다)"
                ),
            }

        print(json.dumps(output, ensure_ascii=False))

    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
