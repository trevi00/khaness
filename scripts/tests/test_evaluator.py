#!/usr/bin/env python3
"""Unit tests for lib/evaluator.py — DGE E2 core (Phase 1 wave 1)
per debate-1778248254-0b7092."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


# ---- D2 cross-provider invariant ----

def test_default_evaluator_model_is_codex_delegated():
    """DEFAULT_EVALUATOR_MODEL='' delegates to Codex CLI configured default.

    Cross-provider invariant enforced at PROVIDER level (OpenAIProvider via
    codex exec) — not at model-id string level. Empty string avoids the
    failure mode where a hardcoded id (e.g. 'gpt-5.5') is unrecognized by
    Codex CLI's actual model namespace.
    """
    from lib.evaluator import DEFAULT_EVALUATOR_MODEL
    assert DEFAULT_EVALUATOR_MODEL == ""


def test_resolve_evaluator_model_default_when_env_unset():
    from lib.evaluator import resolve_evaluator_model, DEFAULT_EVALUATOR_MODEL
    assert resolve_evaluator_model({}) == DEFAULT_EVALUATOR_MODEL


def test_resolve_evaluator_model_empty_default_passes_paradox_guard():
    """Empty string is non-Anthropic by definition (any id starting with
    'claude-' or 'anthropic-' is rejected; '' is neither)."""
    from lib.evaluator import resolve_evaluator_model
    # No raise — empty string falls through cross-provider check
    assert resolve_evaluator_model({}) == ""


def test_resolve_evaluator_model_respects_env_override_non_anthropic():
    from lib.evaluator import resolve_evaluator_model
    assert resolve_evaluator_model({"EVALUATOR_MODEL": "gpt-4o"}) == "gpt-4o"


def test_resolve_evaluator_model_rejects_anthropic_default():
    from lib.evaluator import resolve_evaluator_model, ConfigError
    try:
        resolve_evaluator_model({"EVALUATOR_MODEL": "claude-opus-4-7"})
    except ConfigError as e:
        assert "differ from generator" in str(e)
        return
    raise AssertionError("expected ConfigError on Anthropic family")


def test_resolve_evaluator_model_allows_anthropic_with_override():
    from lib.evaluator import resolve_evaluator_model
    out = resolve_evaluator_model({
        "EVALUATOR_MODEL": "claude-opus-4-7",
        "EVALUATOR_ALLOW_SAME_FAMILY": "1",
    })
    assert out == "claude-opus-4-7"


def test_resolve_evaluator_model_anthropic_prefix_id_also_rejected():
    from lib.evaluator import resolve_evaluator_model, ConfigError
    try:
        resolve_evaluator_model({"EVALUATOR_MODEL": "anthropic-fast"})
    except ConfigError:
        return
    raise AssertionError("expected ConfigError on anthropic- prefix")


def test_resolve_evaluator_model_empty_env_falls_back_to_default():
    from lib.evaluator import resolve_evaluator_model, DEFAULT_EVALUATOR_MODEL
    assert resolve_evaluator_model({"EVALUATOR_MODEL": ""}) == DEFAULT_EVALUATOR_MODEL


# ---- D1 paradox_guard 3-condition invariant ----

def test_paradox_guard_passes_all_three_conditions():
    from lib.evaluator import paradox_guard
    r = paradox_guard(test_pass=True, citation_count=3, ontology_match=True)
    assert r.passes is True
    assert r.reasons == ()


def test_paradox_guard_fails_on_test_fail():
    from lib.evaluator import paradox_guard, ReasonCode
    r = paradox_guard(test_pass=False, citation_count=5, ontology_match=True)
    assert r.passes is False
    assert any(x.code == ReasonCode.TEST_FAIL for x in r.reasons)


def test_paradox_guard_fails_on_insufficient_citations():
    from lib.evaluator import paradox_guard, ReasonCode
    r = paradox_guard(test_pass=True, citation_count=2, ontology_match=True)
    assert r.passes is False
    assert any(x.code == ReasonCode.INSUFFICIENT_CITATIONS for x in r.reasons)


def test_paradox_guard_fails_on_ontology_mismatch():
    from lib.evaluator import paradox_guard, ReasonCode
    r = paradox_guard(test_pass=True, citation_count=3, ontology_match=False)
    assert r.passes is False
    assert any(x.code == ReasonCode.ONTOLOGY_MISMATCH for x in r.reasons)


def test_paradox_guard_fails_with_all_three_reasons_when_all_fail():
    from lib.evaluator import paradox_guard
    r = paradox_guard(test_pass=False, citation_count=0, ontology_match=False)
    assert r.passes is False
    assert len(r.reasons) == 3


def test_paradox_guard_citation_count_exactly_at_threshold_passes():
    """Boundary: count == PARADOX_MIN_CITATION_COUNT is acceptable."""
    from lib.evaluator import paradox_guard, PARADOX_MIN_CITATION_COUNT
    r = paradox_guard(
        test_pass=True,
        citation_count=PARADOX_MIN_CITATION_COUNT,
        ontology_match=True,
    )
    assert r.passes is True


def test_paradox_guard_non_int_citation_count_fails():
    from lib.evaluator import paradox_guard
    r = paradox_guard(test_pass=True, citation_count="three", ontology_match=True)  # type: ignore[arg-type]
    assert r.passes is False


# ---- completeness_pass strict boolean ----

def test_completeness_passes_when_all_three_conditions_met():
    from lib.evaluator import completeness_pass
    assert completeness_pass(True, True, 0) is True


def test_completeness_fails_on_validators_fail():
    from lib.evaluator import completeness_pass
    assert completeness_pass(False, True, 0) is False


def test_completeness_fails_on_units_fail():
    from lib.evaluator import completeness_pass
    assert completeness_pass(True, False, 0) is False


def test_completeness_fails_on_any_known_defect():
    from lib.evaluator import completeness_pass
    assert completeness_pass(True, True, 1) is False
    assert completeness_pass(True, True, 99) is False


def test_completeness_rejects_non_int_known_defects():
    from lib.evaluator import completeness_pass
    assert completeness_pass(True, True, "0") is False  # type: ignore[arg-type]


# ---- clamp_verdict_on_completeness post-LLM normalization ----

def test_clamp_no_op_when_completeness_true():
    from lib.evaluator import clamp_verdict_on_completeness
    v, reason = clamp_verdict_on_completeness("approved", True)
    assert v == "approved"
    assert reason is None


def test_clamp_rewrites_approved_to_iterate_when_completeness_false():
    from lib.evaluator import clamp_verdict_on_completeness, ReasonCode
    v, reason = clamp_verdict_on_completeness("approved", False)
    assert v == "iterate"
    assert reason is not None
    assert reason.code == ReasonCode.COMPLETENESS_BOOLEAN_FALSE


def test_clamp_does_not_alter_iterate_when_completeness_false():
    from lib.evaluator import clamp_verdict_on_completeness
    v, reason = clamp_verdict_on_completeness("iterate", False)
    assert v == "iterate"
    assert reason is None


def test_clamp_does_not_alter_escalate_when_completeness_false():
    from lib.evaluator import clamp_verdict_on_completeness
    v, reason = clamp_verdict_on_completeness("escalate", False)
    assert v == "escalate"


# ---- EvaluatorVerdict + dataclass shape ----

def test_evaluator_verdict_is_frozen_dataclass():
    """D1 invariant: dataclass(frozen=True) — mutation raises."""
    from lib.evaluator import (
        EvaluatorVerdict, ParadoxGuardResult, AxisScores,
    )
    v = EvaluatorVerdict(
        verdict="iterate",
        paradox_guard=ParadoxGuardResult(passes=False),
        axis_scores=None,
        reasons=(),
        model_used="gpt-5.5",
        sid="orch-test-aaa",
    )
    try:
        v.verdict = "approved"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("expected frozen dataclass to reject mutation")


def test_axis_scores_completeness_is_boolean_not_int():
    """D6 axis: 5 axes 1-5 score, completeness is boolean GATE."""
    from lib.evaluator import AxisScores
    a = AxisScores(cohesion=5, coupling=4, extensibility=4,
                   stability=5, usability=5, completeness=True)
    assert isinstance(a.completeness, bool)


def test_evaluator_verdict_field_invariant():
    """Defense-in-depth L4 anti-regression (inverse symmetric to
    ensemble_evaluator.py case 19, commit 66d7e4a):

    Caller spec uses `result.verdict` (single-evaluator path). If schema
    drifts to rename `.verdict` → `.quorum_verdict` (e.g., mistaken
    unification with EnsembleVerdict) OR adds `.quorum_verdict` shadow,
    caller specs in commands/harness-evaluate.md silently break OR
    become ambiguous. Lock both halves:
    """
    import dataclasses as _dc
    from lib.evaluator import EvaluatorVerdict

    field_names = {f.name for f in _dc.fields(EvaluatorVerdict)}

    assert "verdict" in field_names, (
        f"missing 'verdict' field — caller .verdict access broken; "
        f"fields={field_names}"
    )
    assert "quorum_verdict" not in field_names, (
        f"unexpected 'quorum_verdict' field — caller would confuse "
        f"single-evaluator with EnsembleVerdict.quorum_verdict; "
        f"fields={field_names}"
    )
    assert "axis_scores" in field_names, (
        f"missing 'axis_scores' field — forensic axis access broken; "
        f"fields={field_names}"
    )
    assert "paradox_guard" in field_names, (
        f"missing 'paradox_guard' field — caller paradox introspection "
        f"broken; fields={field_names}"
    )


TESTS = [
    test_default_evaluator_model_is_codex_delegated,
    test_resolve_evaluator_model_default_when_env_unset,
    test_resolve_evaluator_model_empty_default_passes_paradox_guard,
    test_resolve_evaluator_model_respects_env_override_non_anthropic,
    test_resolve_evaluator_model_rejects_anthropic_default,
    test_resolve_evaluator_model_allows_anthropic_with_override,
    test_resolve_evaluator_model_anthropic_prefix_id_also_rejected,
    test_resolve_evaluator_model_empty_env_falls_back_to_default,
    test_paradox_guard_passes_all_three_conditions,
    test_paradox_guard_fails_on_test_fail,
    test_paradox_guard_fails_on_insufficient_citations,
    test_paradox_guard_fails_on_ontology_mismatch,
    test_paradox_guard_fails_with_all_three_reasons_when_all_fail,
    test_paradox_guard_citation_count_exactly_at_threshold_passes,
    test_paradox_guard_non_int_citation_count_fails,
    test_completeness_passes_when_all_three_conditions_met,
    test_completeness_fails_on_validators_fail,
    test_completeness_fails_on_units_fail,
    test_completeness_fails_on_any_known_defect,
    test_completeness_rejects_non_int_known_defects,
    test_clamp_no_op_when_completeness_true,
    test_clamp_rewrites_approved_to_iterate_when_completeness_false,
    test_clamp_does_not_alter_iterate_when_completeness_false,
    test_clamp_does_not_alter_escalate_when_completeness_false,
    test_evaluator_verdict_is_frozen_dataclass,
    test_axis_scores_completeness_is_boolean_not_int,
    test_evaluator_verdict_field_invariant,
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
