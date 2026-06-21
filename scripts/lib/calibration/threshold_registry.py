"""threshold_registry — tunable-vs-locked allowlist for telemetry-driven threshold tuning (M22).

Converged design: debate-1781603679-a14912 gen 2 (snapshot sha1
5f5a187040bcb212f2f468aabadda1312be1dfe2), decision D1.

The REGISTRY is a closed-world allowlist: ONLY thresholds listed here may be proposed
(threshold_proposer iterates `REGISTRY.values()`) or applied (threshold_policy re-checks
membership). LOCKED_DENY enumerates the harness's NEVER-tune invariant constants (the
2-Strike / dispatch-quota / graduation / convergence family). The two MUST be disjoint.

Enforcement of disjointness (D1, per gen-1 Critic B4): NOT an import-time `assert` — an
assert is stripped under `python -O`, and an ImportError raised during module load is
uncatchable by a hook's main()-scoped try/except (silently empties `<activated-skills>`).
Instead disjointness is enforced by (a) `assert_locked_disjoint()` raising ValueError,
called at the top of `threshold_proposer.propose_threshold_changes()` (runtime), AND
(b) the `threshold_registry_locked` run_all validator (compile-time boolean pass/fail).

`metric_dotted` / `guard_dotted` are dotted import paths resolved lazily by the gate/proposer
(keeps this module dependency-light: no import of skill_match telemetry code at load time).
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Callable, Literal


@dataclass(frozen=True)
class TunableThreshold:
    """One registered tunable threshold (D1 schema)."""

    name: str                 # canonical key, == f"{module}.{constant}"
    module: str               # the module path holding the live constant
    constant: str             # the constant name it shadows
    default: float            # the in-code default (resolve_threshold falls back to this)
    telemetry_source: str     # telemetry/<name>.jsonl that informs proposals
    target_metric: str        # what the proposal optimizes (higher = better, oriented in metric_fn)
    guard_metric: str         # what must not regress (higher = better, oriented in guard_fn)
    direction_safety: Literal["raise_safe", "lower_safe", "either"]
    step: float               # single-step increment (T3 conservatism)
    process_lifetime: str     # 'short_hook' (resolve-at-import safe) | 'long_lived' (must resolve at call)
    metric_dotted: str = ""   # dotted path 'mod:func' for metric_fn(events, threshold)->float
    guard_dotted: str = ""    # dotted path 'mod:func' for guard_fn(events, threshold)->float

    def qualified(self) -> str:
        return f"{self.module}.{self.constant}"


def _resolve_dotted(path: str) -> Callable[..., Any] | None:
    """Resolve a 'package.module:function' dotted path, or None on failure (fail-soft)."""
    if not path or ":" not in path:
        return None
    mod_path, _, func_name = path.partition(":")
    try:
        mod = importlib.import_module(mod_path)
        fn = getattr(mod, func_name, None)
        return fn if callable(fn) else None
    except Exception:  # noqa: BLE001 — fail-soft: unresolved metric -> gate fails closed
        return None


# --- The tunable allowlist (closed world) ---------------------------------------
# Keyed by canonical name. ONLY these may be proposed/applied. Currently only
# FULL_BODY_MIN_SCORE has live metric/guard wiring + a refactored call-site; the
# other four are registry-declared (governed by the validator) but override-inert
# until each is separately wired + graduated.
REGISTRY: dict[str, TunableThreshold] = {
    "skill_match.FULL_BODY_MIN_SCORE": TunableThreshold(
        name="skill_match.FULL_BODY_MIN_SCORE",
        module="handlers.prompt.skill_match",
        constant="FULL_BODY_MIN_SCORE",
        default=3,
        telemetry_source="skill-match",
        target_metric="full_body_admit_precision",  # higher = fewer borderline admits
        guard_metric="non_truncation_rate",          # higher = less context-budget truncation
        direction_safety="either",
        step=1,
        process_lifetime="short_hook",  # skill_match runs as a fresh per-prompt process
        metric_dotted="lib.calibration.threshold_metrics:full_body_admit_precision",
        guard_dotted="lib.calibration.threshold_metrics:non_truncation_rate",
    ),
    "skill_candidate_detector._THRESHOLD": TunableThreshold(
        name="skill_candidate_detector._THRESHOLD",
        module="lib.skill_candidate_detector", constant="_THRESHOLD", default=10,
        telemetry_source="skill-candidate", target_metric="candidate_signal_rate",
        guard_metric="noise_suppression_rate", direction_safety="raise_safe",
        step=1, process_lifetime="short_hook",
    ),
    "handoff_resume.STALE_DAYS_THRESHOLD": TunableThreshold(
        name="handoff_resume.STALE_DAYS_THRESHOLD",
        module="handlers.prompt.handoff_resume", constant="STALE_DAYS_THRESHOLD", default=7,
        telemetry_source="handoff-resume", target_metric="resume_relevance_rate",
        guard_metric="stale_suppression_rate", direction_safety="either",
        step=1, process_lifetime="short_hook",
    ),
    "skill_telemetry_audit.FP_THIN_RATE": TunableThreshold(
        name="skill_telemetry_audit.FP_THIN_RATE",
        module="cli.skill_telemetry_audit", constant="FP_THIN_RATE", default=0.8,
        telemetry_source="skill-match", target_metric="fp_flag_precision",
        guard_metric="fp_flag_recall", direction_safety="either",
        step=0.05, process_lifetime="long_lived",
    ),
    "ratio_tracker.WARN_THRESHOLD": TunableThreshold(
        name="ratio_tracker.WARN_THRESHOLD",
        module="lib.ratio_tracker", constant="WARN_THRESHOLD", default=3.0,
        telemetry_source="read-edit-ratio", target_metric="warn_precision",
        guard_metric="warn_recall", direction_safety="raise_safe",
        step=0.5, process_lifetime="short_hook",
    ),
}


# --- LOCKED invariants — NEVER tune/propose/apply --------------------------------
# Every entry is a `module.constant` string. These are the 2-Strike, dispatch-quota,
# graduation, evaluator-loop-guard, promotion and convergence invariants the CLAUDE.md
# Mutation table protects. The proposer/apply path must NEVER touch any of these.
LOCKED_DENY: frozenset[str] = frozenset({
    "lib.repeat_error_tracker.STRIKE_THRESHOLD",
    "lib.repeat_error_tracker.ESCALATED_THRESHOLD",
    "lib.strike_dispatcher.RESEARCH_DISPATCH_THRESHOLD",
    "lib.strike_dispatcher.PER_FINGERPRINT_DISPATCH_LIMIT",
    "lib.wonder.WONDER_STRIKE_THRESHOLD",
    "lib.wonder.WONDER_DEPTH_CAP",
    "lib.graduation.GRADUATION_THRESHOLD",
    "lib.evaluator_dispatcher.PER_PHASE_EVAL_LIMIT",
    "lib.l2_promoter._GROUP_THRESHOLD",
    "lib.phase_tree.PROMOTION_STEP_THRESHOLD",
    "lib.phase_tree.PROMOTION_SUB_STEP_THRESHOLD",
    "engine.debate.GENERATION_HARD_CAP",  # convergence gen cap = 4 (conceptual lock)
})


def assert_locked_disjoint() -> None:
    """Raise ValueError if any REGISTRY entry's qualified name is in LOCKED_DENY.

    The runtime half of D1 enforcement (the validator is the compile-time half).
    Called at the top of propose_threshold_changes() so a misconfigured registry
    can NEVER emit a proposal for a locked invariant — fail-closed, not fail-silent.
    """
    overlap = sorted({e.qualified() for e in REGISTRY.values()} & LOCKED_DENY)
    if overlap:
        raise ValueError(
            f"threshold_registry: REGISTRY overlaps LOCKED_DENY (invariants are NEVER "
            f"tunable): {overlap}. Remove these from REGISTRY."
        )


def is_locked(qualified_name: str) -> bool:
    return qualified_name in LOCKED_DENY


def get(name: str) -> TunableThreshold | None:
    return REGISTRY.get(name)


def metric_fn_for(entry: TunableThreshold) -> Callable[..., float] | None:
    return _resolve_dotted(entry.metric_dotted)  # type: ignore[return-value]


def guard_fn_for(entry: TunableThreshold) -> Callable[..., float] | None:
    return _resolve_dotted(entry.guard_dotted)  # type: ignore[return-value]
