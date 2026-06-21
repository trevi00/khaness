"""Harness debate engine — Planner-Critic-Architect loop.

The engine is orchestrated by the /harness-debate slash command. This package
provides:

- prompts.py:     self-contained prompt builders for the 3 subagents
- debate.py:      event-store wrapper, fast-path detection, similarity logging
- cli.py:         post-hoc inspection (list / show / last-verdict)

The DETERMINISTIC convergence rule lives in lib.debate_convergence (consumed by
cli.debate_converge_check) — NOT in this package. A legacy engine.convergence
module was removed 2026-06-20: it was a divergent, zero-caller second
implementation whose hash (no separators, [:12] truncation) was incompatible
with lib.debate_convergence.snapshot_sha1, i.e. a latent loaded gun.

State lives in $CLAUDE_HOME/state/debates/<session_id>/events.jsonl,
mirroring the Ouroboros event-sourcing pattern (stateless resumption).
"""
from .debate import (
    is_fast_path_eligible,
    load_history_snapshots,
    log_similarity_backup,
    new_session_id,
    record_event,
)
from .prompts import architect_prompt, critic_prompt, planner_prompt

__all__ = [
    "architect_prompt",
    "critic_prompt",
    "is_fast_path_eligible",
    "load_history_snapshots",
    "log_similarity_backup",
    "new_session_id",
    "planner_prompt",
    "record_event",
]
