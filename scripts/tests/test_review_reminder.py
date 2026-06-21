#!/usr/bin/env python3
"""Unit tests for lib/review_reminder.py."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import review_reminder as rr  # noqa: E402


def test_base_checks_count():
    assert len(rr.BASE_CHECKS) == 4


def test_lang_checks_includes_python():
    assert ".py" in rr.LANG_CHECKS
    assert "타입 힌트" in rr.LANG_CHECKS[".py"]


def test_lang_checks_includes_typescript_variants():
    for ext in (".js", ".ts", ".tsx", ".jsx"):
        assert ext in rr.LANG_CHECKS
        assert "비동기" in rr.LANG_CHECKS[ext]


def test_get_review_context_wraps_in_tag():
    msg = rr.get_review_context("Write", "foo.py", "")
    assert msg.startswith("<post-tool-review>")
    assert msg.endswith("</post-tool-review>")


def test_get_review_context_includes_filename():
    msg = rr.get_review_context("Edit", "src/utils/foo.py", "")
    assert "(foo.py)" in msg
    # basename only — full path NOT in title line
    assert "src/utils/foo.py" not in msg.split("\n")[1]


def test_get_review_context_includes_base_checks():
    msg = rr.get_review_context("Edit", "foo.py", "")
    for check in rr.BASE_CHECKS:
        assert check in msg


def test_get_review_context_python_appends_type_hint_check():
    msg = rr.get_review_context("Edit", "foo.py", "")
    assert "타입 힌트" in msg


def test_get_review_context_unknown_ext_no_lang_check():
    msg = rr.get_review_context("Edit", "foo.xyz", "")
    # No additional lang check
    assert "타입 힌트" not in msg
    assert "비동기" not in msg
    assert "borrow checker" not in msg


def test_write_appends_consistency_check():
    msg = rr.get_review_context("Write", "foo.py", "")
    assert "기존 코드와의 일관성" in msg


def test_edit_does_not_append_consistency_check():
    msg = rr.get_review_context("Edit", "foo.py", "")
    assert "기존 코드와의 일관성" not in msg


def test_recent_changes_section_only_when_provided():
    msg_empty = rr.get_review_context("Edit", "foo.py", "")
    msg_with = rr.get_review_context("Edit", "foo.py", "- entry\n- entry2")
    assert "최근 수정 기록" not in msg_empty
    assert "최근 수정 기록" in msg_with
    assert "- entry2" in msg_with


def test_get_review_context_handles_empty_path():
    msg = rr.get_review_context("Edit", "", "")
    # Should not crash
    assert "post-tool-review" in msg


def test_get_error_recovery_hint_format():
    msg = rr.get_error_recovery_hint()
    assert msg.startswith("<error-recovery>")
    assert msg.endswith("</error-recovery>")
    assert "에러 복구 가이드" in msg


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
