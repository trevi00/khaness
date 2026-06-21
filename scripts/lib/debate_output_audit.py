"""debate_output_audit — scan debate subagent output for isolation leaks.

Defense-in-depth for the residual surfaced at HANDOFF (subagent isolation =
claude-code platform-level convention-enforced): even if the platform
correctly isolates a subagent's INPUT (no parent context bleed-through),
the platform contract makes no guarantee that subagent OUTPUT will not
mention forbidden paths if the subagent happens to know them from training
or prior turns.

This module reuses the same ``LEAK_PATTERN_REGEX`` that
``lib.evaluator_dispatcher`` applies pre-spawn to evaluator prompts —
running it post-parse on Critic/Architect output catches:

  - direct path mentions (state/debates/, state/orchestrator/, etc.)
  - sid leakage (sid=debate-..., sid=orch-..., sid=interview-...)
  - transcript / history phrases (prior generation, conversation history, ...)
  - role-override / persona injection attempts in the response
  - Korean equivalents

Caller (commands/harness-debate.md after parse_critique / parse_verdict)
treats a non-empty match list as evidence of platform isolation degradation
and appends an ``isolation_leak_observed`` event with the matched tokens.
This is OBSERVABILITY only — no auto-respawn.
"""
from __future__ import annotations

from lib.evaluator_dispatcher import LEAK_PATTERN_REGEX


def scan_for_isolation_leaks(text: str) -> list[str]:
    """Return distinct match tokens (capture group 1) found in ``text``.

    Empty list = no leak detected. Order: first occurrence wins;
    duplicates collapsed (case-preserving on first hit).
    """
    if not isinstance(text, str) or not text:
        return []
    seen: dict[str, None] = {}  # ordered set
    for m in LEAK_PATTERN_REGEX.finditer(text):
        token = (m.group(1) if m.lastindex else m.group(0)).strip()
        if token and token.lower() not in {k.lower() for k in seen}:
            seen[token] = None
    return list(seen.keys())


def render_leak_advisory(actor: str, leaks: list[str]) -> str:
    """One-line advisory text for orchestrator log/event payload."""
    if not leaks:
        return ""
    if not isinstance(actor, str) or not actor:
        actor = "<unknown>"
    return (
        f"[isolation-leak-observed] actor={actor} "
        f"leaked_tokens={leaks} — platform isolation may have degraded; "
        "verdict reliability reduced."
    )
