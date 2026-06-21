#!/usr/bin/env python3
"""Tests for cli/onboard_stack.py — deterministic new-stack onboarding (D1/D3/D5)."""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import yaml

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

# A minimal onboard artifact for a fake 'go' stack: overlay-shaped + oracle.
_ARTIFACT = {
    "stack": "go",
    "source_finder": "find_go_sources",
    "testgen": {"framework": "godog", "runner_cmd": "go test ./..."},
    "applicable_stages": ["requirements", "prd", "convention", "implementation", "unit-test"],
    "stages": {
        "implementation": {"output": "pkg/**/*.go", "gate": ["go build ./... succeeds", "go vet clean"],
                           "skills": ["backend"]},
        "unit-test": {"gate": ["go test ./... 0 failures"], "skills": ["testing"]},
    },
    "expected": {"stage_ids": ["requirements", "implementation", "unit-test"],
                 "tool_tokens": ["go build", "go test"]},
}


def _setup(td: Path):
    """Redirect SKILLS_DIR (candidates+core) and STATE_DIR (onboard artifact) to temp;
    copy the REAL stages.core.yaml so the merge has a genuine core to work against."""
    from lib import pipeline_overlay as po
    from lib import paths as P
    skills = td / "skills"
    (skills / "_pipeline").mkdir(parents=True)
    real_core = _SCRIPTS.parent / "skills" / "_pipeline" / "stages.core.yaml"
    shutil.copy2(real_core, skills / "_pipeline" / "stages.core.yaml")
    po.SKILLS_DIR = skills
    P.STATE_DIR = td / "state"
    P.STATE_DIR.mkdir(parents=True, exist_ok=True)


def _write_artifact(lang: str, artifact: dict):
    from cli.onboard_stack import onboard_artifact_path
    p = onboard_artifact_path(lang)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(artifact, allow_unicode=True), encoding="utf-8")


def test_scaffold_writes_inert_candidates():
    with tempfile.TemporaryDirectory() as td:
        _setup(Path(td))
        _write_artifact("go", _ARTIFACT)
        from cli.onboard_stack import scaffold, candidate_overlay_path, candidate_stages_path, candidate_expected_path, candidate_goldenpin_path
        res = scaffold("go")
        assert res["inert"] is True
        assert candidate_overlay_path("go").is_file()
        assert candidate_stages_path("go").is_file()
        assert candidate_expected_path("go").is_file()
        assert candidate_goldenpin_path("go").is_file()
        # candidates live under _pipeline/candidates/, NOT _pipeline/ (inert to context-loader)
        assert "candidates" in str(candidate_overlay_path("go"))
        # oracle ships operator_authored: false
        exp = yaml.safe_load(candidate_expected_path("go").read_text(encoding="utf-8"))
        assert exp["operator_authored"] is False


def test_scaffold_is_read_only_on_live_pipeline():
    with tempfile.TemporaryDirectory() as td:
        _setup(Path(td))
        _write_artifact("go", _ARTIFACT)
        from cli.onboard_stack import scaffold
        from lib.pipeline_overlay import _pipeline_dir
        scaffold("go")
        # nothing written directly under _pipeline/ (only under candidates/)
        live_files = [p.name for p in _pipeline_dir().glob("*.yaml")]
        assert "stages-go.yaml" not in live_files
        assert not (_pipeline_dir() / "overlays" / "go.overlay.yaml").exists()


def test_verify_candidate_structural_ok():
    with tempfile.TemporaryDirectory() as td:
        _setup(Path(td))
        _write_artifact("go", _ARTIFACT)
        from cli.onboard_stack import scaffold, verify_candidate
        scaffold("go")
        v = verify_candidate("go")
        assert v["structural_ok"] is True, v["diffs"]
        assert v["oracle_authored"] is False


def test_promote_blocked_without_token():
    with tempfile.TemporaryDirectory() as td:
        _setup(Path(td))
        _write_artifact("go", _ARTIFACT)
        from cli.onboard_stack import scaffold, promote
        scaffold("go")
        res = promote("go")  # no token
        assert res["blocked"] is True and res["promoted"] is False
        assert "onboard-stack" in res["reason"]
        assert any("operator_authored" in s for s in res["operator_steps"])


def test_promote_with_token_blocked_until_oracle_authored():
    with tempfile.TemporaryDirectory() as td:
        _setup(Path(td))
        _write_artifact("go", _ARTIFACT)
        from cli.onboard_stack import scaffold, promote, candidate_expected_path, ONBOARD_STACK_TOKEN
        scaffold("go")
        # token present but oracle not operator-authored -> still blocked
        res = promote("go", token=ONBOARD_STACK_TOKEN)
        assert res["blocked"] is True and "operator-authored" in res["reason"]
        # operator authors the oracle
        exp = yaml.safe_load(candidate_expected_path("go").read_text(encoding="utf-8"))
        exp["operator_authored"] = True
        candidate_expected_path("go").write_text(yaml.safe_dump(exp, allow_unicode=True), encoding="utf-8")
        res2 = promote("go", token=ONBOARD_STACK_TOKEN)  # no --allow-in-source -> moves files live, no _VARIANTS edit
        assert res2["promoted"] is True
        from lib.pipeline_overlay import _pipeline_dir
        assert (_pipeline_dir() / "overlays" / "go.overlay.yaml").exists()  # now live


def test_invalid_artifact_rejected():
    with tempfile.TemporaryDirectory() as td:
        _setup(Path(td))
        _write_artifact("bad", {"stack": "bad"})  # missing required fields
        from cli.onboard_stack import scaffold
        try:
            scaffold("bad")
            assert False, "should have raised on invalid artifact"
        except ValueError as e:
            assert "invalid onboard artifact" in str(e)


def main() -> int:
    tests = [
        test_scaffold_writes_inert_candidates,
        test_scaffold_is_read_only_on_live_pipeline,
        test_verify_candidate_structural_ok,
        test_promote_blocked_without_token,
        test_promote_with_token_blocked_until_oracle_authored,
        test_invalid_artifact_rejected,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            import traceback
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failed += 1
    if failed == 0:
        print(f"[OK] {len(tests)} tests passed")
        return 0
    print(f"[FAIL] {failed}/{len(tests)} tests failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
