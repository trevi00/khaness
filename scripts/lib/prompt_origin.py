#!/usr/bin/env python3
"""Shared prompt-origin classification for UserPromptSubmit handlers.

System re-invocations (background-task completions and other harness-injected
turns) arrive on the UserPromptSubmit channel but are NOT user intent. Handlers
that interpret prompt CONTENT must skip these to avoid telemetry / advisory
false positives. Concretely the three consumers are:

  - debate_trigger : a <task-notification> whose summary contains 설계/리팩토링
                     must not be counted as strict-design intent nor fire the
                     /harness-debate advisory.
  - mode_detector  : a notification mentioning 'ultrathink'/'ouroboros'/... must
                     not surface a /harness-* mode suggestion.
  - skill_match    : a notification's structural noise (e.g. the 'pat::' / 'pat:in'
                     substrings in a tool-routing summary) must not score-match a
                     skill like advanced-type-patterns and inject its body.

This is a CALLER-SIDE guard only: the content matchers themselves
(is_strict_design_intent, detect_phase, score_skill) are left untouched so the
debate fast-path and other consumers keep their semantics.

Single source of truth: SYSTEM_REINVOCATION_PREFIXES. Extracted from
handlers/prompt/debate_trigger.py (2026-06-02, commit 2ebaa35) and generalized
to mode_detector + skill_match (self-verifying-harness STEP 3, 2026-06-04).
Adding a marker here propagates to all three handlers at once — keep the set
NARROW: a false gate silently drops a real user prompt, which is worse than the
FP it prevents.
"""
from __future__ import annotations

# Harness-injected re-invocation markers. A prompt whose first non-whitespace
# content begins with one of these is a system turn, not user intent. Matched as
# a LEADING prefix (after lstrip) so a mid-text mention inside a genuine user
# prompt is NOT misclassified as system-origin.
SYSTEM_REINVOCATION_PREFIXES: tuple[str, ...] = ("<task-notification>",)


def is_system_reinvocation(prompt: str) -> bool:
    """True if `prompt` is a harness-injected re-invocation, not user intent.

    Only fires when a marker is the leading token (whitespace-tolerant). Empty
    or whitespace-only prompts are not system-origin.
    """
    # isinstance guard: a non-string prompt (malformed/hostile hook payload) must
    # return cleanly, not raise AttributeError on .lstrip() and crash the hook to
    # exit 1 (deep-audit pass-2 rank 3 — fail-soft for all callers of this helper).
    if not isinstance(prompt, str) or not prompt:
        return False
    return prompt.lstrip().startswith(SYSTEM_REINVOCATION_PREFIXES)
