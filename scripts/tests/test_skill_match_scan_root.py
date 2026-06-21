#!/usr/bin/env python3
"""Tests for handlers/prompt/skill_match._resolve_project_scan_root.

Locked by debate-1779110852-421ba0 (gen 2 conditional → gen 3 approved,
ontology SHA-1 0c5b958b1b2cca73d571eb8d91fad3dfb2ce5abf).

Six scenarios:
  s1: normal project with .claude/tech-stack.yaml → returns parent
  s2: cwd empty → returns (None, 'no_cwd')
  s3: no .claude anywhere → returns (None, 'no_claude_dir')
  s4: cwd equals HOME → returns (None, 'home_dir')
  s5: cwd under HOME, walk-up hits HOME/.claude → returns (None, 'home_dir')
  s6: dogfood — HOME contains tech-stack.yaml → MUST still return (None, 'home_dir')

Isolation: monkeypatch USERPROFILE and HOME env vars to a fake_home under
tmp_path; construct fake_home/.claude/tech-stack.yaml fixture per scenario;
never touch real ~.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


class _EnvPatch:
    """Minimal monkeypatch substitute (run_units.py framework has no pytest)."""

    def __init__(self):
        self._saved = {}

    def setenv(self, key, value):
        self._saved[key] = os.environ.get(key)
        os.environ[key] = value

    def delenv(self, key):
        if key in os.environ:
            self._saved.setdefault(key, os.environ[key])
            del os.environ[key]

    def restore(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._saved.clear()


def _make_fake_home(td):
    fake_home = Path(td) / "fake_home"
    fake_home.mkdir(parents=True, exist_ok=True)
    return fake_home


def _make_project(parent, name="proj", with_tech_stack=True):
    proj = parent / name
    (proj / ".claude").mkdir(parents=True, exist_ok=True)
    if with_tech_stack:
        (proj / ".claude" / "tech-stack.yaml").write_text(
            "stack:\n  language: rust\n", encoding="utf-8"
        )
    return proj


def test_s1_normal_project_with_claude_dir_returns_parent():
    from handlers.prompt.skill_match import _resolve_project_scan_root

    patch = _EnvPatch()
    try:
        with tempfile.TemporaryDirectory() as td:
            fake_home = _make_fake_home(td)
            patch.setenv("USERPROFILE", str(fake_home))
            patch.setenv("HOME", str(fake_home))
            proj = _make_project(Path(td))
            sub = proj / "src" / "deep"
            sub.mkdir(parents=True)
            (proj / "package.json").write_text("{}", encoding="utf-8")

            scan_root, reason = _resolve_project_scan_root(str(sub))
            assert scan_root is not None, f"expected parent, got None ({reason})"
            assert os.path.realpath(scan_root) == os.path.realpath(str(proj)), \
                f"expected {proj}, got {scan_root}"
            assert reason == "", f"expected empty reason, got {reason!r}"
    finally:
        patch.restore()


def test_s2_cwd_empty_returns_None_no_cwd():
    from handlers.prompt.skill_match import _resolve_project_scan_root

    scan_root, reason = _resolve_project_scan_root("")
    assert scan_root is None
    assert reason == "no_cwd"


def test_s3_no_claude_dir_anywhere_returns_None_no_claude_dir():
    from handlers.prompt.skill_match import _resolve_project_scan_root

    patch = _EnvPatch()
    try:
        with tempfile.TemporaryDirectory() as td:
            fake_home = _make_fake_home(td)
            patch.setenv("USERPROFILE", str(fake_home))
            patch.setenv("HOME", str(fake_home))
            barren = Path(td) / "barren"
            barren.mkdir()

            scan_root, reason = _resolve_project_scan_root(str(barren))
            assert scan_root is None, f"expected None, got {scan_root}"
            assert reason == "no_claude_dir", f"got {reason!r}"
    finally:
        patch.restore()


def test_s4_cwd_equals_HOME_returns_None_home_dir():
    """HOME has .claude with tech-stack.yaml; cwd IS home — must reject."""
    from handlers.prompt.skill_match import _resolve_project_scan_root

    patch = _EnvPatch()
    try:
        with tempfile.TemporaryDirectory() as td:
            fake_home = _make_fake_home(td)
            patch.setenv("USERPROFILE", str(fake_home))
            patch.setenv("HOME", str(fake_home))
            (fake_home / ".claude").mkdir(parents=True)
            (fake_home / ".claude" / "tech-stack.yaml").write_text(
                "stack:\n  language: rust\n", encoding="utf-8"
            )

            scan_root, reason = _resolve_project_scan_root(str(fake_home))
            assert scan_root is None, f"expected None, got {scan_root}"
            assert reason == "home_dir", f"got {reason!r}"
    finally:
        patch.restore()


def test_s5_cwd_under_HOME_walk_up_hits_HOME_dot_claude_returns_None_home_dir():
    """cwd is a subdir of HOME; walk-up lands on HOME/.claude → reject."""
    from handlers.prompt.skill_match import _resolve_project_scan_root

    patch = _EnvPatch()
    try:
        with tempfile.TemporaryDirectory() as td:
            fake_home = _make_fake_home(td)
            patch.setenv("USERPROFILE", str(fake_home))
            patch.setenv("HOME", str(fake_home))
            (fake_home / ".claude").mkdir(parents=True)
            (fake_home / ".claude" / "tech-stack.yaml").write_text(
                "stack:\n  language: rust\n", encoding="utf-8"
            )
            subdir = fake_home / "scratch"
            subdir.mkdir()

            scan_root, reason = _resolve_project_scan_root(str(subdir))
            assert scan_root is None, f"expected None, got {scan_root}"
            assert reason == "home_dir", f"got {reason!r}"
    finally:
        patch.restore()


def test_s6_dogfood_HOME_has_tech_stack_yaml_must_still_return_None_home_dir():
    """Belt-and-suspenders: even if HOME has tech-stack.yaml (e.g., user
    dogfooding the harness on their own home dir), the resolver MUST reject
    to prevent the original ~/build.gradle pickup bug."""
    from handlers.prompt.skill_match import _resolve_project_scan_root

    patch = _EnvPatch()
    try:
        with tempfile.TemporaryDirectory() as td:
            fake_home = _make_fake_home(td)
            patch.setenv("USERPROFILE", str(fake_home))
            patch.setenv("HOME", str(fake_home))
            (fake_home / ".claude").mkdir(parents=True)
            (fake_home / ".claude" / "tech-stack.yaml").write_text(
                "stack:\n  language: rust\n", encoding="utf-8"
            )
            (fake_home / "build.gradle").write_text("// junk\n", encoding="utf-8")
            (fake_home / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")

            scan_root, reason = _resolve_project_scan_root(str(fake_home))
            assert scan_root is None, f"dogfood case must reject: got {scan_root}"
            assert reason == "home_dir"
    finally:
        patch.restore()


def test_detect_project_type_integration_normal():
    """End-to-end: detect_project_type on a real project tree returns the
    project's marker-derived types, NOT cwd-direct scan."""
    from handlers.prompt.skill_match import detect_project_type

    patch = _EnvPatch()
    try:
        with tempfile.TemporaryDirectory() as td:
            fake_home = _make_fake_home(td)
            patch.setenv("USERPROFILE", str(fake_home))
            patch.setenv("HOME", str(fake_home))
            proj = _make_project(Path(td))
            (proj / "package.json").write_text("{}", encoding="utf-8")
            (proj / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
            sub = proj / "src"
            sub.mkdir()

            types = detect_project_type(str(sub))
            assert types == {"node", "rust"}, f"got {types}"
    finally:
        patch.restore()


def test_detect_project_type_integration_home_dir_returns_empty():
    """End-to-end: cwd=HOME with junk → empty set (the original bug fixed)."""
    from handlers.prompt.skill_match import detect_project_type

    patch = _EnvPatch()
    try:
        with tempfile.TemporaryDirectory() as td:
            fake_home = _make_fake_home(td)
            patch.setenv("USERPROFILE", str(fake_home))
            patch.setenv("HOME", str(fake_home))
            (fake_home / ".claude").mkdir(parents=True)
            (fake_home / ".claude" / "tech-stack.yaml").write_text(
                "stack:\n  language: rust\n", encoding="utf-8"
            )
            (fake_home / "build.gradle").write_text("// junk\n", encoding="utf-8")
            (fake_home / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
            (fake_home / "docker-compose.yml").write_text("version: '3'\n", encoding="utf-8")

            types = detect_project_type(str(fake_home))
            assert types == set(), f"home junk must not be picked up: got {types}"
    finally:
        patch.restore()


TESTS = [
    test_s1_normal_project_with_claude_dir_returns_parent,
    test_s2_cwd_empty_returns_None_no_cwd,
    test_s3_no_claude_dir_anywhere_returns_None_no_claude_dir,
    test_s4_cwd_equals_HOME_returns_None_home_dir,
    test_s5_cwd_under_HOME_walk_up_hits_HOME_dot_claude_returns_None_home_dir,
    test_s6_dogfood_HOME_has_tech_stack_yaml_must_still_return_None_home_dir,
    test_detect_project_type_integration_normal,
    test_detect_project_type_integration_home_dir_returns_empty,
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
