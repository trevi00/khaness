#!/usr/bin/env python3
"""Unit tests for lib/path_denylist.py — D4 path canonicalization + denylist."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import path_denylist  # noqa: E402

# Derive the .claude prefix from Path.home() exactly as path_denylist source does
# (_RAW_DENY_PREFIXES uses str(Path.home() / ".claude" / ...)). Portable: works
# regardless of the developer's actual home, no hardcoded user path.
_C = Path.home() / ".claude"


def test_canonicalize_returns_none_for_empty():
    assert path_denylist.canonicalize("") is None
    assert path_denylist.canonicalize(None) is None


def test_canonicalize_lowercases_on_windows():
    """normcase folds Windows drive letter and path separators."""
    out = path_denylist.canonicalize(str(_C / "skills" / "_common" / "test.md"))
    assert out is not None
    if sys.platform.startswith("win"):
        assert out.lower() == out, "Windows normcase should lowercase"


def test_is_denied_true_for_skills_meta():
    assert path_denylist.is_denied(str(_C / "skills" / "_meta" / "anything.md")) is True


def test_is_denied_true_for_harness_agent():
    assert path_denylist.is_denied(str(_C / "agents" / "harness-researcher.md")) is True


def test_is_denied_true_for_writeback_self():
    assert path_denylist.is_denied(str(_C / "scripts" / "lib" / "writeback_parser.py")) is True
    assert path_denylist.is_denied(str(_C / "scripts" / "lib" / "writeback_store.py")) is True


def test_is_denied_true_for_debate_trigger():
    assert path_denylist.is_denied(str(_C / "scripts" / "handlers" / "prompt" / "debate_trigger.py")) is True


def test_is_denied_true_for_claude_md():
    assert path_denylist.is_denied(str(_C / "CLAUDE.md")) is True


def test_is_denied_false_for_legit_skill():
    assert path_denylist.is_denied(str(_C / "skills" / "_common" / "test.md")) is False


def test_is_denied_true_for_empty_input():
    """Fail-closed on empty/None — caller defensive."""
    assert path_denylist.is_denied("") is True
    assert path_denylist.is_denied(None) is True


def test_deny_prefixes_count():
    assert len(path_denylist.DENY_PREFIXES) == 6


TESTS = [
    test_canonicalize_returns_none_for_empty,
    test_canonicalize_lowercases_on_windows,
    test_is_denied_true_for_skills_meta,
    test_is_denied_true_for_harness_agent,
    test_is_denied_true_for_writeback_self,
    test_is_denied_true_for_debate_trigger,
    test_is_denied_true_for_claude_md,
    test_is_denied_false_for_legit_skill,
    test_is_denied_true_for_empty_input,
    test_deny_prefixes_count,
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
