#!/usr/bin/env python3
"""Tests for lib/telemetry_read.py — read-side telemetry helpers."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _redirect_telemetry_dir(tmp: Path) -> None:
    from lib import paths as P
    from lib import telemetry_read as T
    P.TELEMETRY_DIR = tmp / "telemetry"
    T.TELEMETRY_DIR = P.TELEMETRY_DIR
    P.TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_iter_events_missing_file_yields_nothing():
    with tempfile.TemporaryDirectory() as td:
        _redirect_telemetry_dir(Path(td))
        from lib.telemetry_read import iter_events
        assert list(iter_events("nonexistent")) == []


def test_iter_events_empty_file_yields_nothing():
    with tempfile.TemporaryDirectory() as td:
        _redirect_telemetry_dir(Path(td))
        target = Path(td) / "telemetry" / "empty.jsonl"
        target.write_text("", encoding="utf-8")
        from lib.telemetry_read import iter_events
        assert list(iter_events("empty")) == []


def test_iter_events_yields_valid_records():
    with tempfile.TemporaryDirectory() as td:
        _redirect_telemetry_dir(Path(td))
        target = Path(td) / "telemetry" / "x.jsonl"
        _write_jsonl(target, [{"a": 1}, {"b": 2}, {"c": 3}])
        from lib.telemetry_read import iter_events
        records = list(iter_events("x"))
        assert records == [{"a": 1}, {"b": 2}, {"c": 3}]


def test_iter_events_skips_malformed_lines():
    with tempfile.TemporaryDirectory() as td:
        _redirect_telemetry_dir(Path(td))
        target = Path(td) / "telemetry" / "x.jsonl"
        target.write_text(
            '{"valid": 1}\nnot-json\n{"valid": 2}\n',
            encoding="utf-8",
        )
        from lib.telemetry_read import iter_events
        records = list(iter_events("x"))
        assert records == [{"valid": 1}, {"valid": 2}]


def test_iter_events_skips_blank_lines():
    with tempfile.TemporaryDirectory() as td:
        _redirect_telemetry_dir(Path(td))
        target = Path(td) / "telemetry" / "x.jsonl"
        target.write_text(
            '{"a": 1}\n\n\n{"b": 2}\n',
            encoding="utf-8",
        )
        from lib.telemetry_read import iter_events
        assert list(iter_events("x")) == [{"a": 1}, {"b": 2}]


def test_count_unreviewed_triggers_zero_when_no_telemetry():
    with tempfile.TemporaryDirectory() as td:
        _redirect_telemetry_dir(Path(td))
        from lib.telemetry_read import count_unreviewed_triggers
        assert count_unreviewed_triggers() == 0


def test_count_unreviewed_triggers_counts_strict_design_only():
    with tempfile.TemporaryDirectory() as td:
        _redirect_telemetry_dir(Path(td))
        # Mock the AdvisoryAck registry to return empty ack set
        from lib import advisory_ack
        original = advisory_ack.REGISTRY.get("strict_design")

        class FakeAck:
            def load(self):
                return set()

        advisory_ack.REGISTRY["strict_design"] = FakeAck()
        try:
            target = Path(td) / "telemetry" / "debate-triggers.jsonl"
            _write_jsonl(target, [
                {"strict_design": True, "ts": "2026-05-09T00:00:00Z"},
                {"strict_design": False, "ts": "2026-05-09T00:00:01Z"},
                {"strict_design": True, "ts": "2026-05-09T00:00:02Z"},
            ])
            from lib.telemetry_read import count_unreviewed_triggers
            assert count_unreviewed_triggers() == 2  # 2 strict_design=True
        finally:
            if original is not None:
                advisory_ack.REGISTRY["strict_design"] = original


def test_count_unreviewed_triggers_excludes_acked():
    with tempfile.TemporaryDirectory() as td:
        _redirect_telemetry_dir(Path(td))
        from lib import advisory_ack
        original = advisory_ack.REGISTRY.get("strict_design")

        class FakeAck:
            def load(self):
                return {"2026-05-09T00:00:00Z"}  # one ts acked

        advisory_ack.REGISTRY["strict_design"] = FakeAck()
        try:
            target = Path(td) / "telemetry" / "debate-triggers.jsonl"
            _write_jsonl(target, [
                {"strict_design": True, "ts": "2026-05-09T00:00:00Z"},
                {"strict_design": True, "ts": "2026-05-09T00:00:01Z"},
            ])
            from lib.telemetry_read import count_unreviewed_triggers
            assert count_unreviewed_triggers() == 1  # 1 acked, 1 unreviewed
        finally:
            if original is not None:
                advisory_ack.REGISTRY["strict_design"] = original


TESTS = [
    test_iter_events_missing_file_yields_nothing,
    test_iter_events_empty_file_yields_nothing,
    test_iter_events_yields_valid_records,
    test_iter_events_skips_malformed_lines,
    test_iter_events_skips_blank_lines,
    test_count_unreviewed_triggers_zero_when_no_telemetry,
    test_count_unreviewed_triggers_counts_strict_design_only,
    test_count_unreviewed_triggers_excludes_acked,
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
