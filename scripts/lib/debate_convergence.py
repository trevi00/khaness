"""debate_convergence — deterministic convergence + severity-invalidate decision (M24).

Pure logic for the harness-debate convergence rule (commands/harness-debate.md step 4),
which until now lived as PROSE the markdown orchestrator computed by hand:

  converged  ⇔  effective_verdict == "approved"
                AND (gen == 1 OR sha1(this ontology_snapshot.fields) == sha1(prev gen's))

  severity override (A1): if a `verdict_invalidated_by_severity` event exists for this gen,
  the architect's declared verdict is treated as "rejected" for the convergence check
  (regardless of its declared status) — the citation-integrity path may have been skipped.

Prose-computed loop control is skippable by an LLM and the SHA-1 was recomputed ad-hoc each
run; this module makes the computation deterministic + canonical. `cli.debate_converge_check`
is the consumer that owns the single `convergence` event append (mirrors M14's
lib.debate_stagnation / cli.debate_stagnation_check split). The convergence RULE is unchanged
— only its evaluation is made deterministic.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


# M10 (debate-1781937446-1281b5 D4): sentinel verdict written into the
# {gen: (verdict, fields)} map when two verdict events for the SAME gen disagree
# on verdict OR snapshot sha. It is NOT 'approved', so it rides the existing
# fail-closed seam in evaluate_convergence with no new status string. Idempotent
# byte-identical re-appends (same verdict AND same sha) do NOT trip it.
CONFLICT_SENTINEL = "__verdict_conflict__"


def snapshot_sha1(fields) -> str | None:
    """Canonical SHA-1 of an ontology_snapshot.fields value, or None if absent/empty.

    Canonical form: json.dumps(sort_keys=True, ensure_ascii=False, separators=(",", ":")).
    This is THE canonical serialization — the single computer of the convergence hash, so
    a LOCK reproduction must be byte-identical in the fields' *content* (key order and
    whitespace are normalized away here, but field shape/values must match). None for a
    missing/empty fields so gen-1 (no prior) and unparseable snapshots are handled explicitly.
    """
    if not fields:
        return None
    try:
        canon = json.dumps(fields, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return None
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ConvergenceResult:
    converged: bool
    status: str                 # 'converged' | 'conditional' | 'rejected'
    declared_verdict: str | None
    effective_verdict: str | None
    severity_invalidated: bool
    this_sha: str | None
    prev_sha: str | None
    gen: int
    reason: str
    error: str | None = None


def _verdicts_and_fields(events: list[dict]) -> dict[int, tuple[str | None, object]]:
    """{gen: (verdict, ontology_snapshot.fields)} from architect `verdict` events. Last wins."""
    out: dict[int, tuple[str | None, object]] = {}
    for ev in events:
        if not isinstance(ev, dict) or ev.get("type") != "verdict":
            continue
        gen = ev.get("gen")
        if not isinstance(gen, int):
            continue
        payload = ev.get("payload") or {}
        verdict = payload.get("verdict") if isinstance(payload.get("verdict"), str) else None
        snap = payload.get("ontology_snapshot") or {}
        fields = snap.get("fields") if isinstance(snap, dict) else None
        if gen not in out:
            out[gen] = (verdict, fields)
            continue
        # M10 D4: a second verdict event for this gen. The conflict MUST be caught
        # HERE, during the overwrite — duplicates collapse before any sha is
        # computed downstream, so evaluate_convergence cannot detect it later.
        existing_verdict, existing_fields = out[gen]
        if existing_verdict == CONFLICT_SENTINEL:
            continue  # already conflicted; a later event never un-conflicts it
        if existing_verdict == verdict and snapshot_sha1(existing_fields) == snapshot_sha1(fields):
            out[gen] = (verdict, fields)  # idempotent byte-identical re-append — tolerated
        else:
            out[gen] = (CONFLICT_SENTINEL, fields)  # disagree on verdict OR sha -> fail-closed marker
    return out


def _severity_invalidated_gens(events: list[dict]) -> set[int]:
    out: set[int] = set()
    for ev in events:
        if isinstance(ev, dict) and ev.get("type") == "verdict_invalidated_by_severity":
            g = ev.get("gen")
            if isinstance(g, int):
                out.add(g)
    return out


def evaluate_convergence(events: list[dict], gen: int) -> ConvergenceResult:
    """Decide convergence for `gen` from the session events. Pure, deterministic.

    Fail-CLOSED on a missing/None verdict for this gen (error set) — the caller must NOT
    treat that as convergence; it is a parse/sequencing fault to escalate.
    """
    vmap = _verdicts_and_fields(events)
    if gen not in vmap or vmap[gen][0] is None:
        return ConvergenceResult(
            converged=False, status="rejected", declared_verdict=None, effective_verdict=None,
            severity_invalidated=False, this_sha=None, prev_sha=None, gen=gen,
            reason="no architect verdict event for this gen -> parse_failure", error="verdict_missing",
        )
    declared, fields = vmap[gen]
    if declared == CONFLICT_SENTINEL:
        # M10 D4: same-gen verdict conflict — fail-CLOSED (never converge on an
        # ambiguous gen). Rides the same escalation path as a missing verdict.
        return ConvergenceResult(
            converged=False, status="rejected", declared_verdict=CONFLICT_SENTINEL,
            effective_verdict="rejected", severity_invalidated=False,
            this_sha=snapshot_sha1(fields), prev_sha=None, gen=gen,
            reason="same-gen verdict conflict (verdict or snapshot sha mismatch) -> fail_closed",
            error="verdict_ambiguous",
        )
    invalidated = gen in _severity_invalidated_gens(events)
    effective = "rejected" if invalidated else declared

    this_sha = snapshot_sha1(fields)
    prev = vmap.get(gen - 1)
    # M10 fail-close: a prior gen that ended in a same-gen verdict CONFLICT must
    # NOT supply a usable prev_sha — otherwise an approved current gen matching
    # the conflicted prev's last-written fields spuriously converges (deep-audit
    # rank 5: defense-in-depth seam against a careless same-gen double-verdict).
    if prev and prev[0] == CONFLICT_SENTINEL:
        prev_sha = None
    else:
        prev_sha = snapshot_sha1(prev[1]) if prev else None

    if effective == "approved":
        if gen == 1:
            converged, reason = True, "approved at gen 1 (no prior snapshot required)"
        elif prev_sha is not None and this_sha is not None and this_sha == prev_sha:
            converged, reason = True, "approved AND ontology snapshot sha1 byte-identical to prev gen"
        else:
            converged, reason = False, (
                "approved but snapshot sha1 != prev gen (LOCK not yet reproduced)"
                if prev_sha is not None else "approved but no prev-gen snapshot to match"
            )
    else:
        converged = False
        reason = (
            f"severity=invalidate forced rejection (declared={declared})"
            if invalidated else f"verdict={effective} -> continue to next gen"
        )

    status = "converged" if converged else (effective if effective in ("conditional", "rejected") else "rejected")
    return ConvergenceResult(
        converged=converged, status=status, declared_verdict=declared, effective_verdict=effective,
        severity_invalidated=invalidated, this_sha=this_sha, prev_sha=prev_sha, gen=gen, reason=reason,
    )
