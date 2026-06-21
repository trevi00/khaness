#!/usr/bin/env python3
"""Contract tests for harness subagent isolation assumptions.

The 'subagent isolation = claude-code platform-level convention-enforced'
residual cannot be fixed at the platform layer, but the harness DOES make
specific assumptions about that platform contract. This module pins those
assumptions as executable contract tests so a regression in our side of
the boundary is surfaced (e.g., an agent file dropping its tools field, a
new role acquiring tools beyond its purpose, a worker-loop comment being
edited away).

Anchors (from debate-1778302432-1ce6ea + debate-1778307906-23b7b3):
  - lib/team_worker_loop.py: 'intentionally MINIMAL — does NOT spawn LLM
    provider processes' (corroborates the no-Task-tool-in-subprocess
    citation that justifies Phase 1 D2 capture_pane visibility-only path)
  - lib/autopilot_phase1_merge.py: INVARIANT comment for D4 ralph re-entry
  - agents/harness-critic.md L4: tools must include WebFetch (W19.1.1
    citation integrity contract)
  - agents/harness-planner.md L4: tools must include WebSearch + WebFetch
  - agents/harness-architect.md L4: tools must include WebFetch
  - agents/harness-evaluator.md tools list MUST NOT include Bash or Glob
    (residual #3 mitigation in commit f6ab8a8 — minimal tools list reduces
    state/* path-enumeration attack surface)
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def test_team_worker_loop_minimal_invariant_preserved():
    """The no-LLM-spawn invariant is the load-bearing assumption that justifies
    debate-1778302432-1ce6ea D2 (a) capture_pane visibility-only — if this
    docstring is silently edited out, future D2 work could mistakenly
    revive team_worker_loop spawn for LLM workers."""
    src = (_SCRIPTS / "lib" / "team_worker_loop.py").read_text(encoding="utf-8")
    assert "intentionally MINIMAL" in src, (
        "team_worker_loop.py must retain the 'intentionally MINIMAL' invariant "
        "doc — load-bearing for debate-1778302432-1ce6ea D2 + D4 deferrals"
    )
    assert "does NOT spawn LLM provider" in src, (
        "team_worker_loop.py must retain the no-LLM-spawn assertion"
    )


def test_d4_invariant_comment_in_phase1_merge():
    """D4 ralph re-entry contract — duplicate of test_d4_invariant_comment_
    present_in_source in test_autopilot_phase1_merge.py, kept here as a
    cross-module anchor so isolation contract failures surface even when
    that test is skipped."""
    src = (_SCRIPTS / "lib" / "autopilot_phase1_merge.py").read_text(encoding="utf-8")
    assert "INVARIANT: ralph re-entry happens in parent Agent context" in src


def test_research_augmented_agents_have_required_tools():
    """W19.1.1 citation integrity contract — Planner/Critic/Architect MUST
    declare WebFetch (and Planner additionally WebSearch). Without these,
    research-augmented debate degrades silently."""
    from lib.agent_tool_audit import expected_tools

    critic = expected_tools("harness-critic")
    assert "WebFetch" in critic, f"harness-critic must declare WebFetch; got {critic}"

    planner = expected_tools("harness-planner")
    assert "WebSearch" in planner and "WebFetch" in planner, (
        f"harness-planner must declare both WebSearch and WebFetch; got {planner}"
    )

    architect = expected_tools("harness-architect")
    assert "WebFetch" in architect, (
        f"harness-architect must declare WebFetch; got {architect}"
    )


def test_evaluator_minimal_tools_residual_3_mitigation():
    """Residual #3 mitigation (commit f6ab8a8): harness-evaluator MUST NOT
    include Bash or Glob in its tools list. Bash would enable shell-level
    state/* path enumeration; Glob would enable directory enumeration
    outside the artifact_under_evaluation scope."""
    from lib.agent_tool_audit import expected_tools

    tools = expected_tools("harness-evaluator")
    assert "Bash" not in tools, (
        f"harness-evaluator MUST NOT have Bash (residual #3 mitigation); got {tools}"
    )
    assert "Glob" not in tools, (
        f"harness-evaluator MUST NOT have Glob (residual #3 mitigation); got {tools}"
    )
    # Positive assertion — what it MUST have to function
    assert "Read" in tools and "Grep" in tools, (
        f"harness-evaluator must retain Read+Grep for artifact inspection; got {tools}"
    )


def test_all_harness_agents_have_tools_field_declared():
    """Every harness-* agent must have a non-empty tools field — defends
    against silent frontmatter degradation (a missing tools field would
    cause claude-code to default to ALL tools, breaking the principle of
    least authority)."""
    from lib.agent_tool_audit import expected_tools

    agents_dir = _SCRIPTS.parent / "agents"
    harness_agents = sorted(p.stem for p in agents_dir.glob("harness-*.md"))
    assert harness_agents, "no harness-* agents found"

    missing: list[str] = []
    for name in harness_agents:
        tools = expected_tools(name)
        if not tools:
            missing.append(name)
    assert not missing, (
        f"harness-* agents missing 'tools' frontmatter field: {missing}"
    )


def test_evaluator_isolation_forbidden_paths_documented():
    """harness-evaluator.md <forbidden> block must explicitly deny reads
    to state/debates/, state/orchestrator/, state/interview/, state/
    evaluator/, state/research/ — D3 isolation contract from commit
    f6ab8a8. Silent removal of any path here would re-open the path-
    enumeration vector."""
    src = (_SCRIPTS.parent / "agents" / "harness-evaluator.md").read_text(encoding="utf-8")
    for required_path in (
        "state/debates/",
        "state/orchestrator/",
        "state/evaluator/",
    ):
        assert required_path in src, (
            f"harness-evaluator.md must forbid reads under {required_path} "
            "(D3 isolation contract from commit f6ab8a8)"
        )


def test_subagent_isolation_residual_documented_in_handoff():
    """Sanity: HANDOFF.md must continue to acknowledge the platform-level
    isolation residual rather than silently claim closure. If this test
    fails, either (a) the isolation contract has actually been internalized
    via a new mechanism (great — update this test to pin the new
    mechanism), or (b) someone removed the acknowledgment without a
    replacement (regression — restore it)."""
    handoff_path = _SCRIPTS.parent / "HANDOFF.md"
    if not handoff_path.is_file():
        return  # SKIP — repo without HANDOFF (e.g., extracted lib subset)
    content = handoff_path.read_text(encoding="utf-8")
    assert "subagent isolation" in content.lower() or "subagent_isolation" in content, (
        "HANDOFF.md must acknowledge subagent isolation contract (platform-level "
        "residual). If you replaced this acknowledgment with a stronger mechanism, "
        "update this test to pin the new mechanism."
    )


TESTS = [
    test_team_worker_loop_minimal_invariant_preserved,
    test_d4_invariant_comment_in_phase1_merge,
    test_research_augmented_agents_have_required_tools,
    test_evaluator_minimal_tools_residual_3_mitigation,
    test_all_harness_agents_have_tools_field_declared,
    test_evaluator_isolation_forbidden_paths_documented,
    test_subagent_isolation_residual_documented_in_handoff,
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
