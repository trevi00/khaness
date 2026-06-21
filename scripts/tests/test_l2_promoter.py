#!/usr/bin/env python3
"""Tests for lib.l2_promoter — L1→L2 projection.

W16 base (debate-1779328283-9076f2) + M25 re-activation (debate-1781649830-m25a01,
LOCK d42ac5e34ecf9dc7a5da558ca9880cfae1c9fa19):
  - D2 session-stable SPO: subject=f'{source_module}/{axis_or_none}',
    predicate=f'{event_type}__axis_{axis_or_none}', object=modal summary[:30];
    fact id injective per (source_module,axis,event_type,summary_prefix) + STABLE as
    support grows (support_count/distinct_sessions off-hash).
  - D3 eligible={orchestrator, skill_candidate}; work_unit_digest RESERVED.
  - D4 _group_key=(source_module,axis,event_type,summary_prefix30); value gate
    len>=3 AND distinct_session>=2 (suppresses single-session bursts).
  - D5 per-edge provenance (l1_entry_id, l1_correlation_id) carried.
  - D8 cascade unchanged (keys on l1_entry_id).
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _reset_modules() -> None:
    for m in list(sys.modules):
        if m.startswith(("lib.paths", "lib.l2_facts", "lib.l2_promoter", "lib.insight_index")):
            del sys.modules[m]


def _l1(id_, event_type, correlation_id, axis, summary, ts, source_module="engine.orchestrator"):
    return {
        "id": id_, "event_type": event_type, "correlation_id": correlation_id,
        "axis": axis, "summary": summary, "ts_unix_ms": ts,
        "source_module": source_module, "tags": [],
    }


def _with_home(fn):
    def wrap():
        with tempfile.TemporaryDirectory() as td:
            saved = os.environ.get("CLAUDE_HOME")
            os.environ["CLAUDE_HOME"] = td
            try:
                _reset_modules()
                fn()
            finally:
                if saved is None:
                    os.environ.pop("CLAUDE_HOME", None)
                else:
                    os.environ["CLAUDE_HOME"] = saved
    wrap.__name__ = fn.__name__
    return wrap


# ---- D3 eligibility ----

@_with_home
def test_eligibility_event_type_only():
    from lib.l2_promoter import project_l1_to_l2
    # 3 skill_candidate across 3 DISTINCT sessions (s1,s2,s3) -> fires; sentinel ineligible.
    l1 = [
        _l1("d1", "skill_candidate", "s1", None, "x", 1),
        _l1("d2", "skill_candidate", "s2", None, "x", 2),
        _l1("d3", "skill_candidate", "s3", None, "x", 3),
        _l1("o1", "__test_only_never_eligible__", "t1", None, "y", 10),
        _l1("o2", "__test_only_never_eligible__", "t2", None, "y", 11),
        _l1("o3", "__test_only_never_eligible__", "t3", None, "y", 12),
    ]
    facts = project_l1_to_l2(l1)
    assert len(facts) == 1
    assert facts[0]["event_type"] == "skill_candidate"
    assert facts[0]["subject"] == "engine.orchestrator/none"  # M25: source_module/axis


@_with_home
def test_orchestrator_now_eligible():
    """M25: orchestrator admitted; cross-session completion pattern fires."""
    from lib.l2_promoter import project_l1_to_l2
    l1 = [_l1(f"o{i}", "orchestrator", f"orch-{i}", "completion", "verdict=complete", 10 + i)
          for i in range(4)]
    facts = project_l1_to_l2(l1)
    assert len(facts) == 1
    assert facts[0]["subject"] == "engine.orchestrator/completion"
    assert facts[0]["predicate"] == "orchestrator__axis_completion"
    assert facts[0]["object"] == "verdict=complete"
    assert facts[0]["support_count"] == 4


@_with_home
def test_work_unit_digest_reserved_not_eligible():
    from lib.l2_promoter import project_l1_to_l2, _ELIGIBLE_EVENT_TYPES, _RESERVED_FUTURE_CLASSES
    assert "work_unit_digest" in _RESERVED_FUTURE_CLASSES
    assert "work_unit_digest" not in _ELIGIBLE_EVENT_TYPES
    l1 = [_l1(f"w{i}", "work_unit_digest", f"s{i}", "work_unit", "digest", i) for i in range(4)]
    assert project_l1_to_l2(l1) == []  # not eligible -> no facts


# ---- D4 value gate + grouping ----

@_with_home
def test_value_gate_suppresses_single_session_burst():
    """M25 D4: 3 members but all ONE session (same correlation_id) -> distinct_session=1 -> suppressed."""
    from lib.l2_promoter import project_l1_to_l2
    l1 = [_l1(f"a{i}", "skill_candidate", "SAME-SID", None, "x", i) for i in range(5)]
    assert project_l1_to_l2(l1) == []  # len>=3 but distinct_session=1 < 2


@_with_home
def test_threshold_3_and_distinct_sessions():
    from lib.l2_promoter import project_l1_to_l2
    two = [_l1("a1", "skill_candidate", "s1", "완성도", "x", 1),
           _l1("a2", "skill_candidate", "s2", "완성도", "x", 2)]
    assert project_l1_to_l2(two) == []                       # len 2 < 3
    three = two + [_l1("a3", "skill_candidate", "s3", "완성도", "x", 3)]
    assert len(project_l1_to_l2(three)) == 1                  # 3 entries, 3 sessions


@_with_home
def test_group_key_separates_by_axis_and_summary():
    """Different axis OR different summary_prefix -> distinct facts."""
    from lib.l2_promoter import project_l1_to_l2
    l1 = []
    for axis in ["완성도", "안정"]:
        for i in range(3):
            l1.append(_l1(f"{axis}-{i}", "skill_candidate", f"s{axis}{i}", axis, f"sum-{axis}", 10 + i))
    facts = project_l1_to_l2(l1)
    assert len(facts) == 2
    preds = {f["predicate"] for f in facts}
    assert any("완성도" in p for p in preds) and any("안정" in p for p in preds)


@_with_home
def test_complete_and_escalate_are_distinct_facts():
    """Same (module,axis,event_type) but different summary_prefix -> 2 injective facts."""
    from lib.l2_promoter import project_l1_to_l2
    l1 = ([_l1(f"c{i}", "orchestrator", f"orch-c{i}", "completion", "verdict=complete", i) for i in range(3)]
          + [_l1(f"e{i}", "orchestrator", f"orch-e{i}", "completion", "verdict=escalate", 100 + i) for i in range(3)])
    facts = project_l1_to_l2(l1)
    assert len(facts) == 2
    objects = {f["object"] for f in facts}
    assert objects == {"verdict=complete", "verdict=escalate"}


# ---- D2 idempotency (the gen-2 Critic's blocker) ----

@_with_home
def test_fact_spo_stable_as_support_grows():
    """M25 D2 idempotency: adding a 4th session must NOT change subject/predicate/object
    (so l2_facts.append computes the SAME fact id); only support_count grows."""
    from lib.l2_promoter import project_l1_to_l2
    three = [_l1(f"o{i}", "orchestrator", f"orch-{i}", "completion", "verdict=complete", i) for i in range(3)]
    four = three + [_l1("o3", "orchestrator", "orch-3", "completion", "verdict=complete", 3)]
    f3, f4 = project_l1_to_l2(three)[0], project_l1_to_l2(four)[0]
    assert (f3["subject"], f3["predicate"], f3["object"]) == (f4["subject"], f4["predicate"], f4["object"])
    assert f3["support_count"] == 3 and f4["support_count"] == 4  # only support grows (off-hash)


@_with_home
def test_determinism_and_permutation_invariance():
    from lib.l2_promoter import project_l1_to_l2
    base = [_l1(f"id{i}", "skill_candidate", f"s{i}", "완성도", "same", i) for i in range(5)]
    perm = list(base)
    random.shuffle(perm)

    def norm(f):
        return tuple(sorted((k, repr(v)) for k, v in f.items()))
    assert [norm(f) for f in project_l1_to_l2(base)] == [norm(f) for f in project_l1_to_l2(base)]
    assert [norm(f) for f in project_l1_to_l2(base)] == [norm(f) for f in project_l1_to_l2(perm)]


@_with_home
def test_ts_zero_is_deterministic_not_wallclock():
    """Regression (잔여-4 flake): a group whose earliest member ts == 0 must keep
    ts_unix_ms == 0, NOT fall through to wall-clock. The old
    `earliest_ts or int(time.time()*1000)` made two back-to-back calls disagree on
    ts whenever they straddled a millisecond, breaking D12 determinism ~1/30. ts=0
    is a legitimate (if unusual) timestamp; only a TRULY ts-less group may use the
    clock."""
    from lib.l2_promoter import project_l1_to_l2
    grp = [_l1(f"z{i}", "skill_candidate", f"s{i}", "완성도", "same", 0) for i in range(3)]
    f1 = project_l1_to_l2(grp)[0]
    f2 = project_l1_to_l2(grp)[0]
    assert f1["ts_unix_ms"] == 0, f"earliest ts 0 must be preserved, got {f1['ts_unix_ms']}"
    assert f1["ts_unix_ms"] == f2["ts_unix_ms"], "two calls on identical input must agree on ts"


# ---- D5 per-edge provenance ----

@_with_home
def test_per_edge_provenance_carries_member_correlation_ids():
    from lib.l2_promoter import project_l1_to_l2
    l1 = [_l1(f"o{i}", "orchestrator", f"orch-{i}", "completion", "verdict=complete", i) for i in range(3)]
    fact = project_l1_to_l2(l1)[0]
    edges = dict(fact["_source_l1_edges"])  # {l1_id: correlation_id}
    assert edges == {"o0": "orch-0", "o1": "orch-1", "o2": "orch-2"}  # each edge its OWN cid


# ---- D8 cascade (unchanged; verify with distinct sessions) ----

def _seed_l1(insight_index, n, event_type="skill_candidate", axis="완성도"):
    insight_index._caller_module_name = lambda skip=2: "handlers.stop.learner"
    return [insight_index.append({
        "event_type": event_type, "summary": "x", "ts_unix_ms": 100 + i,
        "correlation_id": f"sess-{i}", "source_module": "engine.orchestrator",
        "axis": axis, "tags": [],
    }) for i in range(n)]


@_with_home
def test_promote_emits_with_per_edge_evidence():
    from lib import insight_index, l2_facts, l2_promoter
    _seed_l1(insight_index, 3)
    l2_facts._caller_module_name = lambda skip=2: "lib.l2_promoter"
    result = l2_promoter.promote_all()
    assert result["facts_emitted"] == 1 and result["evidence_edges_emitted"] == 3


@_with_home
def test_cascade_tier_a_all_retracted():
    from lib import insight_index, l2_facts, l2_promoter
    l1_ids = _seed_l1(insight_index, 3)
    l2_facts._caller_module_name = lambda skip=2: "lib.l2_promoter"
    l2_promoter.promote_all()
    insight_index._caller_module_name = lambda skip=2: "handlers.stop.learner"
    for lid in l1_ids:
        insight_index.retract(lid, reason="test")
    cascade = l2_promoter.recompute_cascades()
    assert cascade["cascade_retracted"] == 1 and cascade["support_below_threshold_retracted"] == 0
    l2_facts._caller_module_name = lambda skip=2: "handlers.session.init"
    assert l2_facts.query() == []


@_with_home
def test_cascade_tier_b_support_below_threshold():
    from lib import insight_index, l2_facts, l2_promoter
    l1_ids = _seed_l1(insight_index, 3)
    l2_facts._caller_module_name = lambda skip=2: "lib.l2_promoter"
    l2_promoter.promote_all()
    insight_index._caller_module_name = lambda skip=2: "handlers.stop.learner"
    insight_index.retract(l1_ids[0], reason="test")
    cascade = l2_promoter.recompute_cascades()
    assert cascade["cascade_retracted"] == 0 and cascade["support_below_threshold_retracted"] == 1


@_with_home
def test_cascade_tier_c_lazy_no_retraction():
    from lib import insight_index, l2_facts, l2_promoter
    l1_ids = _seed_l1(insight_index, 4)
    l2_facts._caller_module_name = lambda skip=2: "lib.l2_promoter"
    l2_promoter.promote_all()
    insight_index._caller_module_name = lambda skip=2: "handlers.stop.learner"
    insight_index.retract(l1_ids[0], reason="test")  # live=3 still >= threshold
    cascade = l2_promoter.recompute_cascades()
    assert cascade["cascade_retracted"] == 0 and cascade["support_below_threshold_retracted"] == 0


@_with_home
def test_promote_idempotent_no_new_fact_id_on_rerun():
    """Re-promote with same L1 -> same fact id (D9). support_count grows off-hash."""
    from lib import insight_index, l2_facts, l2_promoter
    _seed_l1(insight_index, 3)
    l2_facts._caller_module_name = lambda skip=2: "lib.l2_promoter"
    l2_promoter.promote_all()
    l2_facts._caller_module_name = lambda skip=2: "handlers.session.init"
    ids1 = {f["id"] for f in l2_facts.query()}
    l2_facts._caller_module_name = lambda skip=2: "lib.l2_promoter"
    l2_promoter.promote_all()  # rerun, no L1 change
    l2_facts._caller_module_name = lambda skip=2: "handlers.session.init"
    ids2 = {f["id"] for f in l2_facts.query()}
    assert ids1 == ids2 and len(ids1) == 1  # stable id, no churn


# ---- D7 read-side insight floor ----

@_with_home
def test_is_insight_floor():
    from lib import insight_index, l2_facts, l2_promoter
    _seed_l1(insight_index, 3)  # 3 distinct sessions
    l2_facts._caller_module_name = lambda skip=2: "lib.l2_promoter"
    l2_promoter.promote_all()
    l2_facts._caller_module_name = lambda skip=2: "handlers.session.init"
    facts = l2_facts.query()
    assert facts and l2_facts.is_insight_floor(facts[0]) is True  # 3 support, 3 sessions
    # a fact with no id / no evidence -> False
    assert l2_facts.is_insight_floor({}) is False
    assert l2_facts.is_insight_floor({"id": "nonexistent"}) is False


@_with_home
def test_schema_version_monotonic():
    from lib import insight_index, l2_facts, l2_promoter
    _seed_l1(insight_index, 3)
    l2_facts._caller_module_name = lambda skip=2: "lib.l2_promoter"
    l2_promoter.promote_all()
    l2_facts._caller_module_name = lambda skip=2: "handlers.session.init"
    facts = l2_facts.query()
    assert facts and all(f.get("schema_version") == "1" for f in facts)


TESTS = [
    test_eligibility_event_type_only,
    test_orchestrator_now_eligible,
    test_work_unit_digest_reserved_not_eligible,
    test_value_gate_suppresses_single_session_burst,
    test_threshold_3_and_distinct_sessions,
    test_group_key_separates_by_axis_and_summary,
    test_complete_and_escalate_are_distinct_facts,
    test_fact_spo_stable_as_support_grows,
    test_determinism_and_permutation_invariance,
    test_ts_zero_is_deterministic_not_wallclock,
    test_per_edge_provenance_carries_member_correlation_ids,
    test_promote_emits_with_per_edge_evidence,
    test_cascade_tier_a_all_retracted,
    test_cascade_tier_b_support_below_threshold,
    test_cascade_tier_c_lazy_no_retraction,
    test_promote_idempotent_no_new_fact_id_on_rerun,
    test_is_insight_floor,
    test_schema_version_monotonic,
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
