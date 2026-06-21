#!/usr/bin/env python3
"""Unit tests for lib/atomic_json.py — read_json / write_json_atomic."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import atomic_json as aj  # noqa: E402


def test_read_json_returns_default_for_missing_file():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "missing.json")
        assert aj.read_json(path, default={}) == {}
        assert aj.read_json(path, default=[]) == []
        assert aj.read_json(path, default=None) is None


def test_read_json_returns_default_for_malformed_json():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "bad.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        assert aj.read_json(path, default={}) == {}


def test_read_json_returns_parsed_dict():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "ok.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"a": 1, "b": "two"}, f)
        assert aj.read_json(path, default={}) == {"a": 1, "b": "two"}


def test_read_json_type_mismatch_returns_default():
    """File holds a string but caller expects dict → default returned."""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "wrongtype.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump("a string", f)
        assert aj.read_json(path, default={}) == {}
        assert aj.read_json(path, default=[]) == []


def test_read_json_default_none_skips_type_check():
    """default=None → caller wants raw parsed value regardless of type."""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "any.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump("just a string", f)
        assert aj.read_json(path, default=None) == "just a string"


def test_write_json_atomic_creates_file():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "out.json")
        ok = aj.write_json_atomic(path, {"x": 1})
        assert ok is True
        assert os.path.exists(path)
        with open(path, "r", encoding="utf-8") as f:
            assert json.load(f) == {"x": 1}


def test_write_json_atomic_overwrites_existing():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "out.json")
        aj.write_json_atomic(path, {"v": 1})
        aj.write_json_atomic(path, {"v": 2})
        with open(path, "r", encoding="utf-8") as f:
            assert json.load(f) == {"v": 2}


def test_write_json_atomic_no_tmp_residue_on_success():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "out.json")
        aj.write_json_atomic(path, {"x": 1})
        residue = [n for n in os.listdir(td) if n.endswith(".tmp")]
        assert residue == [], f"expected no .tmp residue, got {residue}"


def test_write_json_atomic_returns_false_on_unwritable():
    """Writing to a directory path (not a file) should fail and return False."""
    with tempfile.TemporaryDirectory() as td:
        # Pass the directory itself as the target — open() will fail.
        ok = aj.write_json_atomic(td, {"x": 1})
        assert ok is False


def test_write_json_atomic_unicode_default_no_ascii_escape():
    """ensure_ascii=False default → Korean chars roundtrip raw, not \\uXXXX."""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "kr.json")
        aj.write_json_atomic(path, {"msg": "안녕"})
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        assert "안녕" in raw
        assert "\\u" not in raw


def test_write_json_atomic_ensure_ascii_true_escapes():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "kr.json")
        aj.write_json_atomic(path, {"msg": "안녕"}, ensure_ascii=True)
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        assert "안녕" not in raw
        assert "\\u" in raw


def test_roundtrip_dict():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "rt.json")
        payload = {"counts": {"a": 5, "b": 7}, "tags": ["x", "y"]}
        aj.write_json_atomic(path, payload)
        assert aj.read_json(path, default={}) == payload


def main() -> int:
    failures = []
    test_count = 0
    for name, obj in list(globals().items()):
        if not name.startswith("test_"):
            continue
        test_count += 1
        try:
            obj()
            print(f"  [OK] {name}")
        except AssertionError as e:
            failures.append((name, str(e)))
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:
            failures.append((name, repr(e)))
            print(f"  [ERR]  {name}: {e!r}")
    if failures:
        print(f"\n{len(failures)} test(s) failed")
        return 1
    print(f"\n[OK] {test_count} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
