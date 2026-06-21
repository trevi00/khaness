#!/usr/bin/env python3
"""Tests for lib/pipeline_yaml.py — stages.yaml resolution + parsing."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _redirect_skills_dir(tmp: Path) -> None:
    from lib import paths as P
    from lib import pipeline_yaml as PY
    P.SKILLS_DIR = tmp / "skills"
    # pipeline_yaml does `from .paths import SKILLS_DIR` at module load,
    # binding a local reference — must mutate the module-local symbol too.
    PY.SKILLS_DIR = P.SKILLS_DIR
    P.SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    (P.SKILLS_DIR / "_pipeline").mkdir(parents=True, exist_ok=True)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_resolve_returns_none_when_no_files():
    with tempfile.TemporaryDirectory() as td:
        _redirect_skills_dir(Path(td))
        from lib.pipeline_yaml import resolve_stages_path
        assert resolve_stages_path(cwd=None, language=None) is None


def test_resolve_global_default():
    with tempfile.TemporaryDirectory() as td:
        _redirect_skills_dir(Path(td))
        global_path = Path(td) / "skills" / "_pipeline" / "stages.yaml"
        _write(global_path, "- id: test\n")
        from lib.pipeline_yaml import resolve_stages_path
        assert resolve_stages_path(cwd=None) == global_path


def test_resolve_language_variant_overrides_global():
    with tempfile.TemporaryDirectory() as td:
        _redirect_skills_dir(Path(td))
        _write(Path(td) / "skills" / "_pipeline" / "stages.yaml", "- id: g\n")
        variant = _write(Path(td) / "skills" / "_pipeline" / "stages-flutter.yaml", "- id: f\n")
        from lib.pipeline_yaml import resolve_stages_path
        assert resolve_stages_path(cwd=None, language="flutter") == variant


def test_resolve_project_override_takes_priority():
    with tempfile.TemporaryDirectory() as td:
        _redirect_skills_dir(Path(td))
        _write(Path(td) / "skills" / "_pipeline" / "stages.yaml", "- id: g\n")
        with tempfile.TemporaryDirectory() as proj:
            _write(Path(proj) / ".claude" / "stages.yaml", "- id: p\n")
            from lib.pipeline_yaml import resolve_stages_path
            assert resolve_stages_path(cwd=proj) == Path(proj) / ".claude" / "stages.yaml"


def test_resolve_project_without_stages_falls_through():
    """A project file without `- id:` content falls through to global."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_skills_dir(Path(td))
        global_path = _write(Path(td) / "skills" / "_pipeline" / "stages.yaml", "- id: g\n")
        with tempfile.TemporaryDirectory() as proj:
            _write(Path(proj) / ".claude" / "stages.yaml", "# empty\n")  # no `- id:`
            from lib.pipeline_yaml import resolve_stages_path
            assert resolve_stages_path(cwd=proj) == global_path


def test_parse_stages_returns_list_of_dicts():
    with tempfile.TemporaryDirectory() as td:
        path = _write(Path(td) / "stages.yaml",
            "- id: requirements\n"
            "  output: docs/req.md\n"
            "  phase: plan\n"
            "- id: implementation\n"
            "  phase: implement\n"
        )
        from lib.pipeline_yaml import parse_stages
        stages = parse_stages(path)
        assert len(stages) == 2
        assert stages[0]["id"] == "requirements"
        assert stages[0]["output"] == "docs/req.md"
        assert stages[0]["phase"] == "plan"
        assert stages[1]["id"] == "implementation"


def test_parse_stages_skips_unknown_keys():
    with tempfile.TemporaryDirectory() as td:
        path = _write(Path(td) / "stages.yaml",
            "- id: x\n"
            "  custom_key: ignored\n"
            "  phase: plan\n"
        )
        from lib.pipeline_yaml import parse_stages
        stages = parse_stages(path)
        assert "custom_key" not in stages[0]
        assert stages[0]["phase"] == "plan"


def test_parse_stages_strips_quotes():
    with tempfile.TemporaryDirectory() as td:
        path = _write(Path(td) / "stages.yaml",
            "- id: x\n"
            "  output: \"docs/with spaces.md\"\n"
        )
        from lib.pipeline_yaml import parse_stages
        stages = parse_stages(path)
        assert stages[0]["output"] == "docs/with spaces.md"


def test_parse_stages_missing_file_returns_empty():
    from lib.pipeline_yaml import parse_stages
    assert parse_stages(Path("/nonexistent/stages.yaml")) == []


def test_parse_output_list_single():
    from lib.pipeline_yaml import parse_output_list
    assert parse_output_list("docs/req.md") == ["docs/req.md"]


def test_parse_output_list_yaml_array():
    from lib.pipeline_yaml import parse_output_list
    assert parse_output_list("[a.md, b.md]") == ["a.md", "b.md"]


def test_parse_output_list_with_quotes():
    from lib.pipeline_yaml import parse_output_list
    assert parse_output_list("['a.md', \"b.md\"]") == ["a.md", "b.md"]


def test_parse_output_list_empty():
    from lib.pipeline_yaml import parse_output_list
    assert parse_output_list("") == []


def test_known_stage_keys_locked():
    """Pin the recognized key set — adding a new field must update both lib + tests."""
    from lib.pipeline_yaml import KNOWN_STAGE_KEYS
    # unified-pipeline D2: +{input, artifact, gate_intent, skills_intent} (additive).
    expected = {"name", "output", "gate", "phase", "optional", "skills", "dge",
                "input", "artifact", "gate_intent", "skills_intent"}
    assert KNOWN_STAGE_KEYS == frozenset(expected)


TESTS = [
    test_resolve_returns_none_when_no_files,
    test_resolve_global_default,
    test_resolve_language_variant_overrides_global,
    test_resolve_project_override_takes_priority,
    test_resolve_project_without_stages_falls_through,
    test_parse_stages_returns_list_of_dicts,
    test_parse_stages_skips_unknown_keys,
    test_parse_stages_strips_quotes,
    test_parse_stages_missing_file_returns_empty,
    test_parse_output_list_single,
    test_parse_output_list_yaml_array,
    test_parse_output_list_with_quotes,
    test_parse_output_list_empty,
    test_known_stage_keys_locked,
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
