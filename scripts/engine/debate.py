"""Orchestrator helpers for the Planner-Critic-Architect debate loop.

This module does NOT spawn subagents itself. The /harness-debate slash
command drives the main agent, which uses the Agent tool to spawn subagents
and calls these helpers between spawns.

Keeping the engine stateless + event-sourced lets the main agent resume a
debate after a context reset — just reload the JSONL log.
"""
from __future__ import annotations

import random
import string
import time
from typing import Any

from lib.event_store import EventStore
from lib.phase_detector import is_strict_design_intent
from lib.similarity import compute_snapshot_similarity


def new_session_id() -> str:
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"debate-{int(time.time())}-{rand}"


def is_fast_path_eligible(
    topic: str,
    proposal: dict[str, Any] | None,
    critic_feedback: list[dict[str, Any]] | None,
) -> bool:
    """Gen-1 Critic bypass rules.

    All of these must hold:
      - not resuming a prior debate (no critic_feedback)
      - Planner produced something with no open_questions
      - topic contains a strict-design keyword (not just "how" alone)
    """
    if critic_feedback:
        return False
    if proposal is None:
        return False
    if proposal.get("open_questions"):
        return False
    # W22 cohesion (worker-1 R2 MED): use lib predicate instead of raw constant
    # so word-boundary semantics match handlers/prompt/debate_trigger.py
    # (previously: substring match here vs word-boundary match there → drift).
    return is_strict_design_intent(topic)


def record_event(
    store: EventStore,
    event_type: str,
    gen: int,
    actor: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return store.append(event_type, gen, actor, payload)


def load_history_snapshots(store: EventStore) -> list[dict[str, Any]]:
    """Every Architect ontology_snapshot in order (excluding the current gen)."""
    snapshots: list[dict[str, Any]] = []
    for ev in store.replay():
        if ev.get("type") == "verdict":
            snap = (ev.get("payload") or {}).get("ontology_snapshot")
            if snap:
                snapshots.append(snap)
    return snapshots


def log_similarity_backup(
    store: EventStore,
    gen: int,
    history_including_current: list[dict[str, Any]],
) -> float | None:
    """Log Ouroboros similarity between the two most recent snapshots.

    Backup signal only — the convergence decision uses Architect verdicts.
    Returns the logged score, or None if insufficient history.
    """
    if len(history_including_current) < 2:
        return None
    sim = compute_snapshot_similarity(
        history_including_current[-2], history_including_current[-1]
    )
    store.append(
        "similarity_log", gen, "engine",
        {"similarity": sim, "note": "backup signal — not used for convergence"},
    )
    return sim
