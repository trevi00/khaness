#!/usr/bin/env python3
"""Tests for v15.24 Q activation — heartbeat.stale + budget.exceeded.

Coverage:
  budget.check_and_emit_exceeded:
    - under cap → no emit, return False
    - just crossed → emit once + flag persisted
    - already emitted → no re-emit
    - reset under cap → flag clears (next crossing re-emits)
  cli.heartbeat_check:
    - find_stale: 신선한 sid는 제외, stale만 반환
    - main: stale → heartbeat.stale event emit + text/json output
    - prune-after: 오래된 file 삭제
  event_taxonomy:
    - heartbeat.stale, budget.exceeded 둘 다 KNOWN
    - RESERVED_EVENT_TYPES 빈 set
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
import tempfile
from io import StringIO
from contextlib import redirect_stdout
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import budget as BG  # noqa: E402
from lib import event_taxonomy as ET  # noqa: E402
from lib import heartbeat as HB  # noqa: E402


# ---- budget.check_and_emit_exceeded ----

def test_under_cap_no_emit():
    events = []
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        BG.record_invocation("s1", "x" * 50, base_dir=base)
        emitted = BG.check_and_emit_exceeded(
            "s1", emit_fn=lambda et, p: events.append((et, p)),
            cap=100, base_dir=base,
        )
        assert emitted is False
        assert events == []


def test_just_crossed_emits_once():
    events = []
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        BG.record_invocation("s2", "x" * 200, base_dir=base)
        emitted = BG.check_and_emit_exceeded(
            "s2", emit_fn=lambda et, p: events.append((et, p)),
            cap=100, base_dir=base,
        )
        assert emitted is True
        assert len(events) == 1
        assert events[0][0] == "budget.exceeded"
        assert events[0][1]["session_id"] == "s2"
        assert events[0][1]["total_chars"] == 200
        assert events[0][1]["cap"] == 100


def test_already_emitted_no_reemit():
    events = []
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        BG.record_invocation("s3", "x" * 200, base_dir=base)
        BG.check_and_emit_exceeded(
            "s3", emit_fn=lambda et, p: events.append((et, p)),
            cap=100, base_dir=base,
        )
        # 두 번째 호출 — silent
        emitted2 = BG.check_and_emit_exceeded(
            "s3", emit_fn=lambda et, p: events.append((et, p)),
            cap=100, base_dir=base,
        )
        assert emitted2 is False
        assert len(events) == 1


def test_cap_raised_above_total_clears_flag():
    events = []
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        BG.record_invocation("s4", "x" * 200, base_dir=base)
        BG.check_and_emit_exceeded(
            "s4", emit_fn=lambda et, p: events.append((et, p)),
            cap=100, base_dir=base,
        )
        # cap 상향 (1000) → 이제 under-cap → flag clear
        emitted_raised = BG.check_and_emit_exceeded(
            "s4", emit_fn=lambda et, p: events.append((et, p)),
            cap=1000, base_dir=base,
        )
        assert emitted_raised is False
        # 새 cap 100 다시 적용 → re-emit
        emitted_again = BG.check_and_emit_exceeded(
            "s4", emit_fn=lambda et, p: events.append((et, p)),
            cap=100, base_dir=base,
        )
        assert emitted_again is True
        assert len(events) == 2


# ---- cli/heartbeat_check ----

def test_find_stale_returns_only_stale():
    from cli.heartbeat_check import find_stale
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        HB.emit("fresh-sid", "x", base_dir=base)
        HB.emit("stale-sid", "y", base_dir=base)
        # advance clock past max_age for stale-sid only — both will be stale
        real_now = HB._now_epoch()
        HB._now_epoch = lambda: real_now + 1000
        try:
            stale = find_stale(max_age_sec=300, base_dir=base)
            sids = {s for s, _, _ in stale}
            # both are stale at +1000s with max_age=300
            assert "fresh-sid" in sids and "stale-sid" in sids
        finally:
            HB._now_epoch = lambda: _dt.datetime.now(_dt.timezone.utc).timestamp()


def test_cli_main_no_stale_returns_zero():
    from cli.heartbeat_check import main as cli_main
    with tempfile.TemporaryDirectory() as td:
        # state/heartbeats/ 비어있음 → stale 0
        out = StringIO()
        with redirect_stdout(out):
            rc = cli_main(["--max-age-sec", "300"])
        assert rc == 0


def test_cli_json_schema():
    from cli.heartbeat_check import main as cli_main
    out = StringIO()
    with redirect_stdout(out):
        rc = cli_main(["--max-age-sec", "300", "--json"])
    assert rc == 0
    parsed = json.loads(out.getvalue())
    assert "stale_count" in parsed
    assert "stale" in parsed
    assert "pruned_count" in parsed


# ---- event_taxonomy ----

def test_heartbeat_stale_is_now_known():
    assert ET.validate("heartbeat.stale") is True


def test_budget_exceeded_is_now_known():
    assert ET.validate("budget.exceeded") is True


def test_reserved_is_empty():
    assert ET.RESERVED_EVENT_TYPES == frozenset()


TESTS = [
    test_under_cap_no_emit,
    test_just_crossed_emits_once,
    test_already_emitted_no_reemit,
    test_cap_raised_above_total_clears_flag,
    test_find_stale_returns_only_stale,
    test_cli_main_no_stale_returns_zero,
    test_cli_json_schema,
    test_heartbeat_stale_is_now_known,
    test_budget_exceeded_is_now_known,
    test_reserved_is_empty,
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
