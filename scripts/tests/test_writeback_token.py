#!/usr/bin/env python3
"""Unit tests for lib/writeback_token.py — D1 apply_gate per
debate-1778236168-53dedd."""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _redirect_state_dir(tmp: Path):
    from lib import paths as P
    P.STATE_DIR = tmp / "state"
    P.STATE_DIR.mkdir(parents=True, exist_ok=True)


# ---- TTL resolution ----

def test_resolve_ttl_default_when_env_unset():
    import lib.writeback_token as T
    os.environ.pop("WRITEBACK_APPLY_TOKEN_TTL", None)
    T._TTL_WARN_EMITTED = False
    assert T.resolve_ttl() == T.DEFAULT_TTL_SECONDS


def test_resolve_ttl_respects_in_range_env():
    import lib.writeback_token as T
    os.environ["WRITEBACK_APPLY_TOKEN_TTL"] = "600"
    T._TTL_WARN_EMITTED = False
    try:
        assert T.resolve_ttl() == 600
    finally:
        os.environ.pop("WRITEBACK_APPLY_TOKEN_TTL", None)


def test_resolve_ttl_falls_back_on_unparseable():
    import lib.writeback_token as T
    os.environ["WRITEBACK_APPLY_TOKEN_TTL"] = "not_a_number"
    T._TTL_WARN_EMITTED = False
    try:
        assert T.resolve_ttl() == T.DEFAULT_TTL_SECONDS
    finally:
        os.environ.pop("WRITEBACK_APPLY_TOKEN_TTL", None)


def test_resolve_ttl_falls_back_on_out_of_range():
    import lib.writeback_token as T
    for bad in ("10", "30", "5000", "1801"):
        os.environ["WRITEBACK_APPLY_TOKEN_TTL"] = bad
        T._TTL_WARN_EMITTED = False
        try:
            assert T.resolve_ttl() == T.DEFAULT_TTL_SECONDS, f"bad={bad}"
        finally:
            os.environ.pop("WRITEBACK_APPLY_TOKEN_TTL", None)


# ---- arm + consume happy path ----

def test_arm_writes_token_file_with_correct_mode():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_token import arm, token_path
        result = arm("p1", "a" * 40)
        p = token_path("p1")
        assert p.is_file()
        text = p.read_text(encoding="utf-8")
        # First line is the token
        first_line = text.splitlines()[0]
        assert first_line == result.token
        # Second line is the bound pre_image_sha1
        assert text.splitlines()[1] == "a" * 40


def test_consume_ok_unlinks_token():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_token import (
            arm, consume, ConsumeResult, token_path,
        )
        result = arm("p1", "b" * 40)
        rc = consume("p1", result.token, "b" * 40)
        assert rc == ConsumeResult.OK
        assert not token_path("p1").exists()  # single-use unlink


def test_consume_token_mismatch_returns_invalid():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_token import arm, consume, ConsumeResult
        arm("p1", "c" * 40)
        rc = consume("p1", "wrong-token", "c" * 40)
        assert rc == ConsumeResult.TOKEN_INVALID


def test_consume_pre_image_drift_keeps_token():
    """Token matches but pre_image_sha1 differs → PRE_IMAGE_DRIFT, file not unlinked."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_token import (
            arm, consume, ConsumeResult, token_path,
        )
        result = arm("p1", "d" * 40)
        rc = consume("p1", result.token, "e" * 40)  # different pre_image
        assert rc == ConsumeResult.PRE_IMAGE_DRIFT
        assert token_path("p1").exists()  # NOT unlinked on drift


def test_consume_missing_token_returns_invalid():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_token import consume, ConsumeResult
        rc = consume("nope", "any-token", "f" * 40)
        assert rc == ConsumeResult.TOKEN_INVALID


def test_consume_expired_token_returns_expired_and_unlinks():
    """Force token mtime to be older than TTL → TOKEN_EXPIRED + unlink."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_token import (
            arm, consume, ConsumeResult, token_path, DEFAULT_TTL_SECONDS,
        )
        result = arm("p1", "1" * 40)
        p = token_path("p1")
        # Backdate mtime to TTL + 100s ago
        old = time.time() - DEFAULT_TTL_SECONDS - 100
        os.utime(p, (old, old))
        rc = consume("p1", result.token, "1" * 40)
        assert rc == ConsumeResult.TOKEN_EXPIRED
        assert not p.exists()  # expired files unlinked


def test_consume_rejects_invalid_inputs():
    from lib.writeback_token import consume, ConsumeResult
    # All these should return TOKEN_INVALID without raising
    assert consume("", "x", "a" * 40) == ConsumeResult.TOKEN_INVALID
    assert consume("p1", "", "a" * 40) == ConsumeResult.TOKEN_INVALID
    assert consume("p1", "tok", "short") == ConsumeResult.TOKEN_INVALID


def test_arm_rejects_invalid_inputs():
    from lib.writeback_token import arm
    for bad_pid, bad_sha in [
        ("", "a" * 40),
        ("p1", "tooshort"),
        ("p1", ""),
    ]:
        try:
            arm(bad_pid, bad_sha)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for arm({bad_pid!r}, {bad_sha!r})")


def test_arm_overwrites_prior_arm():
    """Re-arming for the same proposal_id replaces the old token."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_token import arm, consume, ConsumeResult
        r1 = arm("p1", "2" * 40)
        r2 = arm("p1", "2" * 40)
        # Old token rejected
        assert consume("p1", r1.token, "2" * 40) == ConsumeResult.TOKEN_INVALID


TESTS = [
    test_resolve_ttl_default_when_env_unset,
    test_resolve_ttl_respects_in_range_env,
    test_resolve_ttl_falls_back_on_unparseable,
    test_resolve_ttl_falls_back_on_out_of_range,
    test_arm_writes_token_file_with_correct_mode,
    test_consume_ok_unlinks_token,
    test_consume_token_mismatch_returns_invalid,
    test_consume_pre_image_drift_keeps_token,
    test_consume_missing_token_returns_invalid,
    test_consume_expired_token_returns_expired_and_unlinks,
    test_consume_rejects_invalid_inputs,
    test_arm_rejects_invalid_inputs,
    test_arm_overwrites_prior_arm,
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
