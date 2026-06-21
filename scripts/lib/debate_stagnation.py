"""debate_stagnation — early-termination signals for harness-debate engine.

Motivated by debate-1779008782-230c36 (본 세션 실 경험): 4-gen hard_cap에서
Architect가 매 gen ontology를 re-abstract → SHA-1 drift → convergence 불가.
gen 3↔4에서야 ontology stable. 만약 oscillation/stagnation 조기 감지가 있었다면
gen 2 또는 3에서 hard_cap 조기 호출 → 2-3 gen 분 cost 절약 가능.

## Detection signals

### Oscillation
gen N의 ontology SHA-1이 gen N-2 (또는 N-1, N-3 등)와 *재일치* — Architect가
이전 abstraction로 돌아온 상태. 진행 X, 양옆 사이를 왕복.

### Stagnation
연속 K gen의 verdict가 동일하면서 ontology도 *변하지 않음* — 같은 자리 멈춤.
verdict가 "approved"면 좋은 신호 (이미 수렴) — convergence rule이 처리. 여기서는
"rejected"/"conditional"이 K gen 연속이면 stagnation으로 분류 (debate가 같은
지점 못 통과).

### Blocker plateau
critique.payload.blockers가 K gen 연속 *동일하거나 증가* — Planner가 fix 못
함. downward trend (감소)는 healthy.

## Public surface

- `OscillationResult` (frozen dataclass: detected / window / matched_pair / current_hash)
- `StagnationResult` (frozen dataclass: detected / window / verdicts / current_verdict)
- `BlockerPlateauResult` (frozen dataclass: detected / window / counts / trend)
- `EarlyHardCapRecommendation` (frozen dataclass: recommend / reasons / signals)
- `read_debate_events(events_path)` → `list[dict]`
- `detect_oscillation(events, window=4)` → OscillationResult
- `detect_stagnation(events, window=3, verdicts=("rejected","conditional"))` → StagnationResult
- `detect_blocker_plateau(events, window=3)` → BlockerPlateauResult
- `recommend_early_hard_cap(events, *, ...)` → EarlyHardCapRecommendation

Pure functions — no I/O outside `read_debate_events`. All detectors operate
on the events list so caller can synthesize/mock for tests.

## Boundary

This module emits SIGNALS only. The orchestrator (`commands/harness-debate.md`)
remains the decision-maker — it consumes `recommend_early_hard_cap` and
chooses whether to bail. Operator can override via env var
`DEBATE_DISABLE_EARLY_HARDCAP=1` (interpreted by orchestrator, NOT here).

## NOT scope

- Modifying convergence rule (SHA-1 match + 'approved') — that lives in
  `commands/harness-debate.md` protocol.
- Auto-killing in-flight subagents — orchestrator owns that.
- Cross-session learning (e.g., "this topic always stagnates") — separate
  cycle (telemetry aggregation).
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ============================================================================
# Dataclasses
# ============================================================================


@dataclass(frozen=True)
class OscillationResult:
    """Ontology SHA-1 re-emerged after intermediate change.

    `matched_pair = (gen_a, gen_b)` where gen_b > gen_a and they share
    SHA-1 across a non-monotonic path (i.e., at least one different hash
    exists between them). `current_hash` is the most recent hash.
    """
    detected: bool
    window: int
    matched_pair: tuple[int, int] | None
    current_hash: str | None


@dataclass(frozen=True)
class StagnationResult:
    """K consecutive gens with same verdict (in `verdicts` filter set)
    AND no ontology change across them.

    `verdicts_seen` is the tail-most K verdicts inspected (chronological).
    """
    detected: bool
    window: int
    verdicts_seen: tuple[str, ...]
    current_verdict: str | None
    ontology_changes_in_window: int


@dataclass(frozen=True)
class BlockerPlateauResult:
    """K consecutive critique blocker counts that are non-decreasing.

    `counts` is chronological (oldest→newest within window). `trend` is
    'plateau' (all equal), 'rising' (strict increase), 'mixed' (some
    decreases but never crosses below window[0]). 'falling' means the
    trend is healthy (Planner is making progress) — detected=False.
    """
    detected: bool
    window: int
    counts: tuple[int, ...]
    trend: str  # 'plateau' | 'rising' | 'mixed' | 'falling' | 'empty'


@dataclass(frozen=True)
class EarlyHardCapRecommendation:
    """Aggregated signal for orchestrator: should debate hard-cap early?

    `recommend=True` iff ANY underlying detector fired. `reasons` lists
    the short codes (oscillation / stagnation / blocker_plateau) that
    triggered. `signals` carries the individual result dataclasses for
    forensic review by the orchestrator.
    """
    recommend: bool
    reasons: tuple[str, ...]
    signals: dict = field(default_factory=dict)


# ============================================================================
# Events I/O
# ============================================================================


def read_debate_events(events_path: Path | str) -> list[dict]:
    """Read events.jsonl chronologically. Skip malformed lines.

    Returns [] on missing file / OSError. Each event is the raw dict;
    callers filter by `type`/`gen` as needed.
    """
    if not isinstance(events_path, Path):
        events_path = Path(events_path)
    if not events_path.exists():
        return []
    out: list[dict] = []
    try:
        for raw in events_path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                out.append(rec)
    except OSError:
        return []
    return out


def _ontology_hashes_by_gen(events: list[dict]) -> dict[int, str]:
    """Extract {gen: sha1} of the ontology snapshot per gen. Last wins per gen.

    Primary source = verdict events' ontology_snapshot.fields via snapshot_sha1 —
    the SAME canonical hash convergence uses (deep-audit rank 4). The explicit
    `ontology_hash` event this previously read EXCLUSIVELY is never produced in
    real sessions (0 across 90 sessions), so the map was always empty ->
    unique_hashes=0<=1 vacuously satisfied the 'ontology stable' guard ->
    detect_stagnation MISFIRED on debates making genuine ontology progress, and
    detect_oscillation was permanently inert. An explicit `ontology_hash` event,
    if ever emitted, still OVERRIDES (back-compat + self-check fixtures).
    """
    from lib.debate_convergence import snapshot_sha1
    out: dict[int, str] = {}
    # Base layer: derive from verdict events' ontology snapshot fields (real source).
    for ev in events:
        if ev.get("type") != "verdict":
            continue
        gen = ev.get("gen")
        fields = ((ev.get("payload") or {}).get("ontology_snapshot") or {}).get("fields")
        if isinstance(gen, int) and fields:
            h = snapshot_sha1(fields)
            if h:
                out[gen] = h
    # Override layer: an explicit ontology_hash event wins (back-compat / fixtures).
    for ev in events:
        if ev.get("type") != "ontology_hash":
            continue
        gen = ev.get("gen")
        sha1 = (ev.get("payload") or {}).get("sha1")
        if isinstance(gen, int) and isinstance(sha1, str) and sha1:
            out[gen] = sha1
    return out


def _verdicts_by_gen(events: list[dict]) -> dict[int, str]:
    """Extract {gen: verdict} for verdict events. Last wins per gen."""
    out: dict[int, str] = {}
    for ev in events:
        if ev.get("type") != "verdict":
            continue
        gen = ev.get("gen")
        verdict = (ev.get("payload") or {}).get("verdict")
        if isinstance(gen, int) and isinstance(verdict, str):
            out[gen] = verdict
    return out


def _blocker_counts_by_gen(events: list[dict]) -> dict[int, int]:
    """Extract {gen: blocker_count} for critique events.

    Tolerates both schemas observed in events.jsonl:
      - gen 1: payload.blockers_high (severity-tagged)
      - gen 2+: payload.blockers (count)
    """
    out: dict[int, int] = {}
    for ev in events:
        if ev.get("type") != "critique":
            continue
        gen = ev.get("gen")
        if not isinstance(gen, int):
            continue
        payload = ev.get("payload") or {}
        # Prefer 'blockers' (newer schema); fall back to 'blockers_high'
        count = payload.get("blockers")
        if not isinstance(count, int):
            count = payload.get("blockers_high")
        if isinstance(count, int) and count >= 0:
            out[gen] = count
    return out


# ============================================================================
# Detectors
# ============================================================================


def detect_oscillation(
    events: list[dict],
    *,
    window: int = 4,
) -> OscillationResult:
    """SHA-1 re-emergence across a non-monotonic path within last `window` gens.

    Returns detected=True iff for the most recent N≤window gens, there
    exists a pair (gen_a, gen_b) with same SHA-1 AND at least one different
    SHA-1 between them. The earliest matching pair is reported.

    window=4 default — matches harness-debate gen_cap=4.
    """
    if not isinstance(window, int) or window < 2:
        return OscillationResult(False, window, None, None)

    by_gen = _ontology_hashes_by_gen(events)
    if len(by_gen) < 2:
        # Need at least 2 hashes
        last_hash = None
        if by_gen:
            last_hash = by_gen[max(by_gen.keys())]
        return OscillationResult(False, window, None, last_hash)

    sorted_gens = sorted(by_gen.keys())
    tail = sorted_gens[-window:]
    tail_pairs = [(g, by_gen[g]) for g in tail]

    current_hash = tail_pairs[-1][1] if tail_pairs else None

    # Look for earliest match with at least one different hash in between
    for i in range(len(tail_pairs)):
        for j in range(i + 1, len(tail_pairs)):
            if tail_pairs[i][1] != tail_pairs[j][1]:
                continue
            # Same hash at gen_a and gen_b — check intermediate diff
            between = tail_pairs[i + 1 : j]
            if any(b[1] != tail_pairs[i][1] for b in between):
                return OscillationResult(
                    detected=True,
                    window=window,
                    matched_pair=(tail_pairs[i][0], tail_pairs[j][0]),
                    current_hash=current_hash,
                )
            # Same hash with no intermediate diff = stagnation (not oscillation)
            # — let detect_stagnation handle it.

    return OscillationResult(
        detected=False,
        window=window,
        matched_pair=None,
        current_hash=current_hash,
    )


def detect_stagnation(
    events: list[dict],
    *,
    window: int = 3,
    verdicts: tuple[str, ...] = ("rejected", "conditional"),
) -> StagnationResult:
    """K consecutive verdicts in filter set AND ontology stable across them.

    `verdicts` filter: by default we treat 'rejected' OR 'conditional' as
    stagnation-eligible (debate can't pass). 'approved' verdict is healthy
    (convergence path) and never triggers stagnation.

    "ontology stable across window" means the SHA-1 hashes in the same gens
    are all equal (single hash count <= 1). If hashes differ but verdicts
    are same K times, that's progress (Architect re-thinking) — not stagnation.
    """
    if not isinstance(window, int) or window < 2:
        return StagnationResult(False, window, (), None, 0)
    if not isinstance(verdicts, tuple) or not verdicts:
        return StagnationResult(False, window, (), None, 0)

    verdict_map = _verdicts_by_gen(events)
    if len(verdict_map) < window:
        last_v = verdict_map[max(verdict_map.keys())] if verdict_map else None
        return StagnationResult(False, window, tuple(), last_v, 0)

    sorted_gens = sorted(verdict_map.keys())
    tail_gens = sorted_gens[-window:]
    tail_verdicts = tuple(verdict_map[g] for g in tail_gens)
    current_verdict = tail_verdicts[-1]

    # All tail verdicts in filter set AND all identical
    all_in_filter = all(v in verdicts for v in tail_verdicts)
    all_identical = len(set(tail_verdicts)) == 1

    # Ontology change count in window
    hash_map = _ontology_hashes_by_gen(events)
    tail_hashes = [hash_map.get(g) for g in tail_gens if g in hash_map]
    unique_hashes = len(set(tail_hashes))
    ontology_changes = max(0, unique_hashes - 1)

    detected = all_in_filter and all_identical and unique_hashes <= 1

    return StagnationResult(
        detected=detected,
        window=window,
        verdicts_seen=tail_verdicts,
        current_verdict=current_verdict,
        ontology_changes_in_window=ontology_changes,
    )


def detect_blocker_plateau(
    events: list[dict],
    *,
    window: int = 3,
) -> BlockerPlateauResult:
    """K consecutive blocker counts non-decreasing.

    'plateau': all equal (e.g., 4,4,4).
    'rising': strict monotonic increase (4,5,6).
    'mixed': some decrease but never crosses below window[0]
             (e.g., 4,5,4 — net non-improvement).
    'falling': healthy progress (5,4,3) — detected=False.
    'empty': fewer than `window` critiques available.
    """
    if not isinstance(window, int) or window < 2:
        return BlockerPlateauResult(False, window, tuple(), "empty")

    counts_map = _blocker_counts_by_gen(events)
    if len(counts_map) < window:
        return BlockerPlateauResult(False, window, tuple(), "empty")

    sorted_gens = sorted(counts_map.keys())
    tail = tuple(counts_map[g] for g in sorted_gens[-window:])

    # Classify trend
    first, last = tail[0], tail[-1]
    pairs = list(zip(tail, tail[1:]))
    if all(a == b for a, b in pairs):
        trend = "plateau"
        detected = True
    elif all(a <= b for a, b in pairs) and any(a < b for a, b in pairs):
        trend = "rising"
        detected = True
    elif all(a >= b for a, b in pairs) and any(a > b for a, b in pairs):
        trend = "falling"
        detected = False
    else:
        # Some increases AND some decreases — net non-improvement check
        if last >= first:
            trend = "mixed"
            detected = True
        else:
            trend = "falling"
            detected = False

    return BlockerPlateauResult(
        detected=detected,
        window=window,
        counts=tail,
        trend=trend,
    )


def recommend_early_hard_cap(
    events: list[dict],
    *,
    oscillation_window: int = 4,
    stagnation_window: int = 3,
    blocker_window: int = 3,
) -> EarlyHardCapRecommendation:
    """Aggregate all 3 detectors into a single recommendation.

    Caller (orchestrator) consumes `recommend` + `reasons` to decide
    whether to short-circuit before reaching hard_cap=4. `signals` carries
    the underlying dataclasses for forensic logging.
    """
    osc = detect_oscillation(events, window=oscillation_window)
    stg = detect_stagnation(events, window=stagnation_window)
    blk = detect_blocker_plateau(events, window=blocker_window)

    reasons: list[str] = []
    if osc.detected:
        reasons.append("oscillation")
    if stg.detected:
        reasons.append("stagnation")
    if blk.detected:
        reasons.append("blocker_plateau")

    return EarlyHardCapRecommendation(
        recommend=bool(reasons),
        reasons=tuple(reasons),
        signals={
            "oscillation": osc,
            "stagnation": stg,
            "blocker_plateau": blk,
        },
    )


# ============================================================================
# Embedded self-check
# ============================================================================


def _self_check() -> int:
    failed = 0
    cases: list[tuple[str, bool, str]] = []

    def case(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failed
        cases.append((name, ok, detail))
        if not ok:
            failed += 1

    # Helper to synthesize events list
    def evt(gen: int, type_: str, **payload) -> dict:
        return {"gen": gen, "type": type_, "payload": payload}

    # ---- read_debate_events: empty / missing ----
    case("read_missing_file_returns_empty",
         read_debate_events("/nonexistent/path/events.jsonl") == [])

    # ---- detect_oscillation ----
    # 1. Empty events → no oscillation
    case("osc_empty_no_detect",
         detect_oscillation([]).detected is False)

    # 2. Single hash → no oscillation
    one = [evt(1, "ontology_hash", sha1="aaaa")]
    case("osc_single_hash_no_detect",
         detect_oscillation(one).detected is False)

    # 3. Monotonic distinct hashes → no oscillation
    mono = [
        evt(1, "ontology_hash", sha1="aaaa"),
        evt(2, "ontology_hash", sha1="bbbb"),
        evt(3, "ontology_hash", sha1="cccc"),
    ]
    case("osc_monotonic_no_detect",
         detect_oscillation(mono).detected is False)

    # 4. True oscillation: A → B → A (with intermediate diff)
    osc_pattern = [
        evt(1, "ontology_hash", sha1="aaaa"),
        evt(2, "ontology_hash", sha1="bbbb"),
        evt(3, "ontology_hash", sha1="aaaa"),
    ]
    r_osc = detect_oscillation(osc_pattern)
    case("osc_aba_pattern_detected", r_osc.detected is True)
    case("osc_aba_matched_pair",
         r_osc.matched_pair == (1, 3))
    case("osc_aba_current_hash",
         r_osc.current_hash == "aaaa")

    # 5. Stable (A → A) is NOT oscillation (no intermediate diff)
    stable = [
        evt(1, "ontology_hash", sha1="aaaa"),
        evt(2, "ontology_hash", sha1="aaaa"),
    ]
    case("osc_stable_pair_no_detect",
         detect_oscillation(stable).detected is False)

    # 6. Window respects tail only
    long_seq = [
        evt(1, "ontology_hash", sha1="aaaa"),  # outside window
        evt(2, "ontology_hash", sha1="bbbb"),
        evt(3, "ontology_hash", sha1="cccc"),
        evt(4, "ontology_hash", sha1="dddd"),
        evt(5, "ontology_hash", sha1="eeee"),
    ]
    case("osc_window_excludes_old",
         detect_oscillation(long_seq, window=3).detected is False)

    # 7. Real debate session pattern (본 cycle): e89e → e28c → 69a5 → 69a5
    real_drift = [
        evt(1, "ontology_hash", sha1="e89e57d4d60dc6c3ce49f5f07d44ecfa7962737b"),
        evt(2, "ontology_hash", sha1="e28ca46ff6ffc879cabdba06bb7a2629c64db234"),
        evt(3, "ontology_hash", sha1="69a53541af5a000000000000000000000000000a"),
        evt(4, "ontology_hash", sha1="69a53541af5a000000000000000000000000000a"),
    ]
    # gen 3-4 stable but distinct from gen 1-2 → no oscillation
    case("osc_real_session_drift_to_stable_no_oscillation",
         detect_oscillation(real_drift).detected is False)

    # ---- detect_stagnation ----
    # 1. Empty / insufficient gens
    case("stg_empty_no_detect",
         detect_stagnation([]).detected is False)

    # 2. 3 consecutive 'rejected' + same hash → stagnation
    stag_pattern = [
        evt(1, "verdict", verdict="rejected"),
        evt(1, "ontology_hash", sha1="xxxx"),
        evt(2, "verdict", verdict="rejected"),
        evt(2, "ontology_hash", sha1="xxxx"),
        evt(3, "verdict", verdict="rejected"),
        evt(3, "ontology_hash", sha1="xxxx"),
    ]
    r_stg = detect_stagnation(stag_pattern, window=3)
    case("stg_3_rejected_same_hash_detected", r_stg.detected is True)
    case("stg_verdicts_seen_3",
         r_stg.verdicts_seen == ("rejected", "rejected", "rejected"))
    case("stg_current_verdict_rejected",
         r_stg.current_verdict == "rejected")
    case("stg_zero_ontology_changes",
         r_stg.ontology_changes_in_window == 0)

    # 3. 3 consecutive 'rejected' but hash changes → NOT stagnation
    progress = [
        evt(1, "verdict", verdict="rejected"),
        evt(1, "ontology_hash", sha1="aaaa"),
        evt(2, "verdict", verdict="rejected"),
        evt(2, "ontology_hash", sha1="bbbb"),
        evt(3, "verdict", verdict="rejected"),
        evt(3, "ontology_hash", sha1="cccc"),
    ]
    r_prog = detect_stagnation(progress, window=3)
    case("stg_hash_changing_not_stagnation", r_prog.detected is False)
    case("stg_ontology_changes_counted",
         r_prog.ontology_changes_in_window == 2)

    # 4. 'approved' never triggers stagnation
    approved_seq = [
        evt(1, "verdict", verdict="approved"),
        evt(2, "verdict", verdict="approved"),
        evt(3, "verdict", verdict="approved"),
    ]
    case("stg_approved_not_stagnation",
         detect_stagnation(approved_seq, window=3).detected is False)

    # 5. deep-audit rank 4 (MISFIRE FIX): real-session shape — verdict events carry
    #    ontology_snapshot.fields and NO explicit ontology_hash event. Hashes are
    #    DERIVED from the fields, so genuinely-progressing ontology must NOT be read
    #    as stagnation (the never-produced ontology_hash event used to leave the map
    #    empty -> unique_hashes=0<=1 vacuous-stable -> false stagnation).
    def _vf(gen, val):  # verdict event carrying ontology fields (no ontology_hash)
        return evt(gen, "verdict", verdict="conditional",
                   ontology_snapshot={"fields": [{"name": "a", "type": "t", "value": val}]})
    prog_fields = [_vf(1, "1"), _vf(2, "2"), _vf(3, "3")]  # distinct fields = real progress
    case("stg_derived_hash_progress_not_stagnation",
         detect_stagnation(prog_fields, window=3).detected is False)
    # 6. control: identical fields across 3 same-verdict gens = genuine stagnation
    same_fields = [_vf(1, "X"), _vf(2, "X"), _vf(3, "X")]
    case("stg_derived_hash_identical_detected",
         detect_stagnation(same_fields, window=3).detected is True)

    # 5. Real debate (본 cycle): rejected, rejected, conditional, conditional
    real_verdict = [
        evt(1, "verdict", verdict="rejected"),
        evt(1, "ontology_hash", sha1="hash_g1"),
        evt(2, "verdict", verdict="rejected"),
        evt(2, "ontology_hash", sha1="hash_g2"),
        evt(3, "verdict", verdict="conditional"),
        evt(3, "ontology_hash", sha1="hash_g3"),
        evt(4, "verdict", verdict="conditional"),
        evt(4, "ontology_hash", sha1="hash_g3"),  # gen 3↔4 stable
    ]
    # window=3 over last 3: verdicts=(rejected, conditional, conditional)
    # Not all identical → not stagnation
    case("stg_real_session_mixed_verdicts_no_stagnation",
         detect_stagnation(real_verdict, window=3).detected is False)
    # window=2 over last 2: (conditional, conditional) AND hash stable
    case("stg_real_session_last_2_stagnated",
         detect_stagnation(real_verdict, window=2).detected is True)

    # ---- detect_blocker_plateau ----
    # 1. Empty / insufficient → 'empty'
    bp_empty = detect_blocker_plateau([])
    case("bp_empty_no_detect", bp_empty.detected is False)
    case("bp_empty_trend", bp_empty.trend == "empty")

    # 2. Plateau (all equal)
    plateau = [
        evt(1, "critique", blockers=4),
        evt(2, "critique", blockers=4),
        evt(3, "critique", blockers=4),
    ]
    r_pl = detect_blocker_plateau(plateau, window=3)
    case("bp_plateau_detected", r_pl.detected is True)
    case("bp_plateau_trend", r_pl.trend == "plateau")
    case("bp_plateau_counts", r_pl.counts == (4, 4, 4))

    # 3. Rising (5→6→7)
    rising = [
        evt(1, "critique", blockers=5),
        evt(2, "critique", blockers=6),
        evt(3, "critique", blockers=7),
    ]
    r_ri = detect_blocker_plateau(rising)
    case("bp_rising_detected", r_ri.detected is True)
    case("bp_rising_trend", r_ri.trend == "rising")

    # 4. Falling (7→5→3) → healthy
    falling = [
        evt(1, "critique", blockers=7),
        evt(2, "critique", blockers=5),
        evt(3, "critique", blockers=3),
    ]
    r_fa = detect_blocker_plateau(falling)
    case("bp_falling_not_detect", r_fa.detected is False)
    case("bp_falling_trend", r_fa.trend == "falling")

    # 5. Mixed but net non-improvement (4 → 5 → 4)
    mixed = [
        evt(1, "critique", blockers=4),
        evt(2, "critique", blockers=5),
        evt(3, "critique", blockers=4),
    ]
    r_mx = detect_blocker_plateau(mixed)
    case("bp_mixed_net_same_detected", r_mx.detected is True)
    case("bp_mixed_trend", r_mx.trend == "mixed")

    # 6. Schema tolerance: blockers_high (gen 1 schema)
    schema_v1 = [
        evt(1, "critique", blockers_high=5),
        evt(2, "critique", blockers_high=5),
        evt(3, "critique", blockers_high=5),
    ]
    case("bp_blockers_high_schema_tolerated",
         detect_blocker_plateau(schema_v1, window=3).detected is True)

    # 7. Real debate counts (본 cycle): 5, 4, 4, 2
    real_blockers = [
        evt(1, "critique", blockers_high=5),
        evt(2, "critique", blockers=4),
        evt(3, "critique", blockers=4),
        evt(4, "critique", blockers=2),
    ]
    # window=3 last 3: (4, 4, 2) — mixed (4→4 plateau, 4→2 fall)
    # Both pairs: a<=b false (4>2). So not rising, not plateau.
    # all a>=b: 4>=4 yes, 4>=2 yes; any a>b: 4>2 yes → falling
    r_real = detect_blocker_plateau(real_blockers, window=3)
    case("bp_real_session_falling_healthy", r_real.detected is False)
    case("bp_real_session_trend_falling", r_real.trend == "falling")

    # ---- recommend_early_hard_cap aggregation ----
    rec_clean = recommend_early_hard_cap(mono)  # monotonic, no critique
    case("rec_clean_no_recommend", rec_clean.recommend is False)
    case("rec_clean_no_reasons", rec_clean.reasons == ())

    rec_osc = recommend_early_hard_cap(osc_pattern)
    case("rec_oscillation_recommends", rec_osc.recommend is True)
    case("rec_oscillation_reason_present",
         "oscillation" in rec_osc.reasons)

    rec_stg = recommend_early_hard_cap(stag_pattern, stagnation_window=3)
    case("rec_stagnation_recommends", rec_stg.recommend is True)
    case("rec_stagnation_reason_present",
         "stagnation" in rec_stg.reasons)

    rec_real = recommend_early_hard_cap(real_verdict)
    # real_verdict has window=3 stagnation false but window=3 default
    # Just verify signals dict structure
    case("rec_real_signals_present",
         "oscillation" in rec_real.signals
         and "stagnation" in rec_real.signals
         and "blocker_plateau" in rec_real.signals)

    # ---- Input validation ----
    case("osc_bad_window_no_detect",
         detect_oscillation(osc_pattern, window=1).detected is False)
    case("stg_bad_window_no_detect",
         detect_stagnation(stag_pattern, window=0).detected is False)
    case("bp_bad_window_no_detect",
         detect_blocker_plateau(plateau, window=1).detected is False)

    # ---- Real events.jsonl integration test (skip if missing) ----
    real_path = Path.home() / ".claude" / "state" / "debates" / \
        "debate-1779008782-230c36" / "events.jsonl"
    if real_path.exists():
        real_events = read_debate_events(real_path)
        case("read_real_session_non_empty", len(real_events) > 0)
        rec = recommend_early_hard_cap(real_events)
        # Real session: SHA-1 drift (gen 1→2→3) then stable (3→4).
        # No oscillation (no ABA pattern). Verdicts: rejected/rejected/
        # conditional/conditional — window=3 not all identical → no stagnation.
        # Blocker counts: 5/4/4/2 — falling at the end.
        case("real_session_no_early_hardcap_recommended",
             rec.recommend is False,
             f"unexpected: reasons={rec.reasons}" if rec.recommend else "")
    else:
        case("read_real_session_non_empty", True,
             "(skipped — no real events.jsonl)")
        case("real_session_no_early_hardcap_recommended", True,
             "(skipped)")

    # ---- report ----
    for name, ok, detail in cases:
        marker = "[OK]" if ok else "[FAIL]"
        suffix = f": {detail}" if detail and not ok else ""
        print(f"  {marker} {name}{suffix}")
    if failed:
        print(f"\n[FAIL] {failed}/{len(cases)} self-check assertions failed")
        return 1
    print(f"\n[OK] {len(cases)} self-check assertions passed")
    return 0


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        sys.exit(_self_check())
    print("lib.debate_stagnation — early hard_cap recommender for harness-debate")
    print("  detectors:    oscillation / stagnation / blocker_plateau")
    print("  motivation:   debate-1779008782-230c36 (4-gen hard_cap 경험)")
    print("  not wired:    commands/harness-debate.md 호출은 운영자 토큰 필요")
    print("  use --self-check to run embedded smoke test")
    sys.exit(0)
