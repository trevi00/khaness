"""advisory_research_dispatch — validator advisory HIGH findings as a 2nd research
dispatch source (research-subsystem debate-1781688992-250894, D2 + D4).

The N-strike loop (lib.strike_dispatcher) dispatches harness-researcher when a
RUNTIME error fingerprint recurs. This adds a SECOND lane: a validator advisory
HIGH finding (e.g. a falsy_zero HIGH `X or default` determinism bug) is worth a
root-cause investigation on its FIRST occurrence — a HIGH static-analysis finding
is already a confirmed defect, not a maybe-flake that needs a 2nd sighting.

Design (debate-converged, sha 9d281b9f):
  - D2: reuse lib.strike_dispatcher.should_dispatch with severity='HIGH' (effective
    threshold 1), NOT a shadow constant. Only HIGH dispatches; MED/LOW never.
  - D4: a CROSS-SESSION blocklist. harness-researcher closing an adv:<fp> as
    'no_research_available' persists the fingerprint so later sessions (fresh sid,
    empty per-sid quota) do not re-dispatch the same unfixable finding forever.
    Built on lib.quota_tracker.QuotaCounter(on_corrupt='empty') under the reserved
    sid '_global' — fail-soft: a lost blocklist entry costs at most ONE redundant
    re-dispatch, never recursion (the opposite asymmetry from strike_dispatcher,
    whose quota loss is a safety risk → fail-closed).

This module DECIDES (dispatch-worthy?) and RECORDS (gave-up blocklist); spawning the
harness-researcher subagent stays the orchestrator's job, exactly like
strike_dispatcher. No new mutate token, no edit to the LOCKED strike threshold.
"""
from __future__ import annotations

import hashlib
import re

from . import strike_dispatcher
from .quota_tracker import QuotaCounter

# Reserved sid: the blocklist is deliberately NOT per-session so a determinism bug
# closed as unfixable in one session is not re-investigated in the next.
_GLOBAL_SID = "_global"
_BLOCKLIST = QuotaCounter(subsystem="research_adv_blocklist", on_corrupt="empty",
                          value_mode="filter")

_NORM_WS = re.compile(r"\s+")


def advisory_fingerprint(validator_name: str, finding_key: str) -> str:
    """Stable cross-session fingerprint for an advisory finding: 'adv:' + 12 hex of
    sha1(validator ':' normalized_key). Deterministic so the SAME finding maps to the
    SAME fingerprint across sessions (that is what makes the blocklist meaningful)."""
    key = _NORM_WS.sub(" ", f"{validator_name}:{finding_key}".strip().lower())
    return "adv:" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def is_blocklisted(fingerprint: str) -> bool:
    """True iff this advisory fingerprint was already researched and closed as
    no_research_available in some prior session (cross-session, sid='_global')."""
    return _BLOCKLIST.get(_GLOBAL_SID, fingerprint) > 0


def blocklist_close(fingerprint: str) -> int:
    """Record that harness-researcher gave up on this advisory fingerprint, so future
    sessions skip it. Returns the new (cross-session) count. Called by the consumer
    when the researcher artifact verdict is 'no_research_available'."""
    return _BLOCKLIST.record(_GLOBAL_SID, fingerprint)


def should_dispatch_advisory(validator_name: str, finding_key: str, sid: str, *,
                             severity: str) -> tuple[bool, str]:
    """Decide whether an advisory finding warrants a harness-researcher dispatch.
    Returns (should_dispatch, fingerprint).

    Gates, in order:
      1. severity must be 'HIGH' (MED/LOW never dispatch — D2 HIGH-only).
      2. not cross-session blocklisted (D4 — gave up before).
      3. lib.strike_dispatcher.should_dispatch(..., severity='HIGH') — first
         occurrence clears the effective threshold (1) and the per-(sid,fingerprint)
         quota still bounds in-session recursion exactly as for N-strike.
    """
    fp = advisory_fingerprint(validator_name, finding_key)
    if severity != "HIGH":
        return False, fp
    if is_blocklisted(fp):
        return False, fp
    ok = strike_dispatcher.should_dispatch(fp, sid, strike_count=1, severity="HIGH")
    return ok, fp


def record_advisory_dispatch(fingerprint: str, sid: str) -> int:
    """Increment the per-(sid,fingerprint) quota after a dispatch — reuses the
    strike_dispatcher counter so the PER_FINGERPRINT_DISPATCH_LIMIT recursion bound
    applies to advisory dispatches identically."""
    return strike_dispatcher.record_dispatch(fingerprint, sid)
