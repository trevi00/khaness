"""autopilot_pane_spawn — visibility-only pane wrapper for Phase 1 parallel.

Per debate-1778307906-23b7b3 D2 (gen 1 fast-path approved, 2026-05-09):

The pane is a VISUALIZATION MIRROR of a worker subprocess that the parent
claude-code Agent context already spawns. The pane MUST NOT spawn an LLM
provider (Task tool inheritance does not survive subprocess fork — verified
at lib.team_worker_loop:25-28 and corroborated by Anthropic sub-agents
docs). Pane runs ``tail -f <log_path>`` only — coreutils binary, no
Python, no Agent tool dispatch.

Layer discipline: this module imports only ``lib.psmux`` + stdlib. The
pane subprocess (``tail -f``) cannot import anything because it is a
shell binary.

Workflow (caller-side; lives in autopilot.md command body):

    log_path = sid_dir / "panes" / f"{decision_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.touch()
    session = spawn_visibility_pane(sid, decision_id, log_path, worktree_path)
    # Parent claude-code Agent context now spawns the worker subprocess
    # (e.g., subprocess.Popen with stdout/stderr tee'd to log_path).
    # Operator can run `python -m lib.autopilot_pane_spawn --tail <sid> <did>`
    # or peek programmatically via tail_pane_output().
    snapshot = tail_pane_output(sid, decision_id, max_lines=200)
"""
from __future__ import annotations

import time
from pathlib import Path

from lib import psmux


def session_name(sid: str, decision_id: str) -> str:
    if not sid or not decision_id:
        raise ValueError("sid and decision_id must be non-empty")
    if "/" in decision_id or "\\" in decision_id or ".." in decision_id:
        raise ValueError(f"invalid decision_id: {decision_id!r}")
    return f"auto-{sid}-{decision_id}"


def spawn_visibility_pane(
    sid: str,
    decision_id: str,
    log_path: Path,
    worktree_path: Path | None = None,
) -> str | None:
    """Create a detached psmux session that tails ``log_path``.

    Returns the session name on success, ``None`` if psmux is missing
    or session creation failed (caller should still run the worker
    subprocess; visibility is a nice-to-have, not load-bearing).
    """
    if not psmux.which():
        return None
    name = session_name(sid, decision_id)
    if psmux.has_session(name):
        return name
    started = psmux.new_session(
        name,
        detached=True,
        command_argv=["tail", "-f", str(log_path)],
        start_dir=str(worktree_path) if worktree_path else None,
    )
    return name if started else None


def tail_pane_output(
    sid: str,
    decision_id: str,
    *,
    max_lines: int = 200,
) -> str | None:
    """Read-only scrollback dump of the pane (capture-pane -p)."""
    name = session_name(sid, decision_id)
    if not psmux.has_session(name):
        return None
    return psmux.capture_pane(name, max_lines=max_lines)


def teardown_pane(sid: str, decision_id: str) -> bool:
    """Kill the visibility pane on Phase 1 exit. Idempotent."""
    name = session_name(sid, decision_id)
    if not psmux.has_session(name):
        return False
    return psmux.kill_session(name)


def wait_for_session(
    sid: str,
    decision_id: str,
    *,
    timeout_seconds: float = 15.0,
    poll_interval_seconds: float = 0.5,
) -> bool:
    """Block until ``has_session`` reports the pane present, or timeout.

    Closes the post-spawn race where psmux registration lags the
    ``new_session`` return on cold-start PowerShell (Windows). Callers
    that need to send_keys / capture_pane immediately after spawn should
    gate on this helper instead of hand-rolled polling — the polling
    boundary becomes a single tested function rather than per-caller
    timing tweaks. Returns True if the session appeared within the
    window, False otherwise.
    """
    if timeout_seconds <= 0 or poll_interval_seconds <= 0:
        raise ValueError("timeout and poll_interval must be > 0")
    name = session_name(sid, decision_id)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if psmux.has_session(name):
            return True
        time.sleep(poll_interval_seconds)
    return psmux.has_session(name)


def wait_for_capture_marker(
    sid: str,
    decision_id: str,
    marker: str,
    *,
    timeout_seconds: float = 8.0,
    poll_interval_seconds: float = 0.5,
    max_lines: int = 200,
) -> bool:
    """Block until ``marker`` appears in pane scrollback, or timeout.

    The capture_pane scrollback can lag the underlying ``tail -f`` write
    by hundreds of milliseconds on slow runners. This helper polls
    ``capture_pane`` until ``marker`` is observed in its output. Returns
    True if seen within the window, False otherwise (caller decides
    whether to fail-soft skip or escalate).

    ``marker`` MUST be non-empty — the empty string would match any
    non-None capture and short-circuit the wait.
    """
    if not marker:
        raise ValueError("marker must be non-empty")
    if timeout_seconds <= 0 or poll_interval_seconds <= 0:
        raise ValueError("timeout and poll_interval must be > 0")
    name = session_name(sid, decision_id)
    if not psmux.has_session(name):
        return False
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        snapshot = psmux.capture_pane(name, max_lines=max_lines)
        if snapshot and marker in snapshot:
            return True
        time.sleep(poll_interval_seconds)
    snapshot = psmux.capture_pane(name, max_lines=max_lines) or ""
    return marker in snapshot
