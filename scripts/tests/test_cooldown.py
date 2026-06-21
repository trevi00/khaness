#!/usr/bin/env python3
"""Unit tests for lib/cooldown.py — check_cooldown / cooldown_path / clear_cooldown."""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import cooldown as cd  # noqa: E402


def test_cooldown_path_sanitizes_separators():
    p = cd.cooldown_path("foo.bar/baz")
    assert "_" in os.path.basename(p)
    assert ".bar" not in os.path.basename(p)
    assert "/" not in os.path.basename(p)


def test_cooldown_path_uses_temp_dir():
    p = cd.cooldown_path("xyz")
    assert p.startswith(cd.TEMP_DIR)
    assert os.path.basename(p).startswith(".claude_cd_")


def test_check_cooldown_first_call_returns_true():
    """First check creates the marker and returns True."""
    with tempfile.TemporaryDirectory() as td:
        marker = os.path.join(td, "cd1")
        assert cd.check_cooldown(marker, 60) is True
        assert os.path.exists(marker)


def test_check_cooldown_within_window_returns_false():
    """Second check within the window must return False (stayed inside)."""
    with tempfile.TemporaryDirectory() as td:
        marker = os.path.join(td, "cd2")
        assert cd.check_cooldown(marker, 60) is True
        assert cd.check_cooldown(marker, 60) is False


def test_check_cooldown_after_window_returns_true():
    """When the marker is older than the window, it's expired → True."""
    with tempfile.TemporaryDirectory() as td:
        marker = os.path.join(td, "cd3")
        cd.check_cooldown(marker, 60)
        # Backdate the file to 2 minutes ago.
        old = time.time() - 120
        os.utime(marker, (old, old))
        assert cd.check_cooldown(marker, 60) is True


def test_check_cooldown_io_error_defaults_true():
    """If marker dir cannot be created, default to True (don't block hooks)."""
    # A path that cannot be opened as a writable file (root-only dir).
    bad_path = "/this/directory/does/not/exist/marker"
    assert cd.check_cooldown(bad_path, 60) is True


def test_clear_cooldown_removes_marker():
    with tempfile.TemporaryDirectory() as td:
        marker = os.path.join(td, "cd4")
        cd.check_cooldown(marker, 60)
        assert os.path.exists(marker)
        cd.clear_cooldown(marker)
        assert not os.path.exists(marker)


def test_clear_cooldown_missing_no_error():
    """Clearing a non-existent file should not raise."""
    cd.clear_cooldown("/no/such/file/here")


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
