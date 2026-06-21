#!/usr/bin/env python3
"""Tests for validators.atlas_structure pure helpers (M3 — close the 0-coverage gap).

The atlas_structure validator's main() is run by run_all.py but had NO unit test
(it skips entirely when no ATLAS_DIR exists). These exercise the pure helpers
_is_system_dir + _scan_depth directly. Auto-discovered by run_units.py via main().
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def test_is_system_dir():
    from validators.atlas_structure import _is_system_dir
    assert _is_system_dir("_meta") is True        # leading underscore
    assert _is_system_dir("_anything") is True
    assert _is_system_dir("99-archive") is True    # explicit archive
    assert _is_system_dir("concepts") is False
    assert _is_system_dir("domain") is False


def test_scan_depth_counts_dir_components():
    from validators.atlas_structure import _scan_depth
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "INDEX.md").write_text("x", encoding="utf-8")
        deep = root / "domain" / "concepts"
        deep.mkdir(parents=True)
        (deep / "foo.md").write_text("x", encoding="utf-8")
        deeper = root / "domain" / "sub" / "concepts"
        deeper.mkdir(parents=True)
        (deeper / "bar.md").write_text("x", encoding="utf-8")

        depth = {p.name: d for p, d in _scan_depth(root)}
        assert depth["INDEX.md"] == 0            # root file
        assert depth["foo.md"] == 2              # domain/concepts/foo.md
        assert depth["bar.md"] == 3              # domain/sub/concepts/bar.md


def test_scan_depth_only_markdown():
    from validators.atlas_structure import _scan_depth
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.md").write_text("x", encoding="utf-8")
        (root / "b.txt").write_text("x", encoding="utf-8")
        names = {p.name for p, _ in _scan_depth(root)}
        assert names == {"a.md"}


def main() -> int:
    failed = 0
    n = 0
    for name, obj in list(globals().items()):
        if not name.startswith("test_"):
            continue
        n += 1
        try:
            obj()
            print(f"  [OK] {name}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [ERR] {name}: {e!r}")
    if failed:
        print(f"\n{failed}/{n} failed")
        return 1
    print(f"\n[OK] {n} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
