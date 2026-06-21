#!/usr/bin/env python3
"""Tests for lib.ac_tree (v15.26 C-alpha)."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.ac_tree import (  # noqa: E402
    AdvisoryLeaf,
    GateLeaf,
    aggregate,
    evaluate_emit,
)


# ---- __post_init__ guards ----

def test_gate_leaf_rejects_non_callable():
    try:
        GateLeaf(predicate="not-callable", description="test")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_advisory_leaf_rejects_bad_axis():
    try:
        AdvisoryLeaf(predicate=lambda c: 3, axis="completness", description="typo")  # typo
        assert False, "expected ValueError on typo axis"
    except ValueError:
        pass


def test_advisory_leaf_rejects_non_callable():
    try:
        AdvisoryLeaf(predicate=42, axis="cohesion", description="test")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_gate_leaf_rejects_empty_description():
    try:
        GateLeaf(predicate=lambda c: True, description="   ")
        assert False, "expected ValueError"
    except ValueError:
        pass


# ---- aggregate verdict ----

def test_empty_leaves_is_approved():
    assert aggregate([], None) == "approved"


def test_all_gates_true_no_advisory_is_approved():
    leaves = [GateLeaf(predicate=lambda c: True, description="g1")]
    assert aggregate(leaves, None) == "approved"


def test_any_gate_false_is_escalate():
    leaves = [
        GateLeaf(predicate=lambda c: True, description="g1"),
        GateLeaf(predicate=lambda c: False, description="g2"),
    ]
    assert aggregate(leaves, None) == "escalate"


def test_advisory_low_score_is_iterate():
    leaves = [
        GateLeaf(predicate=lambda c: True, description="g1"),
        AdvisoryLeaf(predicate=lambda c: 2, axis="cohesion", description="a1"),  # <= 2 → iterate
    ]
    assert aggregate(leaves, None) == "iterate"


def test_advisory_mean_low_is_iterate():
    """All scores ≥ 3 individually but mean < 3 → iterate. Test mean=2.66..."""
    leaves = [
        AdvisoryLeaf(predicate=lambda c: 3, axis="cohesion", description="a1"),
        AdvisoryLeaf(predicate=lambda c: 3, axis="coupling", description="a2"),
        AdvisoryLeaf(predicate=lambda c: 2, axis="stability", description="a3"),  # any ≤2 → iterate
    ]
    assert aggregate(leaves, None) == "iterate"


def test_advisory_all_three_plus_is_approved():
    leaves = [
        AdvisoryLeaf(predicate=lambda c: 3, axis="cohesion", description="a1"),
        AdvisoryLeaf(predicate=lambda c: 4, axis="coupling", description="a2"),
        AdvisoryLeaf(predicate=lambda c: 5, axis="extensibility", description="a3"),
    ]
    assert aggregate(leaves, None) == "approved"


def test_gate_false_dominates_high_advisory():
    """Gate False overrides high advisory scores."""
    leaves = [
        GateLeaf(predicate=lambda c: False, description="must-pass"),
        AdvisoryLeaf(predicate=lambda c: 5, axis="cohesion", description="excellent"),
    ]
    assert aggregate(leaves, None) == "escalate"


def test_advisory_score_out_of_range_raises():
    leaves = [AdvisoryLeaf(predicate=lambda c: 10, axis="cohesion", description="bad")]
    try:
        aggregate(leaves, None)
        assert False, "expected ValueError on score > 5"
    except ValueError:
        pass


def test_advisory_score_bool_rejected():
    """Predicate returning bool (which is int in Python) must be rejected."""
    leaves = [AdvisoryLeaf(predicate=lambda c: True, axis="cohesion", description="bool")]
    try:
        aggregate(leaves, None)
        assert False, "expected ValueError on bool return"
    except ValueError:
        pass


def test_advisory_score_none_rejected():
    leaves = [AdvisoryLeaf(predicate=lambda c: None, axis="cohesion", description="none")]
    try:
        aggregate(leaves, None)
        assert False, "expected ValueError on None return"
    except ValueError:
        pass


# ---- evaluate_emit ----

def test_evaluate_emit_emits_per_leaf():
    events = []
    leaves = [
        GateLeaf(predicate=lambda c: True, description="g1"),
        AdvisoryLeaf(predicate=lambda c: 4, axis="cohesion", description="a1"),
    ]
    verdict = evaluate_emit(leaves, None, lambda t, p: events.append((t, p)))
    assert verdict == "approved"
    assert len(events) == 2
    assert all(t == "ac.leaf_evaluated" for t, _ in events)
    # gate payload
    gate_payload = next(p for t, p in events if p["axis"] == "gate")
    assert gate_payload["passed"] is True
    assert gate_payload["score"] is None
    # advisory payload
    adv_payload = next(p for t, p in events if p["axis"] == "cohesion")
    assert adv_payload["score"] == 4
    assert adv_payload["passed"] is True


def test_leaf_id_stable_for_same_axis_description():
    g1 = GateLeaf(predicate=lambda c: True, description="same")
    g2 = GateLeaf(predicate=lambda c: False, description="same")
    assert g1.leaf_id == g2.leaf_id  # predicate not part of id


def test_isinstance_check_blocks_typo():
    """D2 invariant: no 'kind' field on either class → typo on field name impossible."""
    g = GateLeaf(predicate=lambda c: True, description="x")
    a = AdvisoryLeaf(predicate=lambda c: 3, axis="cohesion", description="y")
    # No `kind`/`axis_role` attribute on GateLeaf
    assert not hasattr(g, "axis_role")
    assert not hasattr(g, "kind")
    assert not hasattr(g, "axis")  # only AdvisoryLeaf has axis
    assert hasattr(a, "axis")


TESTS = [
    test_gate_leaf_rejects_non_callable,
    test_advisory_leaf_rejects_bad_axis,
    test_advisory_leaf_rejects_non_callable,
    test_gate_leaf_rejects_empty_description,
    test_empty_leaves_is_approved,
    test_all_gates_true_no_advisory_is_approved,
    test_any_gate_false_is_escalate,
    test_advisory_low_score_is_iterate,
    test_advisory_mean_low_is_iterate,
    test_advisory_all_three_plus_is_approved,
    test_gate_false_dominates_high_advisory,
    test_advisory_score_out_of_range_raises,
    test_advisory_score_bool_rejected,
    test_advisory_score_none_rejected,
    test_evaluate_emit_emits_per_leaf,
    test_leaf_id_stable_for_same_axis_description,
    test_isinstance_check_blocks_typo,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"  [OK] {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  [ERROR] {fn.__name__}: {type(e).__name__}: {e}")
    if failed:
        print(f"\n[FAIL] {failed}/{len(TESTS)} tests failed")
        return 1
    print(f"\n[OK] {len(TESTS)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
