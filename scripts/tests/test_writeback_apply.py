#!/usr/bin/env python3
"""Unit tests for lib/writeback_apply.py — D2 (apply_algorithm) + D6
(invocation_contract) per debate-1778236168-53dedd.

Coverage:
  - D6: validate_operator_context rejects None/wrong-type/synthesized
  - D6: APPLY_MODE constant present and equal 'operator_initiated_only'
  - D2: _parse_hunk_header parses valid headers, defaults count=1, raises
  - D2: apply_hunk_to_text matches context+removed slice, splices new
  - D2: apply_hunk_to_text raises HUNK_MISMATCH on context drift
  - D2: apply_hunk_to_text handles pure insertion (old_count=0)
  - D2: apply_edits_to_text applies multi-hunk in reverse line order
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


# ---- D6 invocation_contract ----

def test_apply_mode_constant_locked():
    from lib.writeback_apply import APPLY_MODE
    assert APPLY_MODE == "operator_initiated_only"


def test_validate_operator_context_accepts_real_operator():
    from lib.writeback_apply import validate_operator_context
    with tempfile.TemporaryDirectory() as td:
        ctx = {"pid": 1234, "sid": "orch-test-aaa", "cwd": td}
        validate_operator_context(ctx)  # must not raise


def test_validate_operator_context_rejects_non_dict():
    from lib.writeback_apply import (
        validate_operator_context, InvalidOperatorContext,
    )
    for bad in (None, "string", [], 42):
        try:
            validate_operator_context(bad)  # type: ignore[arg-type]
        except InvalidOperatorContext:
            continue
        raise AssertionError(f"expected InvalidOperatorContext for {bad!r}")


def test_validate_operator_context_rejects_synthesized_pid():
    from lib.writeback_apply import (
        validate_operator_context, InvalidOperatorContext,
    )
    with tempfile.TemporaryDirectory() as td:
        for bad_pid in (0, -1, None, "1234"):
            ctx = {"pid": bad_pid, "sid": "x", "cwd": td}
            try:
                validate_operator_context(ctx)
            except InvalidOperatorContext:
                continue
            raise AssertionError(f"expected reject for pid={bad_pid!r}")


def test_validate_operator_context_rejects_empty_sid():
    from lib.writeback_apply import (
        validate_operator_context, InvalidOperatorContext,
    )
    with tempfile.TemporaryDirectory() as td:
        for bad_sid in (None, "", 42):
            ctx = {"pid": 1, "sid": bad_sid, "cwd": td}
            try:
                validate_operator_context(ctx)
            except InvalidOperatorContext:
                continue
            raise AssertionError(f"expected reject for sid={bad_sid!r}")


def test_validate_operator_context_rejects_relative_or_missing_cwd():
    from lib.writeback_apply import (
        validate_operator_context, InvalidOperatorContext,
    )
    cases = [
        {"pid": 1, "sid": "x", "cwd": ""},                  # empty
        {"pid": 1, "sid": "x", "cwd": "relative/path"},     # relative
        {"pid": 1, "sid": "x", "cwd": None},                # None
        {"pid": 1, "sid": "x", "cwd": "/no/such/dir/xyz"},  # absent
    ]
    for ctx in cases:
        try:
            validate_operator_context(ctx)
        except InvalidOperatorContext:
            continue
        raise AssertionError(f"expected reject for cwd={ctx['cwd']!r}")


# ---- D2 apply_algorithm ----

def test_parse_hunk_header_full_form():
    from lib.writeback_apply import _parse_hunk_header
    a = _parse_hunk_header("@@ -10,5 +12,7 @@")
    assert a.old_start == 10 and a.old_count == 5
    assert a.new_start == 12 and a.new_count == 7


def test_parse_hunk_header_count_defaults_to_1():
    from lib.writeback_apply import _parse_hunk_header
    a = _parse_hunk_header("@@ -3 +3 @@")
    assert a.old_count == 1 and a.new_count == 1


def test_parse_hunk_header_with_function_name_tail():
    from lib.writeback_apply import _parse_hunk_header
    a = _parse_hunk_header("@@ -1,2 +1,3 @@ def foo():")
    assert a.old_start == 1 and a.new_start == 1


def test_parse_hunk_header_rejects_malformed():
    from lib.writeback_apply import _parse_hunk_header
    for bad in ("not a header", "@@ +1,1 -1,1 @@", "@@ -x,y +z,w @@"):
        try:
            _parse_hunk_header(bad)
        except (ValueError,):
            continue
        raise AssertionError(f"expected raise for {bad!r}")


def test_apply_hunk_to_text_simple_replacement():
    """Replace line 2 (B). Add lines after it."""
    from lib.writeback_apply import apply_hunk_to_text
    target = "A\nB\nC"
    body = [
        " A",   # context: keep
        "-B",   # removed
        "+B-new",
        "+inserted",
        " C",   # context: keep
    ]
    out = apply_hunk_to_text(target, "@@ -1,3 +1,4 @@", body)
    assert out == "A\nB-new\ninserted\nC"


def test_apply_hunk_to_text_pure_insertion():
    """old_count=0 → insert before old_start, no removed lines."""
    from lib.writeback_apply import apply_hunk_to_text
    target = "X\nY\nZ"
    body = ["+A", "+B"]
    out = apply_hunk_to_text(target, "@@ -2,0 +2,2 @@", body)
    assert out == "X\nA\nB\nY\nZ"


def test_apply_hunk_to_text_context_only_no_change():
    """Context-only hunk (no +/-): result equals input but slice validated."""
    from lib.writeback_apply import apply_hunk_to_text
    target = "A\nB\nC"
    body = [" A", " B", " C"]
    out = apply_hunk_to_text(target, "@@ -1,3 +1,3 @@", body)
    assert out == target


def test_apply_hunk_to_text_raises_hunk_mismatch():
    from lib.writeback_apply import apply_hunk_to_text, ApplyError
    target = "A\nDIFFERENT\nC"
    body = [" A", "-B", "+B-new", " C"]
    try:
        apply_hunk_to_text(target, "@@ -1,3 +1,3 @@", body)
    except ApplyError as e:
        assert e.kind == "HUNK_MISMATCH"
        return
    raise AssertionError("expected ApplyError(HUNK_MISMATCH)")


def test_apply_hunk_to_text_ignores_no_newline_marker():
    from lib.writeback_apply import apply_hunk_to_text
    target = "A\nB"
    body = [
        " A",
        "-B",
        "+B-new",
        "\\ No newline at end of file",
    ]
    out = apply_hunk_to_text(target, "@@ -1,2 +1,2 @@", body)
    assert out == "A\nB-new"


def test_apply_hunk_to_text_raises_on_invalid_prefix():
    from lib.writeback_apply import apply_hunk_to_text
    target = "A\nB"
    body = [" A", "?bad-prefix"]
    try:
        apply_hunk_to_text(target, "@@ -1,2 +1,2 @@", body)
    except ValueError:
        return
    raise AssertionError("expected ValueError on invalid prefix")


def test_apply_edits_to_text_reverse_order_preserves_anchors():
    """Two non-overlapping hunks; reverse-order apply keeps both anchors valid."""
    from lib.writeback_apply import apply_edits_to_text
    target = "A\nB\nC\nD\nE"
    edits = [
        # Edit 1: line 2 B → B-new (1 added)
        ("@@ -1,3 +1,3 @@", [" A", "-B", "+B-new", " C"]),
        # Edit 2: line 5 E → E-new
        ("@@ -4,2 +4,2 @@", [" D", "-E", "+E-new"]),
    ]
    out = apply_edits_to_text(target, edits)
    assert out == "A\nB-new\nC\nD\nE-new"


def test_apply_edits_to_text_empty_returns_unchanged():
    from lib.writeback_apply import apply_edits_to_text
    assert apply_edits_to_text("X\nY", []) == "X\nY"


def test_apply_edits_to_text_first_failure_preserves_original():
    """If a later (lower-line) hunk fails, the function raises and the
    caller's original target_text is untouched (function returns nothing)."""
    from lib.writeback_apply import apply_edits_to_text, ApplyError
    target = "A\nB\nC"
    edits = [
        ("@@ -2,1 +2,1 @@", [" WRONG"]),  # context drift on line 2 → fail
    ]
    try:
        apply_edits_to_text(target, edits)
    except ApplyError as e:
        assert e.kind == "HUNK_MISMATCH"
        return
    raise AssertionError("expected ApplyError")


TESTS = [
    test_apply_mode_constant_locked,
    test_validate_operator_context_accepts_real_operator,
    test_validate_operator_context_rejects_non_dict,
    test_validate_operator_context_rejects_synthesized_pid,
    test_validate_operator_context_rejects_empty_sid,
    test_validate_operator_context_rejects_relative_or_missing_cwd,
    test_parse_hunk_header_full_form,
    test_parse_hunk_header_count_defaults_to_1,
    test_parse_hunk_header_with_function_name_tail,
    test_parse_hunk_header_rejects_malformed,
    test_apply_hunk_to_text_simple_replacement,
    test_apply_hunk_to_text_pure_insertion,
    test_apply_hunk_to_text_context_only_no_change,
    test_apply_hunk_to_text_raises_hunk_mismatch,
    test_apply_hunk_to_text_ignores_no_newline_marker,
    test_apply_hunk_to_text_raises_on_invalid_prefix,
    test_apply_edits_to_text_reverse_order_preserves_anchors,
    test_apply_edits_to_text_empty_returns_unchanged,
    test_apply_edits_to_text_first_failure_preserves_original,
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
