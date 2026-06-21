#!/usr/bin/env python3
"""Unit tests for validators/git_flow.py.

Tests regex patterns + commit/branch validators + override detection. Uses
tempfile for isolated git repos to avoid touching real harness state.

Run:
    cd ~/.claude/scripts && python -m tests.test_git_flow
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from validators import git_flow  # noqa: E402


# === Commit message tests (general mode) ===

def test_commit_general_feat_ok():
    assert git_flow._check_commit_message("feat: add login", company_mode=False) is None


def test_commit_general_fix_ok():
    assert git_flow._check_commit_message("fix(auth): null pointer", company_mode=False) is None


def test_commit_general_breaking_ok():
    assert git_flow._check_commit_message("feat!: breaking API change", company_mode=False) is None


def test_commit_general_no_prefix_fails():
    r = git_flow._check_commit_message("just a message", company_mode=False)
    assert r is not None and "Conventional Commits" in r


def test_commit_general_merge_skipped():
    # auto-merge commits don't get linted
    assert git_flow._check_commit_message("Merge branch 'feature/x' into develop", False) is None


def test_commit_general_revert_skipped():
    assert git_flow._check_commit_message("Revert \"feat: bad\"", False) is None


# === Commit message tests (company override) ===

def test_commit_company_fd_ok():
    assert git_flow._check_commit_message("[f/d] 로그인 기능 개발", company_mode=True) is None


def test_commit_company_fix_ok():
    assert git_flow._check_commit_message("[fix] NPE 처리", company_mode=True) is None


def test_commit_company_etc_ok():
    assert git_flow._check_commit_message("[etc] CI 설정", company_mode=True) is None


def test_commit_company_general_prefix_fails():
    # In company mode, conventional commits prefix doesn't pass
    r = git_flow._check_commit_message("feat: add login", company_mode=True)
    assert r is not None and "company prefix" in r


def test_commit_company_uppercase_prefix_fails():
    # Memory says lowercase only
    r = git_flow._check_commit_message("[F/D] login", company_mode=True)
    assert r is not None


# === Branch name tests (general mode) ===

def test_branch_general_main_ok():
    assert git_flow._check_branch_name("main", company_mode=False) is None


def test_branch_general_feature_ok():
    assert git_flow._check_branch_name("feature/login-form", company_mode=False) is None


def test_branch_general_release_slash_ok():
    assert git_flow._check_branch_name("release/1.2.0", company_mode=False) is None


def test_branch_general_random_fails():
    r = git_flow._check_branch_name("my-random-branch", company_mode=False)
    assert r is not None and "general pattern" in r


# === Branch name tests (company override) ===

def test_branch_company_main_ok():
    assert git_flow._check_branch_name("main", company_mode=True) is None


def test_branch_company_release_dash_ok():
    # company uses dash, not slash
    assert git_flow._check_branch_name("release-1.2.0", company_mode=True) is None


def test_branch_company_hotfix_dash_ok():
    assert git_flow._check_branch_name("hotfix-1.2.1", company_mode=True) is None


def test_branch_company_release_slash_fails():
    # general slash form rejected in company mode
    r = git_flow._check_branch_name("release/1.2.0", company_mode=True)
    assert r is not None


def test_branch_company_feature_korean_ok():
    assert git_flow._check_branch_name("feature/로그인-기능", company_mode=True) is None


# === Override detection ===

def test_override_detected():
    with tempfile.TemporaryDirectory() as td:
        claude_dir = Path(td) / ".claude"
        claude_dir.mkdir()
        (claude_dir / "git-flow-overrides.md").write_text("---\noverride: company\n---\n", encoding="utf-8")
        assert git_flow._detect_override(td) is True


def test_override_absent():
    with tempfile.TemporaryDirectory() as td:
        assert git_flow._detect_override(td) is False


# === Empty message handling ===

def test_commit_empty_fails():
    r = git_flow._check_commit_message("", company_mode=False)
    assert r is not None and "empty" in r


def test_commit_whitespace_fails():
    r = git_flow._check_commit_message("   ", company_mode=False)
    assert r is not None and "empty" in r


# === Driver ===

TESTS = [
    test_commit_general_feat_ok,
    test_commit_general_fix_ok,
    test_commit_general_breaking_ok,
    test_commit_general_no_prefix_fails,
    test_commit_general_merge_skipped,
    test_commit_general_revert_skipped,
    test_commit_company_fd_ok,
    test_commit_company_fix_ok,
    test_commit_company_etc_ok,
    test_commit_company_general_prefix_fails,
    test_commit_company_uppercase_prefix_fails,
    test_branch_general_main_ok,
    test_branch_general_feature_ok,
    test_branch_general_release_slash_ok,
    test_branch_general_random_fails,
    test_branch_company_main_ok,
    test_branch_company_release_dash_ok,
    test_branch_company_hotfix_dash_ok,
    test_branch_company_release_slash_fails,
    test_branch_company_feature_korean_ok,
    test_override_detected,
    test_override_absent,
    test_commit_empty_fails,
    test_commit_whitespace_fails,
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
    total = len(TESTS)
    if failed:
        print(f"\n[FAIL] {failed}/{total} tests failed")
        return 1
    print(f"\n[OK] {total} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
