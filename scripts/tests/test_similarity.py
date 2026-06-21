#!/usr/bin/env python3
"""Tests for lib/similarity.py — ontology snapshot similarity scoring."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def test_empty_union_returns_1():
    from lib.similarity import compute_snapshot_similarity
    assert compute_snapshot_similarity({"fields": []}, {"fields": []}) == 1.0


def test_missing_fields_key_treated_as_empty():
    from lib.similarity import compute_snapshot_similarity
    assert compute_snapshot_similarity({}, {}) == 1.0


def test_no_common_ids_returns_half_name_sim():
    from lib.similarity import compute_snapshot_similarity
    prev = {"fields": [{"id": "A", "type": "x", "value": 1}]}
    curr = {"fields": [{"id": "B", "type": "x", "value": 1}]}
    # name_sim = 0/2 = 0.0; no common → 0.5 * 0.0 = 0.0
    assert compute_snapshot_similarity(prev, curr) == 0.0


def test_identical_snapshots_return_1():
    from lib.similarity import compute_snapshot_similarity
    snap = {"fields": [
        {"id": "D1", "type": "api", "value": "spec1"},
        {"id": "D2", "type": "scope", "value": "DEFERRED"},
    ]}
    assert compute_snapshot_similarity(snap, snap) == 1.0


def test_partial_overlap_full_formula():
    from lib.similarity import compute_snapshot_similarity
    prev = {"fields": [
        {"id": "A", "type": "x", "value": 1},
        {"id": "B", "type": "y", "value": 2},
    ]}
    curr = {"fields": [
        {"id": "A", "type": "x", "value": 1},  # full match
        {"id": "C", "type": "y", "value": 3},  # new id
    ]}
    # union = {A,B,C}; common = {A}; name_sim = 1/3
    # type_sim on A = 1/1; exact_sim on A = 1/1
    expected = 0.5 * (1/3) + 0.3 * 1.0 + 0.2 * 1.0
    result = compute_snapshot_similarity(prev, curr)
    assert abs(result - expected) < 1e-9


def test_type_mismatch_reduces_score():
    from lib.similarity import compute_snapshot_similarity
    prev = {"fields": [{"id": "A", "type": "x", "value": 1}]}
    curr = {"fields": [{"id": "A", "type": "y", "value": 1}]}
    # union = {A}; common = {A}; name = 1, type = 0 (x≠y), exact = 1 (1==1)
    expected = 0.5 * 1.0 + 0.3 * 0.0 + 0.2 * 1.0  # = 0.7
    assert abs(compute_snapshot_similarity(prev, curr) - expected) < 1e-9


def test_skips_fields_missing_id_key():
    from lib.similarity import compute_snapshot_similarity
    # Field without 'id' is filtered out by both sides
    prev = {"fields": [{"id": "A", "type": "x", "value": 1}, {"type": "noop"}]}
    curr = {"fields": [{"id": "A", "type": "x", "value": 1}]}
    assert compute_snapshot_similarity(prev, curr) == 1.0


TESTS = [
    test_empty_union_returns_1,
    test_missing_fields_key_treated_as_empty,
    test_no_common_ids_returns_half_name_sim,
    test_identical_snapshots_return_1,
    test_partial_overlap_full_formula,
    test_type_mismatch_reduces_score,
    test_skips_fields_missing_id_key,
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
