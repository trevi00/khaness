#!/usr/bin/env python3
"""Multi-process concurrent .git/index race smoke.

Closes the residual surfaced at commit 30ceb91: cherry_pick_sequential
smoke ran serial git, did not exercise advisory locking when N processes
contend for .git/index simultaneously.

Coverage:
  - N parallel `git worktree add` on the same .git/ → all complete, repo fsck clean
  - N parallel commits on disjoint worktrees of the same repo → no index corruption
  - N parallel `git cherry-pick` racing for the same integration branch →
    at most one wins, others fail-soft via .git/index.lock contention (NO silent
    corruption — losers either succeed serially or surface lock errors)
  - Post-race `git fsck` returns clean (no dangling/corrupt objects)

Skipped silently if git is unavailable.
"""
from __future__ import annotations

import concurrent.futures
import random
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


_GIT = shutil.which("git")


def _run(cwd: Path, *args: str, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_GIT, *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _check(cwd: Path, *args: str) -> str:
    p = _run(cwd, *args)
    if p.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed: rc={p.returncode}\n"
            f"stdout={p.stdout!r}\nstderr={p.stderr!r}"
        )
    return p.stdout.strip()


def _setup_repo(repo: Path) -> str:
    _check(repo, "init", "-q", "-b", "main")
    _check(repo, "config", "user.email", "race@local")
    _check(repo, "config", "user.name", "race")
    _check(repo, "config", "commit.gpgsign", "false")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _check(repo, "add", "base.txt")
    _check(repo, "commit", "-q", "-m", "base")
    return _check(repo, "rev-parse", "HEAD")


def test_concurrent_worktree_add_all_succeed():
    """N parallel `git worktree add` against the same .git/ — Git serializes
    via .git/worktrees/ + .git/index.lock; all should complete, fsck clean."""
    if _GIT is None:
        return
    n_workers = 4
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        repo = root / "repo"
        repo.mkdir()
        _setup_repo(repo)

        wt_root = root / "wts"
        wt_root.mkdir()

        def add_worktree(i: int) -> tuple[int, int]:
            # Concurrent `git worktree add` against one .git/ contends for
            # .git/worktrees/ + config/HEAD locks. Losing that race is EXPECTED git
            # behavior (rc=128 "could not lock" / "File exists"), NOT corruption —
            # git serializes the adds, it does not queue them. So retry ONLY clean
            # lock-contention with jittered backoff (decorrelate the herd); the adds
            # are independent (disjoint branch+path), so each eventually wins. Mirrors
            # the lock-retry the cherry-pick test below already adopted (2026-06-02
            # realignment) — the naive single-shot "all succeed" assertion flaked
            # ~1/30 under load for exactly this lock loss, not a worktree bug.
            wt = wt_root / f"wt-{i}"
            branch = f"race/wt-{i}"
            backoff_ms = 50
            p = None
            for attempt in range(8):
                p = _run(repo, "worktree", "add", "-b", branch, str(wt))
                if p.returncode == 0:
                    return (i, 0)
                msg = ((p.stderr or "") + (p.stdout or "")).lower()
                lock_contended = (
                    "could not lock" in msg or "unable to create" in msg
                    or ".lock" in msg or "file exists" in msg
                    or "another git process" in msg
                )
                if lock_contended and attempt < 7:
                    jitter = random.uniform(0, backoff_ms * 0.5)
                    time.sleep((backoff_ms + jitter) / 1000.0)
                    backoff_ms = min(backoff_ms * 2, 800)
                    continue
                return (i, p.returncode)
            return (i, p.returncode if p else 1)

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as ex:
            results = list(ex.map(add_worktree, range(n_workers)))

        for i, rc in results:
            assert rc == 0, f"worktree add for wt-{i} failed (rc={rc})"

        # All worktrees registered + repo fsck clean
        listing = _check(repo, "worktree", "list", "--porcelain")
        for i in range(n_workers):
            assert f"wt-{i}" in listing, f"wt-{i} missing from list: {listing!r}"

        fsck = _run(repo, "fsck", "--no-progress")
        assert fsck.returncode == 0, (
            f"git fsck failed after concurrent worktree adds: "
            f"stdout={fsck.stdout!r} stderr={fsck.stderr!r}"
        )


def test_concurrent_commits_disjoint_worktrees():
    """N parallel commits on disjoint worktrees — each worktree has its own
    index, so no single .git/index.lock contention; verifies commits land
    cleanly + repo fsck stays valid."""
    if _GIT is None:
        return
    n_workers = 4
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        repo = root / "repo"
        repo.mkdir()
        _setup_repo(repo)

        wts: list[tuple[int, Path]] = []
        for i in range(n_workers):
            wt = root / f"wt-{i}"
            _check(repo, "worktree", "add", "-b", f"race/wt-{i}", str(wt))
            wts.append((i, wt))

        def commit_in(spec: tuple[int, Path]) -> tuple[int, int]:
            i, wt = spec
            (wt / f"file-{i}.txt").write_text(f"content-{i}\n", encoding="utf-8")
            p1 = _run(wt, "add", f"file-{i}.txt")
            if p1.returncode != 0:
                return (i, p1.returncode)
            p2 = _run(wt, "commit", "-q", "-m", f"feat: race-{i}")
            return (i, p2.returncode)

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as ex:
            results = list(ex.map(commit_in, wts))

        for i, rc in results:
            assert rc == 0, f"concurrent commit on wt-{i} failed (rc={rc})"

        # Each branch has exactly 2 commits (base + race-i)
        for i, _wt in wts:
            log = _check(repo, "log", "--oneline", f"race/wt-{i}").splitlines()
            assert len(log) == 2, (
                f"race/wt-{i} log unexpected length {len(log)}: {log}"
            )

        fsck = _run(repo, "fsck", "--no-progress")
        assert fsck.returncode == 0, (
            f"git fsck failed after concurrent commits: stderr={fsck.stderr!r}"
        )


def test_concurrent_cherry_pick_same_target_no_corruption():
    """N threads racing to cherry-pick onto the same branch — git's
    .git/index.lock advisory must serialize them. Some attempts may fail
    with 'index.lock' or 'cannot lock ref' but no silent corruption is
    acceptable. Final state: HEAD reachable, fsck clean, log linear."""
    if _GIT is None:
        return
    n_workers = 3
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        base_sha = _setup_repo(repo)

        # Prep N source commits on disjoint branches for picking.
        sources: list[str] = []
        for i in range(n_workers):
            _check(repo, "checkout", "-q", "-b", f"src-{i}", "main")
            (repo / f"pick-{i}.txt").write_text(f"P{i}\n", encoding="utf-8")
            _check(repo, "add", f"pick-{i}.txt")
            _check(repo, "commit", "-q", "-m", f"feat: pick-{i}")
            sources.append(_check(repo, "rev-parse", "HEAD"))

        _check(repo, "checkout", "-q", "-b", "integration", base_sha)

        def pick(sha: str) -> int:
            # Concurrent cherry-pick onto a shared branch is NOT atomic: git's
            # index.lock serializes each invocation, but the apply→commit pick
            # races across threads. A pick interrupted at commit time can leave
            # CHERRY_PICK_HEAD half-applied, and naively re-running `cherry-pick
            # <sha>` over that state collides ("you are currently cherry-picking"
            # / "now empty") with a NON-lock exit 1. So we retry ONLY clean
            # index.lock contention (jittered backoff to decorrelate the
            # thundering herd); any other collision fail-softs (-1) rather than
            # risk a mid-race `--abort` that resets shared HEAD and undoes a
            # sibling thread. The enforced invariant (module docstring) is NO
            # SILENT CORRUPTION + fail-soft losers, NOT all-win. History:
            # 3 (2026-05-09) → 8 → winners-based realignment (2026-06-02: the
            # all-win assertion contradicted the docstring and flaked on the
            # real non-atomic "now empty" collision, not lock-retry budget).
            backoff_ms = 50
            for attempt in range(8):
                p = _run(repo, "cherry-pick", "--no-edit", sha, timeout=15.0)
                if p.returncode == 0:
                    return 0
                msg = ((p.stderr or "") + (p.stdout or "")).lower()
                clean_lock = (
                    ("could not lock" in msg or "unable to create" in msg
                     or "index.lock" in msg)
                    and "currently cherry-picking" not in msg
                    and "now empty" not in msg
                )
                if clean_lock and attempt < 7:
                    jitter = random.uniform(0, backoff_ms * 0.5)
                    time.sleep((backoff_ms + jitter) / 1000.0)
                    backoff_ms = min(backoff_ms * 2, 800)
                    continue
                return -1  # fail-soft: lock exhausted OR in-progress collision
            return -1

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as ex:
            results = list(ex.map(pick, sources))

        # Single-threaded now — safe to clear any sequencer state a loser left
        # mid-pick and discard its uncommitted changes (idempotent: --quit and
        # reset no-op when nothing is pending). Done here, never mid-race, so a
        # winner's committed work is never undone.
        _run(repo, "cherry-pick", "--quit", timeout=15.0)
        _run(repo, "reset", "--hard", "HEAD", timeout=15.0)

        # Invariant (module docstring): NO SILENT CORRUPTION + fail-soft losers.
        # Concurrent cherry-pick is non-atomic, so not all N necessarily land;
        # we require at least one winner and a fully consistent final state.
        winners = [i for i, rc in enumerate(results) if rc == 0]
        assert winners, f"no cherry-pick won the race: results={results}"

        # Each winner's file materialized (its commit landed cleanly).
        for i in winners:
            assert (repo / f"pick-{i}.txt").exists(), f"winner pick-{i}.txt missing"

        # Linear log: base + exactly one commit per winner — proves no double-
        # apply and no orphan commit from a half-applied loser.
        log = _check(repo, "log", "--oneline", "integration").splitlines()
        assert len(log) == len(winners) + 1, (
            f"integration log {len(log)} != winners {len(winners)}+1: {log}"
        )

        fsck = _run(repo, "fsck", "--no-progress")
        assert fsck.returncode == 0, (
            f"git fsck failed after racing cherry-picks: stderr={fsck.stderr!r}"
        )


TESTS = [
    test_concurrent_worktree_add_all_succeed,
    test_concurrent_commits_disjoint_worktrees,
    test_concurrent_cherry_pick_same_target_no_corruption,
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
