"""l2_promoter — L1 Insight Index → L2 Global Facts projection (S2, debate-1779328283-9076f2 LOCK sha1 59cc1bab06a1af2019763d414cf345a2db7626df).

Implements D3+D4+D8 LOCK:
  D3 — eligibility filter: event_type IN {wonder, debate, evaluator}
       (axis filter DROPPED — axis is Optional[str] per insight_index.py:238-240;
        wonder/debate writers legitimately emit axis=None per gen-3 condition #1)
  D4 — pure deterministic projection: group L1 by (correlation_id, axis, event_type);
       emit fact iff len(group) >= 3; subject=correlation_id,
       predicate=f'{event_type}_axis_{axis_or_none}', object=mode(summary[:30] for e);
       stdlib only (collections.Counter), NO LLM
  D8 — 3-tier retraction cascade:
       (a) all contributors retracted   → emit L2 retraction (cascade)
       (b) support falls below 3        → emit L2 retraction (support_below_threshold)
       (c) remaining >= 3              → do nothing (lazy)

Public surface:
  project_l1_to_l2(l1_entries: list[dict]) -> list[dict]
      Pure function. Same input → same output (D12 determinism invariant).
      Output is candidate L2 records; caller writes via lib.l2_facts.append.
  promote_all() -> dict
      Orchestrator: reads L1 via insight_index.query, projects, writes new facts
      via lib.l2_facts.append, links evidence via add_evidence, runs cascade.
      Returns {facts_emitted, evidence_edges_emitted, cascade_retracted}.
  recompute_cascades() -> dict
      Standalone D8 cascade pass. Called by promote_all and optionally by
      cron when L1 retraction load is the only delta.

Design constraints:
  - lib.l2_promoter is a whitelisted writer of lib.l2_facts (D5 LOCK)
  - lib.l2_promoter is a whitelisted importer of lib.insight_index
    (W16 D17 — added to validators/insight_index_importer_whitelist.py)
  - NO LLM dependency: pure stdlib (collections.Counter)
  - Idempotency (D9): re-running with same L1 input produces same L2 ids;
    repeated append of identical record is a no-op at the latest_wins layer
    of lib.l2_facts.query
"""
from __future__ import annotations

import time
from collections import Counter, defaultdict
from typing import Any

from . import insight_index, l2_facts


# D3 LOCK — eligible L1 event types. NO axis filter (axis optional per
# insight_index.py:238-240; wonder/debate writers legitimately emit None).
#
# W17 D3 AMENDMENT (debate-1779376939-ff5cbe converged gen 3, sha1
# f570e213a9f92403dc7ed68516f2dd331727248e): ACTIVE-only set split from
# documentary RESERVED_FUTURE_CLASSES below. Original W16 D3 LOCK set
# {wonder, debate, evaluator} was a design-time guess; wave-16-postimpl
# production grep found ZERO overlap with actual L1 writers (learner,
# orchestrator, skill_candidate). Of the three, only skill_candidate
# uses a correlation_id (reflection_fingerprint per W14 D5_W2 LOCK) that
# can repeat across sessions to reach threshold=3. orchestrator/learner
# use correlation_id=session_id (unique-per-session) — group-of-1, never
# fires. RESERVED set documents forward-compat without admitting these
# classes to eligibility (avoids dead-capacity storage growth).
#
# M25 AMENDMENT (debate-1781649830-m25a01 converged gen 3, LOCK sha1
# d42ac5e34ecf9dc7a5da558ca9880cfae1c9fa19): admit 'orchestrator'. Live L1
# measurement showed _ELIGIBLE={skill_candidate} had ZERO live entries (L2=0
# facts ever) while the real high-volume writers were orchestrator(20)+
# work_unit_digest(46). The W17 reserved-rationale for orchestrator ('needs
# multi-session correlation_id') is DISSOLVED by the M25 D2/D4 re-key: _group_key
# no longer keys on correlation_id (the session-scoping bug), so orchestrator's
# unique-per-session sids group cross-session on (source_module, axis, event_type,
# summary_prefix). work_unit_digest stays RESERVED — its only repeating cluster is
# single-session, so the distinct_session>=2 value gate suppresses it = dead
# eligibility (anti-dead-capacity discipline preserved).
_ELIGIBLE_EVENT_TYPES: frozenset[str] = frozenset({
    "skill_candidate",
    "orchestrator",
})

# RESERVED: forward-compat docs only; do NOT import into eligibility
# predicates. Promotion of any RESERVED class to ACTIVE requires a
# paired change: either (a) multi-session correlation_id scheme for the
# class's writer, or (b) _group_key modification to avoid the group-of-1
# trap. Until then, listing here is documentation only.
#
# Per-class rationale (W17 D3_AMEND_RETENTION):
#   wonder            — cross-session pattern mining, needs correlation_id schema
#   debate            — multi-gen artifacts, needs _group_key for session collapse
#   evaluator         — E2 verdict streams, blocked by L1 D6 judge-generator isolation
#                       (lib/evaluator_dispatcher.py forbidden from insight_index.append)
#   orchestrator      — autopilot phase events, correlation_id=sess.sid unique-per-session
#                       (engine/orchestrator.py:586); stays RESERVED until multi-session
#                       correlation_id lands
#   learner           — skill-graph deltas, correlation_id=session_id same constraint
#                       (handlers/stop/learner.py:130)
_RESERVED_FUTURE_CLASSES: frozenset[str] = frozenset({
    "wonder", "debate", "evaluator", "learner",
    # M25: work_unit_digest reserved (single-session clusters → distinct_session>=2
    # gate suppresses → admitting it = dead eligibility). orchestrator REMOVED from
    # reserved (now ACTIVE via the M25 re-key).
    "work_unit_digest",
})

# W17 D3_AMEND_TESTS — module-load-time guard. Uses RuntimeError (NOT
# `assert`) so the meta-check survives `python -O` / PYTHONOPTIMIZE=1.
# Test fixtures use this sentinel as the ineligible counter-example;
# the sentinel must never be promoted to ACTIVE.
_TEST_SENTINEL_NEVER_ELIGIBLE: str = "__test_only_never_eligible__"
if _TEST_SENTINEL_NEVER_ELIGIBLE in _ELIGIBLE_EVENT_TYPES:
    raise RuntimeError(
        f"D3 LOCK invariant violated: test sentinel "
        f"{_TEST_SENTINEL_NEVER_ELIGIBLE!r} leaked into _ELIGIBLE_EVENT_TYPES; "
        f"see W17 debate-1779376939-ff5cbe D3_AMEND_TESTS."
    )

# D4 LOCK — minimum group size to emit a fact. Mirrors the streak threshold
# at cron/check_l2_promotion.py:45 (_P99_CONSECUTIVE_TRIGGER=3) for principle
# consistency: 3 = "pattern", < 3 = "coincidence".
_GROUP_THRESHOLD: int = 3

# M25 D4 (debate-1781649830-m25a01) — value gate: a promoted fact must recur across
# >= this many DISTINCT sessions, not be a single-session burst (the cross-session
# "global fact" contract). For orchestrator (correlation_id == sid) this is subsumed
# by _GROUP_THRESHOLD; it is load-bearing for shared-session classes (skill_candidate
# fingerprints, '<sid>-wu') where one session can contribute multiple members.
_MIN_DISTINCT_SESSIONS: int = 2

# Truncation cap for summary used as object material. Bounded so identical
# semantic content with trivial suffix differences still collapses to one
# fact at projection time.
_SUMMARY_PREFIX_CHARS: int = 30


def _group_key(entry: dict) -> tuple[str, str | None, str, str]:
    """M25 D4 LOCK group key — (source_module, axis, event_type, summary_prefix30).

    Re-keyed off correlation_id (the session-scoping bug that forced group-of-1 for
    unique-per-session writers like orchestrator) onto a SESSION-STABLE tuple, so the
    same recurring pattern collapses ACROSS sessions to one fact id (D9 cross-session
    identity). summary_prefix is IN the key so distinct summaries under the same
    module/axis (e.g. orchestrator verdict=complete vs verdict=escalate) become
    DISTINCT facts rather than one mode-collapsed fact.
    """
    return (
        entry.get("source_module", ""),
        entry.get("axis"),
        entry.get("event_type", ""),
        _summary_token(entry),
    )


def _session_of(entry: dict) -> str:
    """M25 D4 — session identity for the distinct_session value gate.

    For orchestrator the correlation_id IS the sid ('orch-<ts>-<hash>') so this is an
    identity map (distinct_session_count == group size there → the >=2 clause is
    subsumed by len>=3). For '<sid>-wu' (work_unit_digest) it strips the suffix to the
    sid. For other classes (skill_candidate reflection_fingerprint) it returns the
    correlation_id verbatim as the session proxy — load-bearing there because a
    fingerprint can recur within ONE session, so distinct_session<len de-tautologizes
    a single-session burst.
    """
    cid = entry.get("correlation_id", "") or ""
    if cid.endswith("-wu"):
        return cid[:-3]
    return cid


def _summary_token(entry: dict) -> str:
    """Stable token derived from L1 summary for D4 'object' modality.

    Uses first _SUMMARY_PREFIX_CHARS chars of summary — bounded, deterministic.
    Empty summary → empty string token (will collapse with siblings).
    """
    s = entry.get("summary", "")
    if not isinstance(s, str):
        return ""
    return s[:_SUMMARY_PREFIX_CHARS]


def _eligible(entry: dict) -> bool:
    """D3 LOCK eligibility predicate. event_type whitelist only, no axis gate."""
    return entry.get("event_type") in _ELIGIBLE_EVENT_TYPES


def project_l1_to_l2(l1_entries: list[dict]) -> list[dict]:
    """D4 LOCK — pure deterministic projection. Same input → same output.

    Algorithm:
      1. filter eligible (D3)
      2. group by (correlation_id, axis, event_type)
      3. for each group with len >= 3:
           subject   = correlation_id
           predicate = f'{event_type}__axis_{axis or "none"}'
           object    = mode of summary[:30] across the group (Counter.most_common(1))
           support_count = len(group)
           source_l1_ids = sorted([e['id'] for e in group])
           correlation_id (record field) = the group's correlation_id
      4. return list of candidate L2 records (caller persists via lib.l2_facts.append)

    Output deterministic for any permutation of input (group_key + sorted source_l1_ids).
    """
    if not isinstance(l1_entries, list):
        raise TypeError(f"l1_entries must be list, got {type(l1_entries).__name__}")

    groups: dict[tuple[str, str | None, str], list[dict]] = defaultdict(list)
    for e in l1_entries:
        if not isinstance(e, dict):
            continue
        if not _eligible(e):
            continue
        groups[_group_key(e)].append(e)

    facts: list[dict] = []
    # Sort group keys for output determinism (axis may be None, sort with key).
    def _sk(k: tuple[str, str | None, str, str]) -> tuple[str, str, str, str]:
        sm, axis, et, sp = k
        return (sm, axis or "", et, sp)

    for key in sorted(groups, key=_sk):
        members = groups[key]
        if len(members) < _GROUP_THRESHOLD:
            continue
        # M25 D4 value gate: a fact is a CROSS-SESSION pattern, not a single-session
        # burst. distinct_session_count = distinct _session_of() over the group.
        if len({_session_of(m) for m in members}) < _MIN_DISTINCT_SESSIONS:
            continue
        source_module, axis, event_type, summary_prefix = key
        # object = modal summary_prefix[:30]. All members share the key's prefix by
        # construction, so the mode IS that prefix — STABLE as support grows (the fact
        # id hashes subject+predicate+object only; support_count/distinct_sessions are
        # off-hash, derived read-side from evidence via lib.l2_facts.is_insight_floor).
        # Lexicographic tie-break keeps output permutation-invariant (D12 #1).
        tokens = [_summary_token(m) for m in members]
        counts = Counter(tokens)
        max_count = max(counts.values())
        most_common_token = sorted(t for t, c in counts.items() if c == max_count)[0]
        # M25 D5 per-edge provenance: (l1_entry_id, l1_correlation_id) pairs, ONE per
        # member (a fact now spans MANY correlation_ids, so a single shared cid would
        # mislabel all-but-one edge). Sorted by l1_entry_id for determinism.
        source_l1_edges = sorted(
            (m.get("id", ""), m.get("correlation_id", "") or "")
            for m in members if isinstance(m.get("id"), str)
        )
        member_cids = sorted(
            c for _, c in source_l1_edges if c
        )
        rep_cid = member_cids[0] if member_cids else (summary_prefix or source_module or "l2")
        # D12 determinism: distinguish "no member has a ts" from "the earliest ts IS
        # 0". The old `min(..., default=0)` + `earliest_ts or wallclock` collapsed
        # both, so a group whose earliest ts == 0 fell through to int(time.time())
        # and the record stopped being a pure function of its input (two back-to-back
        # project() calls could straddle a ms boundary → different ts → permutation/
        # determinism test flake). Real L1 ts are epoch-millis (never 0), so this only
        # ever bit ts=0 fixtures, but the contract is "same input → same output".
        _ts_vals = [m.get("ts_unix_ms") for m in members if isinstance(m.get("ts_unix_ms"), int)]
        earliest_ts = min(_ts_vals) if _ts_vals else None
        record = {
            "subject": f"{source_module}/{axis or 'none'}",
            "predicate": f"{event_type}__axis_{axis or 'none'}",
            "object": most_common_token,
            "object_datatype": "str",
            "ts_unix_ms": earliest_ts if earliest_ts is not None else int(time.time() * 1000),
            "support_count": len(members),
            "event_type": event_type,
            "correlation_id": rep_cid,  # representative (min); per-edge cids in evidence
            "source_module": "lib.l2_promoter",
            # transport-only (popped by promote_all before append):
            "_source_l1_edges": source_l1_edges,
        }
        facts.append(record)
    return facts


def promote_all() -> dict[str, Any]:
    """Run one full L1 → L2 promotion cycle.

    Sequence:
      1. read all unretracted L1 entries via insight_index.query (W16 whitelist OK)
      2. project_l1_to_l2 → candidate facts
      3. for each candidate: l2_facts.append → fact_id; for each source_l1_id:
         l2_facts.add_evidence(fact_id, l1_correlation_id, l1_entry_id)
      4. run recompute_cascades() — applies D8 3-tier cascade rule
      5. return counters: {facts_emitted, evidence_edges_emitted, cascade_retracted}

    Idempotent (D9): re-running with no L1 changes emits 0 new facts (existing
    facts have same content-hash id; latest-wins query already de-dups; we
    still write but the line-level duplication is collapsed at read time).

    Gate (deep-audit pass-2 rank 4 — BY DESIGN, not a missing gate): this function
    has NO token/caller gate, and that is correct. Per the L0 §Mutation table,
    'memory 추가/압축' (L1→L2 derivation) is the auto-OK class; only CRON EXECUTION
    is enable-cron-job-gated, and that token check lives in the cron WRAPPER
    (cron/run_l2_promotion.py), NOT here. Do NOT add a token assert inside this
    library function — it would duplicate the gate and break every legitimate
    in-process test/caller that derives L2 without a token. The self-supplied token
    in the cron wrapper is an accident/cron barrier, not an agent boundary
    (see ~/CLAUDE.md §Mutation honest threat-model).
    """
    l1_entries = insight_index.query(include_retracted=False, limit=None)
    candidates = project_l1_to_l2(l1_entries)
    facts_emitted = 0
    evidence_edges_emitted = 0
    for cand in candidates:
        # M25 D5: per-edge (l1_entry_id, l1_correlation_id) pairs — a fact now spans
        # MANY correlation_ids, so each evidence edge carries its OWN member's cid
        # (the old shared-cid write mislabeled all-but-one edge).
        source_l1_edges = cand.pop("_source_l1_edges", [])
        try:
            fact_id = l2_facts.append(cand)
        except l2_facts.L2ValidationError:
            continue
        facts_emitted += 1
        for l1_id, l1_correlation_id in source_l1_edges:
            if l2_facts.add_evidence(fact_id, l1_correlation_id or cand.get("correlation_id", ""), l1_id):
                evidence_edges_emitted += 1
    cascade_result = recompute_cascades()
    return {
        "facts_emitted": facts_emitted,
        "evidence_edges_emitted": evidence_edges_emitted,
        "cascade_retracted": cascade_result["cascade_retracted"],
        "support_below_threshold_retracted": cascade_result["support_below_threshold_retracted"],
    }


def recompute_cascades() -> dict[str, Any]:
    """D8 LOCK — 3-tier cascade applied to live L2 facts vs current L1 retractions.

    For each live L2 fact:
      - load its evidence edges (lib.l2_facts.evidence_for)
      - count how many of its supporting L1 entries are still live
      - tier (a): all retracted → l2_facts.retract(fact_id, 'cascade_from_l1')
      - tier (b): live count fell below _GROUP_THRESHOLD → retract with reason
                  'support_below_threshold'
      - tier (c): live count >= threshold → no-op (lazy; support_count may be
                  stale on the record itself until next promote_all)

    Returns counters: {cascade_retracted, support_below_threshold_retracted}.
    """
    # Build the set of retracted L1 ids once.
    l1_retracted: set[str] = insight_index._retracted_ids()
    cascade_count = 0
    threshold_count = 0
    live_facts = l2_facts.query(include_retracted=False, limit=None)
    for fact in live_facts:
        fact_id = fact.get("id")
        if not isinstance(fact_id, str):
            continue
        edges = l2_facts.evidence_for(fact_id)
        if not edges:
            continue
        live_support = 0
        for edge in edges:
            l1_id = edge.get("l1_entry_id")
            if isinstance(l1_id, str) and l1_id not in l1_retracted:
                live_support += 1
        if live_support == 0:
            if l2_facts.retract(fact_id, reason="cascade_from_l1"):
                cascade_count += 1
        elif live_support < _GROUP_THRESHOLD:
            if l2_facts.retract(fact_id, reason="support_below_threshold"):
                threshold_count += 1
        # else: tier (c) — leave live, lazy recompute
    return {
        "cascade_retracted": cascade_count,
        "support_below_threshold_retracted": threshold_count,
    }
