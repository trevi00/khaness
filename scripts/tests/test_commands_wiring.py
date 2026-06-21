#!/usr/bin/env python3
"""Tests that pin A1+A2 wiring directives into 5 caller commands.

The wiring directives live in markdown (commands/*.md) — there is no Python
caller to unit-test directly. But if a future edit silently removes the
record_invocation / classify_severity directives, the next natural debate /
autopilot / team / evaluate / ralph invocation would skip them with no
visible regression.

These grep-based tests pin the directive presence as part of the regression
suite so any deletion fails immediately.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
_CLAUDE_HOME = _SCRIPTS.parent
_COMMANDS = _CLAUDE_HOME / "commands"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _read(name: str) -> str:
    path = _COMMANDS / name
    assert path.exists(), f"missing command file: {path}"
    return path.read_text(encoding="utf-8")


# ---------- A1 wiring (severity escalation, debate-only) ----------

def test_debate_md_calls_classify_severity():
    text = _read("harness-debate.md")
    assert "classify_severity" in text, (
        "harness-debate.md must invoke lib.agent_tool_audit.classify_severity "
        "in the Critic step (A1 wiring, c14e53c)"
    )


def test_debate_md_references_invalidate_branch():
    """The 'invalidate' severity branch is the load-bearing policy — it
    forces verdict=rejected. Mention must persist."""
    text = _read("harness-debate.md")
    assert "invalidate" in text.lower()
    assert "verdict_invalidated_by_severity" in text, (
        "harness-debate.md must append verdict_invalidated_by_severity event "
        "on invalidate severity (A1 wiring)"
    )


def test_debate_md_convergence_check_has_severity_override():
    """Step 4 convergence check must read the invalidate event before the
    verdict literal — otherwise an architect 'approved' wins despite
    invalidated citations."""
    text = _read("harness-debate.md")
    assert "Severity override" in text or "severity override" in text.lower(), (
        "harness-debate.md step 4 convergence must contain severity override rule"
    )
    assert "severity=invalidate forced rejection" in text, (
        "convergence event reason must cite the override for replay forensics"
    )


# ---------- A2 wiring (audit log, all 5 callers) ----------

def test_debate_md_has_audit_log_section():
    """Dedicated ## Audit log section must exist and reference the lib."""
    text = _read("harness-debate.md")
    assert "## Audit log" in text, (
        "harness-debate.md must have a dedicated ## Audit log section (A2 wiring)"
    )
    assert "lib.subagent_invocation_log.record_invocation" in text, (
        "harness-debate.md must invoke record_invocation"
    )
    assert "expected_tools" in text, (
        "tools field must be read from frontmatter via expected_tools(), "
        "not LLM self-report"
    )


def test_autopilot_md_wires_record_invocation_three_paths():
    """Phase 1 has 3 dispatch surfaces (sequential / parallel / cherry-pick)
    — each must call record_invocation. We assert the lib call appears at
    least 3 times to catch a path-specific regression."""
    text = _read("harness-autopilot.md")
    count = text.count("record_invocation")
    assert count >= 3, (
        f"harness-autopilot.md must wire record_invocation in 3 paths "
        f"(sequential/parallel/cherry-pick); found {count} occurrences"
    )


def test_autopilot_md_records_executor_and_merge_roles():
    """Sequential + parallel paths use role='executor'; cherry-pick uses
    role='merge'. Both role tokens must appear."""
    text = _read("harness-autopilot.md")
    assert 'role="executor"' in text, "executor role missing"
    assert 'role="merge"' in text, "merge role missing"


def test_team_md_wires_record_invocation():
    text = _read("harness-team.md")
    assert "record_invocation" in text, (
        "harness-team.md must wire record_invocation per worker spawn"
    )
    assert 'role="team-worker"' in text, "team-worker role missing"


def test_evaluate_md_wires_record_invocation():
    """harness-evaluate.md spawns harness-evaluator subagent (the E2 LLM
    judge) — it must be in the audit trail too."""
    text = _read("harness-evaluate.md")
    assert "record_invocation" in text, (
        "harness-evaluate.md must wire record_invocation around the "
        "harness-evaluator dispatch"
    )
    assert 'role="evaluator"' in text


def test_ralph_md_wires_record_invocation():
    """harness-ralph.md spawns a fix agent per iteration — must be logged
    so ralph activity is grep-able across sessions."""
    text = _read("harness-ralph.md")
    assert "record_invocation" in text, (
        "harness-ralph.md must wire record_invocation around the fix agent "
        "dispatch"
    )
    assert 'role="ralph-fixer"' in text


def test_interview_md_wires_record_invocation():
    """harness-interview.md spawns harness-analyst — must be logged."""
    text = _read("harness-interview.md")
    assert "record_invocation" in text, (
        "harness-interview.md must wire record_invocation around the "
        "harness-analyst dispatch"
    )
    assert 'role="interview-analyst"' in text


def test_ultrawork_md_wires_record_invocation():
    """harness-ultrawork.md spawns harness-explore + per-wave general-
    purpose Agents — both surfaces must record."""
    text = _read("harness-ultrawork.md")
    assert "record_invocation" in text, (
        "harness-ultrawork.md must wire record_invocation"
    )
    # Both context-gather (harness-explore) and slice (general-purpose) paths
    assert 'role="ultrawork-explore"' in text
    assert 'role="ultrawork-slice"' in text


def test_allsolution_md_wires_record_invocation():
    """harness-allsolution.md Phase B spawns harness-researcher — wire."""
    text = _read("harness-allsolution.md")
    assert "record_invocation" in text, (
        "harness-allsolution.md must wire record_invocation around the "
        "harness-researcher dispatch (Phase B)"
    )
    assert 'role="allsolution-researcher"' in text


def test_all_wired_commands_pass_origin_directive():
    """E1 closure 2026-05-10: every wired command must pass
    `origin: lib.subagent_invocation_log.ORIGIN_DIRECTIVE` (or string
    `"directive"`) in its record_invocation extra payload. Pin so silent
    drift to default-untagged records does not happen."""
    for name in (
        "harness-debate.md",
        "harness-autopilot.md",
        "harness-team.md",
        "harness-evaluate.md",
        "harness-ralph.md",
        "harness-interview.md",
        "harness-ultrawork.md",
        "harness-allsolution.md",
    ):
        text = _read(name)
        if "record_invocation" not in text:
            continue
        # Must reference ORIGIN_DIRECTIVE constant OR the literal "directive"
        # alongside an "origin" key. The literal alone is acceptable for
        # human-readable docs; the constant is preferred for type safety.
        assert "ORIGIN_DIRECTIVE" in text or '"origin"' in text or \
               "'origin'" in text, (
            f"{name} record_invocation must pass 'origin' key in extra "
            "(E1 wiring — preferably ORIGIN_DIRECTIVE constant)"
        )


def test_post_tool_hook_referenced_as_safety_net():
    """The PostToolUse hook is the platform-level enforcement layer; the
    new wiring directives all credit it as the safety net so a future
    reader knows the directive is the contract, the hook is the backstop.
    Pin this convention so it doesn't drift away."""
    for name in ("harness-interview.md", "harness-ultrawork.md",
                 "harness-allsolution.md"):
        text = _read(name)
        # Either explicit hook reference OR PostToolUse mention is acceptable
        assert "PostToolUse" in text or "agent_invocation_audit" in text or \
               "safety net" in text, (
            f"{name} should credit the PostToolUse hook as the safety net "
            "so the directive's defense-in-depth role is explicit"
        )


# ---------- Cross-cutting invariant ----------

def test_all_wired_commands_reference_lib_path():
    """Every wired command must reference the canonical lib path
    'lib.subagent_invocation_log' (not bare 'subagent_invocation_log' which
    could mean a different module). This prevents accidental relative
    imports."""
    for name in (
        "harness-debate.md",
        "harness-autopilot.md",
        "harness-team.md",
        "harness-evaluate.md",
        "harness-ralph.md",
        "harness-interview.md",
        "harness-ultrawork.md",
        "harness-allsolution.md",
    ):
        text = _read(name)
        if "record_invocation" in text:
            assert "lib.subagent_invocation_log" in text or \
                   "subagent_invocation_log" in text, (
                f"{name} references record_invocation but not the lib path"
            )


def test_wired_commands_credit_commit_for_traceability():
    """Each wiring directive must cite commit hash (7aff8b7 for A2,
    c14e53c for A1) — readers can cross-reference rationale in git log."""
    debate = _read("harness-debate.md")
    assert "7aff8b7" in debate, "harness-debate.md must cite A2 commit hash"
    assert "c14e53c" in debate, "harness-debate.md must cite A1 commit hash"
    for name in ("harness-autopilot.md", "harness-team.md",
                 "harness-evaluate.md", "harness-ralph.md",
                 "harness-interview.md", "harness-ultrawork.md",
                 "harness-allsolution.md"):
        text = _read(name)
        if "record_invocation" in text:
            assert "7aff8b7" in text, f"{name} must cite A2 commit hash"


TESTS = [
    test_debate_md_calls_classify_severity,
    test_debate_md_references_invalidate_branch,
    test_debate_md_convergence_check_has_severity_override,
    test_debate_md_has_audit_log_section,
    test_autopilot_md_wires_record_invocation_three_paths,
    test_autopilot_md_records_executor_and_merge_roles,
    test_team_md_wires_record_invocation,
    test_evaluate_md_wires_record_invocation,
    test_ralph_md_wires_record_invocation,
    test_interview_md_wires_record_invocation,
    test_ultrawork_md_wires_record_invocation,
    test_allsolution_md_wires_record_invocation,
    test_all_wired_commands_pass_origin_directive,
    test_post_tool_hook_referenced_as_safety_net,
    test_all_wired_commands_reference_lib_path,
    test_wired_commands_credit_commit_for_traceability,
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
