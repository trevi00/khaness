"""threshold_proposer — telemetry→numeric-threshold change proposals, STAGED only (M22 D2).

Converged design: debate-1781603679-a14912 gen 2 (D2). Numeric-threshold analog of
lib/calibration/proposer.py (which proposes critic invoke/skip). Mirrors its R1-R4
conservatism, determinism, and fail-soft contract. STAGES proposals only — apply is the
operator's token-gated job (lib/threshold_policy.py); the agent never applies.

Rules (T1-T4, mirroring proposer.py R1-R4):
  T1 min-sample : telemetry sample < MIN_SAMPLE_SIZE → no proposal (insufficient evidence)
  T2 hysteresis : only propose when a single step IMPROVES the target on the TRAILING window
                  by more than HYSTERESIS_MARGIN (avoids flapping re-proposals)
  T3 single-step: suggested = current ± entry.step (never a jump)
  T4 direction  : never propose the unsafe direction for a raise_safe/lower_safe entry

Non-tautology (gen-1 Critic B1): the proposer optimizes the target on a TRAILING window
(events before holdout_boundary) and NEVER sees the held-out later window. The gate
(no_degradation_gate.evaluate_threshold_change) independently validates on the held-out
window, so an accepted proposal is one whose improvement GENERALIZES, not one constructed
to win. On gate-accept a ready-flag is emitted (auto-OK); the token-gated apply consumes it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .proposer import MIN_SAMPLE_SIZE  # reuse the established min-sample floor (=10)
from . import threshold_registry as reg
from ..no_degradation_gate import evaluate_threshold_change, ThresholdGateResult

HOLDOUT_FRACTION: float = 0.30      # last 30% of events (by ts) = held-out validation window
HYSTERESIS_MARGIN: float = 0.02     # trailing-window target must improve by more than this


@dataclass
class ThresholdProposal:
    """A single staged threshold-change proposal (D2 schema)."""

    name: str
    current: float
    suggested: float | None
    evidence: dict[str, Any]
    rationale: str
    holdout_boundary: str | None = None
    gate_result: ThresholdGateResult | None = None
    note: str | None = None


def _ready_flag_path(name: str) -> Path:
    from ..paths import STATE_DIR
    safe = name.replace("/", "_").replace("\\", "_")
    return STATE_DIR / "threshold-ready" / f"{safe}.flag"


def _emit_ready_flag(proposal: ThresholdProposal) -> None:
    """Emit the per-threshold ready-flag (auto-OK; consumption is token-gated in
    threshold_policy). Mirrors lib.graduation ready-flag: emission auto, flip gated."""
    import json
    from ..paths import STATE_DIR, ensure_dir
    from ..logging import now_iso
    try:
        ensure_dir(STATE_DIR / "threshold-ready")
        _ready_flag_path(proposal.name).write_text(
            json.dumps({
                "ts": now_iso(), "name": proposal.name,
                "suggested": proposal.suggested, "current": proposal.current,
                "target_delta_holdout": (proposal.gate_result.target_delta_holdout
                                         if proposal.gate_result else None),
            }, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def _holdout_boundary(events: list[dict]) -> str | None:
    """Return the ts that splits the last HOLDOUT_FRACTION of events (by ts) as held-out."""
    tss = sorted(ev.get("ts") for ev in events if isinstance(ev.get("ts"), str))
    if len(tss) < 2:
        return None
    idx = int(len(tss) * (1.0 - HOLDOUT_FRACTION))
    idx = min(max(idx, 1), len(tss) - 1)
    return tss[idx]


def _direction_allowed(entry: reg.TunableThreshold, proposed: float) -> bool:
    if entry.direction_safety == "either":
        return True
    if entry.direction_safety == "raise_safe":
        return proposed >= entry.default  # only raising is the safe/proposable direction
    if entry.direction_safety == "lower_safe":
        return proposed <= entry.default
    return True


def propose_threshold_changes(
    *,
    telemetry_root: Path | None = None,
    min_sample: int = MIN_SAMPLE_SIZE,
    events_by_source: dict[str, list[dict]] | None = None,
) -> list[ThresholdProposal]:
    """Scan the registry → staged proposals (gate-validated). Deterministic, fail-soft.

    `events_by_source` lets tests inject telemetry directly; otherwise events are read via
    lib.telemetry_read.iter_events(entry.telemetry_source). Proposals are returned in
    registry-name order. Only entries with a resolvable metric/guard AND a gate verdict are
    returned with a suggested value; others may return a note-only advisory.
    """
    reg.assert_locked_disjoint()  # D1 runtime enforcement — fail-closed on locked overlap

    proposals: list[ThresholdProposal] = []
    for name in sorted(reg.REGISTRY):
        entry = reg.REGISTRY[name]
        metric_fn = reg.metric_fn_for(entry)
        guard_fn = reg.guard_fn_for(entry)
        if metric_fn is None or guard_fn is None:
            continue  # entry not yet wired (registry-declared, override-inert)

        if events_by_source is not None:
            events = list(events_by_source.get(entry.telemetry_source, []))
        else:
            from ..telemetry_read import iter_events
            events = list(iter_events(entry.telemetry_source))

        # T1 min-sample floor.
        if len(events) < min_sample:
            continue

        boundary = _holdout_boundary(events)
        if boundary is None:
            continue
        trailing = [e for e in events if not (isinstance(e.get("ts"), str) and e["ts"] >= boundary)]
        if len(trailing) < min_sample:
            continue

        current = float(entry.default)
        cur_target = float(metric_fn(trailing, current))

        # T3 single-step candidates in both directions; T4 filters the unsafe direction.
        # For each candidate that improves the TRAILING target past the hysteresis margin
        # (T2), independently GATE it on the held-out window. The proposer optimizes on
        # trailing but the GATE (held-out + budget guard) decides acceptability — so a
        # candidate that wins the trailing metric vacuously (e.g. lowering the bar below
        # the data) but bloats the budget is rejected by the guard, not shipped. Among
        # gate-ACCEPTED candidates, pick the best held-out target improvement.
        accepted: list[tuple[float, float, "ThresholdGateResult", float]] = []
        last_reject: tuple[float, float, "ThresholdGateResult"] | None = None
        for cand in (current + entry.step, current - entry.step):
            if not _direction_allowed(entry, cand):
                continue
            try:
                cand_target = float(metric_fn(trailing, cand))
            except Exception:  # noqa: BLE001
                continue
            if cand_target - cur_target <= HYSTERESIS_MARGIN:  # T2
                continue
            gate = evaluate_threshold_change(
                events=events, old_value=current, proposed_value=cand,
                metric_fn=metric_fn, guard_fn=guard_fn, holdout_boundary=boundary,
                min_corpus=min_sample,
            )
            if gate.accept:
                accepted.append((cand, cand_target, gate, gate.target_delta_holdout or 0.0))
            else:
                last_reject = (cand, cand_target, gate)

        if accepted:
            accepted.sort(key=lambda x: -x[3])  # best held-out improvement first
            proposed, trailing_target, gate, _ = accepted[0]
            proposal = ThresholdProposal(
                name=name, current=current, suggested=proposed,
                evidence={"sample_size": len(events), "trailing_size": len(trailing),
                          "trailing_target_current": cur_target, "trailing_target_proposed": trailing_target},
                rationale=(
                    f"trailing-window {entry.target_metric} {cur_target:.3f}->{trailing_target:.3f} at "
                    f"{name}={proposed} (step {entry.step}); held-out gate: {gate.reason}. Apply = operator + token."
                ),
                holdout_boundary=boundary, gate_result=gate, note=None,
            )
            _emit_ready_flag(proposal)
            proposals.append(proposal)
        elif last_reject is not None:
            # A trailing improvement existed but no candidate passed the held-out gate —
            # surface as a note-only advisory (no apply offered). 'recommend=False도 누적가치'.
            cand, trailing_target, gate = last_reject
            proposals.append(ThresholdProposal(
                name=name, current=current, suggested=None,
                evidence={"sample_size": len(events), "trailing_size": len(trailing),
                          "trailing_target_current": cur_target, "trailing_target_proposed": trailing_target},
                rationale=(f"trailing improvement at {name}={cand} did not generalize/clear the guard."),
                holdout_boundary=boundary, gate_result=gate,
                note=f"gate did not accept ({gate.reason}) — no apply offered",
            ))
    return proposals
