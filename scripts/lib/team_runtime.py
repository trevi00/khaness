"""team_runtime — psmux + team_mailbox composition for live worker IPC.

Closes vision item #7 (team mode 살아있는 상태로 유지 + JSON 메시지 +
병렬 역할 분담) by binding lib.psmux session lifecycle to lib.team_mailbox
inbox/outbox file IPC. Workers run as detached psmux sessions invoking
`python -m lib.team_worker_loop <team_sid> <worker_id>`; orchestrator
sends tasks via mailbox, captures responses via outbox tail.

Convention:
    psmux session name = `team-<team_sid>-<worker_id>`

This wrapper does NOT prescribe a worker implementation — `team_worker_loop`
is the minimal contract reference. Real workers (claude/codex/gemini)
provide their own subagent_type but reuse this lifecycle.

Tool dependencies (fail-soft if missing):
    - lib.psmux (which() resolves psmux/pmux/tmux binary)
    - lib.team_mailbox (writes inbox/outbox jsonl files)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import psmux


def session_name_for(team_sid: str, worker_id: str) -> str:
    """Conventional psmux session name for a worker pane."""
    return f"team-{team_sid}-{worker_id}"


def spawn_worker(
    team_sid: str,
    worker_id: str,
    *,
    deadline: float | None = None,
    poll_interval: float | None = None,
    python_exe: str | None = None,
) -> str | None:
    """Spawn a detached psmux session running team_worker_loop for this worker.

    Returns the psmux session name on success, None on any failure (binary
    missing, session already exists, spawn failed). Caller can later kill
    via `terminate_worker(team_sid, worker_id)`.

    Uses psmux.new_session(command_argv=...) path to pass argv literally —
    avoids whitespace re-splitting that breaks Windows paths like
    "C:\\Program Files\\Python\\python.exe".
    """
    if not team_sid or not worker_id:
        return None
    if psmux.which() is None:
        return None

    name = session_name_for(team_sid, worker_id)
    if psmux.has_session(name):
        return None  # caller handles already-running case

    py = python_exe or sys.executable
    scripts_dir = Path(__file__).resolve().parent.parent

    # argv passed verbatim — no shell splitting, no quote interpretation
    cmd_argv = [py, "-m", "lib.team_worker_loop", team_sid, worker_id]
    if deadline is not None:
        cmd_argv.extend(["--deadline", str(deadline)])
    if poll_interval is not None:
        cmd_argv.extend(["--poll-interval", str(poll_interval)])

    ok = psmux.new_session(
        name,
        detached=True,
        command_argv=cmd_argv,
        start_dir=str(scripts_dir),
    )
    if not ok:
        return None
    return name


def terminate_worker(team_sid: str, worker_id: str) -> bool:
    """Kill the psmux session for this worker. Returns True if killed,
    False if session was already absent or kill failed."""
    if not team_sid or not worker_id:
        return False
    name = session_name_for(team_sid, worker_id)
    return psmux.kill_session(name)


def is_worker_alive(team_sid: str, worker_id: str) -> bool:
    """True if the worker's psmux session exists (i.e., subprocess running)."""
    if not team_sid or not worker_id:
        return False
    return psmux.has_session(session_name_for(team_sid, worker_id))


def list_team_workers(team_sid: str) -> list[str]:
    """Return the worker_id list for sessions matching `team-<sid>-*`."""
    if not team_sid:
        return []
    prefix = f"team-{team_sid}-"
    out: list[str] = []
    for s in psmux.list_sessions():
        if s.startswith(prefix):
            out.append(s[len(prefix):])
    return out


def capture_worker_pane(team_sid: str, worker_id: str, *, max_lines: int = 200) -> str | None:
    """Capture stdout from the worker's psmux session for inspection."""
    if not is_worker_alive(team_sid, worker_id):
        return None
    return psmux.capture_pane(
        session_name_for(team_sid, worker_id),
        max_lines=max_lines,
    )


# Quiet unused-import lint
_ = os
