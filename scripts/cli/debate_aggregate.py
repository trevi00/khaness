#!/usr/bin/env python3
"""debate_aggregate — cross-session aggregator for debate events.jsonl.

Wave 11 S3 (자가개선 silo S3 closure per A1-A6 분석, interview-1779253986-8554c71f
seed.md). 9+ debate sessions accumulating in state/debates/<sid>/events.jsonl —
prior to this CLI, each session was isolated (resume replay only). This script
provides the missing reader surface: aggregate all debate decisions into a
queryable table so future debates can check "have we debated this topic before?"

## Schema extracted per session

For each `state/debates/<sid>/events.jsonl`:
  - sid              — directory name
  - topic            — first proposal's `topic_restatement` (truncated to 200 chars)
  - gen_count        — max `gen` field across all events
  - terminal_verdict — last verdict event's `verdict` field ('approved'/'rejected'/'conditional')
  - accepted_decisions — last verdict event's `accepted_decisions` list (may be empty)
  - snapshot_hash    — last verdict event's `ontology_sha1` (12-char prefix for display)
  - early_hard_cap   — True if last event includes `early_hard_cap_recommendation`

Sessions without verdict events are still returned (gen_count + topic only); they
represent in-progress or aborted debates.

## Filters

  --topic <substring>  — case-insensitive substring match on topic_restatement
  --verdict <value>    — filter to sessions with terminal_verdict == value
  --since <ISO date>   — sessions whose first event ts >= date (YYYY-MM-DD)
  --format {table,json} — table (default, human-readable) or json (machine-readable)

## Usage

  python -m cli.debate_aggregate                          # all sessions, table
  python -m cli.debate_aggregate --topic RLM_gate         # filter by topic
  python -m cli.debate_aggregate --verdict approved       # only approved
  python -m cli.debate_aggregate --format json            # machine output

## Read-only contract

Does NOT mutate state. Safe to run anytime. Empty state/debates/ → graceful
empty output (exit 0). Malformed events.jsonl → skipped silently (per-line
JSONDecodeError tolerant) + session-level OSError captured in stderr.

## Cross-references

  - lib.event_store.EventStore — append-side authority on events.jsonl
  - HANDOFF wave 11 S3 (interview-1779253986-8554c71f seed)
  - A4 data flow report: dead-end surface closure (writer existed, reader 0)
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.paths import STATE_DIR  # noqa: E402
from lib.criticism_dedup import (  # noqa: E402  (M30)
    DEFAULT_DEDUP_THRESHOLD,
    SEVERITY_SCALE,
    analyze_blockers,
    blocker_severity,
    blocker_target,
    blocker_text,
    canonical_severity,
)
from lib.research_provenance import analyze_citations  # noqa: E402  (M31)


MAX_TOPIC_DISPLAY: int = 200
"""Topic truncation for table output. JSON output preserves full string."""

SNAPSHOT_HASH_DISPLAY: int = 12
"""Snapshot SHA1 prefix length for table display."""


@dataclass(frozen=True)
class DebateSummary:
    """One debate session's aggregated metadata."""
    sid: str
    topic: str
    gen_count: int
    terminal_verdict: str | None
    accepted_decisions: tuple[str, ...]
    snapshot_hash: str | None
    first_ts: str | None
    early_hard_cap: bool
    blocker_axes: tuple[str, ...] = ()  # M8: Critic blocker axes across this session's critiques
    blockers: tuple[dict, ...] = ()  # M30: full Critic blocker dicts (text+severity+target) for dedup/calibration
    proposal_citations: tuple[tuple, ...] = ()  # M31: research_citations per proposal event (provenance)

    @property
    def stalled(self) -> bool:
        """M8: did this debate FAIL to cleanly converge? (Critic blockers won)."""
        return self.early_hard_cap or self.terminal_verdict != "approved"

    def to_dict(self) -> dict[str, Any]:
        return {
            "sid": self.sid,
            "topic": self.topic,
            "gen_count": self.gen_count,
            "terminal_verdict": self.terminal_verdict,
            "accepted_decisions": list(self.accepted_decisions),
            "snapshot_hash": self.snapshot_hash,
            "first_ts": self.first_ts,
            "early_hard_cap": self.early_hard_cap,
            "blocker_axes": list(self.blocker_axes),
            "blockers": [dict(b) for b in self.blockers],
            "proposal_citations": [list(pc) for pc in self.proposal_citations],
        }


def _read_events(path: Path) -> list[dict]:
    """Read events.jsonl. Returns [] on OSError; skips malformed lines."""
    events: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return events


def _summarize_session(sid: str, events: list[dict]) -> DebateSummary:
    """Build DebateSummary from one session's events list."""
    topic = ""
    first_ts: str | None = None
    gen_count = 0
    terminal_verdict: str | None = None
    accepted: tuple[str, ...] = ()
    snapshot_hash: str | None = None
    early_hard_cap = False
    blocker_axes: list[str] = []  # M8: every Critic blocker axis seen this session
    blocker_dicts: list[dict] = []  # M30: every Critic blocker dict seen this session
    proposal_cits: list[tuple] = []  # M31: research_citations per proposal event

    for ev in events:
        if not isinstance(ev, dict):
            continue
        if first_ts is None and isinstance(ev.get("ts"), str):
            first_ts = ev["ts"]
        gen = ev.get("gen")
        if isinstance(gen, int) and gen > gen_count:
            gen_count = gen

        ev_type = ev.get("type")
        payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}

        if ev_type == "proposal":
            if not topic:
                # The orchestrator persists the debate topic on the proposal event as `topic`
                # (M1, 2026-06-16); `topic_restatement` is the older planner-emitted field that
                # the agent does not in practice populate. Prefer whichever is present.
                tr = payload.get("topic_restatement") or payload.get("topic")
                if isinstance(tr, str):
                    topic = tr
            # M31: one provenance record per proposal event (empty tuple = no citations).
            rc = payload.get("research_citations")
            proposal_cits.append(tuple(rc) if isinstance(rc, list) else ())

        if ev_type == "verdict":
            verdict_val = payload.get("verdict")
            if isinstance(verdict_val, str):
                terminal_verdict = verdict_val
            ad_raw = payload.get("accepted_decisions")
            if isinstance(ad_raw, list):
                decisions: list[str] = []
                for d in ad_raw:
                    if isinstance(d, str):
                        decisions.append(d)
                    elif isinstance(d, dict):
                        did = d.get("id") or d.get("decision_id") or d.get("name")
                        if isinstance(did, str):
                            decisions.append(did)
                accepted = tuple(decisions)
            sha = payload.get("ontology_sha1")
            if isinstance(sha, str):
                snapshot_hash = sha
            if payload.get("early_hard_cap_recommendation"):
                early_hard_cap = True

        # M14 (D3): the deterministic cli.debate_stagnation_check writes the
        # early-hard-cap signal as its own events (EventStore is append-only, so the
        # verdict event above can never be patched to carry it). Read it from where the
        # check actually writes: the terminal convergence{status:early_hard_cap} event
        # and/or the forensic early_hard_cap_recommendation{recommend:true} event.
        if ev_type == "convergence" and payload.get("status") == "early_hard_cap":
            early_hard_cap = True
        if ev_type == "early_hard_cap_recommendation" and payload.get("recommend") is True:
            early_hard_cap = True

        # M8: extract Critic blocker axes. The list-of-dicts schema carries `axis`
        # (assumption/failure/simplification) — the only signature stable across
        # heterogeneous sessions (the int-count schema and target ids are not).
        if ev_type == "critique":
            blockers = payload.get("blockers")
            if isinstance(blockers, list):
                for b in blockers:
                    if isinstance(b, dict):
                        blocker_dicts.append(b)  # M30: full dict for dedup/calibration
                        axis = b.get("axis")
                        if isinstance(axis, str) and axis:
                            blocker_axes.append(axis.strip().lower())

    return DebateSummary(
        sid=sid,
        topic=topic,
        gen_count=gen_count,
        terminal_verdict=terminal_verdict,
        accepted_decisions=accepted,
        snapshot_hash=snapshot_hash,
        first_ts=first_ts,
        early_hard_cap=early_hard_cap,
        blocker_axes=tuple(blocker_axes),
        blockers=tuple(blocker_dicts),
        proposal_citations=tuple(proposal_cits),
    )


def aggregate(
    debates_dir: Path,
    *,
    topic_filter: str | None = None,
    verdict_filter: str | None = None,
    since: str | None = None,
) -> list[DebateSummary]:
    """Walk debates_dir/*/events.jsonl, return filtered summary list.

    Filters apply post-extraction (not during read) — simpler + filters can
    cross-reference each other (e.g., topic AND verdict).
    """
    if not debates_dir.is_dir():
        return []

    results: list[DebateSummary] = []
    for entry in sorted(debates_dir.iterdir()):
        if not entry.is_dir():
            continue
        events_path = entry / "events.jsonl"
        if not events_path.exists():
            continue
        events = _read_events(events_path)
        if not events:
            continue
        summary = _summarize_session(entry.name, events)
        results.append(summary)

    if topic_filter:
        tf = topic_filter.lower()
        results = [r for r in results if tf in r.topic.lower()]
    if verdict_filter:
        results = [r for r in results if r.terminal_verdict == verdict_filter]
    if since:
        results = [
            r for r in results
            if r.first_ts and r.first_ts >= since
        ]

    return results


def _format_table(summaries: list[DebateSummary]) -> str:
    """Human-readable table format. Empty list → '(no sessions)' single line."""
    if not summaries:
        return "(no sessions)\n"

    lines: list[str] = []
    lines.append(f"=== debate aggregate ({len(summaries)} sessions) ===")
    lines.append("")
    lines.append(
        f"{'sid':<40} {'gen':>3} {'verdict':<12} {'snapshot':<14} "
        f"{'cap':<4} topic"
    )
    lines.append("-" * 120)
    for s in summaries:
        topic_disp = s.topic[:MAX_TOPIC_DISPLAY]
        if len(s.topic) > MAX_TOPIC_DISPLAY:
            topic_disp += "..."
        snap_disp = (s.snapshot_hash or "")[:SNAPSHOT_HASH_DISPLAY]
        verdict_disp = s.terminal_verdict or "(none)"
        cap_disp = "YES" if s.early_hard_cap else ""
        lines.append(
            f"{s.sid:<40} {s.gen_count:>3} {verdict_disp:<12} "
            f"{snap_disp:<14} {cap_disp:<4} {topic_disp}"
        )
    lines.append("")
    lines.append(
        f"verdict distribution: "
        + ", ".join(
            f"{v}={sum(1 for s in summaries if s.terminal_verdict == v)}"
            for v in ("approved", "rejected", "conditional", "(none)")
            if any(
                (s.terminal_verdict or "(none)") == v for s in summaries
            )
        )
    )
    return "\n".join(lines) + "\n"


def _format_json(summaries: list[DebateSummary]) -> str:
    return json.dumps(
        [s.to_dict() for s in summaries],
        indent=2, ensure_ascii=False,
    ) + "\n"


PLANNER_CONTEXT_MAX = 8  # cap injected prior debates so the Planner prompt stays bounded
_CONTEXT_TOPIC_DISPLAY = 160


def render_planner_context(
    summaries: list[DebateSummary], *, max_items: int = PLANNER_CONTEXT_MAX
) -> str:
    """Render a `<prior_debates>` advisory block for injection into the Planner prompt.

    Surfaces what prior debates on a similar topic REJECTED or STALLED at (avoid
    re-proposing as-is) and what they ACCEPTED (may build on) — the AutoScientists
    "preserve + resurface success/failure" discipline that reduces redundant
    exploration. This is the deterministic READER that closes the dead-end
    ``aggregate()`` surface (M1: spend the collected debate signal).

    Returns "" when there is nothing to inject, so callers can include the result
    unconditionally. ADVISORY ONLY: context for the Planner to weigh, never an
    auto-veto — the Planner still decides.
    """
    if not summaries:
        return ""

    # Most recent first; cap to keep the prompt bounded.
    ordered = sorted(summaries, key=lambda s: s.first_ts or "", reverse=True)[:max_items]

    rejected: list[DebateSummary] = []
    accepted: list[DebateSummary] = []
    for s in ordered:
        if s.terminal_verdict == "approved" and not s.early_hard_cap:
            accepted.append(s)
        else:
            # rejected / conditional / early_hard_cap / unresolved -> a stalled direction
            rejected.append(s)

    def _topic(s: DebateSummary) -> str:
        t = s.topic[:_CONTEXT_TOPIC_DISPLAY]
        return t + "..." if len(s.topic) > _CONTEXT_TOPIC_DISPLAY else t

    lines: list[str] = ["<prior_debates>"]
    lines.append(
        "Advisory only — outcomes of prior debates on a similar topic. Do NOT "
        "re-propose a REJECTED or STALLED direction without addressing why it failed; "
        "you MAY build on an ACCEPTED decision. Context to weigh, not a veto."
    )
    if rejected:
        lines.append("REJECTED / STALLED (do not re-propose as-is):")
        for s in rejected:
            tag = "early_hard_cap" if s.early_hard_cap else (s.terminal_verdict or "unresolved")
            lines.append(f"  - [{tag}] {_topic(s)}")
    if accepted:
        lines.append("ACCEPTED (you may build on these):")
        for s in accepted:
            decs = (
                "; ".join(s.accepted_decisions[:4])
                if s.accepted_decisions
                else "(no explicit decisions recorded)"
            )
            lines.append(f"  - {_topic(s)} -> {decs}")
    lines.append("</prior_debates>")
    return "\n".join(lines) + "\n"


# M8: concrete pre-emption tip per Critic axis (the 3 harness-critic axes).
_AXIS_PREEMPT: dict[str, str] = {
    "assumption": "state preconditions + cite evidence for any load-bearing claim "
                  "(unstated/false premises are the most common kill)",
    "failure": "enumerate failure modes + show how each is handled (where does it break at runtime?)",
    "simplification": "justify necessity of each part + flag any collapsed/unhandled case",
}
BLOCKER_ADVISORY_MIN_SESSIONS = 3  # need >=3 debates carrying axis data before a pattern is worth surfacing


def render_blocker_advisory(summaries: list[DebateSummary]) -> str:
    """Render a `<recurring_blockers>` advisory from cross-session Critic blocker axes.

    M8 (🧵 signal-spend, sibling of M14): the per-session blocker_plateau detector
    (lib.debate_stagnation) terminates a SINGLE debate; this is the cross-session
    aggregation that debate_stagnation explicitly defers ("separate cycle"). It spends
    the collected critique-blocker signal as an advisory: which Critic AXIS most
    reliably blocks proposals (the recurring friction the Planner keeps drawing), so a
    new debate's Planner can pre-empt it and converge faster. Debates that STALLED (did
    not cleanly converge) are highlighted separately — there the axis actually won.

    Uses ALL debates carrying axis data, not just stalls: in a healthy harness most
    debates converge, so a stall-only filter starves the signal — but the Critic still
    raised (and the Planner still had to resolve) the same axes along the way.

    Returns "" when fewer than BLOCKER_ADVISORY_MIN_SESSIONS debates carry axis data.
    ADVISORY ONLY — never a veto.
    """
    eligible = [s for s in summaries if s.blocker_axes]
    if len(eligible) < BLOCKER_ADVISORY_MIN_SESSIONS:
        return ""

    axis_counts: dict[str, int] = {}
    sessions_with_axis: dict[str, int] = {}
    for s in eligible:
        seen_here: set[str] = set()
        for axis in s.blocker_axes:
            axis_counts[axis] = axis_counts.get(axis, 0) + 1
            seen_here.add(axis)
        for axis in seen_here:
            sessions_with_axis[axis] = sessions_with_axis.get(axis, 0) + 1

    if not axis_counts:
        return ""

    total_blockers = sum(axis_counts.values())
    ranked = sorted(axis_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    dominant_axis = ranked[0][0]
    stalled = [s for s in eligible if s.stalled]

    lines: list[str] = ["<recurring_blockers>"]
    lines.append(
        f"Advisory only — across {len(eligible)} prior debates, the Critic blockers "
        f"broke down by axis as below. Pre-empt the dominant axis in your proposal so "
        f"it does not block this debate. Context to weigh, not a veto."
    )
    for axis, count in ranked:
        pct = round(100.0 * count / total_blockers)
        in_sessions = sessions_with_axis.get(axis, 0)
        lines.append(f"  - {axis}: {count} blockers ({pct}%) across {in_sessions} debate(s)")
    tip = _AXIS_PREEMPT.get(dominant_axis)
    if tip:
        lines.append(f"DOMINANT = {dominant_axis} -> {tip}")
    if stalled:
        # Axes that actually WON (debate did not cleanly converge) — highest signal.
        stalled_axes: dict[str, int] = {}
        for s in stalled:
            for axis in set(s.blocker_axes):
                stalled_axes[axis] = stalled_axes.get(axis, 0) + 1
        worst = sorted(stalled_axes.items(), key=lambda kv: (-kv[1], kv[0]))
        worst_str = ", ".join(f"{a}({c})" for a, c in worst)
        lines.append(
            f"Of these, {len(stalled)} STALLED (did not converge); axes that won: {worst_str}."
        )
    lines.append("</recurring_blockers>")
    return "\n".join(lines) + "\n"


# ============================================================================
# M30: severity calibration + criticism-diversity MEASUREMENT (converged design
# debate-1781617065-m30a01 gen-3, LOCK sha1 f28a57e4962b1ba0). Built on the pure
# lib.criticism_dedup primitive. ADVISORY ONLY — read-only, appends NO events,
# never gates. The convergence rule + ontology SHA computation are untouched (these
# blocks are prompt context only). The DEDUP ACTION (collapsing redundant criticisms)
# is deliberately DEFERRED to a docstring cross-ref in lib.criticism_dedup ->
# lib.ensemble_evaluator: measured single-critic content overlap is 0.0%, so dedup
# only bites at the multi-juror seam, which has no live caller yet.
# ============================================================================

CRITICISM_DIVERSITY_MIN_SESSIONS = 3   # need >=3 blocker-bearing sessions before reporting
UNSPEC_UNCALIBRATED_THRESHOLD = 0.20   # D3: windowed unspec_rate >= this -> vocabulary-fix advisory
DIVERSITY_WINDOW_DEFAULT = 20          # D3: trailing N blocker-bearing sessions (NOT all-time)
_CALIB_SNIPPET = 90


def _pool_blockers(summaries: list[DebateSummary]) -> list[dict]:
    out: list[dict] = []
    for s in summaries:
        out.extend(s.blockers)
    return out


def _trailing_blocker_sessions(
    summaries: list[DebateSummary], *, window: int
) -> list[DebateSummary]:
    """The most-recent `window` blocker-bearing sessions by first_ts (D3 windowed
    denominator). Trailing — NOT all-time — so improving severity vocabulary in new
    debates can dilute the UNSPEC rate below threshold and turn the advisory OFF
    (gen-2 Critic's slow-dead-guard fix)."""
    bearing = [s for s in summaries if s.blockers]
    bearing.sort(key=lambda s: s.first_ts or "", reverse=True)
    return bearing[: max(1, window)]


def render_severity_calibration(summaries: list[DebateSummary]) -> str:
    """Render a `<severity_calibration>` calibrated-severity TABLE (M30 D1a/D2).

    Per-debate when the caller filters to one session (the Architect-prompt injection),
    cross-session otherwise. TRIAGE-NEUTRAL: shows ONLY blockers whose canonical severity
    changes triage — the UNSPEC cohort (no recognizable label → can't triage) OR a raw
    label that is not literally the canonical bucket (normalization did real work, e.g.
    raw='blocker' → HIGH). Rows where raw already == canonical are SUPPRESSED (no triage
    change, pure noise). Returns "" when no row changes triage (empty-on-silent, so callers
    can include it unconditionally). NEVER asserts the critic over-flags — calibration
    context only, the Architect judges.
    """
    blockers = _pool_blockers(summaries)
    if not blockers:
        return ""

    rows: list[tuple[str, str, str, str]] = []
    for b in blockers:
        raw = b.get("severity")
        if raw is None:
            raw = b.get("sev")
        canon = blocker_severity(b)
        raw_str = (raw.strip() if isinstance(raw, str) and raw.strip() else "") or "<missing>"
        # Triage changes iff UNSPEC (untriageable) OR the raw token != the canonical bucket.
        if canon == "UNSPEC" or raw_str.upper() != canon:
            txt = blocker_text(b)
            snippet = txt[:_CALIB_SNIPPET] + ("..." if len(txt) > _CALIB_SNIPPET else "")
            rows.append((blocker_target(b) or "?", raw_str, canon, snippet))
    if not rows:
        return ""

    rep = analyze_blockers(blockers)
    dist = ", ".join(
        f"{k}={rep.severity_distribution[k]}" for k in SEVERITY_SCALE
        if rep.severity_distribution[k]
    )
    lines = ["<severity_calibration>"]
    lines.append(
        "Advisory only — canonical severity for blockers whose raw label needs "
        "normalization or cannot be triaged. Weigh each blocker on its own merits; "
        "this is calibration context, not a verdict and not a claim the critic over-flags."
    )
    for tgt, raw_str, canon, snippet in rows:
        lines.append(f"  - [{tgt}] raw={raw_str!r} -> {canon}: {snippet}")
    lines.append(f"distribution: {dist} (total={rep.total_blockers})")
    lines.append("</severity_calibration>")
    return "\n".join(lines) + "\n"


def render_criticism_diversity(
    summaries: list[DebateSummary],
    *,
    window: int = DIVERSITY_WINDOW_DEFAULT,
    threshold: float = DEFAULT_DEDUP_THRESHOLD,
) -> str:
    """Render a `<criticism_diversity>` cross-session MEASUREMENT block (M30 D1b/D3).

    The diversity-half deliverable: overlap_rate (our analog to the AI-Reviewers ~21%
    inter-juror overlap — measured 0% for us, i.e. criticisms rarely repeat) + severity
    distribution + descriptive HIGH-rate. The one LIVE advisory predicate
    UNSPEC_UNCALIBRATED fires when the WINDOWED unspec_rate >= UNSPEC_UNCALIBRATED_THRESHOLD
    — a fifth+ of blockers carrying no recognizable severity means the critic vocabulary is
    fragmented and should emit a canonical HIGH/MED/LOW. Measured over a TRAILING window of
    the most-recent N blocker-bearing sessions (NOT all-time), so vocabulary improvement can
    turn the advisory OFF. No gating inflation verdict ships — both the per-debate and
    cross-session recurrence forms were proven dead guards (HIGH-overlap 0.0% @ Jaccard 0.3).
    Returns "" below CRITICISM_DIVERSITY_MIN_SESSIONS blocker-bearing sessions.
    """
    windowed = _trailing_blocker_sessions(summaries, window=window)
    if len(windowed) < CRITICISM_DIVERSITY_MIN_SESSIONS:
        return ""
    blockers = _pool_blockers(windowed)
    rep = analyze_blockers(blockers, threshold=threshold)
    if rep.total_blockers == 0:
        return ""

    high = rep.severity_distribution.get("HIGH", 0)
    high_rate = high / rep.total_blockers
    overlap_note = ("diverse — criticisms rarely repeat (healthy)"
                    if rep.overlap_rate < 0.10 else "some repeated criticisms across debates")
    dist = ", ".join(
        f"{k}={rep.severity_distribution[k]}" for k in SEVERITY_SCALE
        if rep.severity_distribution[k]
    )

    lines = ["<criticism_diversity>"]
    lines.append(
        f"Advisory only — criticism diversity + severity health across the "
        f"{len(windowed)} most-recent blocker-bearing debates ({rep.total_blockers} "
        f"blockers). Measurement context to weigh, not a verdict."
    )
    lines.append(f"  - overlap_rate: {round(rep.overlap_rate * 100)}% ({overlap_note})")
    lines.append(f"  - severity: {dist}; HIGH-rate {round(high_rate * 100)}%")
    if rep.unspec_severity_rate >= UNSPEC_UNCALIBRATED_THRESHOLD:
        lines.append(
            f"  - UNSPEC_UNCALIBRATED: {round(rep.unspec_severity_rate * 100)}% of blockers "
            f"carry no recognizable severity (>= {round(UNSPEC_UNCALIBRATED_THRESHOLD * 100)}%) "
            f"— critic severity vocabulary is fragmented; emit a canonical HIGH/MED/LOW per blocker."
        )
    lines.append("</criticism_diversity>")
    return "\n".join(lines) + "\n"


# ============================================================================
# M31: research-provenance (discover-vs-confirm / IKD proxy) MEASUREMENT.
# Built on lib.research_provenance. ADVISORY ONLY — read-only, no events, no gate.
# Honest scope: the named target (harness-researcher ## Sources) is DORMANT (0
# artifacts), so this spends the LIVE provenance signal — the debate Planner's
# research_citations[]. A PROXY for IKD (where the agent SAID its grounding came
# from), NOT a closed-book baseline (which would re-run the agent tool-free).
# ============================================================================

RESEARCH_PROVENANCE_MIN_PROPOSALS = 8  # need >=8 proposals before reporting


def render_research_provenance(summaries: list[DebateSummary]) -> str:
    """Render a `<research_provenance>` cross-session discover-vs-confirm block (M31).

    Per-proposal provenance verdict (lib.research_provenance.analyze_citations):
    'discovered' (>=1 external source), 'no_citations' (internal-only), 'confirm_only'
    (cited but 0 external). HONEST framing: 'no_citations' is EXPECTED for internal
    harness-design debates and is NOT flagged — the one narrow live flag is CONFIRM_ONLY
    (the agent went through the motions of citing yet discovered nothing external), which
    never defames a legitimately-internal debate. Returns "" below
    RESEARCH_PROVENANCE_MIN_PROPOSALS.
    """
    pairs: list[tuple[str, tuple]] = []
    for s in summaries:
        for pc in s.proposal_citations:
            pairs.append((s.sid, pc))
    total = len(pairs)
    if total < RESEARCH_PROVENANCE_MIN_PROPOSALS:
        return ""

    grounded = internal_only = 0
    confirm_sids: list[str] = []
    ext_total = cit_total = 0
    for sid, pc in pairs:
        rep = analyze_citations(list(pc))
        cit_total += rep.total
        ext_total += rep.external
        if rep.verdict == "discovered":
            grounded += 1
        elif rep.verdict == "confirm_only":
            confirm_sids.append(sid)
        else:
            internal_only += 1

    lines = ["<research_provenance>"]
    lines.append(
        f"Advisory only — discover-vs-confirm provenance (IKD proxy) across {total} "
        f"proposals in {len(summaries)} debates. Internal-design debates legitimately "
        f"cite nothing, so 'internal_only' is NOT a flag; only 'confirm_only' (cited "
        f"sources but 0 external) is. Measurement context, not a verdict."
    )
    lines.append(f"  - citation_grounded: {grounded} ({round(100 * grounded / total)}%) "
                 f">= 1 external source (discovery evidence)")
    lines.append(f"  - internal_only: {internal_only} ({round(100 * internal_only / total)}%) "
                 f"no citations (expected for internal harness design)")
    if confirm_sids:
        uniq = sorted(set(confirm_sids))
        shown = ", ".join(uniq[:6]) + (" ..." if len(uniq) > 6 else "")
        lines.append(f"  - CONFIRM_ONLY: {len(confirm_sids)} proposal(s) cited sources but 0 "
                     f"external (confirm-not-discover) — sessions: {shown}")
    if cit_total:
        lines.append(f"  - external citation ratio: {round(100 * ext_total / cit_total)}% "
                     f"({ext_total}/{cit_total})")
    lines.append("</research_provenance>")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.debate_aggregate",
        description="Aggregate debate sessions across state/debates/*/events.jsonl",
    )
    parser.add_argument(
        "--topic", default=None,
        help="case-insensitive substring filter on topic_restatement",
    )
    parser.add_argument(
        "--verdict", default=None,
        choices=["approved", "rejected", "conditional"],
        help="filter to sessions with this terminal verdict",
    )
    parser.add_argument(
        "--since", default=None,
        help="ISO date (YYYY-MM-DD) — sessions whose first event ts >= date",
    )
    parser.add_argument(
        "--format", default="table",
        choices=["table", "json", "planner-context", "blocker-advisory",
                 "severity-calibration", "criticism-diversity", "research-provenance"],
        help="output format (default: table). planner-context renders a "
             "<prior_debates> advisory block; blocker-advisory (M8) renders a "
             "<recurring_blockers> cross-session Critic-axis advisory; "
             "severity-calibration (M30) renders a <severity_calibration> "
             "calibrated-severity table (use --session-id for the per-debate Architect "
             "injection); criticism-diversity (M30) renders a <criticism_diversity> "
             "cross-session overlap + severity-health measurement.",
    )
    parser.add_argument(
        "--session-id", default=None,
        help="exact session dir name filter (M30: scope severity-calibration to one debate)",
    )
    parser.add_argument(
        "--window", type=int, default=DIVERSITY_WINDOW_DEFAULT,
        help=f"trailing blocker-bearing-session window for criticism-diversity "
             f"(M30 D3; default {DIVERSITY_WINDOW_DEFAULT})",
    )
    parser.add_argument(
        "--debates-dir", default=None,
        help="override debates dir (default: STATE_DIR/debates)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    # Force utf-8 stdout: the M8/M30/severity renderers emit em-dashes (U+2014)
    # that raise UnicodeEncodeError on a cp949 Windows console. Guarded for pytest
    # capture objects lacking .reconfigure (hook-discipline pattern).
    _reconf = getattr(sys.stdout, "reconfigure", None)
    if callable(_reconf):
        try:
            _reconf(encoding="utf-8")
        except (ValueError, OSError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)

    debates_dir = (
        Path(args.debates_dir) if args.debates_dir
        else STATE_DIR / "debates"
    )

    summaries = aggregate(
        debates_dir,
        topic_filter=args.topic,
        verdict_filter=args.verdict,
        since=args.since,
    )

    # M30: exact session-id filter (scopes severity-calibration to one debate).
    if args.session_id:
        summaries = [s for s in summaries if s.sid == args.session_id]

    if args.format == "json":
        sys.stdout.write(_format_json(summaries))
    elif args.format == "planner-context":
        sys.stdout.write(render_planner_context(summaries))
    elif args.format == "blocker-advisory":
        sys.stdout.write(render_blocker_advisory(summaries))
    elif args.format == "severity-calibration":
        sys.stdout.write(render_severity_calibration(summaries))
    elif args.format == "criticism-diversity":
        sys.stdout.write(render_criticism_diversity(summaries, window=args.window))
    elif args.format == "research-provenance":
        sys.stdout.write(render_research_provenance(summaries))
    else:
        sys.stdout.write(_format_table(summaries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
