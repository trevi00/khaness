#!/usr/bin/env python3
"""team_policy_check — deterministic team monitor consumer (M28).

Replaces `commands/harness-team.md` §5 "Monitor" prose: the markdown told an LLM
orchestrator to poll worker-<i>.out, flag flat heartbeats, and decide kills by
eyeball. This CLI does one deterministic policy pass over a team session and OWNS
the loop-control mutation (terminate + the single events.jsonl append), so the
markdown can branch mechanically on the exit code instead of re-deriving it.

One pass:
  1. discover workers (worker-*.out under --team-dir, ∪ psmux sessions).
  2. load/persist frozen N + killed-set (state/team/<sid>/policy-state.json).
  3. per worker: evaluate_stall (D1) → progressing | stalled | unknown.
  4. decide_pass (D2): kill stalled workers in id-order while the frozen-N quorum
     guard holds; the first skip_below_quorum halts further kills and escalates.
  5. perform terminate_worker for each kill (idempotent); append events.

Control contract (the markdown branches on these):
  stdout: one JSON line {exit, killed[], escalated, frozen_n, threshold, summary, ...}
  exit codes:  0 = no-op (nothing stalled — continue monitoring)
               3 = acted (killed >=1 stalled worker, quorum still reachable)
               5 = escalate-HALT (a stalled worker is load-bearing for quorum —
                   killing it would break quorum; operator must intervene)
               4 = skipped-for-safety (fail-CLOSED: unknown/unreadable worker(s),
                   deferred to the next cycle, nothing killed)
               2 = argparse usage error ONLY (reserved; never a semantic signal)

Idempotent per worker: a killed worker is recorded in policy-state and excluded
from subsequent passes, so re-running does not re-emit kill events. No operator
gate — this is loop-control only (the kill stays within the quorum the operator
already authorized at team launch). Fail-CLOSED: any read fault → never kill.
Mirrors cli.debate_converge_check (single-writer events + fail-closed try/except).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.team_policy import (  # noqa: E402
    EXIT_ACTED,
    EXIT_ERROR,
    EXIT_ESCALATE,
    EXIT_NOOP,
    EXIT_SKIPPED,
    WorkerAssessment,
    decide_pass,
    evaluate_stall,
    make_file_read_fn,
)


# --------------------------------------------------------------------------
# Worker discovery + persisted policy state
# --------------------------------------------------------------------------


def _discover_workers(team_dir: Path, session_id: str) -> list[str]:
    """worker_ids from `<team_dir>/worker-*.out` stems ∪ live psmux sessions."""
    ids: set[str] = set()
    try:
        for p in team_dir.glob("worker-*.out"):
            ids.add(p.stem)
    except OSError:
        pass
    try:
        from lib.team_runtime import list_team_workers
        for wid in list_team_workers(session_id):
            ids.add(wid)
    except Exception:  # noqa: BLE001 — psmux optional / fail-soft
        pass
    return sorted(ids)


def _state_path(session_id: str) -> Path:
    from lib.paths import STATE_DIR, ensure_dir
    return ensure_dir(STATE_DIR / "team" / session_id) / "policy-state.json"


def _load_state(session_id: str) -> dict:
    p = _state_path(session_id)
    if not p.exists():
        return {"frozen_n": None, "killed": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"frozen_n": None, "killed": []}
        data.setdefault("frozen_n", None)
        data.setdefault("killed", [])
        return data
    except (OSError, json.JSONDecodeError):
        return {"frozen_n": None, "killed": []}


def _save_state(session_id: str, state: dict) -> None:
    from lib.atomic_json import write_json_atomic
    write_json_atomic(str(_state_path(session_id)), state)


def _append_event(session_id: str, event_type: str, payload: dict) -> None:
    """Single-writer team events.jsonl append (state/team/<sid>/events.jsonl)."""
    from lib.paths import STATE_DIR, ensure_dir
    from lib.logging import jsonl_append, now_iso
    path = ensure_dir(STATE_DIR / "team" / session_id) / "events.jsonl"
    jsonl_append(path, {"ts": now_iso(), "type": event_type, "payload": payload})


# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------


def run(
    session_id: str,
    team_dir: str,
    *,
    stall_seconds: float = 180.0,
    frozen_n: int | None = None,
    now: float | None = None,
    read_fn=None,
    terminate_fn=None,
    list_workers_fn=None,
    alive_fn=None,
    mailbox_depth_fn=None,
    capture_pane_fn=None,
) -> tuple[dict, int]:
    """One deterministic policy pass. Returns (result_dict, exit_code).

    All IO is injectable for tests: `now`, `read_fn(sid, wid)->WorkerSignals|None`,
    `terminate_fn(sid, wid)->bool`, `list_workers_fn(team_dir, sid)->list[str]`.
    Defaults wire the real artifacts (file read_fn) and psmux team_runtime.
    """
    tdir = Path(team_dir)
    clock = float(now) if now is not None else time.time()

    # Default IO wiring (lazy psmux import; fail-soft if psmux absent).
    if alive_fn is None or mailbox_depth_fn is None or capture_pane_fn is None:
        try:
            from lib import team_runtime
            if alive_fn is None:
                alive_fn = team_runtime.is_worker_alive
            if capture_pane_fn is None:
                capture_pane_fn = team_runtime.capture_worker_pane
        except Exception:  # noqa: BLE001
            pass
        if mailbox_depth_fn is None:
            try:
                from lib.team_mailbox import mailbox_depth as _md
                mailbox_depth_fn = lambda sid, wid: _md(sid, wid, side="outbox")  # noqa: E731
            except Exception:  # noqa: BLE001
                mailbox_depth_fn = None

    if read_fn is None:
        read_fn = make_file_read_fn(
            tdir, alive_fn=alive_fn, mailbox_depth_fn=mailbox_depth_fn,
            capture_pane_fn=capture_pane_fn,
        )
    if terminate_fn is None:
        from lib.team_runtime import terminate_worker as terminate_fn  # type: ignore
    if list_workers_fn is None:
        list_workers_fn = _discover_workers

    workers = list_workers_fn(tdir, session_id)

    state = _load_state(session_id)
    killed_set: set[str] = set(state.get("killed") or [])

    # Freeze N at the first pass (or honor explicit override).
    if frozen_n is not None:
        fz = int(frozen_n)
    elif isinstance(state.get("frozen_n"), int):
        fz = int(state["frozen_n"])
    else:
        fz = len(workers)
    if state.get("frozen_n") != fz:
        state["frozen_n"] = fz
        _save_state(session_id, state)

    # Assess each non-killed worker (D1).
    assessments: list[WorkerAssessment] = []
    for wid in workers:
        if wid in killed_set:
            continue
        try:
            signals = read_fn(session_id, wid)
        except Exception:  # noqa: BLE001 — fail-closed
            signals = None
        stall = evaluate_stall(
            session_id, wid, clock, stall_seconds=stall_seconds,
            read_fn=lambda _s, _w, _sig=signals: _sig,
        )
        alive = signals.alive if signals is not None else None
        responded = signals is not None and signals.alive is False
        assessments.append(WorkerAssessment(wid, stall.status, responded, alive, stall.reason))

    decision = decide_pass(session_id, assessments, frozen_n=fz, already_killed=killed_set)

    # Perform the side effects the pure decision authorized.
    newly_killed: list[str] = []
    for act in decision.actions:
        if act.action == "kill":
            ok = False
            try:
                ok = bool(terminate_fn(session_id, act.worker_id))
            except Exception:  # noqa: BLE001
                ok = False
            newly_killed.append(act.worker_id)
            _append_event(session_id, "team_policy_kill", {
                "worker_id": act.worker_id, "terminated": ok, "reason": act.reason,
                "frozen_n": fz, "threshold": decision.threshold,
            })
        elif act.action == "escalate":
            _append_event(session_id, "team_policy_escalate", {
                "worker_id": act.worker_id, "reason": act.reason,
                "frozen_n": fz, "threshold": decision.threshold,
            })

    if newly_killed:
        state["killed"] = sorted(killed_set | set(newly_killed))
        _save_state(session_id, state)

    _append_event(session_id, "team_policy_pass", {
        "exit": decision.exit_code, "summary": decision.summary,
        "killed": newly_killed, "escalated": decision.exit_code == EXIT_ESCALATE,
        "frozen_n": fz, "threshold": decision.threshold,
        "responded": decision.responded_count, "stalled": decision.stalled_count,
        "unknown": decision.unknown_count,
    })

    result = {
        "exit": decision.exit_code,
        "killed": newly_killed,
        "escalated": decision.exit_code == EXIT_ESCALATE,
        "skipped_for_safety": decision.exit_code == EXIT_SKIPPED,
        "frozen_n": fz,
        "threshold": decision.threshold,
        "responded": decision.responded_count,
        "stalled": decision.stalled_count,
        "unknown": decision.unknown_count,
        "workers": len(assessments),
        "actions": [{"worker_id": a.worker_id, "action": a.action} for a in decision.actions],
        "summary": decision.summary,
        "error": None,
    }
    return result, decision.exit_code


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cli.team_policy_check",
        description="Deterministic team stall-detect + quorum-guarded kill pass (M28).",
    )
    p.add_argument("--session-id", required=True)
    p.add_argument("--team-dir", required=True,
                   help="Directory containing worker-<i>.out / .heartbeat.jsonl artifacts.")
    p.add_argument("--stall-seconds", type=float, default=180.0)
    p.add_argument("--frozen-n", type=int, default=None,
                   help="Override the frozen quorum denominator (else persisted/derived).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)  # argparse owns exit 2 (usage) ONLY
    try:
        result, code = run(
            args.session_id, args.team_dir,
            stall_seconds=args.stall_seconds, frozen_n=args.frozen_n,
        )
    except Exception as exc:  # noqa: BLE001 — fail-CLOSED: any internal error -> skipped(4)
        result = {"exit": EXIT_SKIPPED, "killed": [], "escalated": False,
                  "skipped_for_safety": True,
                  "error": f"{type(exc).__name__}: {exc}"}
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        sys.stderr.write(f"[team_policy_check] FAIL-CLOSED: {result['error']}\n")
        return EXIT_SKIPPED

    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    if code == EXIT_ESCALATE:
        sys.stderr.write(f"[team_policy_check] ESCALATE-HALT: {result['summary']}\n")
    return code


# Keep EXIT_ERROR referenced (argparse maps usage→2 itself; this documents the slot).
_ = EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
