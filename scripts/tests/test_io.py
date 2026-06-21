#!/usr/bin/env python3
"""Tests for lib/io.py — hook stdin/stdout JSON helpers.

io.py is a dep of 7 hook handlers (rationalization / learner / debate_trigger /
on_notification / mode_detector — all subprocess-invoked at runtime), so its
public surface was only transitively exercised. These direct unit tests close
the last zero-import gap in the lib audit.
"""
from __future__ import annotations

import io as _stdlib_io
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


class _StdinPatch:
    """Replace sys.stdin with a StringIO containing `text` for the duration."""

    def __init__(self, text: str):
        self._text = text
        self._saved = None

    def __enter__(self):
        self._saved = sys.stdin
        sys.stdin = _stdlib_io.StringIO(self._text)
        return self

    def __exit__(self, *exc):
        sys.stdin = self._saved


class _StdoutCapture:
    def __init__(self):
        self._saved = None
        self.buf = _stdlib_io.StringIO()

    def __enter__(self):
        self._saved = sys.stdout
        sys.stdout = self.buf
        return self

    def __exit__(self, *exc):
        sys.stdout = self._saved


def test_read_hook_input_returns_dict_for_valid_json():
    from lib.io import read_hook_input
    with _StdinPatch('{"event": "PreToolUse", "tool": "Bash"}'):
        data = read_hook_input()
    assert data == {"event": "PreToolUse", "tool": "Bash"}


def test_read_hook_input_empty_stdin_returns_empty_dict():
    from lib.io import read_hook_input
    with _StdinPatch(""):
        assert read_hook_input() == {}


def test_read_hook_input_whitespace_only_returns_empty_dict():
    from lib.io import read_hook_input
    with _StdinPatch("   \n\t  "):
        assert read_hook_input() == {}


def test_read_hook_input_malformed_json_returns_empty_dict():
    from lib.io import read_hook_input
    with _StdinPatch('{"unterminated":'):
        assert read_hook_input() == {}


def test_read_hook_input_non_dict_payload_returns_empty_dict():
    """Top-level array/string/number → fail-silent empty dict (hook contract)."""
    from lib.io import read_hook_input
    with _StdinPatch('[1, 2, 3]'):
        assert read_hook_input() == {}
    with _StdinPatch('"just a string"'):
        assert read_hook_input() == {}
    with _StdinPatch('42'):
        assert read_hook_input() == {}


def test_read_hook_input_korean_payload_decodes_utf8():
    from lib.io import read_hook_input
    with _StdinPatch('{"prompt": "안녕"}'):
        data = read_hook_input()
    assert data == {"prompt": "안녕"}


def test_write_hook_output_emits_json_line():
    from lib.io import write_hook_output
    with _StdoutCapture() as cap:
        write_hook_output({"a": 1, "b": [2, 3]})
    line = cap.buf.getvalue().rstrip("\n")
    assert json.loads(line) == {"a": 1, "b": [2, 3]}


def test_write_hook_output_empty_payload_is_no_op():
    from lib.io import write_hook_output
    with _StdoutCapture() as cap:
        write_hook_output({})
    assert cap.buf.getvalue() == ""


def test_write_hook_output_korean_payload_uses_utf8_not_escape():
    """ensure_ascii=False — Korean must stay raw, not \\uXXXX-escaped."""
    from lib.io import write_hook_output
    with _StdoutCapture() as cap:
        write_hook_output({"msg": "안녕"})
    raw = cap.buf.getvalue()
    assert "안녕" in raw
    assert "\\u" not in raw  # not escaped


def test_additional_context_wraps_user_prompt_submit():
    from lib.io import additional_context
    out = additional_context("hello world", "UserPromptSubmit")
    assert out == {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "hello world",
        }
    }


def test_additional_context_wraps_all_four_event_kinds():
    """The 4 events that wrap inside hookSpecificOutput (Stop is excluded)."""
    from lib.io import additional_context
    for ev in ("UserPromptSubmit", "PreToolUse", "PostToolUse", "SessionStart"):
        out = additional_context("x", ev)
        assert out["hookSpecificOutput"]["hookEventName"] == ev
        assert out["hookSpecificOutput"]["additionalContext"] == "x"


def test_stop_decision_default_emits_block_decision():
    from lib.io import stop_decision
    out = stop_decision("test reason")
    assert out["decision"] == "block"
    assert out["reason"] == "test reason"
    assert "continue" not in out


def test_stop_decision_no_block_omits_decision():
    from lib.io import stop_decision
    out = stop_decision("ignored", block=False)
    assert "decision" not in out
    assert "reason" not in out


def test_stop_decision_continue_false_with_stop_reason():
    from lib.io import stop_decision
    out = stop_decision("test", continue_=False, stop_reason="user requested halt")
    assert out["continue"] is False
    assert out["stopReason"] == "user requested halt"


def test_stop_decision_continue_false_without_stop_reason_omits_field():
    from lib.io import stop_decision
    out = stop_decision("test", continue_=False, stop_reason=None)
    assert out["continue"] is False
    assert "stopReason" not in out


def test_pre_tool_deny_emits_both_channels():
    """deny must surface BOTH top-level decision/reason AND hookSpecificOutput."""
    from lib.io import pre_tool_deny
    out = pre_tool_deny("forbidden tool")
    assert out["decision"] == "block"
    assert out["reason"] == "forbidden tool"
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "deny"
    assert hso["permissionDecisionReason"] == "forbidden tool"


def test_pre_tool_updated_input_wraps_input_and_note():
    from lib.io import pre_tool_updated_input
    out = pre_tool_updated_input({"command": "ls -la"}, "added -la flag")
    assert out == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": {"command": "ls -la"},
            "additionalContext": "added -la flag",
        }
    }


TESTS = [
    test_read_hook_input_returns_dict_for_valid_json,
    test_read_hook_input_empty_stdin_returns_empty_dict,
    test_read_hook_input_whitespace_only_returns_empty_dict,
    test_read_hook_input_malformed_json_returns_empty_dict,
    test_read_hook_input_non_dict_payload_returns_empty_dict,
    test_read_hook_input_korean_payload_decodes_utf8,
    test_write_hook_output_emits_json_line,
    test_write_hook_output_empty_payload_is_no_op,
    test_write_hook_output_korean_payload_uses_utf8_not_escape,
    test_additional_context_wraps_user_prompt_submit,
    test_additional_context_wraps_all_four_event_kinds,
    test_stop_decision_default_emits_block_decision,
    test_stop_decision_no_block_omits_decision,
    test_stop_decision_continue_false_with_stop_reason,
    test_stop_decision_continue_false_without_stop_reason_omits_field,
    test_pre_tool_deny_emits_both_channels,
    test_pre_tool_updated_input_wraps_input_and_note,
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
