"""event_taxonomy — standardized event_type taxonomy (v15.22 K / v15.9 P1).

event_emit / event_store에 흘러가는 event_type 문자열을 표준화하여:
1. typo로 인한 silent drift 방지 (예: "breaker.opened" vs "breaker.open")
2. dashboard / consumer가 신뢰할 수 있는 enum 제공
3. 새 event_type 추가 시 본 lib 수정 강제 (PR 시 review point)

Schema:
  <domain>.<verb_or_state>

본 시점 alive event_types (v15.22):
  breaker.opened / .reopened / .closed / .probe_started   (D3, v15.10)
  ledger.verification_gap / .human_override                (D5, v15.10)
  ledger.semantic_suspicion                                (v15.13)
  ledger.cross_ref_suspicion                               (v15.21)

미래 reserved (다음 cycle에서 emit 예정):
  heartbeat.emitted / .stale                               (v15.22)
  budget.exceeded                                          (v15.20 후속)

Public API:
- KNOWN_EVENT_TYPES: frozenset[str]
- validate(event_type) → bool
- emit_with_validation(event_dict, emit_fn) → emit_fn 호출 후 unknown은 telemetry warn
"""
from __future__ import annotations

from typing import Callable


# v15.23 시점 alive event_types — emit 발생점 inventory.
# 새 event_type 추가 시 본 set에도 등록 필수 (validate가 unknown으로 분류).
KNOWN_EVENT_TYPES: frozenset[str] = frozenset({
    # D3 (composite breaker, v15.10)
    "breaker.opened",
    "breaker.reopened",
    "breaker.closed",
    "breaker.probe_started",
    # D5 (operator ledger, v15.10)
    "ledger.verification_gap",
    "ledger.human_override",
    # D2.5 (semantic layer, v15.13)
    "ledger.semantic_suspicion",
    # D2.6 (cross_ref, v15.21)
    "ledger.cross_ref_suspicion",
    # D2.7 (boilerplate file classifier, v15.25)
    "ledger.boilerplate_suspicion",
    # heartbeat (v15.23 — RESERVED에서 promote, agent_outcome_audit가 매 dispatch 후 emit)
    "heartbeat.emitted",
    # heartbeat.stale (v15.24 — cli/heartbeat_check가 list_stale 시 emit)
    "heartbeat.stale",
    # budget.exceeded (v15.24 — lib.budget.check_and_emit_exceeded once-per-crossing)
    "budget.exceeded",
    # v15.26 Ouroboros migration (debate-1778987814-41b475 D4)
    # S: lib/seed_lock — freeze + tamper detection
    "seed.locked",
    "seed.tamper_detected",
    # T: lib/ac_tree — single event with payload kind (matches ledger.* precedent)
    "ac.leaf_evaluated",
    # W: lib/wonder — 2-Strike strategic reflection + depth cap
    "wonder.triggered",
    "wonder.depth_exhausted",
    # RF: lib/reflect_feedback — addendum lineage emit
    "reflect.emitted",
})

# Reserved — 다음 cycle에서 emit 예정 (validate는 통과시키되 미사용 advisory)
# v15.24 시점: 모두 KNOWN으로 promote, RESERVED는 빈 set.
RESERVED_EVENT_TYPES: frozenset[str] = frozenset()


def validate(event_type: str) -> bool:
    """True iff event_type is in KNOWN_EVENT_TYPES (RESERVED는 False — 아직 emit 안 됨)."""
    return isinstance(event_type, str) and event_type in KNOWN_EVENT_TYPES


def is_reserved(event_type: str) -> bool:
    """True iff event_type is reserved for future emission."""
    return isinstance(event_type, str) and event_type in RESERVED_EVENT_TYPES


def emit_with_validation(
    event_type: str,
    payload: dict,
    emit_fn: Callable[[str, dict], None],
) -> None:
    """Call emit_fn(event_type, payload); telemetry-warn on unknown event_type.

    KNOWN → emit silently.
    RESERVED → emit + telemetry note (early adoption tracking).
    Unknown → emit + telemetry warn (potential typo).
    """
    try:
        emit_fn(event_type, payload)
    except Exception:
        pass  # fail-open: emit failure should not break upstream

    if validate(event_type):
        return  # KNOWN → no warning

    try:
        from .logging import log_telemetry
        if is_reserved(event_type):
            log_telemetry("event-taxonomy-reserved", {
                "event_type": event_type,
                "note": "reserved type emitted — promote to KNOWN_EVENT_TYPES",
            })
        else:
            log_telemetry("event-taxonomy-unknown", {
                "event_type": event_type,
                "note": "potential typo — add to KNOWN_EVENT_TYPES or fix call site",
            })
    except Exception:
        pass


__all__ = [
    "KNOWN_EVENT_TYPES",
    "RESERVED_EVENT_TYPES",
    "emit_with_validation",
    "is_reserved",
    "validate",
]
