#!/usr/bin/env python3
"""Unit tests for lib.jsonl_cache.load_jsonl_cached.

Pins the invariants the L1 (insight_index) and L2 (l2_facts) layers depend on
after they were de-duplicated onto this canonical reader (hygiene Tier-2).
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.jsonl_cache import load_jsonl_cached


def _write(path: Path, lines: list[str]) -> None:
    path.write_text("".join(l + "\n" for l in lines), encoding="utf-8")


def test_missing_file_returns_empty():
    cache: dict = {}
    assert load_jsonl_cached(Path("does-not-exist.jsonl"), cache) == []
    assert cache == {}  # missing file never populates the cache


def test_basic_parse_dicts_only():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "a.jsonl"
        _write(p, [
            json.dumps({"k": 1}),
            "",                       # blank line skipped
            "   ",                    # whitespace-only skipped
            "{not valid json",        # torn/invalid skipped
            json.dumps([1, 2, 3]),    # non-dict skipped
            json.dumps({"k": 2}),
        ])
        out = load_jsonl_cached(p, {})
        assert out == [{"k": 1}, {"k": 2}]


def test_cache_hit_returns_same_object():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "a.jsonl"
        _write(p, [json.dumps({"k": 1})])
        cache: dict = {}
        first = load_jsonl_cached(p, cache)
        second = load_jsonl_cached(p, cache)
        # unchanged (mtime_ns, size) -> O(1) return of the SAME cached list
        assert second is first
        assert p in cache


def test_cache_invalidates_on_append():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "a.jsonl"
        _write(p, [json.dumps({"k": 1})])
        cache: dict = {}
        first = load_jsonl_cached(p, cache)
        # append changes st_size -> key changes -> re-parse (different list)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"k": 2}) + "\n")
        second = load_jsonl_cached(p, cache)
        assert second is not first
        assert second == [{"k": 1}, {"k": 2}]


def test_per_cache_isolation():
    """Two caller caches do not cross-contaminate (L1 vs L2 isolation)."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "a.jsonl"
        _write(p, [json.dumps({"k": 1})])
        cache_a: dict = {}
        cache_b: dict = {}
        out_a = load_jsonl_cached(p, cache_a)
        assert p in cache_a and p not in cache_b
        out_b = load_jsonl_cached(p, cache_b)
        assert out_b == out_a
        assert out_b is not out_a  # distinct caches -> distinct parsed lists


TESTS = [
    test_missing_file_returns_empty,
    test_basic_parse_dicts_only,
    test_cache_hit_returns_same_object,
    test_cache_invalidates_on_append,
    test_per_cache_isolation,
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
