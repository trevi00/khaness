"""Ontology similarity — ported from Ouroboros evolution/convergence.py.

Used as a BACKUP signal only (logged to telemetry). Primary convergence rule
is Architect verdict-based + deterministic (see lib.debate_convergence; the old
engine/convergence.py was deleted 2026-06-20). This module is a backup signal only.

Formula: 0.5 * name_overlap + 0.3 * type_match + 0.2 * exact_match
"""
from __future__ import annotations

from typing import Any


def compute_snapshot_similarity(
    prev: dict[str, Any], curr: dict[str, Any]
) -> float:
    """Compare two ontology snapshots produced by the Architect.

    Each snapshot has shape: {"fields": [{"id": str, "type": str, "value": Any}, ...]}
    """
    prev_fields = {d["id"]: d for d in prev.get("fields", []) if "id" in d}
    curr_fields = {d["id"]: d for d in curr.get("fields", []) if "id" in d}

    union_ids = set(prev_fields) | set(curr_fields)
    if not union_ids:
        return 1.0

    common_ids = set(prev_fields) & set(curr_fields)
    name_sim = len(common_ids) / len(union_ids)

    if not common_ids:
        return 0.5 * name_sim

    type_sim = sum(
        1
        for k in common_ids
        if prev_fields[k].get("type") == curr_fields[k].get("type")
    ) / len(common_ids)
    exact_sim = sum(
        1
        for k in common_ids
        if prev_fields[k].get("value") == curr_fields[k].get("value")
    ) / len(common_ids)

    return 0.5 * name_sim + 0.3 * type_sim + 0.2 * exact_sim
