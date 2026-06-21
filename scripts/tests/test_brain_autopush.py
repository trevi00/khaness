#!/usr/bin/env python3
"""Tests for lib/brain_autopush.py — orphan brain-snapshots auto-push (D1)."""
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


def _make_work_with_remote(td: Path) -> Path:
    """A work repo (on master) cloned from a bare remote, with code + brain/ committed."""
    bare = td / "remote.git"
    bare.mkdir()
    _git(bare, "init", "--bare", "-q")
    work = td / "work"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], check=True, capture_output=True)
    _git(work, "config", "user.email", "t@t.t")
    _git(work, "config", "user.name", "t")
    (work / "src.py").write_text("# code\n", encoding="utf-8")          # a code file (must NOT reach brain-snapshots)
    (work / "brain" / "l1").mkdir(parents=True)
    (work / "brain" / "l1" / "insight-index.jsonl").write_text('{"id":"a"}\n', encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "init")
    _git(work, "push", "-q", "origin", "HEAD")
    return work


def test_first_run_creates_orphan_brain_only():
    from lib.brain_autopush import autopush
    with tempfile.TemporaryDirectory() as td:
        work = _make_work_with_remote(Path(td))
        head_before = _git(work, "rev-parse", "HEAD").stdout.strip()
        res = autopush(home=work)
        assert res["pushed"] and res["committed"], res
        # brain-snapshots exists on origin and contains ONLY brain/ (orphan, no code)
        _git(work, "fetch", "-q", "origin", "brain-snapshots")
        tree = _git(work, "ls-tree", "--name-only", "origin/brain-snapshots").stdout.split()
        assert tree == ["brain"], f"orphan branch must be brain-only, got {tree}"
        assert "src.py" not in tree
        # operator's HEAD / branch / working tree untouched
        assert _git(work, "rev-parse", "HEAD").stdout.strip() == head_before
        assert _git(work, "branch", "--show-current").stdout.strip() == "master"
        assert _git(work, "status", "--porcelain").stdout.strip() == ""


def test_idempotent_no_change():
    from lib.brain_autopush import autopush
    with tempfile.TemporaryDirectory() as td:
        work = _make_work_with_remote(Path(td))
        autopush(home=work)
        res = autopush(home=work)   # nothing changed
        assert res["pushed"] and not res["committed"], res
        assert "no change" in res["reason"]


def test_brain_change_makes_new_commit():
    from lib.brain_autopush import autopush
    with tempfile.TemporaryDirectory() as td:
        work = _make_work_with_remote(Path(td))
        autopush(home=work)
        (work / "brain" / "l1" / "insight-index.jsonl").write_text(
            '{"id":"a"}\n{"id":"b"}\n', encoding="utf-8")
        res = autopush(home=work)
        assert res["pushed"] and res["committed"], res
        _git(work, "fetch", "-q", "origin", "brain-snapshots")
        n = len(_git(work, "log", "--oneline", "origin/brain-snapshots").stdout.splitlines())
        assert n == 2, "a brain change should add one commit on brain-snapshots"


def test_cross_machine_union_no_loss():
    """Another machine pushes brain-snapshots ahead; our autopush fetches that tip and
    UNIONS our live brain/ into it (FF push) — neither machine's insights are lost."""
    from lib.brain_autopush import autopush
    with tempfile.TemporaryDirectory() as td:
        work = _make_work_with_remote(Path(td))
        autopush(home=work)  # establish brain-snapshots (has id 'a')
        # a second clone advances brain-snapshots on the remote with a DISTINCT insight
        other = Path(td) / "other"
        subprocess.run(["git", "clone", "-q", "-b", "brain-snapshots",
                        str(Path(td) / "remote.git"), str(other)], check=True, capture_output=True)
        _git(other, "config", "user.email", "o@o.o"); _git(other, "config", "user.name", "o")
        (other / "brain" / "l1" / "insight-index.jsonl").write_text('{"id":"a"}\n{"id":"z"}\n', encoding="utf-8")
        _git(other, "add", "-A"); _git(other, "commit", "-q", "-m", "other machine"); _git(other, "push", "-q", "origin", "brain-snapshots")
        # our machine adds its own distinct insight and autopushes
        (work / "brain" / "l1" / "insight-index.jsonl").write_text('{"id":"a"}\n{"id":"local"}\n', encoding="utf-8")
        res = autopush(home=work)
        assert res["pushed"] and res["committed"], res
        # the remote tip now contains ALL ids: a (shared), z (other), local (ours) — union, no loss
        _git(work, "fetch", "-q", "origin", "brain-snapshots")
        blob = _git(work, "show", "origin/brain-snapshots:brain/l1/insight-index.jsonl").stdout
        assert '"id":"z"' in blob.replace(" ", "") and '"id":"local"' in blob.replace(" ", ""), blob


def test_no_brain_dir_failsoft():
    from lib.brain_autopush import autopush
    with tempfile.TemporaryDirectory() as td:
        plain = Path(td) / "p"
        plain.mkdir()
        res = autopush(home=plain)
        assert res["pushed"] is False and "no brain" in res["reason"]


def main() -> int:
    tests = [
        test_first_run_creates_orphan_brain_only,
        test_idempotent_no_change,
        test_brain_change_makes_new_commit,
        test_cross_machine_union_no_loss,
        test_no_brain_dir_failsoft,
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
