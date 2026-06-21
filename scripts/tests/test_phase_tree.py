#!/usr/bin/env python3
"""Unit tests for engine/phase_tree.py — phase tree convention codification.

Per debate-1778161608-713bdc gen 4 byte-identical (snapshot 7add2646...):
  - F9 expected_test_count_delta = 22; this file contributes ~8 toward that gate.

Coverage:
  - should_promote: 5+ steps with nested marker -> True; 5+ flat -> False; <5 -> False
  - transition_status: all DONE -> DONE; any IN_PROGRESS -> IN_PROGRESS;
    DEFERRED+DONE mix (no in_progress) -> IN_PROGRESS (NOT BLOCKED, per convention)
  - render_tree_markdown: produces ASCII tree with done counts
  - render_yaml / parse_yaml: round-trip preserves all fields
  - empty / leaf-only / deeply-nested edge cases
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.phase_tree import (  # noqa: E402
    Phase,
    Status,
    parse_yaml,
    render_tree_markdown,
    render_yaml,
    should_promote,
    transition_status,
)


def test_should_promote_returns_false_for_under_5_steps():
    """Under-5 steps must not trigger promotion regardless of nested marker presence."""
    p = Phase(id="x", steps={"s1": "DONE", "s2": "DONE", "s3": "pending"})
    assert should_promote(p) is False


def test_should_promote_returns_false_for_5_flat_steps_no_nested():
    p = Phase(id="x", steps={f"s{i}": "DONE" for i in range(5)})
    assert should_promote(p) is False


def test_should_promote_returns_true_for_5_steps_with_nested_marker():
    # value with >= 3 commas signals nested sub-step list
    p = Phase(id="x", steps={
        "s1": "DONE",
        "s2": "DONE",
        "s3": "pending: a, b, c, d (4 sub-steps)",
        "s4": "pending",
        "s5": "pending",
    })
    assert should_promote(p) is True


def test_transition_status_all_done():
    assert transition_status([Status.DONE, Status.DONE]) == Status.DONE


def test_transition_status_any_in_progress():
    assert transition_status([Status.DONE, Status.IN_PROGRESS]) == Status.IN_PROGRESS
    assert transition_status([Status.IN_PROGRESS]) == Status.IN_PROGRESS


def test_transition_status_deferred_with_done_is_in_progress_not_blocked():
    """Convention: deferred children do NOT block parent — partial_done as in_progress."""
    assert transition_status([Status.DONE, Status.DEFERRED]) == Status.IN_PROGRESS
    assert transition_status([Status.DEFERRED, Status.PENDING]) == Status.IN_PROGRESS


def test_transition_status_empty_children():
    assert transition_status([]) == Status.IN_PROGRESS


def test_transition_status_blocked_propagates():
    assert transition_status([Status.BLOCKED, Status.DONE]) == Status.BLOCKED


def test_render_tree_markdown_includes_done_count():
    p = Phase(id="root", steps={"a": "DONE", "b": "DONE", "c": "pending"})
    out = render_tree_markdown(p)
    assert "root" in out
    assert "2/3" in out  # 2 done out of 3 steps


def test_render_tree_markdown_nested_phases():
    child = Phase(id="child", status=Status.DONE)
    root = Phase(id="root", sub_phases=[child], status=Status.IN_PROGRESS)
    out = render_tree_markdown(root)
    assert "root" in out and "child" in out
    assert "in_progress" in out and "done" in out


def test_render_tree_markdown_root_has_no_connector():
    """Root line must start at column 0 with the id, NOT a tree connector."""
    root = Phase(id="root-x", status=Status.IN_PROGRESS)
    out = render_tree_markdown(root)
    first_line = out.splitlines()[0]
    assert first_line.startswith("root-x"), f"got: {first_line!r}"
    assert not first_line.startswith(("├", "└", "│")), (
        f"root must not start with connector, got: {first_line!r}"
    )


def test_render_tree_markdown_depth_1_children_have_connector():
    """Direct children of root must render with ├─ / └─ at column 0."""
    c1 = Phase(id="c1", status=Status.DONE)
    c2 = Phase(id="c2", status=Status.DONE)
    root = Phase(id="root", sub_phases=[c1, c2])
    out = render_tree_markdown(root)
    lines = out.splitlines()
    # Line 1 is root, lines 2+ are children
    child_lines = [ln for ln in lines[1:] if "c1" in ln or "c2" in ln]
    assert len(child_lines) >= 2
    for ln in child_lines:
        assert ln.startswith(("├─", "└─")), (
            f"depth-1 child must start with connector at column 0, got: {ln!r}"
        )


def test_yaml_round_trip_simple():
    p = Phase(
        id="autonomous-orchestrator",
        status=Status.IN_PROGRESS,
        goal="자율 진행",
        next_action="phase 1 구현",
        steps={"s1": "DONE", "s2": "pending"},
    )
    text = render_yaml(p)
    parsed = parse_yaml(text)
    assert parsed.id == p.id
    assert parsed.status == p.status
    assert parsed.goal == p.goal
    assert parsed.next_action == p.next_action
    assert parsed.steps == p.steps


def test_yaml_round_trip_with_subphases_and_trigger():
    child = Phase(id="child", status=Status.DEFERRED, trigger="trigger condition X")
    root = Phase(id="root", goal="g", sub_phases=[child])
    text = render_yaml(root)
    parsed = parse_yaml(text)
    assert len(parsed.sub_phases) == 1
    assert parsed.sub_phases[0].id == "child"
    assert parsed.sub_phases[0].status == Status.DEFERRED
    assert parsed.sub_phases[0].trigger == "trigger condition X"


def test_yaml_parse_unknown_status_falls_back_to_in_progress():
    text = "id: x\nstatus: weird_status\n"
    p = parse_yaml(text)
    assert p.status == Status.IN_PROGRESS


def test_yaml_parse_rejects_non_mapping():
    try:
        parse_yaml("- list-not-mapping\n- item2\n")
    except ValueError as e:
        assert "mapping" in str(e)
        return
    raise AssertionError("expected ValueError on non-mapping yaml")


TESTS = [
    test_should_promote_returns_false_for_under_5_steps,
    test_should_promote_returns_false_for_5_flat_steps_no_nested,
    test_should_promote_returns_true_for_5_steps_with_nested_marker,
    test_transition_status_all_done,
    test_transition_status_any_in_progress,
    test_transition_status_deferred_with_done_is_in_progress_not_blocked,
    test_transition_status_empty_children,
    test_transition_status_blocked_propagates,
    test_render_tree_markdown_includes_done_count,
    test_render_tree_markdown_nested_phases,
    test_render_tree_markdown_root_has_no_connector,
    test_render_tree_markdown_depth_1_children_have_connector,
    test_yaml_round_trip_simple,
    test_yaml_round_trip_with_subphases_and_trigger,
    test_yaml_parse_unknown_status_falls_back_to_in_progress,
    test_yaml_parse_rejects_non_mapping,
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
