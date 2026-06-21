#!/usr/bin/env python3
"""Unit tests for lib/bash_tool_routing.py."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import bash_tool_routing as btr  # noqa: E402


def test_rules_count():
    assert len(btr.BASH_TOOL_ROUTING_RULES) == 5


def test_rules_have_expected_tools():
    tools = {r["tool"] for r in btr.BASH_TOOL_ROUTING_RULES}
    assert tools == {"Grep", "Glob", "Read", "Edit", "Write"}


def test_grep_matches_grep_command():
    msg = btr.detect_tool_routing_feedback("grep foo bar.txt")
    assert msg is not None
    assert "Grep" in msg


def test_rg_matches():
    msg = btr.detect_tool_routing_feedback("rg pattern")
    assert msg is not None
    assert "Grep" in msg


def test_find_matches_glob():
    msg = btr.detect_tool_routing_feedback("find . -name '*.py'")
    assert msg is not None
    assert "Glob" in msg


def test_ls_recursive_matches_glob():
    msg = btr.detect_tool_routing_feedback("ls -R /tmp")
    assert msg is not None
    assert "Glob" in msg


def test_cat_matches_read():
    msg = btr.detect_tool_routing_feedback("cat foo.txt")
    assert msg is not None
    assert "Read" in msg


def test_head_matches_read():
    msg = btr.detect_tool_routing_feedback("head -n 10 foo.txt")
    assert msg is not None
    assert "Read" in msg


def test_sed_inplace_matches_edit():
    msg = btr.detect_tool_routing_feedback("sed -i 's/a/b/' foo.txt")
    assert msg is not None
    assert "Edit" in msg


def test_echo_redirect_matches_write():
    msg = btr.detect_tool_routing_feedback("echo hello > foo.txt")
    assert msg is not None
    assert "Write" in msg


def test_echo_append_still_matches_due_to_greedy():
    """echo >> append: regex .*>(?!>) is greedy and finds the SECOND > whose
    next char is not >, so it still matches Write rule. This is acceptable —
    even append-via-echo is better done via Edit/Write tool."""
    msg = btr.detect_tool_routing_feedback("echo hello >> foo.txt")
    # Behavior documented: appendalso flagged. Test asserts current behavior.
    assert msg is not None
    assert "Write" in msg


def test_safe_command_returns_none():
    assert btr.detect_tool_routing_feedback("git status") is None
    assert btr.detect_tool_routing_feedback("npm test") is None


def test_empty_command_returns_none():
    assert btr.detect_tool_routing_feedback("") is None
    assert btr.detect_tool_routing_feedback(None) is None


def test_message_wrapped_in_tag():
    msg = btr.detect_tool_routing_feedback("grep foo")
    assert msg.startswith("<tool-routing-feedback>")
    assert msg.endswith("</tool-routing-feedback>")


def test_first_match_wins():
    """Both grep AND find in same command — Grep rule (first) wins."""
    msg = btr.detect_tool_routing_feedback("grep foo | find .")
    assert "Grep" in msg
    # Glob message should not be in the same response
    glob_msg_substring = "Glob 도구"
    assert glob_msg_substring not in msg


def test_heredoc_cat_not_matched():
    """E8 false-positive guard: cat <<'EOF' ... EOF heredoc is a string literal,
    not a file read. Must not trigger the Read tool routing rule.
    See ~/.claude/skills/_common/repeat-error-tracker.md E8."""
    cmd = "git commit -m \"$(cat <<'EOF'\nrelease notes\nEOF\n)\""
    assert btr.detect_tool_routing_feedback(cmd) is None


def test_heredoc_body_words_not_matched():
    """E8 false-positive guard: words like 'grep'/'head'/'tail'/'find'/'cat'
    appearing inside a heredoc body (commit message prose) must be stripped
    before tool routing checks — they are string literals, not commands."""
    cmd = (
        "git commit -m \"$(cat <<'EOF'\n"
        "fix: use grep result; head of file shows tail end\n"
        "search via find; cat heredoc allowed\n"
        "EOF\n"
        ")\""
    )
    assert btr.detect_tool_routing_feedback(cmd) is None


def test_heredoc_with_real_grep_outside_still_matched():
    """Heredoc-stripping must not mask a real grep usage OUTSIDE the heredoc.
    The Grep rule should still fire for the actual grep command."""
    cmd = (
        "grep needle file && git commit -m \"$(cat <<'EOF'\n"
        "added\n"
        "EOF\n"
        ")\""
    )
    msg = btr.detect_tool_routing_feedback(cmd)
    assert msg is not None
    assert "Grep" in msg


def test_heredoc_dash_variant():
    """`cat <<-EOF` (dash variant for indented heredocs) must also be stripped."""
    cmd = "cat <<-END\n\thead of foo\n\tEND"
    assert btr.detect_tool_routing_feedback(cmd) is None


def test_dash_m_double_quoted_body_not_matched():
    """E8 2nd-pass guard: `-m "..."` body is a commit-message string literal,
    not a shell command. Words inside must not trigger tool routing."""
    cmd = 'git commit -m "fix: use grep result and tail of file"'
    assert btr.detect_tool_routing_feedback(cmd) is None


def test_dash_m_single_quoted_body_not_matched():
    """Same guard for single-quoted bodies."""
    cmd = "git commit -m 'fix: head of foo and find bar'"
    assert btr.detect_tool_routing_feedback(cmd) is None


def test_long_message_flag_not_matched():
    """`--message "..."` (long form) body also stripped."""
    cmd = 'git commit --message "use grep tool and head"'
    assert btr.detect_tool_routing_feedback(cmd) is None


def test_dash_m_with_escaped_quotes_not_matched():
    """`-m "she said \\"grep is bad\\""` — backslash-escaped quotes inside body."""
    cmd = 'git commit -m "she said \\"use grep here\\""'
    assert btr.detect_tool_routing_feedback(cmd) is None


def test_real_grep_outside_dash_m_still_matched():
    """`-m "..."` strip must not mask a real grep usage OUTSIDE the message body."""
    cmd = 'grep needle file && git commit -m "added feature"'
    msg = btr.detect_tool_routing_feedback(cmd)
    assert msg is not None
    assert "Grep" in msg


def test_multiple_dash_m_args_all_stripped():
    """Multiple `-m`/`-m`/`-m` args (multi-paragraph commit) all stripped."""
    cmd = (
        'git commit -m "title with grep" '
        '-m "body with head and tail" '
        '-m "footer with find"'
    )
    assert btr.detect_tool_routing_feedback(cmd) is None


# --- E8 3rd-pass fix: echo quoted body strip ---

def test_echo_with_grep_word_in_double_quotes_not_flagged():
    """`echo "use grep here"` prose must not trigger Grep rule."""
    cmd = 'echo "use grep here"'
    assert btr.detect_tool_routing_feedback(cmd) is None


def test_echo_with_head_tail_words_in_single_quotes_not_flagged():
    """`echo '...head...tail...find...'` prose must not trigger any rule."""
    cmd = "echo 'reading head and tail of file via find'"
    assert btr.detect_tool_routing_feedback(cmd) is None


def test_echo_with_redirect_still_matches_write_rule():
    """`echo "..." > file` must still match Write rule (E8 doesn't mask redirect)."""
    cmd = 'echo "hello world" > out.txt'
    msg = btr.detect_tool_routing_feedback(cmd)
    assert msg is not None
    assert "Write" in msg


def test_echo_with_append_redirect_body_stripped_no_grep_false_positive():
    """`echo ">> redirected text with grep here"` — body stripped regardless of redirect.

    Note: the Write rule (`\\becho\\b.*>(?!>)`) can still match `echo "..." >> file`
    via regex backtracking on `>>` — that is an independent Write-rule behavior
    out of E8 3rd-pass scope. This test asserts only that the echo body
    `grep`/`head`/`tail` words are stripped (no Grep/Read false positive).
    """
    cmd = 'echo "append using grep tool" >> out.txt'
    msg = btr.detect_tool_routing_feedback(cmd)
    # Write rule may or may not match (>> backtracking is out of scope);
    # what must NOT happen: a Grep/Read rule trigger from body prose.
    if msg is not None:
        assert "Grep" not in msg, "echo body prose 'grep' must be stripped"
        assert "Read" not in msg, "echo body prose 'head'/'tail' must be stripped"


def test_real_grep_outside_echo_still_matched():
    """`echo "..."` strip must not mask a real grep usage outside the echo body."""
    cmd = 'grep needle file && echo "done with the search"'
    msg = btr.detect_tool_routing_feedback(cmd)
    assert msg is not None
    assert "Grep" in msg


def test_echo_with_escaped_quotes_stripped():
    """`echo "he said \\"grep\\""` backslash-escaped quotes inside body — strip works."""
    cmd = 'echo "he said \\"use grep\\" earlier"'
    assert btr.detect_tool_routing_feedback(cmd) is None


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
