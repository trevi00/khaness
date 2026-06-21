#!/usr/bin/env python3
"""Unit tests for cli/handoff_render.py — Phase Tree auto-rendering from HANDOFF.md.

Coverage:
  - _coalesce_step_keys: phase_id/phase_goal/parent_phase aliasing,
    flat step_* -> steps dict collapse, recursion into sub_phases
  - extract_yaml_block: regex finds fence under heading; raises when missing
  - render_from_handoff: end-to-end yaml -> ASCII tree
  - check_drift: anchor missing -> True; matching block -> False; stale -> True
  - replace_anchored: overwrites stale block; raises on missing markers
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.handoff_drift import (  # noqa: E402
    ANCHOR_BEGIN,
    ANCHOR_END,
    _coalesce_step_keys,
    _infer_status_from_value,
    check_drift,
    detect_promotable_sub_phases,
    emit_drift_advisory,
    extract_yaml_block,
    promote_sub_phase,
    render_from_handoff,
    replace_anchored,
    status_line_for_session,
)


def test_coalesce_alias_phase_id_to_id():
    out = _coalesce_step_keys({"phase_id": "X", "status": "in_progress"})
    assert out["id"] == "X"
    assert "phase_id" not in out


def test_coalesce_alias_phase_goal_and_parent_phase():
    out = _coalesce_step_keys({
        "phase_id": "X", "phase_goal": "G", "parent_phase": "P",
    })
    assert out["goal"] == "G"
    assert out["parent_id"] == "P"
    assert "phase_goal" not in out
    assert "parent_phase" not in out


def test_coalesce_flat_step_keys_to_steps_dict():
    out = _coalesce_step_keys({
        "id": "x",
        "step_1_foo": "DONE (a)",
        "step_2_bar": "pending",
    })
    assert out["steps"] == {"step_1_foo": "DONE (a)", "step_2_bar": "pending"}
    assert "step_1_foo" not in out
    assert "step_2_bar" not in out


def test_coalesce_preserves_existing_steps_dict():
    out = _coalesce_step_keys({
        "id": "x",
        "steps": {"existing": "DONE"},
        "step_2_added": "pending",
    })
    assert out["steps"]["existing"] == "DONE"
    assert out["steps"]["step_2_added"] == "pending"


def test_coalesce_recurses_into_sub_phases():
    data = {
        "id": "root",
        "sub_phases": [
            {"id": "child", "step_1_x": "DONE", "step_2_y": "pending"},
        ],
    }
    out = _coalesce_step_keys(data)
    assert out["sub_phases"][0]["steps"] == {
        "step_1_x": "DONE", "step_2_y": "pending",
    }


def test_extract_yaml_block_finds_fence():
    text = (
        "# Doc\n\n"
        "## Current Phase Block (machine-readable)\n\n"
        "```yaml\n"
        "id: x\nstatus: in_progress\n"
        "```\n\n"
        "rest of doc\n"
    )
    yaml_text = extract_yaml_block(text)
    assert "id: x" in yaml_text
    assert "status: in_progress" in yaml_text


def test_extract_yaml_block_raises_when_missing():
    try:
        extract_yaml_block("# Doc\nno phase block here\n")
    except ValueError as e:
        assert "Current Phase Block" in str(e)
        return
    raise AssertionError("expected ValueError when yaml block missing")


def test_render_from_handoff_produces_tree_with_root_and_children():
    text = (
        "## Current Phase Block (machine-readable)\n\n"
        "```yaml\n"
        "phase_id: root-x\n"
        "phase_goal: goal\n"
        "status: in_progress\n"
        "sub_phases:\n"
        "  - id: child-1\n"
        "    status: done\n"
        "    step_1_a: DONE\n"
        "  - id: child-2\n"
        "    status: in_progress\n"
        "    step_1_b: pending\n"
        "```\n"
    )
    tree = render_from_handoff(text)
    assert "root-x" in tree
    assert "child-1" in tree
    assert "child-2" in tree


def test_check_drift_when_anchor_missing():
    text = "## doc with no anchors\n"
    assert check_drift(text, "tree") is True


def test_check_drift_false_when_block_matches():
    tree = "root-x  [in_progress]"
    text = (
        f"{ANCHOR_BEGIN}\n"
        f"```\n{tree}\n```\n"
        f"{ANCHOR_END}\n"
    )
    assert check_drift(text, tree) is False


def test_check_drift_true_when_block_stale():
    text = (
        f"{ANCHOR_BEGIN}\n"
        "```\nold-tree\n```\n"
        f"{ANCHOR_END}\n"
    )
    assert check_drift(text, "new-tree") is True


def test_replace_anchored_overwrites_block():
    original = (
        "before\n"
        f"{ANCHOR_BEGIN}\n```\nstale\n```\n{ANCHOR_END}\n"
        "after\n"
    )
    out = replace_anchored(original, "fresh-tree")
    assert "stale" not in out
    assert "fresh-tree" in out
    assert "before" in out
    assert "after" in out


def test_replace_anchored_raises_when_markers_missing():
    try:
        replace_anchored("no markers here", "tree")
    except ValueError as e:
        assert "anchor markers" in str(e)
        return
    raise AssertionError("expected ValueError on missing markers")


# ---------- emit_drift_advisory (PostToolUse hook helper) ----------

import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402


def _write_handoff_with_tree(path: Path, tree: str) -> None:
    """Helper — write a minimal HANDOFF-shaped doc with given anchored tree."""
    text = (
        "# H\n\n"
        "## Current Phase Block (machine-readable)\n\n"
        "```yaml\n"
        "phase_id: root-x\n"
        "status: in_progress\n"
        "```\n\n"
        f"{ANCHOR_BEGIN}\n```\n{tree}\n```\n{ANCHOR_END}\n"
    )
    path.write_text(text, encoding="utf-8")


def test_emit_drift_advisory_returns_none_when_anchored_matches_yaml():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "HANDOFF.md"
        # Render the canonical tree from yaml first, then write it as anchored
        canon = render_from_handoff(
            "## Current Phase Block (machine-readable)\n\n"
            "```yaml\nphase_id: root-x\nstatus: in_progress\n```\n"
        )
        _write_handoff_with_tree(path, canon)
        assert emit_drift_advisory(path) is None


def test_emit_drift_advisory_surfaces_when_block_stale():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "HANDOFF.md"
        _write_handoff_with_tree(path, "very-stale-tree")
        adv = emit_drift_advisory(path)
        assert adv is not None
        assert "phase-tree-drift" in adv
        assert "handoff_render" in adv  # fix hint mentions the CLI


def test_emit_drift_advisory_returns_none_for_nonexistent_path():
    assert emit_drift_advisory("/nonexistent/path/HANDOFF.md") is None


def test_emit_drift_advisory_fail_open_on_malformed_yaml():
    """Malformed yaml must NOT raise — advisory just returns None (fail-open)."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "HANDOFF.md"
        # YAML block exists but is unparseable garbage
        path.write_text(
            "## Current Phase Block (machine-readable)\n\n"
            "```yaml\n: : : not yaml\n```\n",
            encoding="utf-8",
        )
        # Must not raise; returns None on failure
        assert emit_drift_advisory(path) is None


# ---------- status_line_for_session (SessionStart hook helper) ----------

def test_status_line_for_session_returns_none_when_no_handoff():
    with tempfile.TemporaryDirectory() as td:
        # cwd has no HANDOFF.md at all
        assert status_line_for_session(td) is None


def test_status_line_for_session_returns_none_when_in_sync():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "HANDOFF.md"
        canon = render_from_handoff(
            "## Current Phase Block (machine-readable)\n\n"
            "```yaml\nphase_id: root-x\nstatus: in_progress\n```\n"
        )
        _write_handoff_with_tree(path, canon)
        assert status_line_for_session(td) is None


def test_status_line_for_session_surfaces_when_block_stale():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "HANDOFF.md"
        _write_handoff_with_tree(path, "very-stale-tree")
        line = status_line_for_session(td)
        assert line is not None
        assert "phase-tree-drift" in line
        assert "handoff_render" in line  # fix hint mentions the CLI
        # Single-line invariant — the harness-status block joins these directly
        assert "\n" not in line


# ---------- promote_sub_phase (vision item #4: yaml flat → nested) ----------

_PROMOTE_FIXTURE = (
    "# H\n\n"
    "## Current Phase Block (machine-readable)\n\n"
    "```yaml\n"
    "phase_id: root\n"
    "sub_phases:\n"
    "  - id: target-phase\n"
    "    status: in_progress  # preserved comment\n"
    "    step_1_foo: \"DONE (a, b, c, d, e)\"\n"
    "    step_2_bar: pending\n"
    "    step_3_baz: PARTIAL (some progress)\n"
    "    step_4_qux: pending\n"
    "    step_5_quux: pending\n"
    "  - id: other-phase\n"
    "    status: in_progress\n"
    "    step_1_zzz: DONE\n"
    "```\n"
)


def test_infer_status_from_value_done():
    assert _infer_status_from_value("DONE (xyz)") == "done"
    assert _infer_status_from_value('"DONE"') == "done"


def test_infer_status_from_value_partial():
    assert _infer_status_from_value("PARTIAL (some)") == "in_progress"


def test_infer_status_from_value_pending():
    assert _infer_status_from_value("pending") == "pending"
    assert _infer_status_from_value("PENDING") == "pending"


def test_infer_status_from_value_unknown_defaults_in_progress():
    assert _infer_status_from_value("???") == "in_progress"


def test_promote_sub_phase_transforms_flat_to_nested():
    out = promote_sub_phase(_PROMOTE_FIXTURE, "target-phase")
    assert "sub_phases:" in out
    # Original flat keys removed from target-phase
    assert "    step_1_foo:" not in out
    assert "    step_5_quux:" not in out
    # New nested entries present with correct ids
    assert "- id: step_1_foo" in out
    assert "- id: step_5_quux" in out


def test_promote_sub_phase_yaml_still_parses_after_transform():
    """Round-trip via PyYAML to verify structural validity."""
    import re as _re
    import yaml as _yaml

    out = promote_sub_phase(_PROMOTE_FIXTURE, "target-phase")
    m = _re.search(r"```yaml\n(.*?)\n```", out, _re.DOTALL)
    assert m is not None
    data = _yaml.safe_load(m.group(1))
    assert data["phase_id"] == "root"
    target = next(sp for sp in data["sub_phases"] if sp["id"] == "target-phase")
    # target now has nested sub_phases instead of flat step_* keys
    assert "sub_phases" in target
    assert len(target["sub_phases"]) == 5
    # Status inference
    statuses = {sp["id"]: sp["status"] for sp in target["sub_phases"]}
    assert statuses["step_1_foo"] == "done"
    assert statuses["step_2_bar"] == "pending"
    assert statuses["step_3_baz"] == "in_progress"  # PARTIAL → in_progress
    assert statuses["step_5_quux"] == "pending"
    # Notes preserved (raw value as single-element list)
    notes_1 = target["sub_phases"][0]["notes"]
    assert any("DONE" in n for n in notes_1)


def test_promote_sub_phase_preserves_other_sub_phases():
    """Non-target sub_phases must remain byte-identical."""
    out = promote_sub_phase(_PROMOTE_FIXTURE, "target-phase")
    # other-phase block should still have flat step_1_zzz key
    assert "  - id: other-phase" in out
    assert "    step_1_zzz: DONE" in out


def test_promote_sub_phase_preserves_inline_comment():
    """Surgical text replacement must keep yaml comments outside the
    transformed step_* lines (e.g., `status: in_progress  # preserved comment`)."""
    out = promote_sub_phase(_PROMOTE_FIXTURE, "target-phase")
    assert "# preserved comment" in out


def test_promote_sub_phase_raises_on_missing_id():
    try:
        promote_sub_phase(_PROMOTE_FIXTURE, "nonexistent-id")
    except ValueError as e:
        assert "not found" in str(e)
        return
    raise AssertionError("expected ValueError on missing sub_phase id")


def test_promote_sub_phase_raises_when_no_step_keys():
    """Sub_phase with no step_* keys can't be promoted."""
    text = (
        "## Current Phase Block (machine-readable)\n\n"
        "```yaml\n"
        "phase_id: root\n"
        "sub_phases:\n"
        "  - id: empty-phase\n"
        "    status: in_progress\n"
        "    notes:\n"
        "    - first note\n"
        "```\n"
    )
    try:
        promote_sub_phase(text, "empty-phase")
    except ValueError as e:
        assert "no step_*" in str(e)
        return
    raise AssertionError("expected ValueError when no step_* keys to promote")


def test_promote_sub_phase_idempotent_via_no_step_keys():
    """Promoting twice raises on second call (no step_* keys remaining)."""
    once = promote_sub_phase(_PROMOTE_FIXTURE, "target-phase")
    try:
        promote_sub_phase(once, "target-phase")
    except ValueError as e:
        assert "no step_*" in str(e)
        return
    raise AssertionError("expected ValueError on second promote of same sub_phase")


def test_detect_promotable_sub_phases_changes_after_promote():
    """After promote, target should no longer be in promotable list."""
    before = detect_promotable_sub_phases(_PROMOTE_FIXTURE)
    assert "target-phase" in before
    after_text = promote_sub_phase(_PROMOTE_FIXTURE, "target-phase")
    after = detect_promotable_sub_phases(after_text)
    assert "target-phase" not in after


TESTS = [
    test_coalesce_alias_phase_id_to_id,
    test_coalesce_alias_phase_goal_and_parent_phase,
    test_coalesce_flat_step_keys_to_steps_dict,
    test_coalesce_preserves_existing_steps_dict,
    test_coalesce_recurses_into_sub_phases,
    test_extract_yaml_block_finds_fence,
    test_extract_yaml_block_raises_when_missing,
    test_render_from_handoff_produces_tree_with_root_and_children,
    test_check_drift_when_anchor_missing,
    test_check_drift_false_when_block_matches,
    test_check_drift_true_when_block_stale,
    test_replace_anchored_overwrites_block,
    test_replace_anchored_raises_when_markers_missing,
    test_emit_drift_advisory_returns_none_when_anchored_matches_yaml,
    test_emit_drift_advisory_surfaces_when_block_stale,
    test_emit_drift_advisory_returns_none_for_nonexistent_path,
    test_emit_drift_advisory_fail_open_on_malformed_yaml,
    test_status_line_for_session_returns_none_when_no_handoff,
    test_status_line_for_session_returns_none_when_in_sync,
    test_status_line_for_session_surfaces_when_block_stale,
    test_infer_status_from_value_done,
    test_infer_status_from_value_partial,
    test_infer_status_from_value_pending,
    test_infer_status_from_value_unknown_defaults_in_progress,
    test_promote_sub_phase_transforms_flat_to_nested,
    test_promote_sub_phase_yaml_still_parses_after_transform,
    test_promote_sub_phase_preserves_other_sub_phases,
    test_promote_sub_phase_preserves_inline_comment,
    test_promote_sub_phase_raises_on_missing_id,
    test_promote_sub_phase_raises_when_no_step_keys,
    test_promote_sub_phase_idempotent_via_no_step_keys,
    test_detect_promotable_sub_phases_changes_after_promote,
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
