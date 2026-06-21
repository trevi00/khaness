#!/usr/bin/env python3
"""Real-git integration smoke for cherry_pick_sequential protocol.

Closes the team-mode-json-messaging 'git-flow merge runtime 미검증' residual
by exercising the locked F4 protocol (debate-1778161608-713bdc gen 4)
against a real ephemeral git repo:

  - 2 worker branches with non-conflicting commits → integration linear log
  - 2 worker branches with conflicting commits → halt + integration reset
  - single worker branch → trivial cherry-pick path

The protocol itself is described in agents/harness-git-master.md
team_merge_mode block (cherry_pick_sequential ordering, HALT on conflict,
NO theirs/ours auto-resolution). This test does NOT invoke the LLM agent;
it exercises the git plumbing the agent would invoke, so a real git
runtime regression cannot be hidden behind subagent free-form prose.

Skipped silently if git is unavailable (CI environments without git).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


_GIT = shutil.which("git")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_GIT, *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )


def _git_check(repo: Path, *args: str) -> str:
    proc = _git(repo, *args)
    if proc.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed: rc={proc.returncode}\n"
            f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout.strip()


def _setup_base_repo(repo: Path) -> str:
    """Init repo + base commit on 'main'. Returns base commit sha."""
    _git_check(repo, "init", "-q", "-b", "main")
    _git_check(repo, "config", "user.email", "smoke@local")
    _git_check(repo, "config", "user.name", "smoke")
    _git_check(repo, "config", "commit.gpgsign", "false")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git_check(repo, "add", "base.txt")
    _git_check(repo, "commit", "-q", "-m", "base")
    return _git_check(repo, "rev-parse", "HEAD")


def _make_worker_commit(
    repo: Path, branch: str, file_name: str, content: str, msg: str,
) -> str:
    """Create branch from main, add file, commit. Returns commit sha."""
    _git_check(repo, "checkout", "-q", "-b", branch, "main")
    (repo / file_name).write_text(content, encoding="utf-8")
    _git_check(repo, "add", file_name)
    _git_check(repo, "commit", "-q", "-m", msg)
    return _git_check(repo, "rev-parse", "HEAD")


def test_cherry_pick_sequential_clean_path():
    """Two non-conflicting worker branches → integration HEAD has both files
    on a linear log starting from base_ref."""
    if _GIT is None:
        return  # SKIP

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        base_sha = _setup_base_repo(repo)

        sha_a = _make_worker_commit(repo, "auto/x/D1", "a.txt", "A\n", "feat: A")
        sha_b = _make_worker_commit(repo, "auto/x/D3", "b.txt", "B\n", "feat: B")

        # Create integration branch from base_ref
        _git_check(repo, "checkout", "-q", "-b", "team-x/integration", base_sha)

        # cherry_pick_sequential: ordered by decision id (D1, D3)
        for sha in (sha_a, sha_b):
            _git_check(repo, "cherry-pick", "--no-edit", sha)

        # Verify both files materialized
        assert (repo / "a.txt").read_text(encoding="utf-8") == "A\n"
        assert (repo / "b.txt").read_text(encoding="utf-8") == "B\n"

        # Verify linear log: integration HEAD descends from base via 2 commits
        log_lines = _git_check(repo, "log", "--oneline", "team-x/integration").splitlines()
        assert len(log_lines) == 3, f"expected 3 commits (base + 2 picks), got {log_lines}"

        # Verify worker branches UNTOUCHED (F4 invariant L97)
        assert _git_check(repo, "rev-parse", "auto/x/D1") == sha_a
        assert _git_check(repo, "rev-parse", "auto/x/D3") == sha_b


def test_cherry_pick_sequential_halts_on_conflict():
    """Two worker branches modifying the same line on different content →
    second cherry-pick MUST fail; integration_branch must be resettable
    to the last clean state for inspection (no auto theirs/ours)."""
    if _GIT is None:
        return  # SKIP

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _setup_base_repo(repo)
        # Add a shared file at base so both workers can conflict on it
        (repo / "shared.txt").write_text("base-content\n", encoding="utf-8")
        _git_check(repo, "add", "shared.txt")
        _git_check(repo, "commit", "-q", "-m", "add shared")
        base_with_shared = _git_check(repo, "rev-parse", "HEAD")
        # main is already at base_with_shared (we just committed on it);
        # _make_worker_commit branches FROM main, so no force-update needed.

        sha_a = _make_worker_commit(
            repo, "auto/x/D1", "shared.txt", "A-version\n", "feat: A-version",
        )
        sha_b = _make_worker_commit(
            repo, "auto/x/D3", "shared.txt", "B-version\n", "feat: B-version",
        )

        _git_check(repo, "checkout", "-q", "-b", "team-x/integration", base_with_shared)

        # First pick succeeds
        _git_check(repo, "cherry-pick", "--no-edit", sha_a)
        clean_head = _git_check(repo, "rev-parse", "HEAD")

        # Second pick MUST fail (conflict on shared.txt)
        proc = _git(repo, "cherry-pick", "--no-edit", sha_b)
        assert proc.returncode != 0, (
            f"expected cherry-pick conflict to fail; got rc={proc.returncode}"
        )

        # Verify NO theirs/ours auto-resolution applied — repo in cherry-pick
        # state with merge markers in the file
        content = (repo / "shared.txt").read_text(encoding="utf-8")
        assert "<<<<<<< " in content and ">>>>>>> " in content, (
            f"expected conflict markers in shared.txt; got {content!r}"
        )

        # Abort cherry-pick + verify integration HEAD reset to clean state
        _git_check(repo, "cherry-pick", "--abort")
        post_abort_head = _git_check(repo, "rev-parse", "HEAD")
        assert post_abort_head == clean_head, (
            "cherry-pick --abort must restore HEAD to last clean commit"
        )

        # Worker branches still untouched
        assert _git_check(repo, "rev-parse", "auto/x/D1") == sha_a
        assert _git_check(repo, "rev-parse", "auto/x/D3") == sha_b


def test_cherry_pick_sequential_single_worker():
    """Single-worker degenerate case still produces a valid integration ref."""
    if _GIT is None:
        return  # SKIP

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        base_sha = _setup_base_repo(repo)
        sha_a = _make_worker_commit(repo, "auto/x/D1", "a.txt", "A\n", "feat: A")

        _git_check(repo, "checkout", "-q", "-b", "team-x/integration", base_sha)
        _git_check(repo, "cherry-pick", "--no-edit", sha_a)

        head = _git_check(repo, "rev-parse", "HEAD")
        # Cherry-pick must advance HEAD past base; sha may equal sha_a when
        # parent + tree + author/committer + timestamps all match (cherry-pick
        # of a single commit onto its own parent in fast succession).
        assert head != base_sha
        assert (repo / "a.txt").read_text(encoding="utf-8") == "A\n"
        log_lines = _git_check(repo, "log", "--oneline").splitlines()
        assert len(log_lines) == 2  # base + cherry-picked A


def test_real_git_available_for_cherry_pick_protocol():
    """Document that this test module exercises real git when available.
    Always passes; serves as a marker test."""
    # Always pass — the per-test skip handles git absence at runtime
    if _GIT is None:
        # Document the skip path in the test report
        pass
    else:
        # Smoke check: git --version actually runs
        proc = subprocess.run(
            [_GIT, "--version"], capture_output=True, text=True, check=False,
        )
        assert proc.returncode == 0


TESTS = [
    test_real_git_available_for_cherry_pick_protocol,
    test_cherry_pick_sequential_single_worker,
    test_cherry_pick_sequential_clean_path,
    test_cherry_pick_sequential_halts_on_conflict,
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
