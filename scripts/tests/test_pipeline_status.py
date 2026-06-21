#!/usr/bin/env python3
"""Unit tests for lib/pipeline_status.py — stage progression + summary rendering."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import pipeline_status as ps  # noqa: E402


def _stage(stage_id: str, name: str, output: str, *, phase: str = "", optional: str = "false") -> dict:
    return {"id": stage_id, "name": name, "output": output, "phase": phase, "optional": optional}


def test_compute_stage_results_empty():
    results, idx = ps.compute_stage_results([], "/no/such")
    assert results == []
    assert idx == -1


def test_compute_stage_results_all_todo():
    """No outputs exist anywhere → all TODO, current_idx -1."""
    with tempfile.TemporaryDirectory() as td:
        stages = [
            _stage("a", "Stage A", "out_a.md", phase="plan"),
            _stage("b", "Stage B", "out_b.md", phase="plan"),
        ]
        results, idx = ps.compute_stage_results(stages, td)
        assert [s for _, s, _ in results] == ["TODO", "TODO"]
        assert idx == -1


def test_compute_stage_results_first_done():
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "out_a.md"), "w") as f:
            f.write("done")
        stages = [
            _stage("a", "A", "out_a.md"),
            _stage("b", "B", "out_b.md"),
        ]
        results, idx = ps.compute_stage_results(stages, td)
        assert [s for _, s, _ in results] == ["DONE", "TODO"]
        assert idx == 0


def test_compute_stage_results_optional_skip():
    """Optional stage with no output → SKIP, doesn't advance current_idx."""
    with tempfile.TemporaryDirectory() as td:
        stages = [
            _stage("a", "A", "missing.md", optional="true"),
            _stage("b", "B", "also_missing.md"),
        ]
        results, idx = ps.compute_stage_results(stages, td)
        assert [s for _, s, _ in results] == ["SKIP", "TODO"]
        assert idx == -1


def test_compute_stage_results_src_special_case():
    """'src/ 디렉토리 구조' marker → DONE if src/ has files."""
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "src")
        os.makedirs(src)
        with open(os.path.join(src, "Foo.java"), "w") as f:
            f.write("class Foo {}")
        stages = [_stage("scaf", "Scaffolding", "src/ 디렉토리 구조")]
        results, idx = ps.compute_stage_results(stages, td)
        assert results[0][1] == "DONE"
        assert idx == 0


def test_compute_stage_results_src_special_case_empty_src_no_done():
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "src"))
        stages = [_stage("scaf", "Scaffolding", "src/ 디렉토리 구조")]
        results, idx = ps.compute_stage_results(stages, td)
        assert results[0][1] == "TODO"
        assert idx == -1


def test_compute_stage_results_dot_claude_lookup():
    """Output stored under .claude/ should be detected."""
    with tempfile.TemporaryDirectory() as td:
        cdir = os.path.join(td, ".claude")
        os.makedirs(cdir)
        with open(os.path.join(cdir, "plan.md"), "w") as f:
            f.write("p")
        stages = [_stage("plan", "Plan", "plan.md")]
        results, _ = ps.compute_stage_results(stages, td)
        assert results[0][1] == "DONE"


def test_render_pipeline_summary_empty_stages_returns_none():
    assert ps.render_pipeline_summary([], "/no/where") is None


def test_render_pipeline_summary_basic():
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "a.md"), "w") as f:
            f.write("a")
        stages = [
            _stage("a", "Stage A", "a.md", phase="plan"),
            _stage("b", "Stage B", "b.md", phase="implement"),
        ]
        summary = ps.render_pipeline_summary(stages, td)
        assert summary is not None
        assert "Pipeline: 1/2 stages" in summary
        assert "[v] Stage A (plan)" in summary
        assert "[ ] Stage B (implement)" in summary
        assert "<-- CURRENT" in summary
        assert "Next: Stage B" in summary


def test_render_pipeline_summary_skip_icon():
    with tempfile.TemporaryDirectory() as td:
        stages = [_stage("opt", "Optional", "missing.md", optional="true")]
        summary = ps.render_pipeline_summary(stages, td)
        assert "[-] Optional" in summary
        # Optional skipped doesn't count toward total_required
        assert "Pipeline: 0/0 stages" in summary


def test_render_pipeline_summary_no_next_when_complete():
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "a.md"), "w") as f:
            f.write("a")
        with open(os.path.join(td, "b.md"), "w") as f:
            f.write("b")
        stages = [_stage("a", "A", "a.md"), _stage("b", "B", "b.md")]
        summary = ps.render_pipeline_summary(stages, td)
        assert "Pipeline: 2/2 stages" in summary
        assert "Next:" not in summary


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
