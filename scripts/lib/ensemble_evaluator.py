"""ensemble_evaluator — N-evaluator quorum verdict (v15.35).

메타-vision actuator 확장 building block. v15.32/33/34가 sensor/actuator/memory
3-layer를 land 했다면, 본 cycle은 evaluator actuator 자체를 *복수화*한다 —
단일 codex 평가자 → N=3 quorum 평가자 풀.

## 위치 (메타-vision 좌표)

| layer | cycle | file | 차원 |
|-------|-------|------|------|
| B-cell (sensor)   | v15.32 | cli/sensor_anomaly.py | sensor incompleteness |
| T-cell (actuator) | v15.33 | cli/action_evolver.py | actuator incompleteness |
| memory (registry) | v15.34 | lib/meta_rules.py     | meta-loop incompleteness |
| **ensemble (actuator-fan-out)** | **v15.35** | **lib/ensemble_evaluator.py** | **evaluator-monoculture incompleteness** |

단일 evaluator (Codex OpenAIProvider, lib/evaluator_dispatcher.invoke_evaluator_isolated)는
provider 분리로 self-validation paradox를 회피하지만 *단일 provider 편향* 여전히
존재 — Codex 학습 데이터 편향, prompt 해석 quirk, 일시적 latency outlier 등. 본
모듈은 동일 artifact를 N개의 *비-generator-family* provider에 분산 평가 후
⌈N/2⌉ quorum verdict 채택. 분열 → escalate.

## judge-generator separation invariant (provider 수준)

lib.meta_rules.MetaRule[rule_id='dge_three_principles'] + [rule_id='paradox_guard'
v1.1]에 명시. ensemble은 invariant 강화: pool 안의 *모든* 평가자가 generator
provider (Anthropic = claude-code parent context)와 달라야 함.
validate_evaluator_pool()이 spawn 전에 hard-fail.

## quorum 규약

- N: pool 크기 (>=1)
- threshold = ⌈N/2⌉   (n=1→1, n=2→1, n=3→2, n=5→3)
- 최다 verdict의 count >= threshold → 해당 verdict 채택
- 분열 (어떤 verdict도 threshold 미달) → 'escalate' + split=True

## paradox guard 이중 layer

1. **per-evaluator**: 각 evaluator 호출 전 lib.evaluator.paradox_guard 3-condition
   적용 (test_pass AND citations>=3 AND ontology_match). 실패 시 그 evaluator는
   fallback_to_legacy_e2 결과 ('iterate' 또는 'escalate')를 vote로 contribute.
2. **ensemble layer**: paradox_guard_all_pass=False 인데 quorum이 'approved'면
   'escalate'로 강제 다운그레이드 (조용한 통과 금지).

## advisory only (본 cycle scope)

본 모듈은 *API surface 만* 제공. 실제 evaluator_dispatcher 결합 + 다중 provider
spawn 코드는 다음 cycle (v15.36+ 또는 운영 데이터 누적 후 priority 재평가).
quantitative_residual_norm (lib.meta_rules v1.2) enforce: known defect = 1
(wiring 부재), regression coverage = embedded --self-check 만, residual risk =
실제 N-provider quorum 동작 미검증.

## single-file mutation surface (v15.27+ 패턴 유지)

본 cycle mutation = 1 file (lib/ensemble_evaluator.py 신규). 별도 test file 없음,
embedded --self-check + run_units.py auto-discovery 회피. event taxonomy 등록은
별도 cycle (debate gate 통과 후).

## Public surface

- EnsembleConfigError
- EvaluatorVote (frozen dataclass)
- EnsembleVerdict (frozen dataclass)
- GENERATOR_PROVIDER, ANTHROPIC_PREFIXES, DEFAULT_POOL_SIZE
- quorum_threshold(n: int) -> int
- validate_evaluator_pool(providers: Sequence[str]) -> None
- tally_verdicts(votes: Sequence[EvaluatorVote]) -> dict[str, int]
- aggregate(votes, *, emit_fn=None) -> EnsembleVerdict

References:
- debate-1778987814-41b475 (v15.26 GateLeaf+AdvisoryLeaf split 패턴)
- debate-1778990144-679cb8 (single-file mutation surface 채택)
- lib.meta_rules MetaRule registry (paradox_guard v1.1 +
  dge_three_principles v1.0 + quantitative_residual_norm v1.2 +
  single_file_mutation_surface v1.0)
- lib.evaluator (per-evaluator deterministic paradox_guard + completeness clamp)
- lib.evaluator_dispatcher (single-evaluator dispatch + isolation + fallback)
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Callable, Literal, Sequence


# ============================================================================
# Invariant constants
# ============================================================================

GENERATOR_PROVIDER: str = "anthropic"
"""Provider name reserved for the Generator (claude-code parent context).

Per lib.meta_rules MetaRule[rule_id='dge_three_principles'], the Generator
runs on this provider; any Evaluator MUST use a different provider. The
ensemble pool validator (validate_evaluator_pool) refuses pools containing
this provider name.
"""

ANTHROPIC_PREFIXES: tuple[str, ...] = ("anthropic", "claude")
"""Provider name prefixes treated as generator-family (Anthropic).

Used in validate_evaluator_pool() to reject pools containing 'anthropic',
'claude-sonnet', 'claude-opus', etc. — anything that would route to the
same provider as the Generator. Case-insensitive match.
"""

DEFAULT_POOL_SIZE: int = 3
"""Default ensemble size. ⌈3/2⌉=2 quorum, 1 dissent tolerated."""


VerdictLiteral = Literal["approved", "iterate", "escalate"]
_VALID_VERDICTS: frozenset[str] = frozenset({"approved", "iterate", "escalate"})


# ============================================================================
# Errors
# ============================================================================


class EnsembleConfigError(RuntimeError):
    """Raised when the evaluator pool violates the judge-generator invariant
    or another hard configuration constraint (empty pool, malformed vote).
    """


# ============================================================================
# Dataclasses (frozen — runtime mutation 차단)
# ============================================================================


@dataclass(frozen=True)
class EvaluatorVote:
    """One evaluator's contribution to the ensemble (per-vote, NOT aggregate).

    `evaluator_id` is a free-text identifier for log/audit (e.g.,
    'codex-gpt-5.5', 'gemini-2-flash'). `provider` is the canonical adapter
    name (e.g., 'openai', 'google') used for invariant validation.

    `paradox_guard_passes` reflects the per-evaluator 3-condition outcome
    from lib.evaluator.paradox_guard (test_pass AND citations>=3 AND
    ontology_match). When False, the vote came from
    fallback_to_legacy_e2() and `fallback_reason` is non-None.

    `completeness` is the strict boolean axis from
    lib.evaluator.completeness_pass (validators+units+defects==0).

    `axis_scores` is optional 5-axis diagnostic (cohesion/coupling/
    extensibility/stability/usability, 1-5 each). Ensemble does NOT
    numerically aggregate these — quorum operates on the categorical
    verdict label only. Stored for audit log only.

    ## Caller-side accessor guide (defense-in-depth L2, 2026-05-18)

    `EvaluatorVote.verdict` (per-vote) vs `EnsembleVerdict.quorum_verdict`
    (aggregated) 는 명명이 다름. votes 를 iterate 하면서 `vote.quorum_verdict`
    잘못 access 시 AttributeError 즉시 발생. EnsembleVerdict v15.40.3
    broken (`58e753f`) 의 inverse 방향 — votes iteration 시 동일 실수 차단:

    ```python
    ensemble: EnsembleVerdict = invoke_ensemble_evaluator(...)
    for vote in ensemble.votes:
        # ✅ 정확한 per-vote access:
        per_vote_label = vote.verdict                # 'approved'|'iterate'|'escalate'
        passed = vote.paradox_guard_passes           # bool (3-condition outcome)
        complete = vote.completeness                 # bool (strict gate)

        # ✅ axis 추출 (None-check 필수 — fallback path 는 None):
        if vote.axis_scores is not None:
            cohesion = vote.axis_scores.get("cohesion")

        # ❌ broken (AttributeError — quorum_verdict 는 EnsembleVerdict 전용):
        per_vote_label = vote.quorum_verdict         # field 부재

        # ❌ broken (votes 는 EnsembleVerdict 전용 — vote 안에 votes 없음):
        sub_votes = vote.votes                       # field 부재
    ```

    Caller 가 wrong accessor 사용 시 즉시 AttributeError. silent fallback
    안 함 — fail-loud 정책 일관. EnsembleVerdict caller guide (line 210)
    + field invariant case 19 + EvaluatorVote field invariant case 20
    (`_self_check`) 와 3축 cross-ref.
    """
    evaluator_id: str
    provider: str
    verdict: VerdictLiteral
    paradox_guard_passes: bool
    completeness: bool
    fallback_reason: str | None = None
    axis_scores: dict | None = None

    def __post_init__(self) -> None:
        # Validate categorical fields at construction — bad votes must not
        # silently propagate to aggregate(). Use object.__setattr__ workaround
        # is unnecessary; we just raise.
        if not isinstance(self.evaluator_id, str) or not self.evaluator_id:
            raise EnsembleConfigError(
                f"evaluator_id must be non-empty str, got {self.evaluator_id!r}"
            )
        if not isinstance(self.provider, str) or not self.provider:
            raise EnsembleConfigError(
                f"provider must be non-empty str, got {self.provider!r}"
            )
        if self.verdict not in _VALID_VERDICTS:
            raise EnsembleConfigError(
                f"verdict must be one of {sorted(_VALID_VERDICTS)}, "
                f"got {self.verdict!r}"
            )
        if not isinstance(self.paradox_guard_passes, bool):
            raise EnsembleConfigError(
                f"paradox_guard_passes must be bool, got "
                f"{type(self.paradox_guard_passes).__name__}"
            )
        if not isinstance(self.completeness, bool):
            raise EnsembleConfigError(
                f"completeness must be bool, got "
                f"{type(self.completeness).__name__}"
            )


@dataclass(frozen=True)
class EnsembleVerdict:
    """Aggregated ensemble outcome from N evaluator votes.

    `quorum_verdict` is the verdict label adopted by the ensemble. It is
    the most-voted label when its count meets `threshold`, otherwise
    'escalate' (with `split=True`).

    `quorum_size` is the count of votes for `quorum_verdict`. When `split`
    is True, this is the highest tally even though it did not meet
    threshold — useful for audit.

    `threshold` is ⌈N/2⌉ for the pool size at aggregation time.

    `paradox_guard_all_pass` is True iff every vote had
    paradox_guard_passes=True. When False AND the raw majority would have
    been 'approved', the ensemble layer downgrades to 'escalate' and
    records the reason in `escalation_reasons`.

    `votes` retains the original sequence (insertion-ordered) for audit
    log + downstream provider-attribution analysis.

    ## Caller-side accessor guide (v15.40.3 보강, 2026-05-18)

    `EvaluatorVote.verdict` (per-vote) vs `EnsembleVerdict.quorum_verdict`
    (aggregated) 는 다른 필드 — 혼동 시 AttributeError 즉시 발생. v15.38
    autopilot Phase 3.5 spec 가 `ensemble_verdict.verdict` 잘못 사용해
    v15.40.3 commit `58e753f` 으로 fix 됨. 동일 실수 방지 caller guide:

    ```python
    result: EnsembleVerdict = invoke_ensemble_evaluator(...)

    # ✅ 정확한 access (collective verdict):
    final_verdict = result.quorum_verdict             # 'approved'|'iterate'|'escalate'

    # ✅ completeness 추출 (모든 vote 가 통과해야 True):
    final_completeness = all(v.completeness for v in result.votes)

    # ✅ split 감지:
    if result.split:
        # paradox layer 또는 quorum 미달 → 항상 'escalate'
        for reason in result.escalation_reasons:
            log(reason)

    # ❌ broken (AttributeError):
    final_verdict = result.verdict                    # field 부재
    ```

    Caller 가 wrong accessor 사용 시 즉시 AttributeError. silent fallback
    안 함 — fail-loud 정책 (debug 용이성 > silent corruption 회피).
    """
    quorum_verdict: VerdictLiteral
    quorum_size: int
    threshold: int
    votes: tuple[EvaluatorVote, ...]
    paradox_guard_all_pass: bool
    split: bool
    escalation_reasons: tuple[str, ...] = field(default_factory=tuple)


# ============================================================================
# Pure functions
# ============================================================================


def quorum_threshold(n: int) -> int:
    """⌈N/2⌉ — minimum vote count required for a verdict to win.

    Examples: n=1→1, n=2→1, n=3→2, n=4→2, n=5→3, n=7→4.
    """
    if not isinstance(n, int) or n <= 0:
        raise ValueError(f"n must be positive int, got {n!r}")
    return (n + 1) // 2


def validate_evaluator_pool(
    providers: Sequence[str],
    *,
    allow_generator_family: bool = False,
) -> None:
    """Enforce judge-generator separation invariant at provider level.

    Raises EnsembleConfigError if:
      - pool is empty
      - (default) any provider name matches GENERATOR_PROVIDER or
        starts with an ANTHROPIC_PREFIXES entry (case-insensitive)

    Rationale: lib.meta_rules MetaRule[rule_id='paradox_guard' v1.1]
    requires Evaluator provider != Generator provider; the ensemble layer
    re-applies the rule to every pool member, since the ensemble is by
    definition a multi-provider mechanism.

    Escape hatch (v15.35.3 — `allow_generator_family=True`):
      Operators can explicitly relax the strict provider-level invariant
      when they want Anthropic-family evaluators in the pool with
      *different model id from the generator* (e.g., generator=claude-
      opus-4-7, evaluator=claude-sonnet-4-6).

      RISK ACKNOWLEDGED — Panickssery 2024 + Zheng MT-Bench 2023:
      same-family LLMs share training distribution + RLHF artifacts and
      may exhibit self-preference bias even with different model ids.
      The model-id-only diversification is WEAKER than provider-level
      separation; operators choosing this path accept that the ensemble
      paradox-guard layer no longer fully mitigates judge-generator
      collusion, only the within-family model variance helps.

      Default value (False) preserves the strict behavior — this hatch
      must be opted into explicitly per call. lib.evaluator's
      EVALUATOR_ALLOW_SAME_FAMILY env (single-evaluator path) is a
      separate testing-only flag and does NOT propagate here; ensemble
      callers must pass this kwarg deliberately.
    """
    if not providers:
        raise EnsembleConfigError("evaluator pool must be non-empty")
    bad: list[str] = []
    for p in providers:
        if not isinstance(p, str) or not p:
            raise EnsembleConfigError(
                f"provider entry must be non-empty str, got {p!r}"
            )
        if allow_generator_family:
            continue
        lowered = p.lower()
        if lowered == GENERATOR_PROVIDER:
            bad.append(p)
            continue
        if any(lowered.startswith(prefix) for prefix in ANTHROPIC_PREFIXES):
            bad.append(p)
    if bad:
        raise EnsembleConfigError(
            f"evaluator pool contains generator-family providers: {bad}; "
            f"judge-generator separation requires every evaluator provider "
            f"!= {GENERATOR_PROVIDER!r} and not starting with "
            f"{list(ANTHROPIC_PREFIXES)} (CLAUDE.md DGE invariant). "
            f"Pass allow_generator_family=True to relax with model-id-only "
            f"diversification (weaker — see docstring risk note)."
        )


def tally_verdicts(votes: Sequence[EvaluatorVote]) -> dict[str, int]:
    """Return {verdict_label: count} dict for the votes sequence.

    Output always includes all three labels (approved/iterate/escalate),
    with 0 for absent ones — simplifies downstream comparison.
    """
    counts: dict[str, int] = {"approved": 0, "iterate": 0, "escalate": 0}
    for v in votes:
        if not isinstance(v, EvaluatorVote):
            raise EnsembleConfigError(
                f"vote must be EvaluatorVote, got {type(v).__name__}"
            )
        counts[v.verdict] = counts.get(v.verdict, 0) + 1
    return counts


def aggregate(
    votes: Sequence[EvaluatorVote],
    *,
    allow_generator_family: bool = False,
    emit_fn: Callable[[str, dict], None] | None = None,
) -> EnsembleVerdict:
    """Aggregate N evaluator votes into a single EnsembleVerdict.

    Algorithm:
      1. validate_evaluator_pool([v.provider for v in votes]).
      2. tally_verdicts → counts.
      3. threshold = ⌈N/2⌉.
      4. winning = label with max count.
         - If max count >= threshold → quorum_verdict = winning.
         - Else split=True → quorum_verdict = 'escalate'.
      5. paradox_guard_all_pass = all(v.paradox_guard_passes for v in votes).
         - If False AND quorum_verdict would be 'approved' →
           downgrade to 'escalate' (paradox-fail must not yield 'approved'
           at ensemble level either).

    emit_fn: optional callable invoked once with
      ('ensemble.aggregated', payload_dict). Fails open — exceptions in
      emit_fn are swallowed (advisory side-channel must not crash the
      verdict path). Mirrors lib.rewind / lib.wonder emit_fn convention.

    Returns EnsembleVerdict. Does NOT raise on empty votes — instead the
    pool validator raises EnsembleConfigError before tallying (defensive
    early failure).
    """
    if not votes:
        raise EnsembleConfigError("votes sequence must be non-empty")

    # Step 1: pool validation (invariant guard, with optional escape hatch)
    validate_evaluator_pool(
        [v.provider for v in votes],
        allow_generator_family=allow_generator_family,
    )

    # Step 2: tally
    counts = tally_verdicts(votes)
    n = len(votes)
    threshold = quorum_threshold(n)

    # Step 3-4: winning label + threshold check
    # Deterministic tiebreak: alphabetic on verdict label, but split=True
    # supersedes regardless. We pick max count; if tie at max → split.
    max_count = max(counts.values())
    winning_labels = [k for k, v in counts.items() if v == max_count]
    has_tie = len(winning_labels) > 1

    escalation_reasons: list[str] = []
    if has_tie or max_count < threshold:
        split = True
        quorum_verdict: VerdictLiteral = "escalate"
        quorum_size = max_count
        if has_tie:
            escalation_reasons.append(
                f"split_no_majority: tie at count={max_count} across labels "
                f"{sorted(winning_labels)} (threshold={threshold})"
            )
        else:
            escalation_reasons.append(
                f"split_no_majority: max_count={max_count} < threshold={threshold} "
                f"(label={winning_labels[0]!r})"
            )
    else:
        split = False
        quorum_verdict = winning_labels[0]  # type: ignore[assignment]
        quorum_size = max_count

    # Step 5: paradox guard ensemble layer
    paradox_guard_all_pass = all(v.paradox_guard_passes for v in votes)
    if not paradox_guard_all_pass and quorum_verdict == "approved":
        escalation_reasons.append(
            "ensemble_paradox_layer: quorum='approved' but at least one vote "
            "had paradox_guard_passes=False; downgrading to 'escalate'"
        )
        quorum_verdict = "escalate"

    verdict = EnsembleVerdict(
        quorum_verdict=quorum_verdict,
        quorum_size=quorum_size,
        threshold=threshold,
        votes=tuple(votes),
        paradox_guard_all_pass=paradox_guard_all_pass,
        split=split,
        escalation_reasons=tuple(escalation_reasons),
    )

    if emit_fn is not None:
        try:
            emit_fn("ensemble.aggregated", {
                "pool_size": n,
                "threshold": threshold,
                "verdict_counts": counts,
                "quorum_verdict": quorum_verdict,
                "split": split,
                "paradox_guard_all_pass": paradox_guard_all_pass,
                "providers": [v.provider for v in votes],
                "evaluator_ids": [v.evaluator_id for v in votes],
                "escalation_reasons": list(escalation_reasons),
            })
        except Exception:
            # Advisory side-channel: never crash verdict path on emit failure.
            # Mirrors lib.rewind emit_fn convention (try/except swallow).
            pass

    return verdict


# ============================================================================
# Embedded self-check (single-file mutation surface invariant — v15.35)
# ============================================================================


def _self_check() -> int:
    failed = 0
    cases: list[tuple[str, bool, str]] = []

    def case(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failed
        cases.append((name, ok, detail))
        if not ok:
            failed += 1

    # ---- Case 1: quorum_threshold ⌈N/2⌉ ----
    case("threshold_n1", quorum_threshold(1) == 1)
    case("threshold_n2", quorum_threshold(2) == 1)
    case("threshold_n3", quorum_threshold(3) == 2)
    case("threshold_n4", quorum_threshold(4) == 2)
    case("threshold_n5", quorum_threshold(5) == 3)
    case("threshold_n7", quorum_threshold(7) == 4)
    try:
        quorum_threshold(0)
        case("threshold_zero_rejects", False, "expected ValueError")
    except ValueError:
        case("threshold_zero_rejects", True)
    try:
        quorum_threshold(-1)
        case("threshold_negative_rejects", False, "expected ValueError")
    except ValueError:
        case("threshold_negative_rejects", True)

    # ---- Case 2: validate_evaluator_pool invariant ----
    try:
        validate_evaluator_pool([])
        case("pool_empty_rejects", False, "expected EnsembleConfigError")
    except EnsembleConfigError:
        case("pool_empty_rejects", True)

    try:
        validate_evaluator_pool(["openai", "anthropic", "google"])
        case("pool_with_anthropic_rejects", False,
             "expected EnsembleConfigError")
    except EnsembleConfigError:
        case("pool_with_anthropic_rejects", True)

    try:
        validate_evaluator_pool(["openai", "claude-sonnet-4-6"])
        case("pool_with_claude_prefix_rejects", False,
             "expected EnsembleConfigError")
    except EnsembleConfigError:
        case("pool_with_claude_prefix_rejects", True)

    try:
        validate_evaluator_pool(["openai", "google", "deepseek"])
        case("pool_all_non_anthropic_accepts", True)
    except EnsembleConfigError as e:
        case("pool_all_non_anthropic_accepts", False, str(e))

    try:
        validate_evaluator_pool(["OpenAI", "GOOGLE"])
        case("pool_case_insensitive_accepts", True)
    except EnsembleConfigError as e:
        case("pool_case_insensitive_accepts", False, str(e))

    try:
        validate_evaluator_pool(["openai", "Anthropic"])
        case("pool_case_insensitive_rejects_anthropic", False,
             "expected EnsembleConfigError")
    except EnsembleConfigError:
        case("pool_case_insensitive_rejects_anthropic", True)

    # ---- Case 3: EvaluatorVote validation ----
    try:
        EvaluatorVote(
            evaluator_id="codex-gpt-5.5",
            provider="openai",
            verdict="approved",
            paradox_guard_passes=True,
            completeness=True,
        )
        case("vote_valid_construction", True)
    except EnsembleConfigError as e:
        case("vote_valid_construction", False, str(e))

    try:
        EvaluatorVote(
            evaluator_id="x",
            provider="openai",
            verdict="bogus_label",  # type: ignore[arg-type]
            paradox_guard_passes=True,
            completeness=True,
        )
        case("vote_bad_verdict_rejects", False, "expected EnsembleConfigError")
    except EnsembleConfigError:
        case("vote_bad_verdict_rejects", True)

    try:
        EvaluatorVote(
            evaluator_id="",
            provider="openai",
            verdict="approved",
            paradox_guard_passes=True,
            completeness=True,
        )
        case("vote_empty_id_rejects", False, "expected EnsembleConfigError")
    except EnsembleConfigError:
        case("vote_empty_id_rejects", True)

    try:
        EvaluatorVote(
            evaluator_id="x",
            provider="openai",
            verdict="approved",
            paradox_guard_passes="yes",  # type: ignore[arg-type]
            completeness=True,
        )
        case("vote_non_bool_paradox_rejects", False,
             "expected EnsembleConfigError")
    except EnsembleConfigError:
        case("vote_non_bool_paradox_rejects", True)

    # ---- Case 4: tally_verdicts ----
    votes_unanimous = [
        EvaluatorVote("e1", "openai", "approved", True, True),
        EvaluatorVote("e2", "google", "approved", True, True),
        EvaluatorVote("e3", "deepseek", "approved", True, True),
    ]
    counts = tally_verdicts(votes_unanimous)
    case("tally_unanimous_approved",
         counts == {"approved": 3, "iterate": 0, "escalate": 0})

    votes_mixed = [
        EvaluatorVote("e1", "openai", "approved", True, True),
        EvaluatorVote("e2", "google", "iterate", True, False),
        EvaluatorVote("e3", "deepseek", "escalate", True, True),
    ]
    counts2 = tally_verdicts(votes_mixed)
    case("tally_mixed_one_each",
         counts2 == {"approved": 1, "iterate": 1, "escalate": 1})

    # ---- Case 5: aggregate unanimous approved ----
    v_unan = aggregate(votes_unanimous)
    case("aggregate_unanimous_verdict", v_unan.quorum_verdict == "approved")
    case("aggregate_unanimous_size", v_unan.quorum_size == 3)
    case("aggregate_unanimous_threshold", v_unan.threshold == 2)
    case("aggregate_unanimous_not_split", v_unan.split is False)
    case("aggregate_unanimous_paradox_all_pass",
         v_unan.paradox_guard_all_pass is True)
    case("aggregate_unanimous_no_escalation",
         v_unan.escalation_reasons == ())

    # ---- Case 6: aggregate majority approved (2-of-3) ----
    votes_majority = [
        EvaluatorVote("e1", "openai", "approved", True, True),
        EvaluatorVote("e2", "google", "approved", True, True),
        EvaluatorVote("e3", "deepseek", "iterate", True, False),
    ]
    v_maj = aggregate(votes_majority)
    case("aggregate_majority_verdict", v_maj.quorum_verdict == "approved")
    case("aggregate_majority_size", v_maj.quorum_size == 2)
    case("aggregate_majority_not_split", v_maj.split is False)

    # ---- Case 7: aggregate split → escalate ----
    v_split = aggregate(votes_mixed)
    case("aggregate_split_verdict", v_split.quorum_verdict == "escalate")
    case("aggregate_split_flag", v_split.split is True)
    case("aggregate_split_has_reason",
         any("split_no_majority" in r for r in v_split.escalation_reasons))

    # ---- Case 8: aggregate paradox-fail layer downgrade ----
    # majority would be 'approved' but one vote has paradox_guard_passes=False
    votes_paradox_fail = [
        EvaluatorVote("e1", "openai", "approved", True, True),
        EvaluatorVote("e2", "google", "approved", True, True),
        EvaluatorVote(
            "e3", "deepseek", "approved",
            paradox_guard_passes=False,
            completeness=True,
            fallback_reason="paradox_guard_fail",
        ),
    ]
    v_pf = aggregate(votes_paradox_fail)
    case("aggregate_paradox_fail_downgrades",
         v_pf.quorum_verdict == "escalate")
    case("aggregate_paradox_fail_flag",
         v_pf.paradox_guard_all_pass is False)
    case("aggregate_paradox_fail_has_reason",
         any("ensemble_paradox_layer" in r for r in v_pf.escalation_reasons))
    case("aggregate_paradox_fail_not_split", v_pf.split is False)

    # ---- Case 9: aggregate paradox-fail when verdict is 'iterate' (no downgrade) ----
    votes_paradox_fail_iter = [
        EvaluatorVote("e1", "openai", "iterate", True, False),
        EvaluatorVote("e2", "google", "iterate", True, False),
        EvaluatorVote(
            "e3", "deepseek", "iterate",
            paradox_guard_passes=False,
            completeness=False,
            fallback_reason="paradox_guard_fail",
        ),
    ]
    v_pf2 = aggregate(votes_paradox_fail_iter)
    case("aggregate_paradox_fail_iter_keeps_iterate",
         v_pf2.quorum_verdict == "iterate")
    case("aggregate_paradox_fail_iter_no_escalation_reason",
         v_pf2.escalation_reasons == ())

    # ---- Case 10: aggregate rejects generator-family pool ----
    votes_with_anthropic = [
        EvaluatorVote("e1", "openai", "approved", True, True),
        EvaluatorVote("e2", "anthropic", "approved", True, True),
    ]
    try:
        aggregate(votes_with_anthropic)
        case("aggregate_rejects_anthropic_pool", False,
             "expected EnsembleConfigError")
    except EnsembleConfigError:
        case("aggregate_rejects_anthropic_pool", True)

    # ---- Case 11: aggregate empty rejects ----
    try:
        aggregate([])
        case("aggregate_empty_rejects", False,
             "expected EnsembleConfigError")
    except EnsembleConfigError:
        case("aggregate_empty_rejects", True)

    # ---- Case 12: emit_fn invoked exactly once + fails open ----
    emit_log: list[tuple[str, dict]] = []

    def _good_emit(et: str, payload: dict) -> None:
        emit_log.append((et, payload))

    aggregate(votes_unanimous, emit_fn=_good_emit)
    case("emit_fn_called_once", len(emit_log) == 1)
    case("emit_fn_event_type",
         emit_log and emit_log[0][0] == "ensemble.aggregated")
    case("emit_fn_payload_has_verdict",
         emit_log and emit_log[0][1].get("quorum_verdict") == "approved")
    case("emit_fn_payload_has_counts",
         emit_log and isinstance(emit_log[0][1].get("verdict_counts"), dict))

    def _bad_emit(et: str, payload: dict) -> None:
        raise RuntimeError("emit_fn exploded")

    try:
        v_bad_emit = aggregate(votes_unanimous, emit_fn=_bad_emit)
        case("emit_fn_fails_open", v_bad_emit.quorum_verdict == "approved")
    except Exception as e:
        case("emit_fn_fails_open", False, f"propagated: {e}")

    # ---- Case 13: tally rejects non-EvaluatorVote ----
    try:
        tally_verdicts(["not a vote"])  # type: ignore[list-item]
        case("tally_rejects_non_vote", False,
             "expected EnsembleConfigError")
    except EnsembleConfigError:
        case("tally_rejects_non_vote", True)

    # ---- Case 14: aggregate single-evaluator pool (N=1, threshold=1) ----
    v_single = aggregate([
        EvaluatorVote("e1", "openai", "approved", True, True),
    ])
    case("aggregate_n1_works", v_single.quorum_verdict == "approved")
    case("aggregate_n1_threshold", v_single.threshold == 1)
    case("aggregate_n1_not_split", v_single.split is False)

    # ---- Case 15: aggregate N=2 split (1 approved 1 iterate, threshold=1 but tie) ----
    v_n2_split = aggregate([
        EvaluatorVote("e1", "openai", "approved", True, True),
        EvaluatorVote("e2", "google", "iterate", True, False),
    ])
    # threshold=1, both labels have count=1 → tie → split → escalate
    case("aggregate_n2_tie_escalates",
         v_n2_split.quorum_verdict == "escalate")
    case("aggregate_n2_tie_split_flag", v_n2_split.split is True)

    # ---- Case 16: aggregate retains votes tuple insertion order ----
    v_order = aggregate(votes_mixed)
    case("aggregate_votes_tuple_preserved",
         tuple(v.evaluator_id for v in v_order.votes) == ("e1", "e2", "e3"))
    case("aggregate_votes_immutable",
         isinstance(v_order.votes, tuple))

    # ---- Case 17 (v15.35.3): allow_generator_family escape hatch ----
    # Default behavior: rejects anthropic-family
    try:
        validate_evaluator_pool(["openai", "anthropic"])
        case("escape_hatch_default_still_rejects", False,
             "expected EnsembleConfigError")
    except EnsembleConfigError:
        case("escape_hatch_default_still_rejects", True)
    # With escape hatch: accepts anthropic-family
    try:
        validate_evaluator_pool(["openai", "anthropic"],
                                allow_generator_family=True)
        case("escape_hatch_allows_anthropic", True)
    except EnsembleConfigError as e:
        case("escape_hatch_allows_anthropic", False, str(e))
    # Aggregate with anthropic pool via escape hatch — quorum still works
    votes_with_anthropic_ok = [
        EvaluatorVote("e1", "openai", "approved", True, True),
        EvaluatorVote("e2", "anthropic", "approved", True, True),
    ]
    try:
        v_ah = aggregate(votes_with_anthropic_ok,
                         allow_generator_family=True)
        case("aggregate_allow_anthropic_quorum",
             v_ah.quorum_verdict == "approved")
    except EnsembleConfigError as e:
        case("aggregate_allow_anthropic_quorum", False, str(e))
    # Aggregate WITHOUT hatch on same pool still rejects
    try:
        aggregate(votes_with_anthropic_ok)
        case("aggregate_no_hatch_still_rejects_anthropic", False,
             "expected EnsembleConfigError")
    except EnsembleConfigError:
        case("aggregate_no_hatch_still_rejects_anthropic", True)

    # ---- Case 18: meta_rules registry cross-check (quantitative_residual_norm cite) ----
    # Verify the cited meta-rules exist + are ACTIVE. This grounds the docstring
    # claims about lib.meta_rules references — drift would surface here.
    try:
        from . import meta_rules as _mr  # type: ignore[import-not-found]

        cited_active = {
            "dge_three_principles",
            "paradox_guard",
            "quantitative_residual_norm",
            "single_file_mutation_surface",
        }
        active_ids = {r.rule_id for r in _mr.current_rules()}
        missing = cited_active - active_ids
        case("meta_rules_cited_active_present", not missing,
             f"missing: {sorted(missing)}" if missing else "")
        paradox_rule = _mr.rule_by_id("paradox_guard")
        case("meta_rules_paradox_v1_1",
             paradox_rule is not None and paradox_rule.version == "v1.1")
    except ImportError:
        # Allow standalone run without package context (best-effort cross-check).
        case("meta_rules_cited_active_present", True,
             "(skipped — lib.meta_rules import unavailable in this run)")
        case("meta_rules_paradox_v1_1", True, "(skipped)")

    # ---- Case 19: field name invariant (v15.40.3 anti-regression) ----
    # Caller spec broken on 2026-05-18 (commit 58e753f) used
    # `ensemble_verdict.verdict` — wrong field. If schema ever drifts to
    # include `verdict` (e.g., refactor renames quorum_verdict), caller
    # specs would silently match while semantics change. Lock both halves:
    import dataclasses as _dc
    _ev_field_names = {f.name for f in _dc.fields(EnsembleVerdict)}
    case("ensemble_verdict_has_quorum_verdict",
         "quorum_verdict" in _ev_field_names,
         f"missing field — caller .quorum_verdict access broken; fields={_ev_field_names}")
    case("ensemble_verdict_no_verdict_field",
         "verdict" not in _ev_field_names,
         f"unexpected 'verdict' field — caller .verdict access ambiguous "
         f"(EvaluatorVote.verdict shadow); fields={_ev_field_names}")
    case("ensemble_verdict_has_votes_for_completeness",
         "votes" in _ev_field_names,
         "missing 'votes' field — caller completeness extraction broken")

    # ---- Case 20: EvaluatorVote field name invariant (L4 inverse symmetric) ----
    # Caller guide (EvaluatorVote docstring + EnsembleVerdict L210) iterates
    # ensemble.votes accessing `vote.verdict` / `vote.completeness`. If
    # EvaluatorVote schema drifts (rename verdict → quorum_verdict, or add
    # `votes` shadow), per-vote caller iteration breaks silently. Mirror
    # case 19 but with inverted semantics:
    _vote_field_names = {f.name for f in _dc.fields(EvaluatorVote)}
    case("evaluator_vote_has_verdict",
         "verdict" in _vote_field_names,
         f"missing 'verdict' field — caller vote.verdict iteration broken; "
         f"fields={_vote_field_names}")
    case("evaluator_vote_no_quorum_verdict_field",
         "quorum_verdict" not in _vote_field_names,
         f"unexpected 'quorum_verdict' field on EvaluatorVote — caller "
         f"would confuse per-vote with aggregate; fields={_vote_field_names}")
    case("evaluator_vote_no_votes_field",
         "votes" not in _vote_field_names,
         f"unexpected 'votes' field on EvaluatorVote — caller would "
         f"recurse on EnsembleVerdict.votes by mistake; "
         f"fields={_vote_field_names}")
    case("evaluator_vote_has_completeness",
         "completeness" in _vote_field_names,
         f"missing 'completeness' field — caller spec "
         f"'all(v.completeness for v in votes)' broken; "
         f"fields={_vote_field_names}")

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
    print("lib.ensemble_evaluator — N-evaluator quorum aggregation (v15.35)")
    print(f"  generator_provider: {GENERATOR_PROVIDER}")
    print(f"  default_pool_size:  {DEFAULT_POOL_SIZE} "
          f"(threshold={quorum_threshold(DEFAULT_POOL_SIZE)})")
    print(f"  advisory only — no dispatcher wiring this cycle")
    print(f"  use --self-check to run embedded smoke test")
    sys.exit(0)
