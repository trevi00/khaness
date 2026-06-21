#!/usr/bin/env python3
"""Tests for lib/agent_tool_audit.py — closes citation drift audit residual."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


import contextlib


@contextlib.contextmanager
def _redirect_agents_dir(tmp: Path):
    """Context manager: redirect _AGENTS_DIR for the block, restore after.

    Module-global mutation persists across tests if not restored — the
    real-frontmatter tests (which need _AGENTS_DIR pointing at the actual
    repo agents/) would silently fail when run after a redirect test.
    """
    from lib import agent_tool_audit as M
    original = M._AGENTS_DIR
    M._AGENTS_DIR = tmp
    try:
        yield
    finally:
        M._AGENTS_DIR = original


def _write_agent(tmp: Path, name: str, body: str) -> Path:
    path = tmp / f"{name}.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_expected_tools_real_harness_critic_includes_webfetch():
    """Live check against the actual repo: harness-critic must declare WebFetch
    (citation integrity contract per CLAUDE.md W19.1.1)."""
    from lib.agent_tool_audit import expected_tools
    tools = expected_tools("harness-critic")
    assert "WebFetch" in tools, (
        f"harness-critic frontmatter must declare WebFetch; got {tools}"
    )


def test_expected_tools_real_harness_planner_includes_websearch_and_webfetch():
    from lib.agent_tool_audit import expected_tools
    tools = expected_tools("harness-planner")
    assert "WebSearch" in tools
    assert "WebFetch" in tools


def test_expected_tools_real_harness_architect_includes_webfetch():
    from lib.agent_tool_audit import expected_tools
    tools = expected_tools("harness-architect")
    assert "WebFetch" in tools


def test_expected_tools_returns_empty_for_missing_agent():
    from lib.agent_tool_audit import expected_tools
    assert expected_tools("nonexistent-agent-xyz") == set()


def test_expected_tools_parses_comma_separated():
    with tempfile.TemporaryDirectory() as td:
        with _redirect_agents_dir(Path(td)):
            _write_agent(
                Path(td), "test-agent",
                "---\nname: test-agent\ntools: Read, Grep, Glob, WebFetch\n---\nbody\n",
            )
            from lib.agent_tool_audit import expected_tools
            assert expected_tools("test-agent") == {"Read", "Grep", "Glob", "WebFetch"}


def test_expected_tools_handles_no_tools_field():
    with tempfile.TemporaryDirectory() as td:
        with _redirect_agents_dir(Path(td)):
            _write_agent(Path(td), "test-agent", "---\nname: test-agent\n---\nbody\n")
            from lib.agent_tool_audit import expected_tools
            assert expected_tools("test-agent") == set()


def test_expected_tools_strips_whitespace():
    with tempfile.TemporaryDirectory() as td:
        with _redirect_agents_dir(Path(td)):
            _write_agent(
                Path(td), "test-agent",
                "---\ntools:   Read , Grep ,  WebFetch  \n---\nbody",
            )
            from lib.agent_tool_audit import expected_tools
            assert expected_tools("test-agent") == {"Read", "Grep", "WebFetch"}


def test_verify_self_report_consistency_detects_mismatch():
    """Critic claims WebFetch unavailable but frontmatter declares it → flag."""
    from lib.agent_tool_audit import verify_self_report_consistency
    mismatches = verify_self_report_consistency(
        "harness-critic",
        self_reported_missing=["WebFetch"],
    )
    assert mismatches == ["WebFetch"]


def test_verify_self_report_consistency_no_mismatch_for_truly_missing():
    """Critic claims a tool unavailable that's NOT in frontmatter → no flag."""
    from lib.agent_tool_audit import verify_self_report_consistency
    mismatches = verify_self_report_consistency(
        "harness-critic",
        self_reported_missing=["Bash"],  # not in harness-critic frontmatter
    )
    assert mismatches == []


def test_verify_self_report_consistency_multiple_tools():
    from lib.agent_tool_audit import verify_self_report_consistency
    mismatches = verify_self_report_consistency(
        "harness-planner",
        self_reported_missing=["WebSearch", "WebFetch", "Bash"],
    )
    # WebSearch + WebFetch are in planner frontmatter; Bash is not
    assert sorted(mismatches) == ["WebFetch", "WebSearch"]


def test_verify_self_report_consistency_empty_input():
    from lib.agent_tool_audit import verify_self_report_consistency
    assert verify_self_report_consistency(
        "harness-critic", self_reported_missing=[],
    ) == []


def test_verify_self_report_consistency_unknown_agent_no_crash():
    from lib.agent_tool_audit import verify_self_report_consistency
    # Unknown agent = empty expected set → empty mismatches
    assert verify_self_report_consistency(
        "nonexistent-agent", self_reported_missing=["WebFetch"],
    ) == []


def test_render_advisory_empty_when_no_mismatches():
    from lib.agent_tool_audit import render_advisory
    assert render_advisory("harness-critic", []) == ""


def test_render_advisory_format():
    from lib.agent_tool_audit import render_advisory
    msg = render_advisory("harness-critic", ["WebFetch"])
    assert "[self-report-mismatch]" in msg
    assert "harness-critic" in msg
    assert "WebFetch" in msg


def test_classify_severity_clean_when_no_mismatch():
    from lib.agent_tool_audit import classify_severity
    assert classify_severity([], has_research_citations=False) == "clean"
    assert classify_severity([], has_research_citations=True) == "clean"


def test_classify_severity_advisory_when_no_citations():
    """Mismatch present but no citations claimed verified → advisory only."""
    from lib.agent_tool_audit import classify_severity
    assert classify_severity(["WebFetch"], has_research_citations=False) == "advisory"


def test_classify_severity_invalidate_when_citations_present():
    """Mismatch + citations claimed verified → verification path may have
    been silently skipped → caller must treat verdict as rejected."""
    from lib.agent_tool_audit import classify_severity
    assert classify_severity(["WebFetch"], has_research_citations=True) == "invalidate"


def test_render_advisory_invalidate_message_distinct():
    """The invalidate-severity advisory must visually distinguish itself
    so an operator skim can route the gen accordingly."""
    from lib.agent_tool_audit import render_advisory
    advisory_msg = render_advisory("harness-critic", ["WebFetch"], severity="advisory")
    invalidate_msg = render_advisory("harness-critic", ["WebFetch"], severity="invalidate")
    assert "INVALIDATE" in invalidate_msg
    assert "INVALIDATE" not in advisory_msg
    assert "CANNOT" in invalidate_msg
    # Both must still anchor on the agent + mismatch list
    for msg in (advisory_msg, invalidate_msg):
        assert "harness-critic" in msg
        assert "WebFetch" in msg


def test_render_advisory_clean_severity_emits_empty_string():
    """Even with a non-empty mismatch list, severity=clean → empty advisory.
    (Defensive — callers shouldn't call render with clean+mismatches, but
    if they do, we don't surface a misleading message.)"""
    from lib.agent_tool_audit import render_advisory
    assert render_advisory("harness-critic", ["WebFetch"], severity="clean") == ""


# ---------- check_overclaim (양방향 audit) ----------

def test_check_overclaim_detects_undeclared_tool():
    """Critic claims using Bash but harness-critic frontmatter does not
    declare Bash → over-claim flagged."""
    from lib.agent_tool_audit import check_overclaim
    result = check_overclaim("harness-critic", self_reported_used=["Bash"])
    assert result == ["Bash"]


def test_check_overclaim_no_flag_for_declared_tool():
    from lib.agent_tool_audit import check_overclaim
    # WebFetch IS declared in harness-critic frontmatter → no flag
    result = check_overclaim("harness-critic", self_reported_used=["WebFetch"])
    assert result == []


def test_check_overclaim_multiple_undeclared():
    from lib.agent_tool_audit import check_overclaim
    result = check_overclaim(
        "harness-critic",
        self_reported_used=["Bash", "Write", "Edit", "WebFetch", "NotebookEdit"],
    )
    # Bash / Write / Edit / NotebookEdit all undeclared in harness-critic
    # (frontmatter is Read,Grep,Glob,WebFetch). WebFetch is the only
    # declared one, so it does NOT appear in the over-claim list.
    assert "WebFetch" not in result
    for undeclared in ("Bash", "Write", "Edit", "NotebookEdit"):
        assert undeclared in result


def test_check_overclaim_unknown_agent_returns_empty():
    """Unknown agent has no parseable frontmatter — nothing to compare,
    return empty (no false positives)."""
    from lib.agent_tool_audit import check_overclaim
    result = check_overclaim(
        "nonexistent-agent-xyz",
        self_reported_used=["Bash", "WebFetch"],
    )
    assert result == []


def test_check_overclaim_empty_input():
    from lib.agent_tool_audit import check_overclaim
    assert check_overclaim("harness-critic", self_reported_used=[]) == []


def test_check_overclaim_strips_whitespace():
    from lib.agent_tool_audit import check_overclaim
    result = check_overclaim(
        "harness-critic",
        self_reported_used=["  Bash  ", "", "WebFetch"],
    )
    assert result == ["Bash"]


def test_check_overclaim_complementary_to_verify_self_report():
    """The two helpers are duals: verify_self_report catches under-claim
    (declared but reported missing), check_overclaim catches over-claim
    (reported used but not declared). The same tool cannot trigger both
    on the same self-report set."""
    from lib.agent_tool_audit import check_overclaim, verify_self_report_consistency
    under = verify_self_report_consistency(
        "harness-critic", self_reported_missing=["WebFetch"],
    )
    over = check_overclaim(
        "harness-critic", self_reported_used=["WebFetch"],
    )
    # WebFetch is declared. Under-claim flags it (declared but reported
    # missing). Over-claim does NOT flag it (reported used + declared).
    assert under == ["WebFetch"]
    assert over == []


def test_invalid_agent_name_rejected():
    from lib.agent_tool_audit import expected_tools
    for bad in ("../escape", "a/b", "a\\b", ".."):
        try:
            expected_tools(bad)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError on agent_name={bad!r}")


def test_empty_agent_name_rejected():
    from lib.agent_tool_audit import expected_tools
    try:
        expected_tools("")
    except ValueError:
        return
    raise AssertionError("expected ValueError on empty agent_name")


TESTS = [
    test_expected_tools_real_harness_critic_includes_webfetch,
    test_expected_tools_real_harness_planner_includes_websearch_and_webfetch,
    test_expected_tools_real_harness_architect_includes_webfetch,
    test_expected_tools_returns_empty_for_missing_agent,
    test_expected_tools_parses_comma_separated,
    test_expected_tools_handles_no_tools_field,
    test_expected_tools_strips_whitespace,
    test_verify_self_report_consistency_detects_mismatch,
    test_verify_self_report_consistency_no_mismatch_for_truly_missing,
    test_verify_self_report_consistency_multiple_tools,
    test_verify_self_report_consistency_empty_input,
    test_verify_self_report_consistency_unknown_agent_no_crash,
    test_render_advisory_empty_when_no_mismatches,
    test_render_advisory_format,
    test_classify_severity_clean_when_no_mismatch,
    test_classify_severity_advisory_when_no_citations,
    test_classify_severity_invalidate_when_citations_present,
    test_render_advisory_invalidate_message_distinct,
    test_render_advisory_clean_severity_emits_empty_string,
    test_check_overclaim_detects_undeclared_tool,
    test_check_overclaim_no_flag_for_declared_tool,
    test_check_overclaim_multiple_undeclared,
    test_check_overclaim_unknown_agent_returns_empty,
    test_check_overclaim_empty_input,
    test_check_overclaim_strips_whitespace,
    test_check_overclaim_complementary_to_verify_self_report,
    test_invalid_agent_name_rejected,
    test_empty_agent_name_rejected,
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
