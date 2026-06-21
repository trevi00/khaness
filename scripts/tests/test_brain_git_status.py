#!/usr/bin/env python3
"""Tests for lib/brain_git_status.py — brain_durability (branch + fallback modes)."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], check=check,
                          capture_output=True, text=True)


def _init_repo_with_remote(td: Path) -> Path:
    bare = td / "remote.git"
    bare.mkdir()
    _git(bare, "init", "--bare", "-q")
    root = td / "repo"
    subprocess.run(["git", "clone", "-q", str(bare), str(root)], check=True, capture_output=True)
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "t")
    (root / "brain" / "l1").mkdir(parents=True)
    (root / "brain" / "l1" / "insight-index.jsonl").write_text('{"id":"a"}\n', encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    _git(root, "push", "-q", "origin", "HEAD")
    return root


# ---- fallback mode (no brain-snapshots branch yet) ----

def test_fallback_clean_not_at_risk():
    from lib.brain_git_status import brain_durability, at_risk
    with tempfile.TemporaryDirectory() as td:
        root = _init_repo_with_remote(Path(td))
        d = brain_durability(home=root)
        assert d["mode"] == "fallback" and d["at_risk"] is False
        assert at_risk(home=root) is False


def test_fallback_uncommitted_brain_at_risk():
    from lib.brain_git_status import brain_durability
    with tempfile.TemporaryDirectory() as td:
        root = _init_repo_with_remote(Path(td))
        (root / "brain" / "l1" / "insight-index.jsonl").write_text('{"id":"a"}\n{"id":"b"}\n', encoding="utf-8")
        d = brain_durability(home=root)
        assert d["mode"] == "fallback" and d["at_risk"] is True
        assert "uncommitted" in d["detail"]


# ---- branch mode (origin/brain-snapshots exists — measures CONTENT) ----

def _make_snapshot_branch(root: Path) -> None:
    """Create an orphan brain-snapshots on origin matching the current brain/."""
    from lib.brain_autopush import autopush
    autopush(home=root)
    _git(root, "fetch", "-q", "origin", "brain-snapshots")


def test_branch_mode_matches_remote_not_at_risk():
    from lib.brain_git_status import brain_durability
    with tempfile.TemporaryDirectory() as td:
        root = _init_repo_with_remote(Path(td))
        _make_snapshot_branch(root)
        d = brain_durability(home=root)
        # live brain/ == origin/brain-snapshots -> not at risk, branch mode
        assert d["mode"] == "branch" and d["at_risk"] is False, d


def test_branch_mode_live_differs_at_risk():
    from lib.brain_git_status import brain_durability
    with tempfile.TemporaryDirectory() as td:
        root = _init_repo_with_remote(Path(td))
        _make_snapshot_branch(root)
        # a new live brain insight not yet auto-pushed -> differs from origin/brain-snapshots
        (root / "brain" / "l1" / "insight-index.jsonl").write_text('{"id":"a"}\n{"id":"new"}\n', encoding="utf-8")
        d = brain_durability(home=root)
        assert d["mode"] == "branch" and d["at_risk"] is True, d
        assert "brain-snapshots" in d["detail"]


def test_branch_mode_silent_after_autopush():
    """Coherence: after the autopush that E1 measures against, E1 goes SILENT."""
    from lib.brain_git_status import brain_durability
    from lib.brain_autopush import autopush
    with tempfile.TemporaryDirectory() as td:
        root = _init_repo_with_remote(Path(td))
        _make_snapshot_branch(root)
        (root / "brain" / "l1" / "insight-index.jsonl").write_text('{"id":"a"}\n{"id":"x"}\n', encoding="utf-8")
        assert brain_durability(home=root)["at_risk"] is True   # at risk before push
        autopush(home=root)
        _git(root, "fetch", "-q", "origin", "brain-snapshots")
        assert brain_durability(home=root)["at_risk"] is False  # silent after push (coherent)


# ---- fail-soft ----

def test_failsoft_non_repo():
    from lib.brain_git_status import brain_durability, at_risk
    with tempfile.TemporaryDirectory() as td:
        plain = Path(td) / "p"
        plain.mkdir()
        assert brain_durability(home=plain)["at_risk"] is False
        assert at_risk(home=plain) is False


def main() -> int:
    tests = [
        test_fallback_clean_not_at_risk,
        test_fallback_uncommitted_brain_at_risk,
        test_branch_mode_matches_remote_not_at_risk,
        test_branch_mode_live_differs_at_risk,
        test_branch_mode_silent_after_autopush,
        test_failsoft_non_repo,
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
