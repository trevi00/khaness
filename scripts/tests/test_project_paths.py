#!/usr/bin/env python3
"""Unit tests for lib/project_paths.py — walk_up + find_claude_dir + find_project_root."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import project_paths as pp  # noqa: E402


def test_walk_up_predicate_at_cwd():
    with tempfile.TemporaryDirectory() as td:
        result = pp.walk_up(td, lambda d: d == os.path.normpath(td))
        assert result == os.path.normpath(td)


def test_walk_up_predicate_at_parent():
    with tempfile.TemporaryDirectory() as td:
        sub = os.path.join(td, "a", "b")
        os.makedirs(sub)
        target = os.path.normpath(td)
        result = pp.walk_up(sub, lambda d: d == target)
        assert result == target


def test_walk_up_no_match_returns_none():
    with tempfile.TemporaryDirectory() as td:
        result = pp.walk_up(td, lambda d: False)
        assert result is None


def test_walk_up_max_levels_caps_iteration():
    """Max-levels=1 → only checks cwd, not parents."""
    with tempfile.TemporaryDirectory() as td:
        sub = os.path.join(td, "a", "b", "c")
        os.makedirs(sub)
        target = os.path.normpath(td)
        # With max_levels=1, can't walk back from sub to td (3 levels up).
        result = pp.walk_up(sub, lambda d: d == target, max_levels=1)
        assert result is None


def test_walk_up_stops_at_filesystem_root():
    """Should not loop forever when reaching /."""
    # Use a path we know exists at filesystem root level.
    result = pp.walk_up("/", lambda d: False, max_levels=20)
    assert result is None


def test_find_claude_dir_no_claude_returns_none():
    """Bound max_levels so the test doesn't walk up to a real $HOME/.claude."""
    with tempfile.TemporaryDirectory() as td:
        assert pp.find_claude_dir(td, max_levels=1) is None


def test_find_claude_dir_finds_marker_only():
    """Without content_files predicate, .claude/ existing is enough."""
    with tempfile.TemporaryDirectory() as td:
        cdir = os.path.join(td, ".claude")
        os.makedirs(cdir)
        result = pp.find_claude_dir(td)
        assert result == cdir


def test_find_claude_dir_requires_content_when_specified():
    """With content_files, empty .claude/ is rejected."""
    with tempfile.TemporaryDirectory() as td:
        cdir = os.path.join(td, ".claude")
        os.makedirs(cdir)
        # No content files exist, predicate fails.
        result = pp.find_claude_dir(td, content_files=["plan.md"])
        assert result is None


def test_find_claude_dir_accepts_when_content_present():
    with tempfile.TemporaryDirectory() as td:
        cdir = os.path.join(td, ".claude")
        os.makedirs(cdir)
        with open(os.path.join(cdir, "plan.md"), "w") as f:
            f.write("hi")
        result = pp.find_claude_dir(td, content_files=["plan.md", "context.md"])
        assert result == cdir


def test_find_claude_dir_walks_up_parent():
    with tempfile.TemporaryDirectory() as td:
        cdir = os.path.join(td, ".claude")
        os.makedirs(cdir)
        sub = os.path.join(td, "a", "b")
        os.makedirs(sub)
        result = pp.find_claude_dir(sub)
        assert result == cdir


def test_find_project_root_no_marker_returns_none():
    with tempfile.TemporaryDirectory() as td:
        # max_levels=1: tempdir is under USERPROFILE on Windows, where the
        # user's home contains real project markers (e.g. build.gradle); the
        # walk-up would otherwise reach those instead of returning None.
        assert pp.find_project_root(td, max_levels=1) is None


def test_find_project_root_finds_default_marker():
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "package.json"), "w") as f:
            f.write("{}")
        result = pp.find_project_root(td)
        assert result == os.path.normpath(td)


def test_find_project_root_finds_custom_marker():
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "myMarker"), "w") as f:
            f.write("")
        result = pp.find_project_root(td, markers=["myMarker"])
        assert result == os.path.normpath(td)


def test_find_project_root_walks_up():
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "pom.xml"), "w") as f:
            f.write("")
        sub = os.path.join(td, "src", "main", "java")
        os.makedirs(sub)
        result = pp.find_project_root(sub)
        assert result == os.path.normpath(td)


def test_project_markers_includes_common():
    """Sanity: PROJECT_MARKERS still has the canonical set."""
    expected = {"package.json", "pom.xml", "pubspec.yaml", "go.mod", "Cargo.toml"}
    assert expected <= set(pp.PROJECT_MARKERS)


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
