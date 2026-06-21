"""autopilot_state — atomic state file for autopilot resume mechanism.

Per debate-1778224899-c24de4 (converged at gen 3, snapshot SHA-1
41442ef446d9b274c270be177602a9be0938b271):
  - D2'' = "merged"       — single read/write path via atomic_json.write_json_atomic
  - D5  = "inline_in_command" — config residence is the command body, not external file
  - D7  = "stdlib_dataclass"  — IO contract uses stdlib dataclass + manual validation

Per prior debate-1778223294-b01a35:
  - D4  = "iter+wallclock"    — termination policy (both caps enforced)

State file location: ~/.claude/state/autopilot/<sid>.json

Schema (locked v1):
  {
    "sid":               str,                # orch-<unix_ts>-<rand6>
    "iter":              int,                # 0..max_iterations (D4)
    "goal_hash":         str,                # 40-char sha1 of goal text (D5 inline assertion key)
    "status":            "in_progress" | "done" | "failed",
    "started_ts":        float,              # monotonic wallclock anchor (D4 wallclock cap)
    "last_heartbeat_ts": float,              # set on every advance() — D2 SessionStart staleness check
    "tag_miss_count":    int,                # D3'' retry taxonomy
    "json_error_count":  int,                # D3'' retry taxonomy
    "cwd":               str | None,         # schema v2 (debate-1781937446): launch cwd; None=legacy v1
    "schema_version":    2,                  # written by to_dict; reads tolerate its absence (v1)
  }

Caps (D4):
  - max_iterations  = 30  (logical cap)
  - max_wallclock_seconds = 1800  (wall-time cap; both must be within bound to retry)

Retry taxonomy (D3'' addenda from gen 2 verdict):
  - tag_miss        : counter++, terminal `tag_miss_exhausted` at MAX_TAG_MISS=2
  - json_error      : counter++, terminal `json_error_exhausted` at MAX_JSON_ERROR=2
  - empty_body      : no counter, re-emits each turn; NO per-occurrence terminal
                      (`empty_body_persisted` UNIMPLEMENTED — deep-audit pass-2 rank 8);
                      termination via the global wallclock cap (1800s), not a ceiling.
"""
from __future__ import annotations

import hashlib
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .atomic_json import read_json, write_json_atomic


# Locked caps per debate D4
MAX_ITERATIONS: int = 30
MAX_WALLCLOCK_SECONDS: int = 1800

# D3'' retry taxonomy
MAX_TAG_MISS: int = 2
MAX_JSON_ERROR: int = 2

# Resume-window staleness cutoff (D2'' SessionStart scan)
RESUME_WINDOW_SECONDS: int = 24 * 3600  # 24h


_STATUSES = frozenset({"in_progress", "done", "failed"})


@dataclass
class AutopilotState:
    """Single-iteration autopilot state record. D7 stdlib_dataclass.

    Manual validation in __post_init__ instead of pydantic. Keeps the
    harness's lib/ tree pydantic-free per debate-1778224899-c24de4 D7.
    """

    sid: str
    iter: int
    goal_hash: str
    status: Literal["in_progress", "done", "failed"]
    started_ts: float
    last_heartbeat_ts: float
    tag_miss_count: int = 0
    json_error_count: int = 0
    # schema v2 (debate-1781937446-1281b5 D2): the cwd the autopilot session was
    # launched in. None = legacy v1 file (excluded from cwd-scoped scans). Binds
    # list_active_sids to the right project so a Stop in cwd B cannot drive cwd A's run.
    cwd: str | None = None

    def __post_init__(self) -> None:
        # 4-field manual validation per debate D7
        if not isinstance(self.sid, str) or not self.sid:
            raise ValueError(f"sid must be non-empty str, got {self.sid!r}")
        if not isinstance(self.iter, int) or not (0 <= self.iter <= MAX_ITERATIONS):
            raise ValueError(
                f"iter must be int in [0, {MAX_ITERATIONS}], got {self.iter!r}"
            )
        if not isinstance(self.goal_hash, str) or len(self.goal_hash) != 40:
            raise ValueError(
                f"goal_hash must be 40-char sha1 hex, got len={len(self.goal_hash) if isinstance(self.goal_hash, str) else type(self.goal_hash).__name__}"
            )
        if self.status not in _STATUSES:
            raise ValueError(
                f"status must be one of {sorted(_STATUSES)}, got {self.status!r}"
            )
        # Counter sanity (D3'' addenda)
        if self.tag_miss_count < 0 or self.json_error_count < 0:
            raise ValueError("retry counters cannot be negative")

    # ---------- D4 termination + D3'' retry checks ----------

    def wallclock_elapsed(self) -> float:
        return max(0.0, time.time() - self.started_ts)

    def iter_cap_hit(self) -> bool:
        return self.iter >= MAX_ITERATIONS

    def wallclock_cap_hit(self) -> bool:
        return self.wallclock_elapsed() >= MAX_WALLCLOCK_SECONDS

    def tag_miss_exhausted(self) -> bool:
        return self.tag_miss_count >= MAX_TAG_MISS

    def json_error_exhausted(self) -> bool:
        return self.json_error_count >= MAX_JSON_ERROR

    def can_continue(self) -> bool:
        """D4 + D3'' combined gate. False = caller must terminate this run."""
        return (
            self.status == "in_progress"
            and not self.iter_cap_hit()
            and not self.wallclock_cap_hit()
            and not self.tag_miss_exhausted()
            and not self.json_error_exhausted()
        )

    def is_stale(self, *, now: float | None = None,
                 window: int = RESUME_WINDOW_SECONDS) -> bool:
        """D2'' SessionStart resume-window check."""
        cur = time.time() if now is None else now
        return (cur - self.last_heartbeat_ts) > window

    # ---------- Serialization ----------

    def to_dict(self) -> dict:
        return {
            "sid": self.sid,
            "iter": self.iter,
            "goal_hash": self.goal_hash,
            "status": self.status,
            "started_ts": self.started_ts,
            "last_heartbeat_ts": self.last_heartbeat_ts,
            "tag_miss_count": self.tag_miss_count,
            "json_error_count": self.json_error_count,
            "cwd": self.cwd,
            "schema_version": 2,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AutopilotState":
        return cls(
            sid=data["sid"],
            iter=int(data["iter"]),
            goal_hash=data["goal_hash"],
            status=data["status"],
            started_ts=float(data["started_ts"]),
            last_heartbeat_ts=float(data["last_heartbeat_ts"]),
            tag_miss_count=int(data.get("tag_miss_count", 0)),
            json_error_count=int(data.get("json_error_count", 0)),
            cwd=data.get("cwd"),  # None for legacy v1 files (no cwd key)
        )


# ---------- D2'' merged read/write path ----------

def _state_dir() -> Path:
    """Lazy import of STATE_DIR to honor test fixture redirection (same
    pattern as lib/strike_dispatcher and lib/team_mailbox)."""
    from .paths import STATE_DIR
    d = STATE_DIR / "autopilot"
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_path(sid: str) -> Path:
    return _state_dir() / f"{sid}.json"


def hash_goal(goal: str) -> str:
    """Goal-text → 40-char sha1 hex. D5 inline_in_command assertion key."""
    return hashlib.sha1(goal.encode("utf-8")).hexdigest()


def new_state(sid: str, goal: str, cwd: str | None = None) -> AutopilotState:
    """Mint a fresh AutopilotState for iter=0. Caller is responsible for
    writing it via write_state(). `cwd` (D2) binds the session to its project;
    defaults to the current working directory when not supplied."""
    now = time.time()
    return AutopilotState(
        sid=sid,
        iter=0,
        goal_hash=hash_goal(goal),
        status="in_progress",
        started_ts=now,
        last_heartbeat_ts=now,
        cwd=cwd if cwd else os.getcwd(),
    )


def write_state(state: AutopilotState) -> bool:
    """Atomic write via lib.atomic_json (D2'' merged single write path).
    Returns True on success, False on any I/O failure (caller decides)."""
    return write_json_atomic(state_path(state.sid), state.to_dict())


def read_state(sid: str) -> AutopilotState | None:
    """Single read path. Returns None if file missing or unparseable
    (fail-soft per D2'' merged contract). Caller treats None as "no
    autopilot session resumable for this sid"."""
    data = read_json(state_path(sid), default=None)
    if not isinstance(data, dict):
        return None
    try:
        return AutopilotState.from_dict(data)
    except (KeyError, ValueError, TypeError):
        return None


def advance_iter(state: AutopilotState) -> AutopilotState:
    """Bump iter + last_heartbeat_ts. Returns NEW state object (immutable
    style). Caller writes via write_state()."""
    return AutopilotState(
        sid=state.sid,
        iter=state.iter + 1,
        goal_hash=state.goal_hash,
        status=state.status,
        started_ts=state.started_ts,
        last_heartbeat_ts=time.time(),
        tag_miss_count=state.tag_miss_count,
        json_error_count=state.json_error_count,
        cwd=state.cwd,
    )


def cleanup_terminal_sessions(now: float | None = None,
                              window: int = RESUME_WINDOW_SECONDS) -> int:
    """Delete state files for terminal sessions (status in {done, failed})
    whose `last_heartbeat_ts` is older than `window`. Returns count of files
    removed.

    In-progress files are never touched here — staleness of an active session
    is an operator decision (manual cleanup or explicit failure marking).
    Unparseable files are left alone (read_state returns None → skipped).
    """
    cur = time.time() if now is None else now
    d = _state_dir()
    if not d.exists():
        return 0
    removed = 0
    for p in d.glob("*.json"):
        st = read_state(p.stem)
        if st is None:
            continue
        if st.status not in ("done", "failed"):
            continue
        if (cur - st.last_heartbeat_ts) <= window:
            continue
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def list_active_sids(cwd_filter: str | None = None) -> list[str]:
    """Scan state/autopilot/ for `in_progress` sessions whose heartbeat is
    within RESUME_WINDOW_SECONDS. Used by SessionStart resume scan (D2'').

    cwd_filter (D2, debate-1781937446-1281b5): when given, return ONLY sessions
    whose bound `cwd` matches (via work_unit_store._cwd_match — separator/case/
    subtree tolerant). Legacy v1 files (cwd is None) are EXCLUDED from a
    cwd-scoped scan, so a Stop in cwd B can never select a session bound to cwd A.
    When cwd_filter is None the scan is unscoped (all active sessions).
    """
    out: list[str] = []
    d = _state_dir()
    if not d.exists():
        return out
    cwd_match = None
    if cwd_filter is not None:
        from lib.work_unit_store import _cwd_match
        cwd_match = _cwd_match
    for p in d.glob("*.json"):
        st = read_state(p.stem)
        if st is None:
            continue
        if st.status != "in_progress":
            continue
        if st.is_stale():
            continue
        if cwd_match is not None and (st.cwd is None or not cwd_match(cwd_filter, st.cwd)):
            continue
        out.append(st.sid)
    return out


# Quiet unused-import lint — `sys` reserved for future stdin debug helpers.
_ = sys
