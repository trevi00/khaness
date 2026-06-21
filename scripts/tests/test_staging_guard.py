#!/usr/bin/env python3
"""Unit tests for lib.staging_guard — D3 Layer-B runtime guard.

debate-1779462559-c29f2b LOCK (gen-2 byte-identical, sha1
67c44483a06d6504209644d792edfd943c4ee3a9).

Cases:
    (a) assert_in_staging accepts paths under _CANDIDATES_ROOT
    (b) assert_in_staging accepts paths under _TRACKER_ROOT
    (c) assert_in_staging accepts nested paths (cid subdir)
    (d) assert_in_staging raises StagingInvariantViolation for tempdir
    (e) assert_in_staging raises for sibling under ~/.claude/ (not staging)
    (f) Exception message names the offending path
    (g) Telemetry event emitted on violation
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.staging_guard import (  # noqa: E402
    ALLOWED_ROOTS,
    StagingInvariantViolation,
    assert_in_staging,
)

_CANDIDATES_ROOT, _TRACKER_ROOT = ALLOWED_ROOTS


def test_accepts_candidates_root_direct_child():
    assert_in_staging(_CANDIDATES_ROOT / "abc123.json")
    print("[OK] test_accepts_candidates_root_direct_child")


def test_accepts_tracker_root_direct_child():
    assert_in_staging(_TRACKER_ROOT / "session-x.json")
    print("[OK] test_accepts_tracker_root_direct_child")


def test_accepts_nested_cid_subdir():
    assert_in_staging(_CANDIDATES_ROOT / "cid42" / "research.jsonl")
    print("[OK] test_accepts_nested_cid_subdir")


def test_raises_for_tempdir():
    bad = Path(tempfile.gettempdir()) / "evil.json"
    try:
        assert_in_staging(bad)
    except StagingInvariantViolation:
        print("[OK] test_raises_for_tempdir")
        return
    print("[FAIL] test_raises_for_tempdir — no exception raised")


def test_raises_for_sibling_claude_path():
    # ~/.claude/skills/_common/something.md — under ~/.claude/ but NOT staging
    bad = Path.home() / ".claude" / "skills" / "_common" / "something.md"
    try:
        assert_in_staging(bad)
    except StagingInvariantViolation:
        print("[OK] test_raises_for_sibling_claude_path")
        return
    print("[FAIL] test_raises_for_sibling_claude_path — no exception raised")


def test_exception_message_names_offending_path():
    bad = Path(tempfile.gettempdir()) / "evil.json"
    try:
        assert_in_staging(bad)
    except StagingInvariantViolation as exc:
        msg = str(exc)
        if str(bad) in msg and "staging" in msg.lower():
            print("[OK] test_exception_message_names_offending_path")
            return
        print(f"[FAIL] test_exception_message_names_offending_path — message: {msg!r}")
        return
    print("[FAIL] test_exception_message_names_offending_path — no exception")


def test_telemetry_emitted_on_violation():
    from lib.paths import TELEMETRY_DIR
    telemetry_file = TELEMETRY_DIR / "staging-invariant-violation.jsonl"
    before_size = telemetry_file.stat().st_size if telemetry_file.exists() else 0
    bad = Path(tempfile.gettempdir()) / "telemetry-probe.json"
    try:
        assert_in_staging(bad)
    except StagingInvariantViolation:
        pass
    after_size = telemetry_file.stat().st_size if telemetry_file.exists() else 0
    if after_size > before_size:
        print("[OK] test_telemetry_emitted_on_violation")
        return
    print(f"[FAIL] test_telemetry_emitted_on_violation — file unchanged: {before_size}→{after_size}")


def main() -> int:
    cases = [
        test_accepts_candidates_root_direct_child,
        test_accepts_tracker_root_direct_child,
        test_accepts_nested_cid_subdir,
        test_raises_for_tempdir,
        test_raises_for_sibling_claude_path,
        test_exception_message_names_offending_path,
        test_telemetry_emitted_on_violation,
    ]
    failures = 0
    for c in cases:
        try:
            c()
        except Exception as e:
            failures += 1
            print(f"[ERROR] {c.__name__}: {type(e).__name__}: {e}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
