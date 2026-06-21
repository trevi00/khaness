"""N-strike research dispatcher (Phase 2 of autonomous orchestrator MVP).

Per debate-1778161608-713bdc gen 4 (snapshot 7add26467f703f7b119c1903ff0dcfca5b227a65):

Locked decisions wired here:
  - F2 strike_dispatch_threshold = 2 (warning emit and researcher dispatch
    coincide at strike #2 — locked invariant STRIKE_THRESHOLD=2 reused
    via direct import from lib.repeat_error_tracker; no shadow constant)
  - F6 resume_idempotency_storage = events_jsonl_replay_plus_atomic_counter_sidecar
    (this module owns the sidecar at state/orchestrator/<sid>/dispatch_counter.json)
  - F7 n_strike_recursion_safeguard = atomic_counter_plus_timeout
    (counter scoped per (sid, fingerprint); timeout owned by researcher_runner)

Implementation conditions (Architect gen 3):
  - B5 cold-start: FileNotFoundError -> counter starts at {}, JSONDecodeError ->
    fail-closed (raise; never silent zero). Distinct branches.
  - F2 = STRIKE_THRESHOLD invariant alignment: dispatch fires at the same
    strike that emits the warning (no deadlock window).

Public API:
  should_dispatch(fingerprint, sid, *, strike_count, severity='strike') -> bool
  record_dispatch(fingerprint, sid)         -> int (new count)
  load_counter(sid)                          -> dict[str, int]
  reset_counter(sid)                         -> None  (test/admin only)

The dispatcher itself does NOT spawn the researcher subagent — that is
the orchestrator/autopilot caller's job (uses Agent tool with
subagent_type='harness-researcher'). This module decides only WHEN.
"""
from __future__ import annotations

from pathlib import Path

from lib.quota_tracker import QuotaCounter
from lib.repeat_error_tracker import STRIKE_THRESHOLD

# STATE_DIR resolved lazily inside the shared QuotaCounter so test fixtures that
# redirect `lib.paths.STATE_DIR` after import take effect.


# F2 = 2: dispatch coincides with warning emission. Single source of truth via
# lib.repeat_error_tracker.STRIKE_THRESHOLD; no shadow constant per Critic B4.
RESEARCH_DISPATCH_THRESHOLD: int = STRIKE_THRESHOLD

# Per-(sid, fingerprint) quota. 4th invocation for the same fingerprint within
# a sid is blocked (debate D6_revised). New fingerprints in the same sid
# unaffected.
PER_FINGERPRINT_DISPATCH_LIMIT: int = 3

# Shared per-(sid, key) sidecar counter (M10). Fail-CLOSED on corruption: this
# quota bounds N-strike researcher recursion (F7), so a silently-zeroed counter
# would re-enable infinite recursion — never empty-on-corrupt. `coerce` preserves
# the legacy `int(v)` value handling. Subsystem dir + filename unchanged
# (state/orchestrator/<sid>/dispatch_counter.json), so on-disk state is compatible.
_TRACKER = QuotaCounter(
    "orchestrator", on_corrupt="raise", value_mode="coerce", label="strike_dispatcher",
)


def _counter_path(sid: str) -> Path:
    return _TRACKER.path(sid)


def load_counter(sid: str) -> dict[str, int]:
    """Load per-fingerprint counter for a session.

    B5 cold-start branches (delegated to QuotaCounter, on_corrupt='raise'):
      - missing/empty file -> {} (bootstrap, allow dispatch)
      - JSONDecodeError / non-object -> RuntimeError (fail-closed; never silent
        zero because zeroing would re-enable infinite recursion which F7 prevents)
    """
    return _TRACKER.load(sid)


def should_dispatch(fingerprint: str, sid: str, *, strike_count: int,
                    severity: str = "strike") -> bool:
    """Return True iff researcher dispatch is warranted.

    Two gates:
      1. strike_count >= effective threshold
      2. per-fingerprint dispatch count for this sid < PER_FINGERPRINT_DISPATCH_LIMIT
         (F7 + D6_revised: prevent recursion when same fingerprint keeps hitting)

    `severity` (research-subsystem debate-1781688992-250894 D2 — severity-branch, NO
    shadow constant) selects the effective threshold AT CALL TIME over the single
    LOCKED constant, instead of a second module-level threshold that could drift:
      - 'strike' (default): RESEARCH_DISPATCH_THRESHOLD (F2 = 2) — repeat-error
        escalation; a pattern needs 2 occurrences. Preserves every existing caller.
      - 'HIGH': effective threshold 1 — a validator advisory HIGH (e.g. a falsy_zero
        determinism bug) dispatches on FIRST occurrence by independent advisory policy.
        This is NOT a relaxation of the LOCKED 2-strike threshold (which still governs
        repeat-error escalation); it is a distinct severity lane.
    Only 'HIGH' lowers the bar; any other value uses the locked F2 threshold.
    """
    if not fingerprint or not sid:
        return False
    effective_threshold = 1 if severity == "HIGH" else RESEARCH_DISPATCH_THRESHOLD
    if strike_count < effective_threshold:
        return False
    counter = load_counter(sid)
    return counter.get(fingerprint, 0) < PER_FINGERPRINT_DISPATCH_LIMIT


def record_dispatch(fingerprint: str, sid: str) -> int:
    """Increment the per-fingerprint counter atomically. Returns new count.

    Atomic write via the shared QuotaCounter (tmp + os.replace). Crash mid-write
    cannot leave a half file. (Arg order (fingerprint, sid) is the strike public
    contract; the primitive takes (sid, key).)
    """
    return _TRACKER.record(sid, fingerprint)


def reset_counter(sid: str) -> None:
    """Test/admin helper. Removes the sidecar file. NOT for production callers
    (the F7 safeguard would be defeated by silent reset)."""
    _TRACKER.reset(sid)


def remaining_quota(fingerprint: str, sid: str) -> int:
    """How many more dispatches this (sid, fingerprint) pair is allowed.
    Useful for advisory messaging when approaching the limit.
    """
    return _TRACKER.remaining(sid, fingerprint, PER_FINGERPRINT_DISPATCH_LIMIT)
