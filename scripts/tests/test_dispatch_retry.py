#!/usr/bin/env python3
"""Tests for engine.dispatch_retry.call_with_retry (M15 D1). Auto-discovered via main()->int."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from engine.dispatch_retry import call_with_retry, full_jitter  # noqa: E402


def _classify(exc):
    return "permanent" if isinstance(exc, (TypeError, KeyError, ValueError)) else "transient"


def test_success_first_try_no_sleep():
    sleeps = []
    assert call_with_retry(lambda: 42, classify=_classify, sleep_fn=sleeps.append) == 42
    assert sleeps == []


def test_transient_then_success():
    seq = [RuntimeError("a"), RuntimeError("b"), "OK"]
    sleeps = []

    def fn():
        x = seq.pop(0)
        if isinstance(x, Exception):
            raise x
        return x

    r = call_with_retry(fn, classify=_classify, max_attempts=3,
                        sleep_fn=sleeps.append, jitter=lambda cap: cap)
    assert r == "OK"
    assert sleeps == [0.5, 1.0]  # base*2^0, base*2^1 (no jitter via identity)


def test_permanent_reraises_immediately():
    sleeps = []

    def fn():
        raise TypeError("bug")

    try:
        call_with_retry(fn, classify=_classify, sleep_fn=sleeps.append)
        raise AssertionError("expected TypeError")
    except TypeError:
        pass
    assert sleeps == [], "permanent must not sleep/retry"


def test_transient_exhaustion_reraises_last():
    n = [0]

    def fn():
        n[0] += 1
        raise RuntimeError(f"down{n[0]}")

    try:
        call_with_retry(fn, classify=_classify, max_attempts=3, sleep_fn=lambda s: None, jitter=lambda c: c)
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "down3" in str(e)  # last exception
    assert n[0] == 3  # exactly max_attempts total attempts


def test_backoff_cap_respected():
    sleeps = []

    def fn():
        raise RuntimeError("x")

    try:
        call_with_retry(fn, classify=_classify, max_attempts=6, backoff_base_sec=1.0,
                        backoff_cap_sec=4.0, sleep_fn=sleeps.append, jitter=lambda cap: cap)
    except RuntimeError:
        pass
    # caps: 1,2,4,4,4 (min(1*2^k,4)) over 5 sleeps (6 attempts)
    assert sleeps == [1.0, 2.0, 4.0, 4.0, 4.0], sleeps


def test_full_jitter_bounds():
    for cap in (0.0, 0.5, 8.0):
        for _ in range(20):
            v = full_jitter(cap)
            assert 0.0 <= v <= cap


def main() -> int:
    failed = 0
    n = 0
    for name, obj in list(globals().items()):
        if not name.startswith("test_"):
            continue
        n += 1
        try:
            obj()
            print(f"  [OK] {name}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [ERR] {name}: {e!r}")
    if failed:
        print(f"\n{failed}/{n} failed")
        return 1
    print(f"\n[OK] {n} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
