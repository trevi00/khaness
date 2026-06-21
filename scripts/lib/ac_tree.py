"""ac_tree — Acceptance Criteria tree with axis-typed leaves (v15.26 T).

debate-1778987814-41b475 D2: GateLeaf + AdvisoryLeaf split — no discriminator
field, isinstance-based aggregation eliminates typo-bypass. __post_init__
guards raise ValueError at construction on bad axis or non-callable predicate.

Verdict aggregation rule (S1 short-circuit composition, debate-1778987814-41b475):
- any GateLeaf returns False → tree_verdict='escalate' (hard fail)
- all GateLeaf True + (any AdvisoryLeaf score ≤ 2 OR mean < 3) → 'iterate'
- all GateLeaf True + (all AdvisoryLeaf scores ≥ 3 AND mean ≥ 3) → 'approved'

5 advisory axes (subset of ISO 25010 quality model):
- cohesion / coupling / extensibility / stability / usability — score 1..5 int
Plus 1 strict-gate axis (separate type, no axis field):
- GateLeaf — predicate→bool, used for "completeness" + binary functional checks

Per harness-evaluator.md schema (lines 64-71, 96-101): advisory axes live in
axis_scores dict; completeness lives as separate top-level boolean GATE field.
This module respects that separation structurally via two distinct classes.

D-AC-PHASE-1TO1: each AC leaf maps to Phase Tree sub_step. Leaf id is
SHA-1[:16] of (axis + description) for stable cross-reference.

Public API:
- GateLeaf(predicate, description) — bool gate
- AdvisoryLeaf(predicate, axis: Literal[5], description) — int 1..5 advisory
- aggregate(leaves, ctx) -> str ∈ {'approved', 'iterate', 'escalate'}
- evaluate_emit(leaves, ctx, emit_fn) — runs predicates + emits ac.leaf_evaluated per leaf

Invariant: NO LLM, NO embedder. Pure stdlib.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Literal


Axis = Literal["cohesion", "coupling", "extensibility", "stability", "usability"]
_ALLOWED_AXES: frozenset[str] = frozenset(
    {"cohesion", "coupling", "extensibility", "stability", "usability"}
)

_ADVISORY_LOW_THRESHOLD = 2  # any score <= this → iterate
_ADVISORY_MEAN_THRESHOLD = 3.0  # mean < this → iterate
_HASH_PREFIX_LEN = 16


def _leaf_id(axis: str, description: str) -> str:
    return hashlib.sha1(f"{axis}|{description}".encode("utf-8")).hexdigest()[:_HASH_PREFIX_LEN]


@dataclass
class GateLeaf:
    """Strict boolean gate. predicate(ctx) → bool. NO axis field (structural distinction)."""

    predicate: Callable[[Any], bool]
    description: str

    def __post_init__(self):
        if not callable(self.predicate):
            raise ValueError(
                f"GateLeaf.predicate must be callable, got {type(self.predicate).__name__}"
            )
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("GateLeaf.description must be non-empty string")

    @property
    def leaf_id(self) -> str:
        return _leaf_id("gate", self.description)


@dataclass
class AdvisoryLeaf:
    """Advisory 1..5 score on a single primary axis. predicate(ctx) → int."""

    predicate: Callable[[Any], int]
    axis: Axis
    description: str

    def __post_init__(self):
        if self.axis not in _ALLOWED_AXES:
            raise ValueError(
                f"AdvisoryLeaf.axis must be in {sorted(_ALLOWED_AXES)}, got {self.axis!r}"
            )
        if not callable(self.predicate):
            raise ValueError(
                f"AdvisoryLeaf.predicate must be callable, got {type(self.predicate).__name__}"
            )
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("AdvisoryLeaf.description must be non-empty string")

    @property
    def leaf_id(self) -> str:
        return _leaf_id(self.axis, self.description)


Leaf = "GateLeaf | AdvisoryLeaf"


def _coerce_score(raw: Any) -> int:
    """Runtime guard against advisory predicate returning bool/None/out-of-range."""
    if isinstance(raw, bool):
        # bool is int in Python — explicit reject (True==1, False==0 ambiguity)
        raise ValueError(f"AdvisoryLeaf predicate returned bool ({raw!r}) — must be int 1..5")
    if raw is None:
        raise ValueError("AdvisoryLeaf predicate returned None — must be int 1..5")
    if not isinstance(raw, int):
        raise ValueError(
            f"AdvisoryLeaf predicate returned {type(raw).__name__} — must be int 1..5"
        )
    if not 1 <= raw <= 5:
        raise ValueError(f"AdvisoryLeaf predicate score out of range: {raw} (must be 1..5)")
    return raw


def aggregate(leaves: list, ctx: Any = None) -> str:
    """Aggregate verdict ∈ {'approved', 'iterate', 'escalate'} per D2 rule.

    Empty leaf list returns 'approved' (no constraint to violate).
    Mixed leaf types use isinstance for branch — typo on field name impossible
    because GateLeaf has no axis field at all.

    Raises TypeError on unknown leaf type, ValueError on bad predicate return.
    """
    if not leaves:
        return "approved"
    gate_results: list[bool] = []
    advisory_scores: list[int] = []
    for leaf in leaves:
        if isinstance(leaf, GateLeaf):
            gate_results.append(bool(leaf.predicate(ctx)))
        elif isinstance(leaf, AdvisoryLeaf):
            advisory_scores.append(_coerce_score(leaf.predicate(ctx)))
        else:
            raise TypeError(f"Unknown leaf type: {type(leaf).__name__}")

    if not all(gate_results):
        return "escalate"
    if not advisory_scores:
        return "approved"
    mean = sum(advisory_scores) / len(advisory_scores)
    if any(s <= _ADVISORY_LOW_THRESHOLD for s in advisory_scores) or mean < _ADVISORY_MEAN_THRESHOLD:
        return "iterate"
    return "approved"


def evaluate_emit(
    leaves: list,
    ctx: Any,
    emit_fn: Callable[[str, dict], None],
) -> str:
    """Run all predicates + emit `ac.leaf_evaluated` per leaf, return aggregate verdict.

    Payload schema (single event type per D4, matches ledger.* precedent):
      axis: 'gate' | <one of 5 advisory>
      passed: bool
      score: int | None  (None for gate)
      leaf_id: SHA-1[:16]

    Predicates are called once per leaf. Aggregate is computed from collected
    pass/scores (not by re-calling predicates — avoids double side effects).
    """
    gate_results: list[bool] = []
    advisory_scores: list[int] = []
    for leaf in leaves:
        if isinstance(leaf, GateLeaf):
            passed = bool(leaf.predicate(ctx))
            gate_results.append(passed)
            try:
                emit_fn("ac.leaf_evaluated", {
                    "axis": "gate",
                    "passed": passed,
                    "score": None,
                    "leaf_id": leaf.leaf_id,
                })
            except Exception:
                pass
        elif isinstance(leaf, AdvisoryLeaf):
            score = _coerce_score(leaf.predicate(ctx))
            advisory_scores.append(score)
            try:
                emit_fn("ac.leaf_evaluated", {
                    "axis": leaf.axis,
                    "passed": score >= 3,
                    "score": score,
                    "leaf_id": leaf.leaf_id,
                })
            except Exception:
                pass
        else:
            raise TypeError(f"Unknown leaf type: {type(leaf).__name__}")

    if not all(gate_results):
        return "escalate"
    if not advisory_scores:
        return "approved"
    mean = sum(advisory_scores) / len(advisory_scores)
    if any(s <= _ADVISORY_LOW_THRESHOLD for s in advisory_scores) or mean < _ADVISORY_MEAN_THRESHOLD:
        return "iterate"
    return "approved"
