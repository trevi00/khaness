#!/usr/bin/env python3
"""Unit tests for lib.timefmt.iso_to_epoch (harness-full-review rank 4 dedup)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.timefmt import iso_to_epoch


def test_none_on_empty_and_nonstr():
    assert iso_to_epoch("") is None
    assert iso_to_epoch(None) is None
    assert iso_to_epoch(123) is None
    assert iso_to_epoch("not a timestamp") is None


def test_t_separated_naive():
    assert iso_to_epoch("2026-05-17T12:34:56") == datetime(2026, 5, 17, 12, 34, 56).timestamp()


def test_t_separated_fractional():
    assert iso_to_epoch("2026-05-17T12:34:56.789") == datetime(2026, 5, 17, 12, 34, 56, 789000).timestamp()


def test_space_separated_naive():
    # The shape observe.py had and action_evolver/sensor_anomaly LACKED.
    assert iso_to_epoch("2026-05-17 12:34:56") == datetime(2026, 5, 17, 12, 34, 56).timestamp()


def test_tz_offset_regression_observe_gap():
    # The shape observe.py LACKED (silently dropped). Must now parse to the absolute epoch.
    got = iso_to_epoch("2026-05-17T02:55:04+00:00")
    assert got is not None
    assert got == datetime(2026, 5, 17, 2, 55, 4, tzinfo=timezone.utc).timestamp()


def test_tz_offset_fractional():
    got = iso_to_epoch("2026-05-17T02:55:04.500000+00:00")
    assert got is not None
    assert got == datetime(2026, 5, 17, 2, 55, 4, 500000, tzinfo=timezone.utc).timestamp()


def test_trailing_z_stripped():
    assert iso_to_epoch("2026-05-17T12:34:56Z") == datetime(2026, 5, 17, 12, 34, 56).timestamp()


TESTS = [
    test_none_on_empty_and_nonstr,
    test_t_separated_naive,
    test_t_separated_fractional,
    test_space_separated_naive,
    test_tz_offset_regression_observe_gap,
    test_tz_offset_fractional,
    test_trailing_z_stripped,
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
