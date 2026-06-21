#!/usr/bin/env python3
"""Unit tests for validators/claim_verifier.py — advisory commit-hash claim
verifier (Track 1 debate-1780722434-e5h19n D3/C4). Hermetic: git resolution is
stubbed and doc targets / REPO_MAP are redirected to temp; one best-effort
real-git smoke confirms the live wiring.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from validators import claim_verifier as cv  # noqa: E402

H_PRESENT = "abcdef0123456789abcdef0123456789abcdef01"  # 40-hex, resolves
H_DANGLING = "0123456789ab0123456789ab0123456789ab0123"  # 40-hex, dangling
H_SHORT = "d54437b"  # 7-hex → below MIN_HEX, skipped


def test_min_hex_threshold_skips_short_hashes():
    # 7-hex backtick hash is below MIN_HEX (12) → counted, never resolved.
    txt = f"landed at `{H_SHORT}` and `{H_PRESENT}` per ~/.claude"
    assert cv.MIN_HEX == 12
    with tempfile.TemporaryDirectory() as td:
        doc = Path(td) / "HANDOFF.md"
        doc.write_text(txt, encoding="utf-8")
        saved_targets, saved_map, saved_git = cv._doc_targets, cv.REPO_MAP, cv._git_has_commit
        try:
            cv._doc_targets = lambda: [(doc, "claude-home")]
            cv.REPO_MAP = {"claude-home": Path(td)}
            cv._git_has_commit = lambda repo, sha: "present"
            r = cv.scan()
        finally:
            cv._doc_targets, cv.REPO_MAP, cv._git_has_commit = saved_targets, saved_map, saved_git
        assert r["below_threshold"] == 1, "7-hex must be below-threshold-skipped"
        assert r["checked"] == 1, "only the 40-hex hash is checked"
        assert r["present"] == 1


def test_bind_repo_by_surrounding_cue():
    # example_project cue near the hash → bound to example_project (not the doc default).
    txt = f"example_project-analysis wave landed `{H_PRESENT}` (this commit)"
    key = cv._bind_repo(txt, txt.index(H_PRESENT), txt.index(H_PRESENT) + 40, "home")
    assert key == "example_project"
    # ~/.claude cue → claude-home
    txt2 = f"~/.claude origin/master = `{H_PRESENT}` push"
    key2 = cv._bind_repo(txt2, txt2.index(H_PRESENT), txt2.index(H_PRESENT) + 40, "home")
    assert key2 == "claude-home"
    # no cue → doc default
    txt3 = f"some prose `{H_PRESENT}` more prose"
    key3 = cv._bind_repo(txt3, txt3.index(H_PRESENT), txt3.index(H_PRESENT) + 40, "home")
    assert key3 == "home"


def test_dangling_and_present_routing():
    txt = (f"~/.claude commit `{H_PRESENT}` landed ok; "
           f"~/.claude commit `{H_DANGLING}` orphan bad")
    resolved = {H_PRESENT: "present", H_DANGLING: "dangling"}
    with tempfile.TemporaryDirectory() as td:
        doc = Path(td) / "HANDOFF.md"
        doc.write_text(txt, encoding="utf-8")
        saved_targets, saved_map, saved_git = cv._doc_targets, cv.REPO_MAP, cv._git_has_commit
        try:
            cv._doc_targets = lambda: [(doc, "claude-home")]
            cv.REPO_MAP = {"claude-home": Path(td)}
            cv._git_has_commit = lambda repo, sha: resolved[sha]
            r = cv.scan()
        finally:
            cv._doc_targets, cv.REPO_MAP, cv._git_has_commit = saved_targets, saved_map, saved_git
        assert r["present"] == 1
        assert len(r["dangling_warns"]) == 1 and "dangling" in r["dangling_warns"][0]
        assert len(r["unverifiable_warns"]) == 0


def test_snapshot_sha_excluded_from_commit_check():
    # The dominant false-positive class: a 40-hex debate-snapshot / LOCK SHA is
    # NOT a git-commit claim. A 'sha1'/'snapshot' cue in the window excludes it.
    txt = f"ontology_snapshot sha1 `{H_PRESENT}` converged (gen-2)"
    with tempfile.TemporaryDirectory() as td:
        doc = Path(td) / "HANDOFF.md"
        doc.write_text(txt, encoding="utf-8")
        saved_targets, saved_git = cv._doc_targets, cv._git_has_commit
        try:
            cv._doc_targets = lambda: [(doc, "claude-home")]
            cv._git_has_commit = lambda repo, sha: (_ for _ in ()).throw(
                AssertionError("snapshot SHA must NOT be git-resolved"))
            r = cv.scan()
        finally:
            cv._doc_targets, cv._git_has_commit = saved_targets, saved_git
        assert r["checked"] == 0, "snapshot SHA must not be checked as a commit"
        assert r["non_commit_skipped"] == 1
        assert r["dangling_warns"] == [] and r["unverifiable_warns"] == []


def test_unverifiable_never_silent_pass():
    # hash bound to a repo whose path is absent → unverifiable WARN (not silent).
    txt = f"example_project commit landed `{H_PRESENT}` claim"
    with tempfile.TemporaryDirectory() as td:
        doc = Path(td) / "HANDOFF.md"
        doc.write_text(txt, encoding="utf-8")
        saved_targets, saved_map = cv._doc_targets, cv.REPO_MAP
        try:
            cv._doc_targets = lambda: [(doc, "example_project")]
            cv.REPO_MAP = {"example_project": Path(td) / "does_not_exist"}
            r = cv.scan()  # real _git_has_commit → repo absent → unverifiable
        finally:
            cv._doc_targets, cv.REPO_MAP = saved_targets, saved_map
        assert len(r["unverifiable_warns"]) == 1
        assert "unverifiable" in r["unverifiable_warns"][0]
        assert r["present"] == 0 and r["dangling_warns"] == []


def test_scan_is_failsoft_and_main_advisory():
    # missing doc files must not raise; main() is advisory (exit 0).
    saved_targets = cv._doc_targets
    try:
        cv._doc_targets = lambda: [(Path("/nonexistent/HANDOFF.md"), "home")]
        r = cv.scan()
        assert r["checked"] == 0
    finally:
        cv._doc_targets = saved_targets
    assert cv.main() == 0  # always advisory


def test_real_git_smoke_present_and_dangling():
    # Best-effort: build a tiny real repo, assert a real commit resolves and a
    # fabricated hash dangles. Skipped if git is unavailable.
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        print("    (git unavailable — smoke skipped)")
        return
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        env_run = lambda *a: subprocess.run(["git", "-C", str(repo), *a],
                                            capture_output=True, timeout=10)
        env_run("init", "-q")
        env_run("config", "user.email", "t@t")
        env_run("config", "user.name", "t")
        (repo / "f.txt").write_text("x", encoding="utf-8")
        env_run("add", ".")
        env_run("commit", "-qm", "c0")
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
        assert cv._git_has_commit(repo, head) == "present"
        assert cv._git_has_commit(repo, H_DANGLING) == "dangling"


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            import traceback
            failed += 1
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
    if failed:
        print(f"[FAIL] {failed}/{len(tests)} failed")
        return 1
    print(f"[OK] {len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
