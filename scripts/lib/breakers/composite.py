"""composite-key circuit breaker (v15.10 D3, debate-1778946602-jj7vxk).

Key: (agent_type, failure_mode) tuple — independent breaker per pair so
that a Researcher's evidence_fabrication trip does not silence
Researcher schema_violation calls, and an executor's tool_misuse trip
does not silence executor evidence_fabrication calls.

State machine:

    CLOSED ──fail accumulation──> OPEN ──cool_off elapsed──> HALF_OPEN
       ▲                            ▲                            │
       │                            │ probe fail (re-open)       │
       │  probe success ────────────┴────────────────────────────┘
       │  (success_to_close == 1)
       │
       └── never returns from OPEN without HALF_OPEN

Trip rules:
  - Primary  : >= TRIP_PER_MODE failures in the most recent TRIP_WINDOW
               failures-or-successes for THIS composite key (≈30% rate
               at TRIP_PER_MODE=3, TRIP_WINDOW=10, deliberately sensitive
               vs Hystrix 50%/many-second window).
  - Secondary: >= TRIP_ANY_MODE failures in the most recent
               TRIP_ANY_WINDOW events across ALL failure modes for the
               SAME agent_type (cross-mode safety net for an agent that
               is sporadically bad in many ways without any single mode
               crossing the per-mode threshold).

Half-open:
  - Calling code MUST call `try_acquire()` before spawning; True means
    "go" (closed OR half-open with probe budget free). False means
    "still open, do not spawn".
  - In half-open, exactly ONE probe is permitted at a time. record_success
    after the probe → state goes CLOSED with `trip_count` reset.
    record_failure → state goes back to OPEN with `trip_count += 1` and
    `backoff = min(2^trip_count * 60s, 3600s)` (cap 1 hour).

Persistence:
  - JSON file per composite key under
    state/breakers/<project_id>/<agent_type>__<failure_mode>.json.
  - project_id supplied by caller (matches v15.10 D5 path scheme).
  - Reads via `lib.atomic_json.read_json`, writes via `write_json_atomic`
    so concurrent hook fires don't shred state.
  - File schema is documented inside _load_record().

Event emission:
  - When the breaker transitions CLOSED→OPEN it calls
    `emit_fn(event_type, payload)` with event_type="breaker.opened".
    HALF_OPEN→OPEN re-trip emits "breaker.reopened".
    OPEN→HALF_OPEN emits "breaker.probe_started".
    HALF_OPEN→CLOSED emits "breaker.closed".
  - Operator visibility lives entirely in the caller's emit_fn — this
    module never substitutes a different agent (runtime_policy_gate).

Citations: Hystrix wiki (sanity-check magnitude) + Azure half-open
(canonical shape). Both accepted in CONVERGED.json evidence_review.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Iterable

from ..atomic_json import read_json, write_json_atomic
from ..paths import STATE_DIR
from .config import resolve_thresholds


# --- Thresholds (calibrated by D3, source of truth) ------------------------------
# v15.16: module-level constants kept as DEFAULTS for back-compat (external
# importers + test fixtures). Runtime behavior is driven by
# `resolve_thresholds()` which merges yaml override → BreakerThresholds.
# If no yaml exists, these values are used verbatim.
TRIP_PER_MODE: int = 3
TRIP_WINDOW: int = 10
TRIP_ANY_MODE: int = 5
TRIP_ANY_WINDOW: int = 20
BACKOFF_BASE_SEC: int = 60
BACKOFF_CAP_SEC: int = 3600
SUCCESS_TO_CLOSE: int = 1   # calibrated dual of sensitive trip — NOT yaml-overridable yet
# M15 (debate-1781607404-695af5 follow-up): a half-open probe reserved by try_acquire is
# released by the contractually-required record_success/record_failure. If the probe HOLDER
# is hard-killed in between (SIGKILL, crash) the slot would stay reserved forever and the
# key wedges in HALF_OPEN — no future probe ever admitted. PROBE_TTL_SEC lets a later
# try_acquire RECLAIM a probe whose reservation is older than this, so the breaker self-heals
# instead of permanently muting the backend. Generous (a real probe resolves in seconds).
PROBE_TTL_SEC: int = 120


# --- Public types ----------------------------------------------------------------

class State(str, Enum):
    """str-Enum so JSONL ledger writes the value, not the repr."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class BreakerSnapshot:
    """Immutable snapshot for inspection — never mutated by breaker code."""

    agent_type: str
    failure_mode: str
    state: State
    trip_count: int
    history: tuple[bool, ...]   # True = success, False = failure (newest last)
    opened_at: float | None     # epoch seconds; None if not currently open
    cool_off_until: float | None
    probe_in_flight: bool


# --- Default no-op emitter -------------------------------------------------------

def _noop_emit(event_type: str, payload: dict) -> None:
    """Default emit_fn — caller supplies a real one to surface escalations."""
    return None


# --- Helpers ---------------------------------------------------------------------

def _now() -> float:
    """Indirection so tests can monkey-patch lib.breakers.composite._now."""
    return time.time()


def _key_filename(agent_type: str, failure_mode: str) -> str:
    """Composite key → flat filename (forward-slash-safe, no path traversal)."""
    safe_at = agent_type.replace("/", "_").replace("\\", "_")
    safe_fm = failure_mode.replace("/", "_").replace("\\", "_")
    return f"{safe_at}__{safe_fm}.json"


def _project_dir(project_id: str, base_dir: os.PathLike | str | None = None) -> str:
    """Resolve <base>/breakers/<project_id>/ — default base is STATE_DIR."""
    base = os.fspath(base_dir) if base_dir is not None else os.fspath(STATE_DIR)
    return os.path.join(base, "breakers", project_id)


def _default_record() -> dict:
    """Empty record matching the on-disk schema below."""
    return {
        "state": State.CLOSED.value,
        "trip_count": 0,
        "history": [],            # list[bool] — True=success, False=failure
        "opened_at": None,        # float epoch | None
        "cool_off_until": None,   # float epoch | None
        "probe_in_flight": False,
        "probe_reserved_at": None,  # float epoch | None — M15: half-open probe reservation time
    }


def _trim_history(history: list[bool], window: int) -> list[bool]:
    """Keep at most `window` newest entries; older drop off the front."""
    if len(history) <= window:
        return history
    return history[-window:]


# --- Per-key breaker class -------------------------------------------------------

class CompositeBreaker:
    """One instance per (agent_type, failure_mode, project_id) tuple.

    Construct cheaply per call site — state is on disk, not in the object.
    The class is thread-unsafe; use a process-level lock if multiple workers
    write to the same composite key (the hook layer is single-threaded per
    fire, so the typical caller is safe).
    """

    def __init__(
        self,
        agent_type: str,
        failure_mode: str,
        project_id: str,
        *,
        base_dir: os.PathLike | str | None = None,
        emit_fn: Callable[[str, dict], None] = _noop_emit,
        any_mode_keys: Iterable[str] | None = None,
        thresholds: "Any | None" = None,
    ) -> None:
        """`any_mode_keys` — optional iterable of OTHER failure_mode names
        sharing the same agent_type; passed in by caller because cross-mode
        secondary trip requires reading those siblings' history. If None
        the secondary trip rule is silently disabled (back-compat — only
        primary 3/10 fires).
        """
        if not agent_type or not failure_mode or not project_id:
            raise ValueError(
                "CompositeBreaker requires non-empty agent_type, "
                "failure_mode, project_id"
            )
        self.agent_type = agent_type
        self.failure_mode = failure_mode
        self.project_id = project_id
        self.base_dir = base_dir
        self.emit_fn = emit_fn
        self.any_mode_keys: tuple[str, ...] = tuple(any_mode_keys or ())
        # M15 (debate-1781607404-695af5 D2): optional per-instance threshold override.
        # None → resolve_thresholds() (yaml/global, back-compat for every existing caller).
        # external_jury injects a short-cap BreakerThresholds so a flaky juror recovers in
        # minutes (cap≈300s) instead of the 3600s global hook default. Additive, not forked.
        self._thresholds = thresholds

    def _thresholds_or_global(self):
        return self._thresholds if self._thresholds is not None else resolve_thresholds()

    # --- file-path resolution
    @property
    def record_path(self) -> str:
        return os.path.join(
            _project_dir(self.project_id, self.base_dir),
            _key_filename(self.agent_type, self.failure_mode),
        )

    def _sibling_record_path(self, other_mode: str) -> str:
        return os.path.join(
            _project_dir(self.project_id, self.base_dir),
            _key_filename(self.agent_type, other_mode),
        )

    # --- read/write
    def _load(self) -> dict:
        rec = read_json(self.record_path, _default_record())
        # defensive: missing keys default to safe values (back-compat with old files)
        merged = _default_record()
        merged.update({k: v for k, v in rec.items() if k in merged})
        # normalize history element type to bool
        merged["history"] = [bool(x) for x in merged["history"] if isinstance(x, (bool, int))]
        # normalize state string → enum-string round trip
        try:
            State(merged["state"])
        except ValueError:
            merged["state"] = State.CLOSED.value
        # numeric fields: a poisoned non-numeric value (hand-edited file or a torn
        # concurrent write) would crash int()/float()/comparison in snapshot(),
        # try_acquire() (`now < cool_off`), and record_failure() (`2 ** trip_count`)
        # — ALL of which run on the post_tool hook path, so a raise there is a
        # hook-fail-CLOSED wedge that blocks every tool. Coerce fail-soft, exactly
        # like state above (deep-audit pass-2 completeness: breaker file poisoning).
        d = _default_record()
        try:
            tc = int(merged["trip_count"])
            merged["trip_count"] = tc if tc >= 0 else d["trip_count"]
        except (ValueError, TypeError):
            merged["trip_count"] = d["trip_count"]
        for _tk in ("opened_at", "cool_off_until", "probe_reserved_at"):
            v = merged.get(_tk)
            if v is None:
                continue
            try:
                merged[_tk] = float(v)
            except (ValueError, TypeError):
                merged[_tk] = None  # poisoned timestamp → treat as unset (re-derives safely)
        return merged

    def _save(self, rec: dict) -> None:
        os.makedirs(os.path.dirname(self.record_path), exist_ok=True)
        write_json_atomic(self.record_path, rec)

    # --- public API
    def snapshot(self) -> BreakerSnapshot:
        rec = self._load()
        return BreakerSnapshot(
            agent_type=self.agent_type,
            failure_mode=self.failure_mode,
            state=State(rec["state"]),
            trip_count=int(rec["trip_count"]),
            history=tuple(bool(x) for x in rec["history"]),
            opened_at=rec["opened_at"],
            cool_off_until=rec["cool_off_until"],
            probe_in_flight=bool(rec["probe_in_flight"]),
        )

    def try_acquire(self) -> bool:
        """Caller's gate before spawning.

        Returns True iff state is CLOSED, or state has elapsed cool_off
        and we can promote OPEN→HALF_OPEN and reserve the single probe.
        Returns False if already half-open with probe in flight, or
        cool_off has not yet elapsed.

        Performs the OPEN→HALF_OPEN transition AND sets probe_in_flight
        atomically when it returns True from open state — caller is
        contractually obliged to call record_success or record_failure.
        """
        rec = self._load()
        st = State(rec["state"])
        now = _now()

        if st == State.CLOSED:
            return True

        if st == State.OPEN:
            cool_off = rec.get("cool_off_until")
            if cool_off is not None and now < cool_off:
                return False
            # promote to half-open + reserve probe (stamp the reservation for TTL reclaim)
            rec["state"] = State.HALF_OPEN.value
            rec["probe_in_flight"] = True
            rec["probe_reserved_at"] = now
            self._save(rec)
            self.emit_fn(
                "breaker.probe_started",
                {
                    "agent_type": self.agent_type,
                    "failure_mode": self.failure_mode,
                    "trip_count": rec["trip_count"],
                },
            )
            return True

        if st == State.HALF_OPEN:
            if not bool(rec["probe_in_flight"]):
                return True
            # A probe is reserved. Reclaim it ONLY if the reservation is stale beyond
            # PROBE_TTL_SEC (the holder is presumed dead) — otherwise a live probe is in
            # flight and we must not double-admit. reserved_at None (legacy/pre-M15 record)
            # is treated as stale so an old wedged key can self-heal.
            reserved_at = rec.get("probe_reserved_at")
            if reserved_at is None or (now - float(reserved_at)) > PROBE_TTL_SEC:
                rec["probe_reserved_at"] = now  # fresh reservation for the new caller
                self._save(rec)
                self.emit_fn(
                    "breaker.probe_reclaimed",
                    {
                        "agent_type": self.agent_type,
                        "failure_mode": self.failure_mode,
                        "trip_count": rec["trip_count"],
                    },
                )
                return True
            return False

        return False  # unreachable; defensive

    def record_failure(self) -> State:
        """Record one failure; may trip CLOSED→OPEN or re-trip HALF_OPEN→OPEN.

        Returns the new state for caller convenience.
        """
        th = self._thresholds_or_global()
        rec = self._load()
        st = State(rec["state"])
        rec["history"] = _trim_history(list(rec["history"]) + [False], th.trip_window)

        if st == State.HALF_OPEN:
            # Probe failed → re-open with increased backoff.
            rec["trip_count"] = int(rec["trip_count"]) + 1
            backoff = min(th.backoff_base_sec * (2 ** rec["trip_count"]), th.backoff_cap_sec)
            rec["state"] = State.OPEN.value
            rec["opened_at"] = _now()
            rec["cool_off_until"] = rec["opened_at"] + backoff
            rec["probe_in_flight"] = False
            rec["probe_reserved_at"] = None
            self._save(rec)
            self.emit_fn(
                "breaker.reopened",
                {
                    "agent_type": self.agent_type,
                    "failure_mode": self.failure_mode,
                    "trip_count": rec["trip_count"],
                    "backoff_sec": backoff,
                    "cool_off_until": rec["cool_off_until"],
                },
            )
            return State.OPEN

        if st == State.OPEN:
            # Failure while open shouldn't normally happen (try_acquire blocks),
            # but if it does, just extend the trip — no state change.
            self._save(rec)
            return State.OPEN

        # CLOSED — check trip conditions
        failures_in_window = sum(1 for x in rec["history"] if not x)
        primary_trip = failures_in_window >= th.trip_per_mode
        # Pass the in-flight (post-append) history so secondary sees this failure too.
        secondary_trip = self._secondary_trip(
            current_history=rec["history"], thresholds=th,
        )

        if primary_trip or secondary_trip:
            rec["trip_count"] = int(rec["trip_count"]) + 1
            backoff = min(th.backoff_base_sec * (2 ** rec["trip_count"]), th.backoff_cap_sec)
            rec["state"] = State.OPEN.value
            rec["opened_at"] = _now()
            rec["cool_off_until"] = rec["opened_at"] + backoff
            rec["probe_in_flight"] = False
            rec["probe_reserved_at"] = None
            self._save(rec)
            self.emit_fn(
                "breaker.opened",
                {
                    "agent_type": self.agent_type,
                    "failure_mode": self.failure_mode,
                    "trigger": "secondary" if (secondary_trip and not primary_trip) else "primary",
                    "trip_count": rec["trip_count"],
                    "backoff_sec": backoff,
                    "cool_off_until": rec["cool_off_until"],
                },
            )
            return State.OPEN

        self._save(rec)
        return State.CLOSED

    def record_success(self) -> State:
        """Record one success. In half-open with success_to_close=1 this closes."""
        th = self._thresholds_or_global()
        rec = self._load()
        st = State(rec["state"])
        rec["history"] = _trim_history(list(rec["history"]) + [True], th.trip_window)

        if st == State.HALF_OPEN:
            # Close — reset trip_count to 0 per Azure canonical shape.
            rec["state"] = State.CLOSED.value
            rec["opened_at"] = None
            rec["cool_off_until"] = None
            rec["probe_in_flight"] = False
            rec["probe_reserved_at"] = None
            rec["trip_count"] = 0
            self._save(rec)
            self.emit_fn(
                "breaker.closed",
                {
                    "agent_type": self.agent_type,
                    "failure_mode": self.failure_mode,
                },
            )
            return State.CLOSED

        # CLOSED or OPEN — record success in history but no state change
        # (OPEN successes shouldn't happen since try_acquire blocks, but
        # if upstream code reports one we silently absorb it).
        self._save(rec)
        return st

    # --- secondary trip helper
    def _secondary_trip(
        self,
        *,
        current_history: list[bool] | None = None,
        thresholds=None,
    ) -> bool:
        """≥ trip_any_mode failures in last trip_any_window events across all
        known modes for this agent_type.

        `current_history` lets record_failure pass the in-flight (post-append)
        history for the active mode so the current failure is counted instead
        of seeing the stale on-disk version.

        `thresholds` (v15.16): caller can pass a pre-resolved BreakerThresholds
        to avoid double yaml read. None → resolve fresh.
        """
        th = thresholds if thresholds is not None else resolve_thresholds()
        if not self.any_mode_keys:
            return False
        combined: list[bool] = []
        # Own history: prefer the in-flight rec if provided, else load from disk.
        if current_history is not None:
            own_hist = list(current_history)
        else:
            own_rec = read_json(self.record_path, _default_record())
            own_hist = list(own_rec.get("history", [])) if isinstance(own_rec, dict) else []
        combined.extend(bool(x) for x in own_hist)
        for m in self.any_mode_keys:
            if m == self.failure_mode:
                continue
            sib = read_json(self._sibling_record_path(m), _default_record())
            hist = sib.get("history") if isinstance(sib, dict) else None
            if not isinstance(hist, list):
                continue
            combined.extend(bool(x) for x in hist)
        # Deterministic tail: count failures in newest trip_any_window entries
        # of the concatenation (source-iteration order is stable).
        recent = combined[-th.trip_any_window:]
        failures = sum(1 for ok in recent if not ok)
        return failures >= th.trip_any_mode
