"""team_worker_loop — minimal stay-alive worker for team-mode IPC.

Runs as a subprocess (typically inside a psmux pane via lib.team_runtime)
that polls its inbox via lib.team_mailbox.tail_since_cursor and emits
results to its outbox. Closes vision item #7 (team mode 살아있는 상태로
유지 + JSON 메시지 + 병렬 역할 분담) by giving each worker a real
fork+exec entry point with a deterministic IPC loop.

Usage:
    python -m lib.team_worker_loop <team_sid> <worker_id> [--deadline N] [--poll-interval N]

Environment:
    ORCH_SID can substitute for the positional team_sid arg (matches the
    existing run-worker.sh contract documented in commands/harness-team.md).

Message protocol (from lib.team_mailbox.VALID_TYPES):
    inbox:
        type='task'  → process payload, write 'answer' to outbox
        type='query' → process payload, write 'answer' to outbox
        type='done'  → exit cleanly with rc=0
        type='error' → exit with rc=2 (orchestrator-injected fault)
    outbox:
        type='answer' → echo of received task with worker tag

The worker is intentionally MINIMAL — it does NOT spawn LLM provider
processes here. Real worker types (claude/codex/gemini) extend this
loop in their own modules; this module is the contract reference +
integration-test target.

Termination:
    - stdin EOF / SIGTERM / SIGINT → graceful exit
    - 'done' message in inbox → graceful exit
    - deadline expired → exit with rc=1
    - 'error' message → exit with rc=2
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.team_mailbox import (  # noqa: E402
    envelope,
    send_to_outbox,
    tail_since_cursor,
)


DEFAULT_DEADLINE_SECONDS: float = 60.0
DEFAULT_POLL_INTERVAL: float = 0.2


def _process_task(team_sid: str, worker_id: str, msg: dict) -> None:
    """Default task handler — echo to outbox.

    Real workers override this by importing the loop and supplying their
    own dispatch table. For test/integration use, echo is sufficient.
    """
    payload = msg.get("payload", {})
    answer = envelope(
        sender=worker_id,
        recipient="orch",
        msg_type="answer",
        payload={"echo": payload, "worker_id": worker_id},
    )
    send_to_outbox(team_sid, worker_id, answer)


def worker_main(
    team_sid: str,
    worker_id: str,
    *,
    deadline: float = DEFAULT_DEADLINE_SECONDS,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
) -> int:
    """Run the worker loop. Returns an exit code (0=done, 1=deadline, 2=error).

    Loop:
      1. Tail inbox for new messages.
      2. For each message:
         - 'done'  → return 0
         - 'error' → return 2
         - 'task' / 'query' → call _process_task, continue loop
         - other  → log + skip
      3. Sleep poll_interval. If deadline exceeded → return 1.

    The function is interruptible by KeyboardInterrupt (rc=130 via SIGINT).
    """
    if not team_sid or not worker_id:
        return 2

    started = time.monotonic()

    try:
        while time.monotonic() - started < deadline:
            saw_terminal = False
            for msg in tail_since_cursor(team_sid, worker_id, side="inbox"):
                msg_type = msg.get("type", "")
                if msg_type == "done":
                    return 0
                if msg_type == "error":
                    return 2
                if msg_type in ("task", "query"):
                    try:
                        _process_task(team_sid, worker_id, msg)
                    except Exception as e:
                        # Per hook discipline: never crash on malformed payload;
                        # surface the error to the outbox and continue.
                        send_to_outbox(team_sid, worker_id, envelope(
                            sender=worker_id,
                            recipient="orch",
                            msg_type="error",
                            payload={"reason": str(e)[:200]},
                        ))
                # other types ignored (e.g., 'answer' arriving in inbox)
                _ = saw_terminal  # reserved for future batch-terminate logic
            time.sleep(poll_interval)
        return 1  # deadline elapsed without 'done'
    except KeyboardInterrupt:
        return 130


def _parse_argv(argv: list[str] | None = None) -> tuple[str, str, float, float]:
    parser = argparse.ArgumentParser(prog="team_worker_loop")
    parser.add_argument("team_sid", nargs="?", default=os.environ.get("ORCH_SID", ""))
    parser.add_argument("worker_id")
    parser.add_argument("--deadline", type=float, default=DEFAULT_DEADLINE_SECONDS)
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL)
    args = parser.parse_args(argv)
    return args.team_sid, args.worker_id, args.deadline, args.poll_interval


def main(argv: list[str] | None = None) -> int:
    team_sid, worker_id, deadline, poll = _parse_argv(argv)
    if not team_sid:
        print(
            "team_sid required as positional arg or ORCH_SID env",
            file=sys.stderr,
        )
        return 2
    return worker_main(team_sid, worker_id, deadline=deadline, poll_interval=poll)


if __name__ == "__main__":
    sys.exit(main())
