#!/usr/bin/env python3
"""PreToolUse hook — Agent recursion depth cap (v15.20 B / v15.9 P0 #2).

매 Agent tool dispatch 전에 ORCH_DEPTH 검사. next_depth > MAX_AGENT_DEPTH(=3)
이면 deny 반환. root caller (depth=0)부터 시작하여 3 단계까지 spawn 허용.

Block 패턴 (PreToolUse hookSpecificOutput):
  {"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "agent recursion depth cap (3) exceeded — ..."
  }}

Non-Agent tool은 silent no-op. fail-soft: 어떤 예외든 exit 0 + 본 hook이 dispatch
차단하지 않도록 함 (운영자가 hook 자체를 disable하지 않는 한, 본 hook이 broken
이면 차라리 통과 — recursion cap이 hard requirement는 아니고 advisory hard cap).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def main() -> None:
    try:
        raw = sys.stdin.read()
    except Exception:
        return
    if not raw.strip():
        return
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict):
        return
    if payload.get("tool_name") != "Agent":
        return

    try:
        from lib.agent_depth import MAX_AGENT_DEPTH, current_depth, would_exceed_cap
    except Exception:
        return  # fail-soft — depth cap absent rather than blocking

    if not would_exceed_cap():
        return  # within cap → silent pass

    depth = current_depth()
    reason = (
        f"agent recursion depth cap ({MAX_AGENT_DEPTH}) would be exceeded — "
        f"current ORCH_DEPTH={depth}, next would be {depth + 1}. "
        f"Spawn blocked to prevent Anthropic 15x token multiplier + Cognition "
        f"telephone-game loss. Run agent inline or reduce nesting."
    )
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False))

    # Telemetry
    try:
        from lib.logging import log_telemetry
        log_telemetry(
            "agent-depth-cap-blocked",
            {
                "depth_current": depth,
                "depth_attempted": depth + 1,
                "max_depth": MAX_AGENT_DEPTH,
                "subagent_type": payload.get("tool_input", {}).get("subagent_type", ""),
            },
        )
    except Exception:
        pass


if __name__ == "__main__":
    main()
