#!/usr/bin/env python3
"""Tests for lib/reverse_prd_checkpoint.py — per-release checkpoint + source drift."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def _src_repo(td: Path) -> Path:
    src = td / "src"
    src.mkdir()
    _git(src, "init", "-q"); _git(src, "config", "user.email", "t@t.t"); _git(src, "config", "user.name", "t")
    (src / "a.txt").write_text("v1", encoding="utf-8")
    _git(src, "add", "-A"); _git(src, "commit", "-q", "-m", "c1")
    return src


def test_record_and_load():
    from lib.reverse_prd_checkpoint import record_release, load_checkpoint, source_commit
    with tempfile.TemporaryDirectory() as td:
        src = _src_repo(Path(td))
        out = Path(td) / "out"
        commit = source_commit(src)
        assert commit and len(commit) == 40
        assert record_release(out, "1-A", src_commit=commit, status="complete") is True
        ck = load_checkpoint(out)
        assert ck["releases"]["1-A"]["status"] == "complete"
        assert ck["releases"]["1-A"]["src_commit"] == commit


def test_no_drift_when_source_unchanged():
    from lib.reverse_prd_checkpoint import record_release, check_drift, source_commit
    with tempfile.TemporaryDirectory() as td:
        src = _src_repo(Path(td))
        out = Path(td) / "out"
        record_release(out, "1-A", src_commit=source_commit(src), status="complete")
        d = check_drift(out, src)
        assert d["drift"] is False and d["drifted_releases"] == []


def test_drift_detected_when_source_moves():
    from lib.reverse_prd_checkpoint import record_release, check_drift, source_commit
    with tempfile.TemporaryDirectory() as td:
        src = _src_repo(Path(td))
        out = Path(td) / "out"
        record_release(out, "1-A", src_commit=source_commit(src), status="complete")
        # source advances after release 1-A was built
        (src / "a.txt").write_text("v2", encoding="utf-8")
        _git(src, "add", "-A"); _git(src, "commit", "-q", "-m", "c2")
        d = check_drift(out, src)
        assert d["drift"] is True and d["drifted_releases"] == ["1-A"]


def test_invalid_release_or_status_rejected():
    from lib.reverse_prd_checkpoint import record_release
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "out"
        assert record_release(out, "9-Z", src_commit="x", status="complete") is False
        assert record_release(out, "1-A", src_commit="x", status="bogus") is False


def test_failsoft_no_crash_and_no_release_no_drift():
    """source_commit returns a commit-or-None without crashing (a path under an enclosing
    repo legitimately resolves to that repo's HEAD — not a failure); with NO releases
    recorded, check_drift reports no drift regardless. Fail-soft contract."""
    from lib.reverse_prd_checkpoint import source_commit, check_drift
    with tempfile.TemporaryDirectory() as td:
        plain = Path(td) / "plain"
        plain.mkdir()
        sc = source_commit(plain)
        assert sc is None or (isinstance(sc, str) and len(sc) == 40)   # no crash
        # no releases recorded under out -> never drifts
        assert check_drift(Path(td) / "out", plain)["drift"] is False


def main() -> int:
    tests = [
        test_record_and_load,
        test_no_drift_when_source_unchanged,
        test_drift_detected_when_source_moves,
        test_invalid_release_or_status_rejected,
        test_failsoft_no_crash_and_no_release_no_drift,
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
