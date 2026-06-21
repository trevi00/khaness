"""evaluator — DGE E2 (Generator 후 검증) Evaluator core.

Per debate-1778248254-0b7092 (4-gen converged 2026-05-08; ontology SHA-1
21fb480910cf2b3ada65e5fc3eb819ddda2a36cb):

  D1 functional_dataclass — frozen dataclass EvaluatorVerdict + pure
     functions paradox_guard / score_six_axis / evaluate. No class
     hierarchy, no module-level state.
  D2 env_driven_default_evaluator_model_cross_provider —
     EVALUATOR_MODEL env, default 'gpt-5.5' (cross-provider invariant:
     evaluator family MUST differ from generator/Anthropic). Override
     EVALUATOR_ALLOW_SAME_FAMILY=1 testing-only.
  D3 subagent_context_isolation — agents/harness-evaluator.md owned
     externally; this module passes only artifact + phase_locks +
     axis_rubric. No prior debate transcript references.
  D4 new_evaluator_dispatcher_module — see lib/evaluator_dispatcher.py
     (sibling, lands in subsequent wave).
  D5 agent_plus_function_split — paradox_guard + completeness clamp are
     deterministic here; only score_six_axis delegates to subagent.
  D6 axis_scores_jsonl_event_log — see state/evaluator/<sid>/axis_scores.jsonl
     append via lib.atomic_json (event-log convention).
  D7 e2_line_extend_only — CLAUDE.md L18-20 amendment additive only.

Phase A interview (interview-1778247600-a62643/seed.md) locked:
  - Structure: split + chain (E1 unchanged, E2 new + autopilot Phase 4 hook)
  - Paradox guard hard-fail (verdict='approved' invariant): test_pass=True
    AND research_citation_count>=3 AND ontology_match=True
  - Dispatch: autopilot Phase 4 자동 1회 + /harness-evaluate manual
  - Completeness axis: strict boolean (validators 100% + units 100% +
    known_defects=0); per-axis 1-5 score is diagnostic advisory only.

Public surface:
  - EvaluatorVerdict, ParadoxGuardResult, AxisScores, ReasonCode
  - DEFAULT_EVALUATOR_MODEL, ANTHROPIC_FAMILY, ConfigError
  - resolve_evaluator_model(env=None) -> str
  - paradox_guard(test_pass, citations, ontology_match) -> ParadoxGuardResult
  - completeness_pass(validators_passed, units_passed, known_defects) -> bool
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


# ---- D2 cross-provider invariant ----

DEFAULT_EVALUATOR_MODEL: str = ""
"""Cross-provider default. Empty string → delegate to Codex CLI's
configured default (mirrors lib/providers/openai.py:25). Evaluator goes
through OpenAIProvider (codex exec subprocess), generator goes through
claude-code parent context (Anthropic) — cross-provider invariant
enforced at PROVIDER level, not by model-id string match.

Operator override via EVALUATOR_MODEL env: any non-Anthropic-family id
recognized by Codex CLI (`codex exec -m <id>`). Anthropic-family ids are
rejected unless EVALUATOR_ALLOW_SAME_FAMILY=1 (testing-only).

Mitigates self-preference bias per Panickssery 2024 / Zheng MT-Bench
2023 (debate-1778248254-0b7092 D2). Empty default avoids bypass-by-
unrecognized-id failure mode (gpt-5.5 hardcode replaced 2026-05-08
after user surfaced Codex CLI namespace mismatch concern).
"""

# Anthropic-family model id substrings. Used by resolve_evaluator_model
# to enforce cross-provider invariant unless EVALUATOR_ALLOW_SAME_FAMILY=1.
ANTHROPIC_FAMILY: tuple[str, ...] = (
    "claude-",        # claude-opus-X-Y, claude-sonnet-X-Y, claude-haiku-X-Y
    "anthropic-",     # any anthropic-prefixed identifier
)


class ConfigError(RuntimeError):
    """Raised when evaluator config violates a hard invariant.

    Specifically: EVALUATOR_MODEL resolves to an Anthropic-family id
    while EVALUATOR_ALLOW_SAME_FAMILY!='1'. CLAUDE.md documents the
    override as testing-only.
    """


def _is_anthropic_family(model_id: str) -> bool:
    """Check whether `model_id` belongs to the Anthropic family."""
    if not isinstance(model_id, str):
        return False
    lowered = model_id.lower()
    return any(lowered.startswith(prefix) for prefix in ANTHROPIC_FAMILY)


def resolve_evaluator_model(env: dict | None = None) -> str:
    """Resolve evaluator model id with cross-provider invariant.

    INVARIANT: evaluator.provider != generator.provider.

    Resolution order:
      1. env['EVALUATOR_MODEL'] if present and non-empty
      2. DEFAULT_EVALUATOR_MODEL ('gpt-5.5')

    If the resolved id is Anthropic-family AND env['EVALUATOR_ALLOW_SAME_FAMILY']
    != '1', raise ConfigError. Override is testing-only per CLAUDE.md.
    """
    src = env if env is not None else os.environ
    raw = src.get("EVALUATOR_MODEL")
    resolved = raw if (isinstance(raw, str) and raw) else DEFAULT_EVALUATOR_MODEL

    if _is_anthropic_family(resolved):
        override = src.get("EVALUATOR_ALLOW_SAME_FAMILY")
        if override != "1":
            raise ConfigError(
                f"evaluator family must differ from generator (Anthropic); "
                f"resolved={resolved!r}. Set EVALUATOR_ALLOW_SAME_FAMILY=1 "
                f"for testing scenarios only (CLAUDE.md)."
            )
    return resolved


# ---- D1 dataclasses ----

class ReasonCode(Enum):
    """Structured reason codes emitted by paradox_guard / clamp paths."""
    TEST_FAIL = "test_fail"
    INSUFFICIENT_CITATIONS = "insufficient_citations"
    ONTOLOGY_MISMATCH = "ontology_mismatch"
    COMPLETENESS_BOOLEAN_FALSE = "completeness_boolean_false"
    LLM_TIMEOUT = "llm_timeout"
    LLM_EXCEPTION = "llm_exception"


VerdictLiteral = Literal["approved", "iterate", "escalate"]


@dataclass(frozen=True)
class StructuredReason:
    """One reason entry — axis label + ReasonCode + free-text detail."""
    axis: str
    code: ReasonCode
    detail: str = ""


@dataclass(frozen=True)
class ParadoxGuardResult:
    """3-condition paradox guard outcome (Phase A locked invariant).

    `passes` is True iff ALL 3 conditions hold:
      - test_pass = True
      - research_citation_count >= 3
      - ontology_match = True
    Otherwise `reasons[]` enumerates the failed conditions.
    """
    passes: bool
    reasons: tuple[StructuredReason, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AxisScores:
    """6-axis diagnostic scores (per-axis 1-5).

    Axes 1-5 (응집/결합/확장/안정/사용) are LLM-graded advisory.
    `completeness` (6th axis) is the strict boolean GATE — Phase A lock.
    """
    cohesion: int                      # 응집도 (1-5)
    coupling: int                      # 결합도 (1-5)
    extensibility: int                 # 확장성 (1-5)
    stability: int                     # 안정성 (1-5)
    usability: int                     # 사용성 (1-5)
    completeness: bool                 # 완성도 boolean (GATE)


@dataclass(frozen=True)
class EvaluatorVerdict:
    """Final evaluator output (single-evaluator, NOT ensemble). verdict='approved'
    iff paradox_guard passes AND completeness=True (post-LLM clamp enforces).

    `axis_scores` is None if paradox_guard short-circuited before
    score_six_axis was invoked.
    `model_used` records which evaluator model was resolved (for audit).
    `fallback_reason` is set when path degenerated to legacy E2
    (validators+units only).

    ## Caller-side accessor guide (defense-in-depth L2, 2026-05-18)

    `EvaluatorVerdict.verdict` (single-evaluator) vs
    `EnsembleVerdict.quorum_verdict` (aggregated) 는 다른 필드 이름.
    Tier 2 (single) → Tier 3 (ensemble) 전환 시 caller 가 잘못 access 하면
    AttributeError 즉시 발생. EnsembleVerdict 의 v15.40.3 broken (commit
    `58e753f`, `ensemble_verdict.verdict` 잘못 사용) 의 inverse 방향 보호:

    ```python
    result: EvaluatorVerdict = ...  # single-subagent path retval

    # ✅ 정확한 access (single-evaluator verdict):
    final_verdict = result.verdict                # 'approved'|'iterate'|'escalate'

    # ✅ axis 추출 (paradox short-circuit 시 None — None-check 필수):
    if result.axis_scores is not None:
        cohesion = result.axis_scores.cohesion    # 1-5 int

    # ✅ fallback 감지 (legacy E2 분기):
    if result.fallback_reason is not None:
        log(f"degraded to legacy E2: {result.fallback_reason}")

    # ❌ broken (AttributeError — quorum_verdict 는 EnsembleVerdict 전용):
    final_verdict = result.quorum_verdict         # field 부재

    # ❌ broken (axis_scores=None on paradox fail — None.cohesion crash):
    cohesion = result.axis_scores.cohesion        # AttributeError without guard
    ```

    Caller 가 wrong accessor 사용 시 즉시 AttributeError. silent fallback
    안 함 — fail-loud 정책 (debug 용이성 > silent corruption 회피).
    EnsembleVerdict caller guide (lib/ensemble_evaluator.py:210) 와
    field-name invariant 가 대칭으로 enforce.
    """
    verdict: VerdictLiteral
    paradox_guard: ParadoxGuardResult
    axis_scores: AxisScores | None
    reasons: tuple[StructuredReason, ...]
    model_used: str
    sid: str
    fallback_reason: str | None = None


# ---- D5 deterministic helpers ----

PARADOX_MIN_CITATION_COUNT: int = 3


def paradox_guard(test_pass: bool, citation_count: int,
                  ontology_match: bool) -> ParadoxGuardResult:
    """3-condition hard-fail invariant per Phase A interview lock.

    verdict='approved' is unreachable unless `passes=True`. Caller
    (evaluate / dispatcher) MUST short-circuit when passes=False.

    Executable examples: ``tests/test_evaluator.py::test_paradox_guard_*``
    (7 cases, L81-130) — kept in sync via unit-test regression, immune to
    ReasonCode enum / append-order refactor.
    """
    reasons: list[StructuredReason] = []
    if not test_pass:
        reasons.append(StructuredReason(
            axis="paradox_guard",
            code=ReasonCode.TEST_FAIL,
            detail="test_pass is False (validators+units regression failed)",
        ))
    if not isinstance(citation_count, int) or citation_count < PARADOX_MIN_CITATION_COUNT:
        reasons.append(StructuredReason(
            axis="paradox_guard",
            code=ReasonCode.INSUFFICIENT_CITATIONS,
            detail=f"citation_count={citation_count} < {PARADOX_MIN_CITATION_COUNT}",
        ))
    if not ontology_match:
        reasons.append(StructuredReason(
            axis="paradox_guard",
            code=ReasonCode.ONTOLOGY_MISMATCH,
            detail="ontology_match is False (Designer ontology not preserved)",
        ))
    return ParadoxGuardResult(
        passes=(len(reasons) == 0),
        reasons=tuple(reasons),
    )


def completeness_pass(validators_passed: bool, units_passed: bool,
                       known_defects: int) -> bool:
    """Strict boolean completeness gate per Phase A lock.

    True iff validators_passed AND units_passed AND known_defects==0.
    No fuzzy thresholds.
    """
    if not isinstance(known_defects, int):
        return False
    return bool(validators_passed) and bool(units_passed) and known_defects == 0


def clamp_verdict_on_completeness(verdict: VerdictLiteral,
                                    completeness: bool) -> tuple[VerdictLiteral, StructuredReason | None]:
    """Post-LLM normalization: completeness=False forces verdict to
    'iterate' (not 'approved'). Returns (clamped_verdict, clamp_event_reason).

    Per debate gen 1 condition C2: no LLM/subagent response can override
    the completeness boolean; any 'approved' verdict with completeness=False
    is rewritten to 'iterate' with a clamp event recorded.
    """
    if completeness:
        return verdict, None
    if verdict == "approved":
        return "iterate", StructuredReason(
            axis="completeness",
            code=ReasonCode.COMPLETENESS_BOOLEAN_FALSE,
            detail="LLM emitted 'approved' but completeness=False — clamped to 'iterate'",
        )
    return verdict, None
