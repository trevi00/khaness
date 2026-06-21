#!/usr/bin/env python3
"""Unit tests for lib/git_flow_override.py — frontmatter-only parsing,
AND-condition is_solo_mode, key whitelist (W20+W24).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.git_flow_override import (  # noqa: E402
    is_company_mode,
    is_solo_mode,
    read_settings,
)


def _write_override(tmp_root: Path, content: str) -> None:
    d = tmp_root / ".claude"
    d.mkdir(parents=True, exist_ok=True)
    (d / "git-flow-overrides.md").write_text(content, encoding="utf-8")


def test_missing_file_returns_empty():
    with tempfile.TemporaryDirectory() as td:
        # max_levels=1 prevents walk-up from picking up
        # ~/.claude/git-flow-overrides.md when tempdir is under USERPROFILE
        # (Windows default tempfile location).
        assert read_settings(td, max_levels=1) == {}
        assert is_solo_mode(td, max_levels=1) is False
        assert is_company_mode(td, max_levels=1) is False


def test_frontmatter_only_solo_mode():
    with tempfile.TemporaryDirectory() as td:
        _write_override(Path(td), "---\nmode: solo\ndirect_push_main: allow\n---\n")
        s = read_settings(td)
        assert s == {"mode": "solo", "direct_push_main": "allow"}
        assert is_solo_mode(td) is True


def test_solo_mode_requires_BOTH_keys():
    """W20 fail-closed AND condition (worker-3 R2 HIGH)."""
    with tempfile.TemporaryDirectory() as td:
        _write_override(Path(td), "---\nmode: solo\n---\n")
        assert is_solo_mode(td) is False, "mode alone must NOT activate"

    with tempfile.TemporaryDirectory() as td:
        _write_override(Path(td), "---\ndirect_push_main: allow\n---\n")
        assert is_solo_mode(td) is False, "direct_push_main alone must NOT activate"


def test_body_lines_ignored():
    """W20 frontmatter-only parser — body content cannot activate policy."""
    with tempfile.TemporaryDirectory() as td:
        _write_override(Path(td), "---\noverride: company\n---\n\nmode: solo\ndirect_push_main: allow\n")
        # Frontmatter has only `override: company`; body's mode/direct_push_main ignored
        assert is_solo_mode(td) is False
        assert is_company_mode(td) is True


def test_unknown_keys_dropped():
    """W20 key whitelist."""
    with tempfile.TemporaryDirectory() as td:
        _write_override(Path(td), "---\nmalicious_setting: yes\nmode: solo\ndirect_push_main: allow\n---\n")
        s = read_settings(td)
        assert "malicious_setting" not in s
        assert s.get("mode") == "solo"


def test_missing_frontmatter_fence_fails_closed():
    with tempfile.TemporaryDirectory() as td:
        _write_override(Path(td), "mode: solo\ndirect_push_main: allow\n")
        # No `---` fence → empty
        assert read_settings(td) == {}
        assert is_solo_mode(td) is False


def test_company_mode_independent_of_solo():
    with tempfile.TemporaryDirectory() as td:
        _write_override(Path(td), "---\noverride: company\n---\n")
        assert is_company_mode(td) is True
        assert is_solo_mode(td) is False


TESTS = [
    test_missing_file_returns_empty,
    test_frontmatter_only_solo_mode,
    test_solo_mode_requires_BOTH_keys,
    test_body_lines_ignored,
    test_unknown_keys_dropped,
    test_missing_frontmatter_fence_fails_closed,
    test_company_mode_independent_of_solo,
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
    total = len(TESTS)
    if failed:
        print(f"\n[FAIL] {failed}/{total} tests failed")
        return 1
    print(f"\n[OK] {total} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
