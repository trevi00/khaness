#!/usr/bin/env python3
"""Unit tests for lib/pipeline_stage_picker.py."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import pipeline_stage_picker as psp  # noqa: E402


def test_parse_skill_list_bracket_form():
    assert psp._parse_skill_list("[backend, mybatis]") == ["backend.md", "mybatis.md"]


def test_parse_skill_list_space_form():
    assert psp._parse_skill_list("backend mybatis") == ["backend.md", "mybatis.md"]


def test_parse_skill_list_quoted_items():
    assert psp._parse_skill_list("['a', \"b\"]") == ["a.md", "b.md"]


def test_parse_skill_list_empty():
    assert psp._parse_skill_list("") == []
    assert psp._parse_skill_list("[]") == []


def test_stage_done_finds_output_in_cwd(tmp_path):
    (tmp_path / "design.md").write_text("x", encoding="utf-8")
    stage = {"output": "design.md"}
    assert psp._stage_done(str(tmp_path), stage) is True


def test_stage_done_finds_in_dot_claude(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "convention.md").write_text("x", encoding="utf-8")
    stage = {"output": "convention.md"}
    assert psp._stage_done(str(tmp_path), stage) is True


def test_stage_done_finds_in_design_subdir(tmp_path):
    (tmp_path / ".claude" / "design").mkdir(parents=True)
    (tmp_path / ".claude" / "design" / "skeleton-design.md").write_text(
        "x", encoding="utf-8"
    )
    stage = {"output": "skeleton-design.md"}
    assert psp._stage_done(str(tmp_path), stage) is True


def test_stage_done_src_heuristic(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x", encoding="utf-8")
    stage = {"output": "src/main.py"}
    assert psp._stage_done(str(tmp_path), stage) is True


def test_stage_done_src_empty_returns_false(tmp_path):
    (tmp_path / "src").mkdir()  # empty
    stage = {"output": "src/main.py"}
    assert psp._stage_done(str(tmp_path), stage) is False


def test_stage_done_no_output_returns_false(tmp_path):
    stage = {"output": ""}
    assert psp._stage_done(str(tmp_path), stage) is False


def test_stage_done_missing_returns_false(tmp_path):
    stage = {"output": "missing.md"}
    assert psp._stage_done(str(tmp_path), stage) is False


def test_detect_pipeline_skills_no_cwd():
    assert psp.detect_pipeline_skills(None) == ([], "", "")
    assert psp.detect_pipeline_skills("") == ([], "", "")


def test_detect_pipeline_skills_no_pipeline(tmp_path):
    """Empty project — no stages.yaml, no tech-stack — falls through cleanly."""
    result = psp.detect_pipeline_skills(str(tmp_path))
    # Empty path returns the global default stages last stage if any
    # but for tmp_path with no .claude/, this depends on global discovery
    assert isinstance(result, tuple) and len(result) == 3


def main() -> int:
    failures = []
    test_count = 0
    import inspect
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
