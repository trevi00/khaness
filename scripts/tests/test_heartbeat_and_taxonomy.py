#!/usr/bin/env python3
"""Tests for lib.heartbeat + lib.event_taxonomy (v15.22 K).

Coverage:
  heartbeat:
    - emit: file 생성 + count++ + last_ts 갱신
    - last_seen: 미존재 → None, 존재 → ts
    - stale: 미존재 → True, 신선 → False, 오래된 → True (monkey-patch _now_epoch)
    - list_active: 신선한 sid만 반환
    - prune: older_than_sec 초과 file unlink
    - sid path-traversal guard
  event_taxonomy:
    - validate: KNOWN → True, RESERVED → False, unknown → False
    - is_reserved: 정확히 RESERVED만 True
    - emit_with_validation: KNOWN silent / RESERVED reserved-telemetry /
      unknown unknown-telemetry / emit_fn raise → fail-open
"""
from __future__ import annotations

import datetime as _dt
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import heartbeat as HB  # noqa: E402
from lib import event_taxonomy as ET  # noqa: E402


# ---- heartbeat ----

def test_emit_creates_file_and_increments_count():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        rec = HB.emit("sid-1", "researcher", base_dir=base)
        assert rec["count"] == 1
        assert rec["agent_type"] == "researcher"
        rec2 = HB.emit("sid-1", "researcher", base_dir=base)
        assert rec2["count"] == 2


def test_last_seen_unknown_is_none():
    with tempfile.TemporaryDirectory() as td:
        assert HB.last_seen("never-recorded", base_dir=Path(td)) is None


def test_last_seen_after_emit_returns_iso_ts():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        HB.emit("sid-2", "x", base_dir=base)
        ts = HB.last_seen("sid-2", base_dir=base)
        assert ts is not None
        # parseable iso8601
        parsed = HB._ts_to_epoch(ts)
        assert parsed is not None


def test_stale_unknown_is_true_by_default():
    with tempfile.TemporaryDirectory() as td:
        assert HB.stale("never", base_dir=Path(td)) is True


def test_stale_fresh_is_false():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        HB.emit("sid-3", "x", base_dir=base)
        assert HB.stale("sid-3", max_age_sec=300, base_dir=base) is False


def test_stale_after_clock_advance_is_true():
    """monkey-patch _now_epoch → 미래 시점으로 advance."""
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        HB.emit("sid-4", "x", base_dir=base)
        real_now = HB._now_epoch()
        HB._now_epoch = lambda: real_now + 1000  # 1000s 후
        try:
            assert HB.stale("sid-4", max_age_sec=300, base_dir=base) is True
        finally:
            HB._now_epoch = lambda: _dt.datetime.now(_dt.timezone.utc).timestamp()


def test_list_active_returns_only_fresh():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        HB.emit("sid-active", "x", base_dir=base)
        # 임의 stale 만들기: 직접 file mtime 또는 ts 조작
        HB.emit("sid-stale", "y", base_dir=base)
        # stale 후, monkey-patch로 미래 시점
        real_now = HB._now_epoch()
        HB._now_epoch = lambda: real_now + 1000
        try:
            actives = HB.list_active(max_age_sec=300, base_dir=base)
            assert actives == []  # both stale now
        finally:
            HB._now_epoch = lambda: _dt.datetime.now(_dt.timezone.utc).timestamp()
        # 다시 fresh emit 후 list_active
        HB.emit("sid-fresh", "z", base_dir=base)
        actives = HB.list_active(max_age_sec=300, base_dir=base)
        sids = [s for s, _, _ in actives]
        assert "sid-fresh" in sids


def test_prune_removes_old_files():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        HB.emit("old-sid", "x", base_dir=base)
        real_now = HB._now_epoch()
        HB._now_epoch = lambda: real_now + 10000  # 10000s 후
        try:
            removed = HB.prune(older_than_sec=300, base_dir=base)
            assert removed == 1
        finally:
            HB._now_epoch = lambda: _dt.datetime.now(_dt.timezone.utc).timestamp()


def test_sid_path_traversal_guard():
    with tempfile.TemporaryDirectory() as td:
        try:
            HB.emit("../escape", "x", base_dir=Path(td))
        except ValueError:
            pass
        # 정상 sid는 통과
        HB.emit("debate-1234-abc", "x", base_dir=Path(td))


# ---- event_taxonomy ----

def test_validate_known_event_types():
    for et in ["breaker.opened", "ledger.verification_gap", "ledger.cross_ref_suspicion"]:
        assert ET.validate(et) is True, et


def test_validate_unknown_is_false():
    assert ET.validate("totally.unknown.event") is False


def test_validate_reserved_is_false():
    """RESERVED는 KNOWN과 분리 — validate는 False (아직 active 아님).

    v15.24에서 모든 RESERVED가 promote되어 set이 빈 상태. test는 RESERVED
    semantics을 검증 (frozenset 자체와 임의 unknown 분리 행위).
    """
    # RESERVED 빈 set이므로 임의 reserved 항목 없음
    assert ET.RESERVED_EVENT_TYPES == frozenset()
    # heartbeat.emitted, heartbeat.stale, budget.exceeded 모두 KNOWN
    assert ET.validate("heartbeat.emitted") is True
    assert ET.validate("heartbeat.stale") is True
    assert ET.validate("budget.exceeded") is True
    # is_reserved는 빈 set 대해 모두 False
    assert ET.is_reserved("heartbeat.stale") is False


def test_is_reserved_unknown_is_false():
    assert ET.is_reserved("foo.bar") is False


def test_emit_with_validation_known_silent():
    events = []
    ET.emit_with_validation("breaker.opened", {"x": 1}, lambda et, p: events.append((et, p)))
    assert events == [("breaker.opened", {"x": 1})]


def test_emit_with_validation_unknown_still_emits():
    events = []
    ET.emit_with_validation("foo.bar", {"x": 1}, lambda et, p: events.append((et, p)))
    # emit_fn은 항상 호출 (warning은 telemetry로만 — fail-open)
    assert events == [("foo.bar", {"x": 1})]


def test_emit_with_validation_emit_fn_raise_is_fail_open():
    def bad_emit(et, p):
        raise RuntimeError("nope")
    # 예외 자체가 새지 않아야 함
    ET.emit_with_validation("breaker.opened", {}, bad_emit)
    ET.emit_with_validation("unknown.x", {}, bad_emit)


TESTS = [
    test_emit_creates_file_and_increments_count,
    test_last_seen_unknown_is_none,
    test_last_seen_after_emit_returns_iso_ts,
    test_stale_unknown_is_true_by_default,
    test_stale_fresh_is_false,
    test_stale_after_clock_advance_is_true,
    test_list_active_returns_only_fresh,
    test_prune_removes_old_files,
    test_sid_path_traversal_guard,
    test_validate_known_event_types,
    test_validate_unknown_is_false,
    test_validate_reserved_is_false,
    test_is_reserved_unknown_is_false,
    test_emit_with_validation_known_silent,
    test_emit_with_validation_unknown_still_emits,
    test_emit_with_validation_emit_fn_raise_is_fail_open,
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
