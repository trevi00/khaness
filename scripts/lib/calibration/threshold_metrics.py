"""threshold_metrics — metric/guard functions replayed by the M22 gate over skill-match telemetry.

Converged design: debate-1781603679-a14912 (D3). These are the dotted-path targets the
registry references for `skill_match.FULL_BODY_MIN_SCORE`. Each is a PURE function of
(events, threshold) returning a float where HIGHER = BETTER, so the gate computes a simple
`metric(proposed) - metric(old)` oriented delta.

The gate's non-tautology (gen-1 Critic B1) comes from the CALLER replaying these on a
TEMPORAL HELD-OUT window the proposer did not optimize — see threshold_proposer +
evaluate_threshold_change. The guard's non-deadness (B2) comes from `non_truncation_rate`
RE-SIMULATING context-budget pressure at the hypothetical threshold (not the live-recorded
truncated flag), which requires per-skill `body_chars` in the telemetry (added by the
skill_match producer). When body_chars is absent the guard returns NaN → the gate fails
closed (the acknowledged-safe inert mode until telemetry is enriched).

Budget constants mirror handlers/prompt/skill_match.py (MAX_CONTEXT_CHARS=4000,
FULL_BODY_TOP_K=3) — kept local to avoid importing the hook module into lib/.
"""
from __future__ import annotations

import math

_MAX_CONTEXT_CHARS = 4000   # mirrors skill_match.py:48
_FULL_BODY_TOP_K = 3        # mirrors skill_match.py:54


def _top_entries(event: dict) -> list[dict]:
    top = event.get("top")
    return [e for e in top if isinstance(e, dict)] if isinstance(top, list) else []


def split_by_holdout(events: list[dict], holdout_boundary: str) -> tuple[list[dict], list[dict]]:
    """Half-open temporal partition by event `ts`: (trailing ts<boundary, holdout ts>=boundary).

    Strict half-open so no event is shared across the split (gen-2 Critic boundary note).
    Events without a `ts` go to trailing (they predate boundary-aware logging).
    """
    trailing: list[dict] = []
    holdout: list[dict] = []
    for ev in events:
        ts = ev.get("ts")
        if isinstance(ts, str) and ts >= holdout_boundary:
            holdout.append(ev)
        else:
            trailing.append(ev)
    return trailing, holdout


def full_body_admit_precision(events: list[dict], threshold: float) -> float:
    """Fraction of full-body-eligible matches (score>=threshold) that are NOT borderline
    (score strictly > threshold). Higher = the bar admits fewer marginal matches.

    Vacuous case (no eligible matches at this threshold) → 1.0 (nothing marginal admitted).
    Pure, deterministic. Independent of body_chars.
    """
    eligible = 0
    clearly = 0
    for ev in events:
        for e in _top_entries(ev):
            score = e.get("score")
            if not isinstance(score, (int, float)) or isinstance(score, bool):
                continue
            if score >= threshold:
                eligible += 1
                if score > threshold:
                    clearly += 1
    if eligible == 0:
        return 1.0
    return clearly / eligible


def non_truncation_rate(events: list[dict], threshold: float) -> float:
    """1 - (fraction of events whose full-body set would overflow the context budget at
    `threshold`). Higher = less truncation = better. RE-SIMULATES budget pressure at the
    hypothetical threshold using per-skill `body_chars` (so lowering the bar admits more
    bodies → more overflow → lower score → Δ_guard can fire, killing the gen-1 dead guard).

    Returns NaN when NO event carries usable body_chars (telemetry predates the producer
    enrichment) → the gate treats NaN as non-finite and fails closed (safe inert mode).
    """
    usable = 0
    truncated = 0
    for ev in events:
        sized = [
            (e.get("score"), e.get("body_chars"))
            for e in _top_entries(ev)
            if isinstance(e.get("score"), (int, float)) and not isinstance(e.get("score"), bool)
            and isinstance(e.get("body_chars"), int) and e.get("body_chars") >= 0
        ]
        if not sized:
            continue
        usable += 1
        eligible = sorted((s for s in sized if s[0] >= threshold), key=lambda x: -x[0])
        chosen = eligible[:_FULL_BODY_TOP_K]
        total = sum(bc for _s, bc in chosen)
        if total > _MAX_CONTEXT_CHARS:
            truncated += 1
    if usable == 0:
        return math.nan
    return 1.0 - (truncated / usable)
