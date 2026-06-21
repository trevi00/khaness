#!/usr/bin/env python3
"""Unit tests for lib/writeback_parser.py — D1 diff-only unified format parser."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.writeback_parser import (  # noqa: E402
    Edit,
    ParsedProposal,
    RejectReason,
    parse_proposal,
    parse_unified_diff,
)


# ---- parse_unified_diff ----

def test_parse_unified_diff_simple_hunk():
    diff = (
        "--- a/skills/_common/test.md\n"
        "+++ b/skills/_common/test.md\n"
        "@@ -1,3 +1,4 @@\n"
        " ## Gotchas\n"
        " - existing rule\n"
        "+- NEW rule from research\n"
        " - other existing\n"
    )
    edits = parse_unified_diff(diff)
    assert len(edits) == 1
    assert isinstance(edits[0], Edit)
    assert edits[0].target_path == "skills/_common/test.md"
    assert edits[0].hunk_header.startswith("@@")


def test_parse_unified_diff_strips_b_prefix():
    diff = (
        "--- a/foo.md\n"
        "+++ b/foo.md\n"
        "@@ -1 +1 @@\n"
        "+new\n"
    )
    edits = parse_unified_diff(diff)
    assert edits[0].target_path == "foo.md"


def test_parse_unified_diff_raises_on_empty():
    try:
        parse_unified_diff("")
    except ValueError:
        return
    raise AssertionError("expected ValueError on empty diff")


def test_parse_unified_diff_raises_on_no_hunks():
    try:
        parse_unified_diff("not a diff at all")
    except ValueError:
        return
    raise AssertionError("expected ValueError when no hunks present")


def test_parse_unified_diff_multi_hunk():
    diff = (
        "--- a/foo.md\n"
        "+++ b/foo.md\n"
        "@@ -1 +1 @@\n"
        "+a\n"
        "@@ -10 +11 @@\n"
        "+b\n"
    )
    edits = parse_unified_diff(diff)
    assert len(edits) == 2


# ---- parse_proposal end-to-end ----

def _write_strike_artifact(
    path: Path, *, with_diff: bool = True, with_proposal_section: bool = True,
    diff_target_skill: str | None = None,
) -> None:
    target = diff_target_skill or "/home/user/.claude/skills/_common/test.md"
    section = "## Proposed permanent change\n\n" if with_proposal_section else ""
    diff_block = ""
    if with_diff:
        diff_block = (
            "```diff\n"
            f"--- a/{target}\n"
            f"+++ b/{target}\n"
            "@@ -1,2 +1,3 @@\n"
            " ## Gotchas\n"
            "+- NEW gotcha rule\n"
            " - existing\n"
            "```\n"
        )
    body = (
        "# Strike abc123 — example\n\n"
        "## Root cause\nsomething\n\n"
        f"{section}{diff_block}\n"
        "## Verdict\naccepted_change\n"
    )
    path.write_text(body, encoding="utf-8")


def test_parse_proposal_success():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "abc123.md"
        _write_strike_artifact(p)
        result = parse_proposal(p)
        assert isinstance(result, ParsedProposal)
        assert result.fingerprint == "abc123"
        assert len(result.edits) == 1


def test_parse_proposal_no_proposal_section():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "x.md"
        _write_strike_artifact(p, with_proposal_section=False)
        result = parse_proposal(p)
        assert result == RejectReason.NO_PROPOSAL_SECTION


def test_parse_proposal_unsupported_grammar_when_no_diff_fence():
    """Section exists but no ```diff fence → insertion-spec form → REJECTED."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "x.md"
        _write_strike_artifact(p, with_diff=False)
        result = parse_proposal(p)
        assert result == RejectReason.UNSUPPORTED_GRAMMAR


def test_parse_proposal_self_modify_denied():
    """Diff targets a denylisted path → SELF_MODIFY_DENIED."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "x.md"
        _write_strike_artifact(
            p, diff_target_skill=str(Path.home() / ".claude" / "skills" / "_meta" / "forbidden.md")
        )
        result = parse_proposal(p)
        assert result == RejectReason.SELF_MODIFY_DENIED


def test_parse_proposal_invalid_target():
    """Diff targets path outside skills/ → INVALID_TARGET."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "x.md"
        _write_strike_artifact(
            p, diff_target_skill="/some/random/path.md"
        )
        result = parse_proposal(p)
        assert result == RejectReason.INVALID_TARGET


def test_parse_proposal_no_gotchas_anchor():
    """Diff modifies a skill but not the ## Gotchas section."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "x.md"
        target = "/home/user/.claude/skills/_common/test.md"
        body = (
            "## Proposed permanent change\n\n"
            "```diff\n"
            f"--- a/{target}\n"
            f"+++ b/{target}\n"
            "@@ -1 +1 @@\n"
            "+- random change without Gotchas header\n"
            "```\n"
        )
        p.write_text(body, encoding="utf-8")
        result = parse_proposal(p)
        assert result == RejectReason.NO_GOTCHAS_ANCHOR


def test_parse_proposal_missing_file():
    result = parse_proposal("/nonexistent/path.md")
    assert result == RejectReason.NO_PROPOSAL_SECTION


TESTS = [
    test_parse_unified_diff_simple_hunk,
    test_parse_unified_diff_strips_b_prefix,
    test_parse_unified_diff_raises_on_empty,
    test_parse_unified_diff_raises_on_no_hunks,
    test_parse_unified_diff_multi_hunk,
    test_parse_proposal_success,
    test_parse_proposal_no_proposal_section,
    test_parse_proposal_unsupported_grammar_when_no_diff_fence,
    test_parse_proposal_self_modify_denied,
    test_parse_proposal_invalid_target,
    test_parse_proposal_no_gotchas_anchor,
    test_parse_proposal_missing_file,
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
