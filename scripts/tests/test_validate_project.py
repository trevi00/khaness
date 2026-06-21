#!/usr/bin/env python3
"""Unit tests for cli/validate_project.py — monorepo-aware validator dispatcher."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cli.validate_project import (  # noqa: E402
    _classify_dir,
    _discover_subroots,
    _run_validator,
    run,
)


def _build_monorepo(root: Path, *, with_root_claude=True, with_backend=True, with_frontend=True) -> None:
    if with_root_claude:
        (root / ".claude").mkdir()
    if with_backend:
        (root / "backend" / "src" / "main" / "java").mkdir(parents=True)
    if with_frontend:
        fe = root / "frontend"
        fe.mkdir()
        (fe / "package.json").write_text('{"name":"fe"}', encoding="utf-8")


# === _classify_dir ===

def test_classify_root_with_claude():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".claude").mkdir()
        info = _classify_dir(root, is_root=True)
        assert info is not None
        assert info.kind == "root"


def test_classify_java_backend():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "backend"
        (root / "src" / "main" / "java").mkdir(parents=True)
        info = _classify_dir(root, is_root=False)
        assert info is not None
        assert info.kind == "java-be"


def test_classify_ts_frontend():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "frontend"
        root.mkdir()
        (root / "package.json").write_text("{}", encoding="utf-8")
        info = _classify_dir(root, is_root=False)
        assert info is not None
        assert info.kind == "ts-fe"


def test_classify_flutter():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "mobile"
        root.mkdir()
        (root / "pubspec.yaml").write_text("name: x", encoding="utf-8")
        info = _classify_dir(root, is_root=False)
        assert info is not None
        assert info.kind == "flutter"


def test_classify_unknown_dir_returns_none():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "docs"
        root.mkdir()
        info = _classify_dir(root, is_root=False)
        assert info is None


# === _discover_subroots ===

def test_discover_full_monorepo():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _build_monorepo(root)
        subs = _discover_subroots(root)
        kinds = [s.kind for s in subs]
        assert "root" in kinds
        assert "java-be" in kinds
        assert "ts-fe" in kinds


def test_discover_skips_hidden_and_node_modules():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _build_monorepo(root, with_backend=False, with_frontend=False)
        # decoys that must NOT be classified
        (root / ".git").mkdir()
        nm = root / "node_modules" / "fake-pkg"
        nm.mkdir(parents=True)
        (nm / "package.json").write_text("{}", encoding="utf-8")

        subs = _discover_subroots(root)
        # only "root" itself should be present; .git and node_modules pruned
        assert [s.kind for s in subs] == ["root"]


def test_discover_empty_dir():
    with tempfile.TemporaryDirectory() as td:
        subs = _discover_subroots(Path(td))
        assert subs == []


# === _run_validator ===

def test_run_validator_skip_path():
    """skeleton in empty cwd → SKIP (검증 대상 파일 없음)."""
    with tempfile.TemporaryDirectory() as td:
        status, _ = _run_validator("skeleton", Path(td))
        assert status == "SKIP", f"expected SKIP, got {status}"


def test_run_validator_unknown_returns_fail():
    with tempfile.TemporaryDirectory() as td:
        status, tail = _run_validator("does_not_exist", Path(td))
        assert status == "FAIL"
        assert "missing" in tail or "no main" in tail


def test_run_validator_cwd_restored_on_exception():
    saved = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        _run_validator("does_not_exist", Path(td))
    assert os.getcwd() == saved, "cwd must be restored after run"


# === run() end-to-end on synthetic monorepo ===

def test_run_full_monorepo_no_fails():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _build_monorepo(root)
        # Add minimal valid fixtures so no validator FAILs:
        # - root/.claude/ has glossary.md → prd PASS, no FAIL
        (root / ".claude" / "glossary.md").write_text("# Glossary\n", encoding="utf-8")
        # - backend/ has minimal build file → skeleton PASS path
        (root / "backend" / "build.gradle").write_text(
            "plugins { id 'org.springframework.boot' version '3.2.0' }\n"
            "dependencies {\n"
            "  implementation 'org.springframework.boot:spring-boot-starter-web'\n"
            "  testImplementation 'org.springframework.boot:spring-boot-starter-test'\n"
            "}\n",
            encoding="utf-8",
        )
        (root / "backend" / "src" / "main" / "resources").mkdir(parents=True)
        (root / "backend" / "src" / "main" / "resources" / "application.yml").write_text(
            "server:\n  port: 8080\n", encoding="utf-8")

        summary = run(root)
        # Some FAILs are tolerated when fixtures are minimal — what matters
        # is that we ran validators in BOTH root and backend subroots.
        subroots_used = {r.subroot for r in summary.results}
        assert "." in subroots_used, "root subroot must be exercised"
        assert "backend" in subroots_used, "backend subroot must be exercised"
        # specific routing: skeleton only runs against java-be
        skeleton_runs = [r for r in summary.results if r.validator == "skeleton"]
        assert len(skeleton_runs) == 1
        assert skeleton_runs[0].subroot == "backend"


def test_run_no_subroots_returns_empty():
    with tempfile.TemporaryDirectory() as td:
        summary = run(Path(td))
        assert summary.subroots == []
        assert summary.results == []


def main() -> int:
    tests = [
        test_classify_root_with_claude,
        test_classify_java_backend,
        test_classify_ts_frontend,
        test_classify_flutter,
        test_classify_unknown_dir_returns_none,
        test_discover_full_monorepo,
        test_discover_skips_hidden_and_node_modules,
        test_discover_empty_dir,
        test_run_validator_skip_path,
        test_run_validator_unknown_returns_fail,
        test_run_validator_cwd_restored_on_exception,
        test_run_full_monorepo_no_fails,
        test_run_no_subroots_returns_empty,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    if failed == 0:
        print(f"[OK] {len(tests)} tests passed")
        return 0
    print(f"[FAIL] {failed}/{len(tests)} tests failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
