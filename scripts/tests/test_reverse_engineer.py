#!/usr/bin/env python3
"""Tests for cli/reverse_engineer._select_extractors — doc_classifier isolation (P2 D2 ⓒ)."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cli.reverse_engineer import _select_extractors  # noqa: E402
from lib.extractors import get_extractor  # noqa: E402


def _names(stage):
    return [e.name for e in _select_extractors(stage)]


def test_default_walk_excludes_doc_classifier():
    names = _names(None)
    assert "doc_classifier" not in names, names
    # code extractors still present
    assert {"convention", "er", "logical"} <= set(names), names


def test_stage_includes_doc_classifier_explicitly():
    sel = _select_extractors("doc_classifier")
    assert [e.name for e in sel] == ["doc_classifier"], sel


def test_unknown_stage_empty():
    assert _select_extractors("nonexistent") == []


def test_doc_classifier_marked_non_code():
    assert getattr(get_extractor("doc_classifier"), "code_extractor", True) is False


def test_code_extractors_default_true():
    for n in ("convention", "er", "logical"):
        assert getattr(get_extractor(n), "code_extractor", True) is True, n


def main() -> int:
    tests = [
        test_default_walk_excludes_doc_classifier,
        test_stage_includes_doc_classifier_explicitly,
        test_unknown_stage_empty,
        test_doc_classifier_marked_non_code,
        test_code_extractors_default_true,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    if failed == 0:
        print(f"[OK] {len(tests)} tests passed")
        return 0
    print(f"[FAIL] {failed}/{len(tests)} tests failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
