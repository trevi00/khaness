#!/usr/bin/env python3
"""PreToolUse hook — v15.10 D4 critic policy advisor.

For every `Agent` tool spawn this hook:
  1. Resolves the per-agent critic decision via lib.critic_policy.resolve.
  2. Surfaces the decision through:
       - additionalContext (PreToolUse hookSpecificOutput) so the agent
         author / orchestrator sees the result in-band
       - telemetry category 'critic-policy-decision' for long-term audit
       - env var ORCH_CRITIC_DECISION (best-effort; consumed by the
         post_tool agent_outcome_audit.py to write critic_invoked into
         the operator ledger)
  3. NEVER blocks the dispatch — D4 is advisory at the runtime layer.
     The actual Critic invocation is the orchestrator's responsibility
     (today there is no automatic critic-of-agent process; the policy
     is read by ledger code so the audit trail records the decision).

Fail-soft contract:
  - On any exception the hook exits 0 with empty stdout — the parent
    Agent dispatch proceeds normally. Failure is surfaced via telemetry
    category 'critic-policy-advisor-failed'.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _log_failure(stage: str, exc: Exception) -> None:
    try:
        from lib.logging import log_telemetry
        log_telemetry(
            "critic-policy-advisor-failed",
            {
                "stage": stage,
                "error_type": type(exc).__name__,
                "error_repr": repr(exc)[:200],
            },
        )
    except Exception:
        pass


def main() -> None:
    try:
        raw = sys.stdin.read()
    except Exception as exc:
        _log_failure("stdin_read", exc)
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

    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return
    subagent_type = tool_input.get("subagent_type", "") or ""
    if not subagent_type:
        return

    try:
        from lib.critic_policy import resolve as resolve_policy
        decision = resolve_policy(subagent_type)
    except Exception as exc:
        _log_failure("policy_resolve", exc)
        return

    # Persist decision for the matching post_tool hook (best-effort)
    os.environ["ORCH_CRITIC_DECISION"] = str(decision)

    # Telemetry — long-term audit of every dispatch + policy outcome
    try:
        from lib.logging import log_telemetry
        log_telemetry(
            "critic-policy-decision",
            {
                "agent_type": subagent_type,
                "decision": decision,
                "session_id": payload.get("session_id", ""),
            },
        )
    except Exception as exc:
        _log_failure("telemetry", exc)

    # In-band advisory (PreToolUse additionalContext — surfaces to LLM)
    advisory = (
        f"[critic-policy] {subagent_type} -> {decision} "
        f"(v15.10 D4; flip via configure-critic-policy token)"
    )
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": advisory,
        }
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
