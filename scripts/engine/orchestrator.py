"""Resumable super-session for autonomous orchestrator MVP.

Per debate-1778161608-713bdc gen 4 byte-identical convergence
(snapshot 7add26467f703f7b119c1903ff0dcfca5b227a65):

Locked decisions wired here:
  - F1 mvp_scope = phase_1_2 (this is Phase 1 implementation)
  - F3 allsolution_form = autopilot_phase_extension (no separate command)
  - F6 resume_idempotency_storage = events_jsonl_replay_plus_atomic_counter_sidecar
  - F7 n_strike_recursion_safeguard = atomic_counter_plus_timeout (counter file
    lives next to events.jsonl; orchestrator hands sid to strike_dispatcher)

Implementation conditions (Architect gen 3):
  - B5 cold-start: FileNotFoundError -> bootstrap (None / counter=0),
    JSONDecodeError -> fail-closed (raise; do NOT silently zero state)
  - D4b TTY: sys.stdin.isatty() check, non-tty -> 'resume' default

Persists three artifacts under STATE_DIR/orchestrator/<sid>/:
  events.jsonl     — append-only super-session log (replayable)
  phase-tree.md    — derived human-readable mirror (regenerated each update)
  child_sids.json  — orchestrator phase_id -> child engine sid mapping
                     (atomic via lib/atomic_json)

Events.jsonl is canonical for resume; child_sids.json is the only sidecar
this MVP introduces beyond what F6 mandates. The dispatch_counter sidecar
(F6) is owned by lib/strike_dispatcher.py, not here.
"""
from __future__ import annotations

import json
import secrets
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lib.atomic_json import read_json, write_json_atomic
from lib.logging import jsonl_append, now_iso
from lib.paths import STATE_DIR, ensure_dir
from lib.phase_tree import (
    Phase,
    Status,
    parse_yaml,
    render_tree_markdown,
    render_yaml,
)


ORCHESTRATOR_DIR: Path = STATE_DIR / "orchestrator"


def mint_session_id() -> str:
    """`orch-<unix_ts>-<random6>`. Mirrors debate sid shape for visual parity."""
    return f"orch-{int(time.time())}-{secrets.token_hex(3)}"


@dataclass
class OrchestratorSession:
    sid: str
    goal: str
    root_phase: Phase
    child_sids: dict[str, str] = field(default_factory=dict)

    @property
    def dir(self) -> Path:
        return ensure_dir(ORCHESTRATOR_DIR / self.sid)

    @property
    def events_path(self) -> Path:
        return self.dir / "events.jsonl"

    @property
    def phase_tree_path(self) -> Path:
        return self.dir / "phase-tree.md"

    @property
    def child_sids_path(self) -> Path:
        return self.dir / "child_sids.json"


# ---------- Lifecycle ----------

def new_session(goal: str) -> OrchestratorSession:
    """Create a fresh super-session. Writes initial state + session_start event."""
    sid = mint_session_id()
    root = Phase(
        id=f"root-{sid}",
        goal=goal,
        status=Status.IN_PROGRESS,
        next_action="phase_0_design_via_debate",
    )
    sess = OrchestratorSession(sid=sid, goal=goal, root_phase=root)
    _persist_phase_tree(sess)
    _append_event(sess, event_type="session_start",
                  payload={"goal": goal, "sid": sid})
    return sess


def load_session(sid: str) -> OrchestratorSession | None:
    """Resume per F6. Returns None on FileNotFoundError (cold-start B5).

    On JSONDecodeError of child_sids.json: fail-closed (raise) — corrupt
    sidecar must NOT silently reset to {} or quota would be lost.
    Corrupt lines in events.jsonl are skipped (replay tolerance) since
    the dispatch counter sidecar (lib/strike_dispatcher) is authoritative
    for quota — replay just rebuilds best-effort phase state.
    """
    events_path = ORCHESTRATOR_DIR / sid / "events.jsonl"
    if not events_path.exists():
        return None  # B5 cold-start: missing session is not an error

    events = _replay_events(events_path)
    start = next((e for e in events if e.get("type") == "session_start"), None)
    if not start:
        return None
    goal = start.get("payload", {}).get("goal", "(unknown)")

    latest_phase_update = next(
        (e for e in reversed(events) if e.get("type") == "phase_update"),
        None,
    )
    if latest_phase_update:
        phase_yaml = latest_phase_update.get("payload", {}).get("phase_yaml", "")
        try:
            root = parse_yaml(phase_yaml)
        except Exception:
            root = Phase(id=f"root-{sid}", goal=goal, status=Status.IN_PROGRESS)
    else:
        root = Phase(id=f"root-{sid}", goal=goal, status=Status.IN_PROGRESS)

    child_sids_path = ORCHESTRATOR_DIR / sid / "child_sids.json"
    if child_sids_path.exists():
        try:
            text = child_sids_path.read_text(encoding="utf-8")
            child_sids = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError as e:
            # B5 fail-closed: corrupt sidecar = explicit error, never silent zero
            raise RuntimeError(
                f"orchestrator child_sids.json corrupt for sid={sid}: {e}. "
                "Manually inspect or delete the file to bootstrap fresh."
            ) from e
    else:
        child_sids = {}

    return OrchestratorSession(
        sid=sid, goal=goal, root_phase=root, child_sids=child_sids
    )


def confirm_resume_or_new(sid: str) -> str:
    """D4b TTY check. Non-tty (e.g. autopilot child spawn) -> 'resume' default.

    Returns one of: 'resume' | 'new' | 'abort'.
    """
    if not sys.stdin.isatty():
        return "resume"

    print(f"Orchestrator session {sid} already exists. Choose:")
    print("  [r] resume / [n] new sid / [a] abort")
    try:
        choice = input("> ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "abort"
    if choice in ("r", "resume", ""):
        return "resume"
    if choice in ("n", "new"):
        return "new"
    return "abort"


# ---------- Mutation ----------

def update_phase(sess: OrchestratorSession, phase: Phase) -> None:
    """Replace root phase, regenerate phase-tree.md, append phase_update event."""
    sess.root_phase = phase
    _persist_phase_tree(sess)
    _append_event(sess, event_type="phase_update", payload={
        "phase_yaml": render_yaml(phase),
        "status": phase.status.value,
    })


def link_child(sess: OrchestratorSession, phase_id: str, child_sid: str) -> None:
    """Map an orchestrator phase to a child engine sid (debate / ralph / team).

    child_sids.json written via tmp+os.replace (lib/atomic_json) so a crash
    mid-write cannot leave a half-file.
    """
    sess.child_sids[phase_id] = child_sid
    write_json_atomic(str(sess.child_sids_path), sess.child_sids)
    _append_event(sess, event_type="child_linked", payload={
        "phase_id": phase_id,
        "child_sid": child_sid,
    })


# ---------- Research dispatch (Phase 2 wiring) ----------

def build_research_dispatch_payload(
    sess: OrchestratorSession,
    fingerprint: str,
    error_excerpt: str,
    tool_name: str,
    strike_count: int,
) -> dict | None:
    """Phase 2 dispatch helper — does NOT spawn the Agent itself.

    Per debate-1778161608-713bdc gen 4: dispatch is gated by
    `lib.strike_dispatcher.should_dispatch`. This function (a) checks the
    gate, (b) records the dispatch in the per-fingerprint counter
    (atomic), (c) appends a `research_dispatched` event, and (d) returns
    a payload dict the autopilot caller hands to the Agent tool.

    Returns None when the gate denies dispatch (below threshold OR
    per-fingerprint quota exhausted). Caller falls back to the strike
    warning advisory text without spawning a subagent.

    The Agent tool invocation is the caller's responsibility — orchestrator
    cannot invoke tools directly (it lives in lib/, no tool harness).
    """
    from lib.strike_dispatcher import (
        should_dispatch,
        record_dispatch,
        remaining_quota,
    )

    if not should_dispatch(fingerprint, sess.sid, strike_count=strike_count):
        return None

    new_count = record_dispatch(fingerprint, sess.sid)
    quota_left = remaining_quota(fingerprint, sess.sid)

    payload = {
        "subagent_type": "harness-researcher",
        "fingerprint": fingerprint,
        "error_excerpt": error_excerpt[:400],  # match agent input cap
        "tool_name": tool_name,
        "attempts": strike_count,
        "sid": sess.sid,
        "dispatch_count_for_fingerprint": new_count,
        "remaining_quota": quota_left,
    }
    _append_event(sess, event_type="research_dispatched", payload=payload)
    return payload


# ---------- Goal-completion loop (W21+ autonomous-to-goal) ----------

DEFAULT_MAX_ITERATIONS: int = 3


def list_sessions() -> list[dict[str, Any]]:
    """Return summary of all orch super-sessions in ORCHESTRATOR_DIR.

    Per-entry schema: {sid, started_ts, iter, status, phase_id, goal}.
    Sorted by (started_ts, sid) descending — newest first, with sid as a
    deterministic tiebreak so sessions sharing a second (started_ts is
    second-resolution) never order by filesystem iteration (STEP 5 flaky fix).

    Replay-based: each entry is reconstructed by reading sid/events.jsonl.
    Sessions with corrupt or missing events.jsonl are skipped silently
    (operator can inspect state/orchestrator/ directly if needed).

    Use case: `python -m engine.orchestrator list-sessions` operator
    surface for super-session visibility (referenced by autopilot
    --resume failure path: 'aborted_resume_unknown_sid + suggest
    list-sessions').
    """
    out: list[dict[str, Any]] = []
    if not ORCHESTRATOR_DIR.exists():
        return out

    for sid_dir in ORCHESTRATOR_DIR.iterdir():
        if not sid_dir.is_dir():
            continue
        sid = sid_dir.name
        events_path = sid_dir / "events.jsonl"
        if not events_path.is_file():
            continue
        try:
            events = _replay_events(events_path)
        except Exception:
            continue
        if not events:
            continue

        # First event = session_started; carries goal + started_ts.
        first = events[0]
        started_ts = first.get("ts", "")
        goal = first.get("payload", {}).get("goal", "")

        # Iteration count = number of iteration_started events.
        iter_count = sum(
            1 for e in events if e.get("type") == "iteration_started"
        )

        # Latest phase_id from most recent phase_update / phase_complete.
        phase_id = ""
        status = "in_progress"
        for e in reversed(events):
            t = e.get("type")
            if t in ("phase_update", "phase_complete"):
                phase_id = e.get("payload", {}).get("phase_id") or e.get("phase", "") or phase_id
            if t == "autopilot_run_complete":
                status = e.get("payload", {}).get("status", "complete")
                break

        out.append({
            "sid": sid,
            "started_ts": started_ts,
            "iter": iter_count,
            "status": status,
            "phase_id": phase_id,
            "goal": goal,
        })

    # Newest first; `sid` as a deterministic tiebreak so equal or empty
    # started_ts values never produce filesystem-iteration-order-dependent
    # (flaky) output (STEP 5 flaky fix).
    out.sort(key=lambda x: (x.get("started_ts", ""), x.get("sid", "")), reverse=True)
    return out


# ---------- Pane shard aggregation (D6 wave (a) — debate-1778302432-1ce6ea) ----------
#
# Per-pane shards live at <sid_dir>/panes/<pane_id>.jsonl (per
# lib.autopilot_pane_events). Pane subprocesses MUST NOT write to the
# canonical events.jsonl (Windows file-locking is advisory only — concurrent
# appends from N panes + the orchestrator process would interleave partial
# JSON lines).
#
# Two helpers below run from the orchestrator process only:
#
#   replay_pane_state(sid) — pure read; latest pane_status per pane_id from
#       both still-pending shards AND already-merged canonical events. Used
#       for `list-sessions --verbose` and operator visibility.
#
#   merge_pane_shards(sid) — physical merge. For each shard whose final event
#       is a terminal pane_status (status in {exited, killed}), append every
#       record to canonical events.jsonl (re-stamped through `_append_event`
#       semantics: each line gets sid + replay-friendly shape) and delete
#       the shard. Shards belonging to still-running panes are skipped.
#       Idempotent because deleted shards do not re-merge.

_TERMINAL_PANE_STATUSES = frozenset({"exited", "killed", "failed"})


def _pane_shard_dir(sid: str) -> Path:
    return ORCHESTRATOR_DIR / sid / "panes"


def _read_pane_shard(path: Path) -> list[dict[str, Any]]:
    """Tolerant per-shard reader (mirrors `_replay_events` discipline)."""
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return out


def _is_pane_event(event: dict[str, Any]) -> bool:
    t = event.get("type") or event.get("payload", {}).get("type")
    return t in ("pane_started", "pane_status")


def replay_pane_state(sid: str) -> dict[str, dict[str, Any]]:
    """Reconstruct latest known state per pane for ``sid``.

    Reads BOTH the per-pane shard directory AND any already-merged pane
    events in the canonical ``events.jsonl``. Latest pane_status wins
    (sorted by ``ts``).
    """
    sid_dir = ORCHESTRATOR_DIR / sid
    if not sid_dir.is_dir():
        return {}

    snapshot: dict[str, dict[str, Any]] = {}

    def _ingest(events: list[dict[str, Any]]) -> None:
        for ev in events:
            if not _is_pane_event(ev):
                continue
            pane_id = ev.get("pane_id") or ev.get("payload", {}).get("pane_id")
            if not pane_id:
                continue
            existing = snapshot.get(pane_id)
            ev_ts = ev.get("ts", "")
            if existing is None or ev_ts >= existing.get("_latest_ts", ""):
                merged = dict(existing or {})
                merged.update({k: v for k, v in ev.items() if k != "type"})
                if "payload" in ev and isinstance(ev["payload"], dict):
                    merged.update(
                        {k: v for k, v in ev["payload"].items() if k != "type"}
                    )
                merged["_latest_ts"] = ev_ts
                merged["_latest_type"] = ev.get("type") or ev.get(
                    "payload", {}
                ).get("type")
                snapshot[pane_id] = merged

    canonical = sid_dir / "events.jsonl"
    if canonical.is_file():
        _ingest(_replay_events(canonical))

    shard_dir = _pane_shard_dir(sid)
    if shard_dir.is_dir():
        for shard in sorted(shard_dir.glob("*.jsonl")):
            _ingest(_read_pane_shard(shard))

    return snapshot


def merge_pane_shards(sid: str) -> int:
    """Merge terminal-pane shards into canonical events.jsonl; return count merged.

    Only shards whose final event is a pane_status with status in
    ``_TERMINAL_PANE_STATUSES`` are eligible. Running panes are skipped
    (their shard remains for the next sweep).
    """
    sid_dir = ORCHESTRATOR_DIR / sid
    shard_dir = _pane_shard_dir(sid)
    if not shard_dir.is_dir():
        return 0

    canonical = sid_dir / "events.jsonl"
    merged_count = 0

    for shard in sorted(shard_dir.glob("*.jsonl")):
        events = _read_pane_shard(shard)
        if not events:
            try:
                shard.unlink()
            except OSError:
                pass
            continue

        last = events[-1]
        last_type = last.get("type")
        last_status = last.get("status")
        if last_type != "pane_status" or last_status not in _TERMINAL_PANE_STATUSES:
            continue

        for ev in events:
            jsonl_append(
                canonical,
                {
                    "type": ev.get("type", "pane_event"),
                    "sid": sid,
                    "payload": {k: v for k, v in ev.items() if k != "ts"},
                },
            )

        try:
            shard.unlink()
        except OSError:
            pass
        merged_count += 1

    return merged_count


# ---------- Phase 1 entry helpers (wires lib D1+D5 into orchestrator) ----------
#
# autopilot.md's Phase 1 directive references lib.autopilot_worktree_probe
# (D1) and lib.autopilot_flip_policy (D5) via prose. These two helpers give
# the LLM-driven autopilot a single Python entry point per concern instead
# of composing primitives manually — closes the "markdown-only wiring" gap.

def phase1_onedrive_check(
    sess: OrchestratorSession,
    repo_root: Path | str,
) -> tuple[bool, str | None]:
    """D1 wrapper — call is_onedrive_path + emit worktree_probe_failed on positive.

    Returns ``(ok, reason)``. When ``ok=False``, the orchestrator has already
    appended a ``worktree_probe_failed`` event to the canonical events.jsonl;
    caller (autopilot Phase 1 entry) should HALT (no auto fallback — D5
    Phase 2 territory).
    """
    from lib.autopilot_worktree_probe import is_onedrive_path

    root = Path(repo_root) if isinstance(repo_root, str) else repo_root
    ok, reason = is_onedrive_path(root)
    if not ok:
        _append_event(
            sess,
            event_type="worktree_probe_failed",
            payload={"reason": reason or "unknown", "repo_root": str(root)},
        )
    return (ok, reason)


def record_parallel_run_outcome(
    sess: OrchestratorSession,
    *,
    status: str,
    merge_conflicts: int = 0,
    pane_failures: int = 0,
    **extra: Any,
) -> None:
    """D5 wrapper — call log_parallel_run_outcome (write-only telemetry).

    Called from autopilot Phase 5 when AUTOPILOT_PARALLEL=1 was set AND the
    run reached a terminal state. Observability only — NOT a flip trigger.
    """
    from lib.autopilot_flip_policy import log_parallel_run_outcome

    log_parallel_run_outcome(
        sid=sess.sid,
        status=status,
        merge_conflicts=merge_conflicts,
        pane_failures=pane_failures,
        **extra,
    )


def current_iteration(sess: OrchestratorSession) -> int:
    """Count `iteration_started` events in events.jsonl.

    Derived from the canonical event log so resume sees the correct count
    without an extra sidecar. Iteration 0 = before any iteration has started
    (initial Phase 0-5 run is iteration 1).
    """
    if not sess.events_path.exists():
        return 0
    return sum(
        1 for e in _replay_events(sess.events_path)
        if e.get("type") == "iteration_started"
    )


def bump_iteration(sess: OrchestratorSession) -> int:
    """Append `iteration_started` event and return the new iteration count.

    Caller (autopilot) invokes this BEFORE each Phase 0-5 cycle. The first
    call after `new_session` returns 1.
    """
    new_count = current_iteration(sess) + 1
    _append_event(sess, event_type="iteration_started", payload={
        "iteration": new_count,
    })
    return new_count


def evaluate_completion(
    sess: OrchestratorSession,
    *,
    validators_passed: bool,
    tests_passed: bool,
    blocking_question_count: int = 0,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    evaluator_verdict: str | None = None,
    require_evaluator: bool = False,
) -> str:
    """Thin wrapper preserving the session-typed signature. Pure decision
    logic lives in `lib.completion_gate.decide_completion` since v15.40+
    so `handlers/stop/autopilot_continue.py` can adjudicate without a
    `handlers → engine` import (commit_layer_adjacency 4-tier model).

    `require_evaluator` (debate-1780564679-8mgxsd D5): forwarded verbatim;
    defaults to False so existing engine callers are byte-identical. When
    True a missing `evaluator_verdict` can never yield 'complete' (E2
    platform enforcement — see decide_completion docstring D1/D4).

    Returns one of: 'complete' | 'iterate' | 'escalate'. See
    `lib.completion_gate.decide_completion` for the full truth table.
    """
    from lib.completion_gate import decide_completion
    verdict = decide_completion(
        current_iteration(sess),
        validators_passed=validators_passed,
        tests_passed=tests_passed,
        blocking_question_count=blocking_question_count,
        max_iterations=max_iterations,
        evaluator_verdict=evaluator_verdict,
        require_evaluator=require_evaluator,
    )
    # S2 W3 wiring (debate-1779267594-edb2a2 D5_W3_site LOCK):
    # record one insight per terminal verdict ('complete' / 'escalate').
    # 'iterate' is skipped — only mid-cycle, not convergence.
    if verdict in ("complete", "escalate"):
        try:
            from lib import insight_index as _ii
            from datetime import datetime, timezone
            _ii.append({
                "event_type": "orchestrator",
                "summary": (
                    f"orchestrator verdict={verdict} sid={sess.sid} "
                    f"iter={current_iteration(sess)}/{max_iterations} "
                    f"validators={validators_passed} tests={tests_passed} "
                    f"evaluator={evaluator_verdict}"
                )[:280],
                "ts_unix_ms": int(datetime.now(tz=timezone.utc).timestamp() * 1000),
                "correlation_id": sess.sid,
                "source_module": "engine.orchestrator",
                "axis": "completion",
                "tags": ["orchestrator", verdict],
                "body_ref": None,
            })
        except Exception:
            # Never break orchestrator on insight-index failure.
            pass
    return verdict


# ---------- Internals ----------

def _persist_phase_tree(sess: OrchestratorSession) -> None:
    sess.phase_tree_path.write_text(
        render_tree_markdown(sess.root_phase),
        encoding="utf-8",
    )


def _append_event(sess: OrchestratorSession, *,
                  event_type: str, payload: dict[str, Any]) -> None:
    record = {
        "ts": now_iso(),
        "type": event_type,
        "sid": sess.sid,
        "payload": payload,
    }
    jsonl_append(sess.events_path, record)


def _replay_events(path: Path) -> list[dict[str, Any]]:
    """Tolerate corrupt lines (skip + continue). Counter sidecar is authoritative
    for quota; replay only reconstructs phase state.
    """
    events: list[dict[str, Any]] = []
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
