"""no_degradation_gate — conservative acceptance gate for strike→skill candidates (M18).

Converged design: debate-1781594208-53fee4 gen 3 (snapshot sha1
286f4c8e18a4427dcc897e2b86a4e1844b5a6c79), decision D2.

For a **skill_gotcha** candidate (the only auto-stageable change type), the gate is:

    accept == (probe_passed AND secret_clean)

The held-in/held-out dual-suite + scratch-apply machinery from the first draft was
DROPPED here, on purpose, after the gen-1/gen-2 debate established that a skill_gotcha
is advisory markdown appended to a `skills/*.md` Gotchas section — which `tests/run_all.py`
(validator walk) and `tests/run_units.py` (`tests/test_*.py` glob) NEVER execute. So the
"held-in" pass-count delta (Δ_in) is *identically zero* for every skill_gotcha; a dual-suite
re-run could neither veto nor carry the verdict. The only load-bearing evidence a
skill_gotcha can offer is that the fingerprint it documents is a real, deterministically
reproducible failure (probe_passed, via lib.repro_probe) and that the candidate carries no
leaked secret (secret_clean, via lib.skill_candidate_detector._secret_scan_pass).

FUTURE RESERVATION (do NOT delete the intent): a future `hook_rule`/`code-patch` candidate
type DOES change validator/unit pass-counts when applied. For that type the held-in/held-out
two-split regression gate (Self-Harness-style: apply to a scratch copy, re-run run_units +
run_all, accept only on no-degradation) is the correct shape and should be added here as
`evaluate_code_patch(...)`. It is deliberately NOT wired for skill_gotcha.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GateResult:
    """Outcome of the no-degradation gate for one candidate."""

    accept: bool
    probe_passed: bool
    secret_clean: bool
    reason: str


def evaluate_skill_gotcha(candidate, probe) -> GateResult:
    """Gate a skill_gotcha candidate: accept == (probe_passed AND secret_clean).

    Args:
      candidate: a lib.skill_candidate_detector.SkillCandidate (or any object with a
        `.secret_scan_clean` bool — the secret scan is run by the caller via
        `_secret_scan_pass` and reflected onto the candidate; we read the result here
        so the gate stays a pure decision function with no I/O).
      probe: a lib.repro_probe.Probe or None. None means the fingerprint is NOT
        deterministically reproducible (transient class or precondition-fidelity lost)
        → the caller routes to operator-escalation; here it simply fails the gate
        (accept=False) WITHOUT staging. The caller MUST distinguish None-probe
        (escalate) from probe.passed()==False — but in this design a constructed
        Probe always passes, so None is the only non-accept probe state.

    Fail-safe: any unexpected shape collapses to a non-accept GateResult (never stages
    on uncertainty), mirroring the M14 fail-closed contract.
    """
    try:
        probe_passed = bool(probe is not None and probe.passed())
    except Exception:  # noqa: BLE001 — defensive: a malformed probe must not stage
        return GateResult(False, False, False, "probe_eval_error")

    try:
        secret_clean = bool(getattr(candidate, "secret_scan_clean", False))
    except Exception:  # noqa: BLE001
        return GateResult(False, probe_passed, False, "candidate_shape_error")

    accept = probe_passed and secret_clean
    if accept:
        reason = "accept: probe grounded + secret-clean"
    elif not probe_passed:
        reason = "no-stage: probe is None (non-deterministic/transient) -> escalate"
    else:
        reason = "no-stage: secret scan dirty"
    return GateResult(accept=accept, probe_passed=probe_passed,
                      secret_clean=secret_clean, reason=reason)


# ============================================================================
# M22 (debate-1781603679-a14912, D3) — numeric-threshold change gate.
# This is the "future code-patch / pass-count-changing candidate type" the module
# docstring reserved. A threshold change DOES move metrics, so unlike skill_gotcha it
# gets the conservative no-degradation regression gate — applied on a TEMPORAL HELD-OUT
# window so the gate is non-tautological (validates that the improvement GENERALIZES to
# events the proposer did not optimize on, not that it was constructed). GateResult and
# evaluate_skill_gotcha above are left BYTE-UNTOUCHED (gen-1 Critic B6).
# ============================================================================

import math as _math  # noqa: E402


@dataclass(frozen=True)
class ThresholdGateResult:
    """Outcome of the no-degradation gate for a numeric-threshold change (M22 D3)."""

    accept: bool
    target_delta_holdout: float | None
    guard_delta: float | None
    reason: str


def evaluate_threshold_change(
    *,
    events: list,
    old_value: float,
    proposed_value: float,
    metric_fn,
    guard_fn,
    holdout_boundary: str,
    min_corpus: int = 10,
) -> ThresholdGateResult:
    """Gate a numeric-threshold change. ACCEPT iff the proposed value improves the target
    metric on a TEMPORAL HELD-OUT window AND does not regress the budget-pressure guard.

    Split: events with ts < holdout_boundary are the proposer's TRAILING (train) window;
    events with ts >= holdout_boundary are the HELD-OUT window the gate validates on. The
    target delta is measured ONLY on the held-out window (non-tautological, B1); the guard
    delta is measured on the full corpus (a general budget property, not the optimization
    target). metric_fn/guard_fn return floats where HIGHER = BETTER.

      ACCEPT == (delta_target > 0 on held-out) AND (delta_guard >= 0)

    FAIL-CLOSED (accept=False) on: corpus or either split below min_corpus
    (corpus_too_small / insufficient_holdout); metric_fn/guard_fn raises (replay_error);
    any of the four metric values non-finite (non_finite — e.g. guard returns NaN because
    telemetry lacks body_chars). Mirrors the M18 fail-closed contract: never accept on
    uncertainty.
    """
    if metric_fn is None or guard_fn is None:
        return ThresholdGateResult(False, None, None, "unresolved_metric_fn")
    if not isinstance(events, list) or len(events) < min_corpus:
        return ThresholdGateResult(False, None, None, "corpus_too_small")

    try:
        from .calibration.threshold_metrics import split_by_holdout
        trailing, holdout = split_by_holdout(events, holdout_boundary)
    except Exception as exc:  # noqa: BLE001
        return ThresholdGateResult(False, None, None, f"split_error:{type(exc).__name__}")

    if len(holdout) < min_corpus or len(trailing) < min_corpus:
        return ThresholdGateResult(False, None, None, "insufficient_holdout")

    try:
        t_new = float(metric_fn(holdout, proposed_value))
        t_old = float(metric_fn(holdout, old_value))
        g_new = float(guard_fn(events, proposed_value))
        g_old = float(guard_fn(events, old_value))
    except Exception as exc:  # noqa: BLE001 — fail-closed on any replay error
        return ThresholdGateResult(False, None, None, f"replay_error:{type(exc).__name__}")

    if not all(_math.isfinite(v) for v in (t_new, t_old, g_new, g_old)):
        return ThresholdGateResult(False, None, None, "non_finite_metric")

    target_delta = t_new - t_old
    guard_delta = g_new - g_old
    accept = (target_delta > 0) and (guard_delta >= 0)
    if accept:
        reason = "accept: target improves on held-out, guard not regressed"
    elif target_delta <= 0:
        reason = "no-stage: target did not improve on held-out window"
    else:
        reason = "no-stage: guard regressed (budget pressure increased)"
    return ThresholdGateResult(accept, target_delta, guard_delta, reason)
