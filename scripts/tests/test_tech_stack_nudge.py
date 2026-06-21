#!/usr/bin/env python3
"""Unit tests for lib/tech_stack_nudge.py — tech-stack.yaml missing warning."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import tech_stack_nudge as tsn  # noqa: E402


def _make_project(td, *, with_tech_stack: bool = False, marker_file: str = "package.json"):
    """Create a fake project root under td with a project marker file (so
    find_project_root resolves it) and optional .claude/tech-stack.yaml.
    """
    root = Path(td) / "proj"
    root.mkdir(parents=True, exist_ok=True)
    (root / marker_file).write_text("{}", encoding="utf-8")  # marker file (not dir)
    if with_tech_stack:
        (root / ".claude").mkdir(parents=True, exist_ok=True)
        (root / ".claude" / "tech-stack.yaml").write_text("stack:\n  language: python\n", encoding="utf-8")
    return root


def test_returns_none_when_tech_stack_present():
    with tempfile.TemporaryDirectory() as td:
        root = _make_project(td, with_tech_stack=True)
        cache_path = os.path.join(td, "cache.json")
        with patch.object(tsn, "TECH_STACK_WARN_CACHE", cache_path):
            assert tsn.maybe_emit_tech_stack_warning(str(root)) is None


def test_emits_warning_when_tech_stack_missing():
    with tempfile.TemporaryDirectory() as td:
        root = _make_project(td, with_tech_stack=False)
        cache_path = os.path.join(td, "cache.json")
        with patch.object(tsn, "TECH_STACK_WARN_CACHE", cache_path):
            result = tsn.maybe_emit_tech_stack_warning(str(root))
        assert result is not None
        assert "tech-stack.yaml" in result
        assert "harness-warning" in result
        # Cache was written
        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)
        assert any(str(root).replace("\\", "/") == k for k in cache)


def test_returns_none_on_second_call_within_ttl():
    with tempfile.TemporaryDirectory() as td:
        root = _make_project(td, with_tech_stack=False)
        cache_path = os.path.join(td, "cache.json")
        with patch.object(tsn, "TECH_STACK_WARN_CACHE", cache_path):
            first = tsn.maybe_emit_tech_stack_warning(str(root))
            second = tsn.maybe_emit_tech_stack_warning(str(root))
        assert first is not None
        assert second is None  # suppressed by cache


def test_re_emits_after_ttl_expiry():
    with tempfile.TemporaryDirectory() as td:
        root = _make_project(td, with_tech_stack=False)
        cache_path = os.path.join(td, "cache.json")
        # Pre-populate cache with a stale entry (TTL = 24h, write 25h-old timestamp)
        old_ts = time.time() - (25 * 3600)
        key = str(root).replace("\\", "/")
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({key: old_ts}, f)
        with patch.object(tsn, "TECH_STACK_WARN_CACHE", cache_path):
            result = tsn.maybe_emit_tech_stack_warning(str(root))
        assert result is not None  # stale entry was aged out, warning re-emitted


def test_returns_none_when_cwd_outside_any_project():
    with tempfile.TemporaryDirectory() as td:
        # No marker file inside — find_project_root returns None.
        # max_levels=1: tempdir is under USERPROFILE on Windows; without the
        # cap, walk-up reaches user home which has real project markers.
        cache_path = os.path.join(td, "cache.json")
        with patch.object(tsn, "TECH_STACK_WARN_CACHE", cache_path):
            assert tsn.maybe_emit_tech_stack_warning(td, max_levels=1) is None


def main() -> int:
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  [OK] {fn.__name__}")
        except Exception:
            failed += 1
            print(f"  [FAIL] {fn.__name__}")
            traceback.print_exc()
    print(f"\n[{'FAIL' if failed else 'OK'}] {len(fns) - failed}/{len(fns)} tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
