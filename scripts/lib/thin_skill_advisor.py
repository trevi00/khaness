"""thin_skill_advisor — prompt-time advisory for historically-thin matched skills (M2a).

The skill matcher already DEMOTES weak per-prompt matches (base_score <
FULL_BODY_MIN_SCORE) to one-line pointers, so thin matches don't get injected as
authoritative guides — UNLESS a skill that USUALLY fires thin happens to spike on
a coincidental multi-signal prompt and crosses the full-body threshold. Live
telemetry confirms this is real, not hypothetical: 8 of 16 M7 false-positive
candidates reach full-body injection at least sometimes (e.g. a skill firing thin
81% of the time yet occasionally scoring 12). When that happens the model is handed
a known-broad-match guide as if it were a precise fit, with no warning.

This module is the prompt-time CONSUMER of M7's thin-fire signal (signal collect →
signal spend): given the skills about to be full-body-injected and the historical
skill-match telemetry, it emits ONE advisory line naming any injected skill that is
a historical false-positive candidate. The matcher surfaces it so the model treats
that guidance critically and the operator sees which broad-surface skills keep
getting injected.

Single source of truth: the thin-fire classification constants + predicate live
HERE; cli/skill_telemetry_audit (the passive M7 audit) imports them, so the
prompt-time and report-time definitions can never drift. Pure + fail-soft; the
caller (handlers/prompt/skill_match.py) wraps the call so any error degrades to
silence — a thin-advisory lookup must never break the prompt hook.
"""
from __future__ import annotations

import statistics
from typing import Any, Iterable

# Thin-fire classification — shared by the passive audit CLI (M7) and this
# prompt-time advisor (M2a). A match scoring <= the ceiling is a thin /
# coincidental signal; a skill matching >= MIN_SAMPLES times that is thin >=
# FP_THIN_RATE of the time AND has a median in the thin band is a false-positive
# candidate (its keyword/intent surface is too broad).
THIN_SCORE_CEILING: int = 2
MIN_SAMPLES: int = 3
FP_THIN_RATE: float = 0.8

# Bound per-prompt aggregation cost — this runs in the short-lived
# UserPromptSubmit hook. Only the most recent N skill-match events are considered
# (older history doesn't reflect the current keyword surface, and reading an
# unbounded log every prompt would regress). Fail-soft regardless.
MAX_EVENTS: int = 4000


def is_fp_candidate(count: int, thin_rate: float, median: float) -> bool:
    """The shared false-positive-candidate predicate (M7 definition). Pure."""
    return (count >= MIN_SAMPLES
            and thin_rate >= FP_THIN_RATE
            and median <= THIN_SCORE_CEILING)


def thin_fire_stats(events: Iterable[dict]) -> dict[str, dict[str, Any]]:
    """Per-skill {count, median, thin_rate} over skill-match `top` entries. Pure.

    Each skill-match telemetry event carries a `top` list of {name, score, ...}.
    Mirrors cli.skill_telemetry_audit's score aggregation but returns only what the
    candidate predicate needs (no dim weighting / rendering)."""
    scores: dict[str, list[int]] = {}
    for ev in events:
        for entry in (ev.get("top") if isinstance(ev, dict) else None) or []:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            score = entry.get("score")
            if isinstance(name, str) and isinstance(score, int) and not isinstance(score, bool):
                scores.setdefault(name, []).append(score)
    out: dict[str, dict[str, Any]] = {}
    for name, sc in scores.items():
        count = len(sc)
        thin = sum(1 for s in sc if s <= THIN_SCORE_CEILING)
        out[name] = {
            "count": count,
            "median": statistics.median(sc),
            "thin_rate": thin / count,
        }
    return out


def fp_candidate_names(events: Iterable[dict]) -> set[str]:
    """The set of skill names classified as historical thin-fire / FP candidates."""
    return {
        n for n, s in thin_fire_stats(events).items()
        if is_fp_candidate(s["count"], s["thin_rate"], s["median"])
    }


def injected_thin_advisory(
    injected_names: Iterable[str],
    events: Iterable[dict],
    *,
    max_events: int | None = MAX_EVENTS,
) -> str | None:
    """One advisory line iff a FULL-BODY-injected skill is a historical FP candidate.

    `injected_names`: skills selected for full-body injection THIS prompt (filenames,
        matching the telemetry `top[].name` form).
    `events`: historical skill-match telemetry (iterable of dicts).
    Returns None when nothing injected this prompt is a known thin-fire candidate.
    """
    names = [n for n in injected_names if isinstance(n, str) and n]
    if not names:
        return None
    ev_list = list(events)
    if max_events is not None and max_events >= 0 and len(ev_list) > max_events:
        ev_list = ev_list[-max_events:]
    fps = fp_candidate_names(ev_list)
    flagged = sorted(n for n in dict.fromkeys(names) if n in fps)
    if not flagged:
        return None
    shown = ", ".join(flagged)
    return (
        f"주의: 주입된 스킬 중 과거 약-신호(thin) 매칭이 잦은 false-positive 후보가 "
        f"있습니다 ({shown}). 이 가이드를 비판적으로 검토하고, 반복되면 키워드 표면을 "
        f"좁히세요 (python -m cli.skill_telemetry_audit 로 확인)."
    )
