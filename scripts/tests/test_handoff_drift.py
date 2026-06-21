#!/usr/bin/env python3
"""Unit tests for validators/handoff_drift.py and lib.handoff_drift.is_anchor_present.

Validator behavior matrix (autonomous closure 4th surveillance surface):
  no HANDOFF.md           -> [PASS] skip
  HANDOFF without yaml    -> [PASS] skip
  HANDOFF + yaml + no anchor    -> [PASS] opt-out
  HANDOFF + yaml + anchor in_sync -> [PASS]
  HANDOFF + yaml + anchor stale   -> [WARN]
  HANDOFF + malformed yaml -> [WARN]

Pattern mirrors test_subagent_refs.py — main() inspects signatures and
injects tmp_path for tests that request it.
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from validators import handoff_drift as VD  # noqa: E402
from lib.handoff_drift import (  # noqa: E402
    ANCHOR_BEGIN,
    ANCHOR_END,
    detect_promotable_sub_phases,
    is_anchor_present,
    render_from_handoff,
)


# ---------- helpers ----------

def _run_validator_in_cwd(cwd: Path) -> str:
    """chdir into cwd, capture stdout of VD.main(), restore cwd."""
    saved = os.getcwd()
    os.chdir(cwd)
    try:
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            VD.main()
        finally:
            sys.stdout = old
        return buf.getvalue()
    finally:
        os.chdir(saved)


def _write_handoff_with_anchor(path: Path, tree: str, *, yaml_extra: str = "") -> None:
    text = (
        "# H\n\n"
        "## Current Phase Block (machine-readable)\n\n"
        "```yaml\n"
        "phase_id: root-x\n"
        "status: in_progress\n"
        f"{yaml_extra}"
        "```\n\n"
        f"{ANCHOR_BEGIN}\n```\n{tree}\n```\n{ANCHOR_END}\n"
    )
    path.write_text(text, encoding="utf-8")


# ---------- is_anchor_present (lib helper) ----------

def test_is_anchor_present_returns_true_when_both_markers():
    text = (
        "before\n"
        f"{ANCHOR_BEGIN}\n```\nx\n```\n{ANCHOR_END}\n"
        "after\n"
    )
    assert is_anchor_present(text) is True


def test_is_anchor_present_returns_false_when_no_markers():
    assert is_anchor_present("just some text\n") is False


def test_is_anchor_present_returns_false_when_only_begin_marker():
    """Half-anchored doc must NOT count as present — both BEGIN+END required."""
    text = f"{ANCHOR_BEGIN}\nincomplete\n"
    assert is_anchor_present(text) is False


# ---------- validator main() decision lattice ----------

def test_validator_pass_when_no_handoff(tmp_path):
    out = _run_validator_in_cwd(tmp_path)
    assert "[PASS]" in out, out
    assert "no HANDOFF.md" in out, out
    assert "[WARN]" not in out, out


def test_validator_pass_when_handoff_has_no_yaml_block(tmp_path):
    (tmp_path / "HANDOFF.md").write_text(
        "# H\n\nno phase block here\n", encoding="utf-8"
    )
    out = _run_validator_in_cwd(tmp_path)
    assert "[PASS]" in out, out
    assert "no '## Current Phase Block'" in out, out


def test_validator_pass_when_anchor_absent(tmp_path):
    """yaml block exists, but no <!-- BEGIN/END phase-tree-visualization --> markers."""
    (tmp_path / "HANDOFF.md").write_text(
        "## Current Phase Block (machine-readable)\n\n"
        "```yaml\nphase_id: root-x\nstatus: in_progress\n```\n",
        encoding="utf-8",
    )
    out = _run_validator_in_cwd(tmp_path)
    assert "[PASS]" in out, out
    assert "anchor block absent" in out, out


def test_validator_pass_when_anchored_block_in_sync(tmp_path):
    path = tmp_path / "HANDOFF.md"
    canon = render_from_handoff(
        "## Current Phase Block (machine-readable)\n\n"
        "```yaml\nphase_id: root-x\nstatus: in_progress\n```\n"
    )
    _write_handoff_with_anchor(path, canon)
    out = _run_validator_in_cwd(tmp_path)
    assert "[PASS]" in out, out
    assert "matches yaml-rendered tree" in out, out
    assert "[WARN]" not in out, out


def test_validator_warns_when_anchored_block_drifts(tmp_path):
    path = tmp_path / "HANDOFF.md"
    _write_handoff_with_anchor(path, "very-stale-tree")
    out = _run_validator_in_cwd(tmp_path)
    assert "[WARN]" in out, out
    assert "anchored block != yaml-rendered tree" in out, out
    assert "handoff_render" in out, out  # fix hint cites the CLI


def test_validator_warns_when_yaml_malformed(tmp_path):
    """Malformed yaml inside the fenced block surfaces as [WARN] — not [FAIL]."""
    (tmp_path / "HANDOFF.md").write_text(
        "## Current Phase Block (machine-readable)\n\n"
        "```yaml\n: : : not yaml\n```\n",
        encoding="utf-8",
    )
    out = _run_validator_in_cwd(tmp_path)
    assert "[WARN]" in out, out
    assert "yaml parse error" in out, out


# ---------- detect_promotable_sub_phases (lib helper) ----------

def test_detect_promotable_returns_empty_for_minimal_yaml():
    text = (
        "## Current Phase Block (machine-readable)\n\n"
        "```yaml\nphase_id: root\nstatus: in_progress\n```\n"
    )
    assert detect_promotable_sub_phases(text) == []


def test_detect_promotable_returns_id_for_5_step_with_nested_marker():
    text = (
        "## Current Phase Block (machine-readable)\n\n"
        "```yaml\n"
        "phase_id: root\n"
        "sub_phases:\n"
        "  - id: candidate-phase\n"
        "    status: in_progress\n"
        "    step_1: \"DONE (Read,Grep,Glob,WebSearch,WebFetch + extras)\"\n"
        "    step_2: pending\n"
        "    step_3: pending\n"
        "    step_4: pending\n"
        "    step_5: pending\n"
        "  - id: small-phase\n"
        "    status: in_progress\n"
        "    step_1: pending\n"
        "    step_2: pending\n"
        "```\n"
    )
    candidates = detect_promotable_sub_phases(text)
    assert "candidate-phase" in candidates
    assert "small-phase" not in candidates


def test_detect_promotable_returns_empty_on_parse_error():
    """Malformed yaml -> empty list (fail-soft, no exception)."""
    text = (
        "## Current Phase Block (machine-readable)\n\n"
        "```yaml\n: : : not yaml\n```\n"
    )
    assert detect_promotable_sub_phases(text) == []


def test_validator_warns_promotion_candidate(tmp_path):
    """Validator surfaces [WARN] for each promotable sub_phase (orthogonal to drift)."""
    (tmp_path / "HANDOFF.md").write_text(
        "## Current Phase Block (machine-readable)\n\n"
        "```yaml\n"
        "phase_id: root\n"
        "sub_phases:\n"
        "  - id: my-fat-phase\n"
        "    status: in_progress\n"
        "    step_1: \"DONE (a,b,c,d,e + tail)\"\n"
        "    step_2: pending\n"
        "    step_3: pending\n"
        "    step_4: pending\n"
        "    step_5: pending\n"
        "```\n",
        encoding="utf-8",
    )
    out = _run_validator_in_cwd(tmp_path)
    assert "[WARN]" in out, out
    assert "my-fat-phase" in out, out
    assert "promotion rule" in out, out


def main() -> int:
    import inspect
    failures: list[tuple[str, str]] = []
    test_count = 0
    for name, obj in list(globals().items()):
        if not name.startswith("test_"):
            continue
        test_count += 1
        sig = inspect.signature(obj)
        try:
            if "tmp_path" in sig.parameters:
                with tempfile.TemporaryDirectory() as td:
                    obj(Path(td))
            else:
                obj()
            print(f"  [OK] {name}")
        except AssertionError as e:
            failures.append((name, str(e)))
            # Truncate assertion message to avoid leaking [FAIL]/[ERROR] tokens
            # captured from validator stdout (would trip run_all's silent-failure
            # regex). The validator emits [PASS]/[WARN] only — no [FAIL] token —
            # but defensive trim guards against future test additions.
            print(f"  [test-failed] {name}")
        except Exception as e:
            failures.append((name, repr(e)))
            print(f"  [test-errored] {name}: {type(e).__name__}")
    if failures:
        print(f"\n{len(failures)} test(s) failed")
        return 1
    print(f"\n[OK] {test_count} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
