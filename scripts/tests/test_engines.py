#!/usr/bin/env python3
"""Tests for lib/engines.py — engine registry."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def test_list_engines_returns_tuple():
    from lib.engines import list_engines
    engines = list_engines()
    assert isinstance(engines, tuple)
    assert len(engines) >= 2  # at minimum debate + ralph


def test_list_engines_contains_debate_and_ralph():
    from lib.engines import list_engines
    names = {e.name for e in list_engines()}
    assert "debate" in names
    assert "ralph" in names


def test_engine_meta_fields_populated():
    from lib.engines import list_engines, EngineMeta
    for meta in list_engines():
        assert isinstance(meta, EngineMeta)
        assert meta.name and isinstance(meta.name, str)
        assert meta.state_subdir and isinstance(meta.state_subdir, str)
        assert meta.session_prefix and isinstance(meta.session_prefix, str)
        assert meta.description and isinstance(meta.description, str)


def test_state_dir_for_known_engine_returns_path():
    from lib.engines import state_dir_for
    p = state_dir_for("debate")
    assert p is not None
    assert "debates" in str(p)


def test_state_dir_for_unknown_engine_returns_none():
    from lib.engines import state_dir_for
    assert state_dir_for("nonexistent-engine") is None


def test_state_dir_for_ralph():
    from lib.engines import state_dir_for
    p = state_dir_for("ralph")
    assert p is not None
    assert "ralph" in str(p)


def test_engine_meta_is_frozen():
    from lib.engines import list_engines
    meta = list_engines()[0]
    try:
        meta.name = "mutated"  # type: ignore[misc]
    except (AttributeError, Exception):
        return
    raise AssertionError("EngineMeta must be frozen dataclass (immutable)")


TESTS = [
    test_list_engines_returns_tuple,
    test_list_engines_contains_debate_and_ralph,
    test_engine_meta_fields_populated,
    test_state_dir_for_known_engine_returns_path,
    test_state_dir_for_unknown_engine_returns_none,
    test_state_dir_for_ralph,
    test_engine_meta_is_frozen,
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
