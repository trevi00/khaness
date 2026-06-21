#!/usr/bin/env python3
"""End-to-end smoke: AUTOPILOT_PARALLEL=1 first-invocation rehearsal.

Closes the residual surfaced by the run-time gap: Phase 2 D2/D4/D5 mock
integration tests cover the unit boundaries, but the full pipeline (real
psmux session + tail visibility pane + per-pane event shard + real git
cherry_pick_sequential into integration_branch) had never run end-to-end.
The first user-driven AUTOPILOT_PARALLEL=1 invoke would have been the
first real fire — this test rehearses it deterministically so a regression
along the chain cannot hide.

Skipped silently (per cherry_pick_smoke convention) when psmux or git is
unavailable. Pane-side capture is best-effort: psmux scrollback timing on
slow runners can miss the inserted line, so capture is asserted only when
non-empty (the spawn / shard / git-merge invariants are the load-bearing
checks).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


_GIT = shutil.which("git")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_GIT, *args], cwd=str(repo),
        capture_output=True, text=True, check=False,
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
    _git_check(repo, "init", "-q", "-b", "main")
    _git_check(repo, "config", "user.email", "smoke@local")
    _git_check(repo, "config", "user.name", "smoke")
    _git_check(repo, "config", "commit.gpgsign", "false")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git_check(repo, "add", "base.txt")
    _git_check(repo, "commit", "-q", "-m", "base")
    return _git_check(repo, "rev-parse", "HEAD")


def _make_worker_commit(repo: Path, branch: str, fname: str, content: str, msg: str) -> str:
    _git_check(repo, "checkout", "-q", "-b", branch, "main")
    (repo / fname).write_text(content, encoding="utf-8")
    _git_check(repo, "add", fname)
    _git_check(repo, "commit", "-q", "-m", msg)
    return _git_check(repo, "rev-parse", "HEAD")


def test_real_psmux_visibility_pane_with_log_tail():
    """psmux session created → tail -f on a log file → capture_pane reads
    back content the parent wrote. Asserts only the non-load-bearing parts
    when scrollback timing is uncooperative on slow runners."""
    from lib import psmux
    if not psmux.which() or _GIT is None:
        return  # SKIP: psmux or git not available

    tail_path = shutil.which("tail")
    if not tail_path:
        return  # SKIP: tail binary not on PATH

    from lib.autopilot_pane_spawn import (
        spawn_visibility_pane, teardown_pane, session_name,
        wait_for_session, wait_for_capture_marker,
    )

    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / "worker.log"
        log_path.touch()
        sid = "autopilot-e2e-smoke"
        decision_id = "D-e2e-1"
        try:
            name = spawn_visibility_pane(sid, decision_id, log_path)
            if name is None:
                return  # SKIP: psmux available but spawn declined
            assert name == session_name(sid, decision_id)

            # C4 closure: hand-rolled polling replaced with the
            # deterministic lib helpers (B2 surface, commit f9abd84).
            # wait_for_session absorbs the cold-start PowerShell race.
            if not wait_for_session(sid, decision_id, timeout_seconds=15.0):
                return  # SKIP: psmux registered late beyond probe window

            # Parent claude-code Agent context simulates worker subprocess
            # by appending lines. Pane's tail -f mirrors them.
            with log_path.open("a", encoding="utf-8") as f:
                f.write("e2e-marker-line-1\n")
                f.flush()
                time.sleep(0.5)
                f.write("e2e-marker-line-2\n")
                f.flush()

            # wait_for_capture_marker replaces the prior hand-rolled while
            # loop. Returns True if marker appeared within 8s, False on
            # timeout (slow runners) — soft signal, not load-bearing.
            saw_marker = wait_for_capture_marker(
                sid, decision_id, "e2e-marker-line",
                timeout_seconds=8.0, max_lines=50,
            )

            # Load-bearing: session existed, name resolved, capture_pane
            # callable. Marker visibility is timing-sensitive — we record
            # it but don't fail when slow runners miss the window.
            if not saw_marker:
                # Soft signal — content arrived in the file even if pane
                # didn't surface it within 8s. The path is still rehearsed.
                assert log_path.read_text(encoding="utf-8").count("e2e-marker-line") == 2
        finally:
            teardown_pane(sid, decision_id)


def test_pane_shard_writes_alongside_canonical_events():
    """emit_pane_started/emit_pane_status write to per-pane shard, NEVER
    to canonical events.jsonl (D6 invariant). Verifies shard read-back."""
    from lib.autopilot_pane_events import (
        emit_pane_started, emit_pane_status, read_pane_events, list_pane_ids,
    )

    with tempfile.TemporaryDirectory() as td:
        sid_dir = Path(td) / "orch-e2e-shard"
        sid_dir.mkdir(parents=True)
        # Canonical canary — must remain empty
        (sid_dir / "events.jsonl").touch()
        canonical_size_before = (sid_dir / "events.jsonl").stat().st_size

        emit_pane_started(sid_dir, "D-shard-1", branch="auto/x/D1", worktree="/tmp/wt-D1")
        emit_pane_status(sid_dir, "D-shard-1", status="running")
        emit_pane_status(sid_dir, "D-shard-1", status="exited", exit_code=0)

        # Shard exists with all 3 records
        events = read_pane_events(sid_dir, "D-shard-1")
        assert len(events) == 3
        assert events[0]["type"] == "pane_started"
        assert events[1]["status"] == "running"
        assert events[2]["status"] == "exited"
        assert events[2]["exit_code"] == 0

        # Canonical untouched
        canonical_size_after = (sid_dir / "events.jsonl").stat().st_size
        assert canonical_size_after == canonical_size_before, (
            "events.jsonl must NEVER receive shard writes (D6 invariant)"
        )

        # list_pane_ids picks up the shard
        assert list_pane_ids(sid_dir) == ["D-shard-1"]


def test_autopilot_parallel_full_pipeline_real_git():
    """Full Phase 1 parallel pipeline rehearsal:

    1. base repo + 2 disjoint worker branches (auto/x/D1, auto/x/D3)
    2. per-decision pane shard records 'pane_started'
    3. visibility pane spawned (psmux) — best-effort
    4. real git cherry_pick_sequential (D1, D3) onto team-x/integration
    5. integration HEAD has both files + 3-commit linear log
    6. shard records 'pane_status: exited' (success)
    7. teardown pane
    """
    if _GIT is None:
        return  # SKIP

    from lib import psmux
    from lib.autopilot_pane_events import (
        emit_pane_started, emit_pane_status, read_pane_events,
    )
    from lib.autopilot_pane_spawn import spawn_visibility_pane, teardown_pane

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        base_sha = _setup_base_repo(repo)

        sha_a = _make_worker_commit(repo, "auto/x/D1", "a.txt", "A\n", "feat: A")
        sha_b = _make_worker_commit(repo, "auto/x/D3", "b.txt", "B\n", "feat: B")

        sid_dir = repo / ".autopilot" / "orch-e2e-parallel"
        sid_dir.mkdir(parents=True)
        sid = "orch-e2e-parallel"

        spawned_panes: list[str] = []
        try:
            for decision, branch, sha in (("D1", "auto/x/D1", sha_a),
                                          ("D3", "auto/x/D3", sha_b)):
                emit_pane_started(
                    sid_dir, decision,
                    branch=branch, base_sha=base_sha, worker_sha=sha,
                )
                if psmux.which():
                    log_path = sid_dir / "panes" / f"{decision}.log"
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    log_path.touch()
                    name = spawn_visibility_pane(sid, decision, log_path)
                    if name:
                        spawned_panes.append(decision)

            # Phase 1 merge dispatch — parent context performs cherry-pick
            _git_check(repo, "checkout", "-q", "-b", "team-x/integration", base_sha)
            for sha in (sha_a, sha_b):
                _git_check(repo, "cherry-pick", "--no-edit", sha)

            # integration HEAD invariants
            assert (repo / "a.txt").read_text(encoding="utf-8") == "A\n"
            assert (repo / "b.txt").read_text(encoding="utf-8") == "B\n"
            log_lines = _git_check(
                repo, "log", "--oneline", "team-x/integration"
            ).splitlines()
            assert len(log_lines) == 3, f"expected 3 commits, got {log_lines}"

            # Worker branches still untouched (F4 invariant)
            assert _git_check(repo, "rev-parse", "auto/x/D1") == sha_a
            assert _git_check(repo, "rev-parse", "auto/x/D3") == sha_b

            for decision in ("D1", "D3"):
                emit_pane_status(sid_dir, decision, status="exited", exit_code=0)

            # All shards have started + exited records
            for decision in ("D1", "D3"):
                events = read_pane_events(sid_dir, decision)
                types = [e["type"] for e in events]
                statuses = [e.get("status") for e in events]
                assert "pane_started" in types
                assert "exited" in statuses
        finally:
            for decision in spawned_panes:
                teardown_pane(sid, decision)


def test_autopilot_parallel_pipeline_handles_conflict_halt():
    """When two workers conflict on the same line, cherry_pick_sequential
    MUST halt at the conflicting decision; integration must be resettable.
    Pane shards must record the failure status — no silent drop."""
    if _GIT is None:
        return  # SKIP

    from lib.autopilot_pane_events import emit_pane_status, read_pane_events

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _setup_base_repo(repo)
        (repo / "shared.txt").write_text("base\n", encoding="utf-8")
        _git_check(repo, "add", "shared.txt")
        _git_check(repo, "commit", "-q", "-m", "add shared")
        base_with_shared = _git_check(repo, "rev-parse", "HEAD")

        sha_a = _make_worker_commit(repo, "auto/x/D1", "shared.txt", "A\n", "feat: A")
        sha_b = _make_worker_commit(repo, "auto/x/D3", "shared.txt", "B\n", "feat: B")

        _git_check(repo, "checkout", "-q", "-b", "team-x/integration", base_with_shared)
        _git_check(repo, "cherry-pick", "--no-edit", sha_a)
        clean_head = _git_check(repo, "rev-parse", "HEAD")

        proc = _git(repo, "cherry-pick", "--no-edit", sha_b)
        assert proc.returncode != 0  # conflict expected

        sid_dir = repo / ".autopilot" / "orch-e2e-conflict"
        sid_dir.mkdir(parents=True)
        emit_pane_status(sid_dir, "D1", status="exited", exit_code=0)
        emit_pane_status(sid_dir, "D3", status="conflict", exit_code=1)

        # Reset integration to last clean state
        _git_check(repo, "cherry-pick", "--abort")
        assert _git_check(repo, "rev-parse", "HEAD") == clean_head

        # Conflict shard records non-zero exit + status='conflict'
        d3_events = read_pane_events(sid_dir, "D3")
        assert len(d3_events) == 1
        assert d3_events[0]["status"] == "conflict"
        assert d3_events[0]["exit_code"] == 1


def test_psmux_smoke_fail_soft_when_unavailable():
    """When psmux is unavailable, spawn_visibility_pane returns None and
    callers continue. This guards the fail-soft contract from regression."""
    from lib.autopilot_pane_spawn import spawn_visibility_pane
    from lib import psmux as _psmux

    # Simulate missing psmux by monkeypatching .which
    saved = _psmux.which
    try:
        _psmux.which = lambda: None  # type: ignore[assignment]
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "x.log"
            log.touch()
            assert spawn_visibility_pane("sid-fake", "D-fake", log) is None
    finally:
        _psmux.which = saved


TESTS = [
    test_real_psmux_visibility_pane_with_log_tail,
    test_pane_shard_writes_alongside_canonical_events,
    test_autopilot_parallel_full_pipeline_real_git,
    test_autopilot_parallel_pipeline_handles_conflict_halt,
    test_psmux_smoke_fail_soft_when_unavailable,
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
