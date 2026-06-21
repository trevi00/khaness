#!/usr/bin/env python3
"""Tests for lib/stop_phrases.py — lazy-code-pattern detector for Edit/Write.

Audit note (2026-05-09): the lazy-code marker substrings inside test
fixture strings below are test INPUTS, not backlog items. They exist to
verify the detector fires on real-world patterns, and lib/stop_phrases.py
HOOK_SCRIPT_DIRS at line 23 suppresses runtime findings under
``.claude/scripts`` — this file is intentionally below that suppress
boundary so the production hook never flags it either.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _input(file_path: str, content: str, *, tool: str = "Write") -> dict:
    if tool == "Write":
        return {"file_path": file_path, "content": content}
    return {"file_path": file_path, "new_string": content}


def test_unsupported_tool_returns_empty():
    from lib.stop_phrases import check_stop_phrases
    assert check_stop_phrases("Read", {}) == []
    assert check_stop_phrases("Bash", {}) == []


def test_hook_script_dir_suppresses_findings():
    """Files under HOOK_SCRIPT_DIRS are skipped (they contain pattern defs)."""
    from lib.stop_phrases import check_stop_phrases
    # Use a non-marker fixture (Phase 2 future-work pattern) — still trips
    # a stop-phrase normally, but the dir suppression must short-circuit.
    inp = _input(
        "/home/user/.claude/scripts/handlers/some.py",
        "# Phase 2: future expansion\n" * 5,
    )
    assert check_stop_phrases("Write", inp) == []


def test_short_content_returns_empty():
    from lib.stop_phrases import check_stop_phrases
    inp = _input("/repo/src/foo.py", "tiny")
    assert check_stop_phrases("Write", inp) == []


def test_pattern_definition_file_skipped():
    """Content that looks like a regex pattern definition is suppressed."""
    from lib.stop_phrases import check_stop_phrases
    inp = _input(
        "/repo/src/lib_patterns.py",
        "PATTERNS = (re.compile(r'TODO: implement later'), 'msg')",
    )
    assert check_stop_phrases("Write", inp) == []


def test_incomplete_marker_pattern_detected():
    from lib.stop_phrases import check_stop_phrases
    inp = _input(
        "/repo/src/foo.py",
        "def foo():\n    # TODO: implement later\n    pass\n",
    )
    findings = check_stop_phrases("Write", inp)
    assert findings
    # Match the message produced by lib/stop_phrases.py without including
    # the literal marker word in this test's source (audit hygiene).
    assert any("지금 구현하세요" in f for f in findings)


def test_phase_2_comment_pattern_detected():
    from lib.stop_phrases import check_stop_phrases
    inp = _input(
        "/repo/src/foo.py",
        "def foo():\n    # Phase 2: future expansion\n    pass\n",
    )
    findings = check_stop_phrases("Write", inp)
    assert any("작업 미루기" in f for f in findings)


def test_quick_fix_pattern_detected():
    from lib.stop_phrases import check_stop_phrases
    inp = _input(
        "/repo/src/foo.py",
        "def foo():\n    # quick fix for the bug\n    return None\n",
    )
    findings = check_stop_phrases("Write", inp)
    assert any("근본 원인" in f for f in findings)


def test_temporary_workaround_pattern_detected():
    from lib.stop_phrases import check_stop_phrases
    inp = _input(
        "/repo/src/foo.py",
        "def foo():\n    # temporary workaround until V2\n    pass\n",
    )
    findings = check_stop_phrases("Write", inp)
    assert any("임시 해결책" in f for f in findings)


def test_blame_shifting_comment_detected():
    from lib.stop_phrases import check_stop_phrases
    inp = _input(
        "/repo/src/foo.py",
        "def foo():\n    # not caused by my change\n    return None\n",
    )
    findings = check_stop_phrases("Write", inp)
    assert any("책임 회피" in f for f in findings)


def test_removed_code_comment_detected():
    from lib.stop_phrases import check_stop_phrases
    inp = _input(
        "/repo/src/foo.py",
        "def foo():\n    # removed: old logic was here\n    return 1\n",
    )
    findings = check_stop_phrases("Write", inp)
    assert any("삭제 코드" in f for f in findings)


def test_clean_code_no_findings():
    from lib.stop_phrases import check_stop_phrases
    inp = _input(
        "/repo/src/foo.py",
        "def foo():\n    \"\"\"Compute the answer.\"\"\"\n    return 42\n",
    )
    assert check_stop_phrases("Write", inp) == []


def test_phase_21_not_false_positive():
    """[2-9](?!\\d) excludes multi-digit phase markers like Phase 21."""
    from lib.stop_phrases import check_stop_phrases
    inp = _input(
        "/repo/docs/changelog.md",
        "## Phase 21 — refactor complete\nAll items shipped.\n",
        tool="Write",
    )
    findings = check_stop_phrases("Write", inp)
    # 'Phase 21' must NOT trigger '작업 미루기' (which targets Phase 2-9)
    assert all("Phase" not in f or "미루" not in f for f in findings)


def test_multiedit_uses_new_string():
    from lib.stop_phrases import check_stop_phrases
    inp = {"file_path": "/repo/src/foo.py",
           "new_string": "def foo():\n    # temp hack pending real fix\n    pass\n"}
    findings = check_stop_phrases("MultiEdit", inp)
    assert findings


def test_edit_tool_uses_new_string_field():
    from lib.stop_phrases import check_stop_phrases
    inp = _input(
        "/repo/src/foo.py",
        "# temporary hack pending refactor",
        tool="Edit",
    )
    findings = check_stop_phrases("Edit", inp)
    assert any("임시" in f for f in findings)


TESTS = [
    test_unsupported_tool_returns_empty,
    test_hook_script_dir_suppresses_findings,
    test_short_content_returns_empty,
    test_pattern_definition_file_skipped,
    test_incomplete_marker_pattern_detected,
    test_phase_2_comment_pattern_detected,
    test_quick_fix_pattern_detected,
    test_temporary_workaround_pattern_detected,
    test_blame_shifting_comment_detected,
    test_removed_code_comment_detected,
    test_clean_code_no_findings,
    test_phase_21_not_false_positive,
    test_multiedit_uses_new_string,
    test_edit_tool_uses_new_string_field,
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
