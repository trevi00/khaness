"""Team-mode JSON message bus (Phase 3 of autonomous orchestrator MVP).

Per debate-1778161608-713bdc gen 4 (snapshot 7add26467f703f7b119c1903ff0dcfca5b227a65):
  - F8 team_mailbox_format = jsonl_per_worker

Layout under STATE_DIR/team/<sid>/mailbox/:
  worker-<i>.inbox.jsonl   — orchestrator -> worker (queue of tasks/queries)
  worker-<i>.outbox.jsonl  — worker -> orchestrator (queue of done/answer/error)

Message envelope schema:
  {ts, from, to, type, payload}
  type ∈ {"task", "query", "answer", "done", "error"}

Both files are append-only JSONL. Tail-since-cursor read pattern lets a
worker poll its inbox without re-scanning. Atomic-append via lib/logging
guarantees a crash mid-write does not leave a half-line.

Phase 3 module — Phase 1+2 MVP does not call this yet. Lives here so the
team-mode work can land without touching engine/ layer adjacency rules
(this is pure utility, lib-shaped).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterator

from lib.atomic_json import write_json_atomic
from lib.logging import jsonl_append, now_iso
from lib.paths import ensure_dir


VALID_TYPES: frozenset[str] = frozenset({"task", "query", "answer", "done", "error"})


def _safe_seg(name: str) -> str:
    """Neutralize path separators / parent refs in an sid or worker_id so a
    crafted token cannot escape STATE_DIR/team/ when interpolated into a path.
    Defense-in-depth (mirrors lib.operator_ledger._safe_segment): these ids are
    harness-generated tokens today (`worker-0`, session ids), so this is a no-op
    for every legitimate value — it just removes the latent traversal.
    deep-audit pass-2 completeness: team_mailbox unsanitized path interpolation."""
    s = str(name).replace("/", "_").replace("\\", "_")
    return "_" if s in ("", ".", "..") else s


def _mailbox_dir(sid: str) -> Path:
    # Lazy import: honors test fixtures that redirect lib.paths.STATE_DIR
    # after this module loads (same pattern as lib/strike_dispatcher.py).
    from lib.paths import STATE_DIR
    return ensure_dir(STATE_DIR / "team" / _safe_seg(sid) / "mailbox")


def inbox_path(sid: str, worker_id: str) -> Path:
    return _mailbox_dir(sid) / f"{_safe_seg(worker_id)}.inbox.jsonl"


def outbox_path(sid: str, worker_id: str) -> Path:
    return _mailbox_dir(sid) / f"{_safe_seg(worker_id)}.outbox.jsonl"


def cursor_path(sid: str, worker_id: str, *, side: str) -> Path:
    """Per-(sid, worker_id, side) cursor file. `side` = 'inbox' or 'outbox'."""
    if side not in ("inbox", "outbox"):
        raise ValueError(f"side must be 'inbox' or 'outbox', got {side!r}")
    return _mailbox_dir(sid) / f"{_safe_seg(worker_id)}.{side}.cursor"


def envelope(*, sender: str, recipient: str, msg_type: str, payload: dict) -> dict:
    """Build a message envelope. Validates msg_type up-front."""
    if msg_type not in VALID_TYPES:
        raise ValueError(
            f"msg_type must be one of {sorted(VALID_TYPES)}, got {msg_type!r}"
        )
    return {
        "ts": now_iso(),
        "from": sender,
        "to": recipient,
        "type": msg_type,
        "payload": dict(payload),
    }


def send_to_inbox(sid: str, worker_id: str, env: dict) -> None:
    """Append a message envelope to a worker's inbox (orchestrator -> worker)."""
    if env.get("type") not in VALID_TYPES:
        raise ValueError(f"envelope missing/invalid type: {env.get('type')!r}")
    jsonl_append(inbox_path(sid, worker_id), env)


def send_to_outbox(sid: str, worker_id: str, env: dict) -> None:
    """Append a message envelope to a worker's outbox (worker -> orchestrator)."""
    if env.get("type") not in VALID_TYPES:
        raise ValueError(f"envelope missing/invalid type: {env.get('type')!r}")
    jsonl_append(outbox_path(sid, worker_id), env)


def _read_cursor(path: Path) -> int:
    """Parse {"position": N} cursor file (matches _write_cursor schema)."""
    if not path.exists():
        return 0
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return 0
        data = json.loads(text)
        if isinstance(data, dict):
            return int(data.get("position", 0))
        return 0
    except (ValueError, OSError, json.JSONDecodeError):
        return 0


def _write_cursor(path: Path, position: int) -> None:
    write_json_atomic(str(path), {"position": position})


def tail_since_cursor(
    sid: str,
    worker_id: str,
    *,
    side: str,
    advance_cursor: bool = True,
) -> Iterator[dict]:
    """Yield envelopes appended since the last cursor read.

    On crash mid-tail (advance_cursor=True), the cursor reflects the last
    position written — at-least-once delivery semantics. Caller must
    handle idempotent message processing.
    """
    if side == "inbox":
        log_path = inbox_path(sid, worker_id)
    elif side == "outbox":
        log_path = outbox_path(sid, worker_id)
    else:
        raise ValueError(f"side must be 'inbox' or 'outbox', got {side!r}")

    cur_path = cursor_path(sid, worker_id, side=side)
    cursor = _read_cursor(cur_path)

    if not log_path.exists():
        return

    new_cursor = cursor
    try:
        with log_path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i < cursor:
                    continue
                line = line.strip()
                if not line:
                    new_cursor = i + 1
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    # Skip malformed lines (defensive; jsonl_append is atomic
                    # so this should be rare). Cursor still advances past it
                    # to avoid re-yielding noise.
                    pass
                new_cursor = i + 1
    finally:
        if advance_cursor:
            _write_cursor(cur_path, new_cursor)


def read_all_messages(sid: str, worker_id: str, *, side: str) -> list[dict]:
    """Read every message in a worker's mailbox without advancing cursor.
    Useful for orchestrator-side audit / team_watch TUI rendering.
    """
    if side == "inbox":
        log_path = inbox_path(sid, worker_id)
    elif side == "outbox":
        log_path = outbox_path(sid, worker_id)
    else:
        raise ValueError(f"side must be 'inbox' or 'outbox', got {side!r}")

    if not log_path.exists():
        return []

    out: list[dict] = []
    try:
        with log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return out
    return out


def mailbox_depth(sid: str, worker_id: str, *, side: str) -> int:
    """Count messages in a mailbox (does not advance cursor)."""
    return len(read_all_messages(sid, worker_id, side=side))


# Quiet unused-import lint — `time` reserved for future heartbeat helpers.
_ = time


# ---------- CLI entry (invoked by run-worker.sh inbox poll loop) ----------
# Usage:
#   python -m lib.team_mailbox tail <sid> <worker_id> <inbox|outbox>
#   python -m lib.team_mailbox send <sid> <worker_id> <inbox|outbox> <type> <json_payload>
#
# `tail`: prints new envelopes (one JSON per line) since last cursor read,
# advances cursor. Used by run-worker.sh inbox poll loop.
# `send`: appends a single envelope to inbox or outbox. Used by workers
# emitting query/answer/done/error to orchestrator.

def _cli(argv: list[str]) -> int:
    import sys
    if not argv:
        print("usage: tail <sid> <worker_id> <inbox|outbox>", file=sys.stderr)
        print("       send <sid> <worker_id> <inbox|outbox> <type> <json_payload>",
              file=sys.stderr)
        return 2

    cmd = argv[0]
    if cmd == "tail" and len(argv) == 4:
        _, sid, worker_id, side = argv
        for env in tail_since_cursor(sid, worker_id, side=side):
            print(json.dumps(env, ensure_ascii=False))
        return 0
    if cmd == "send" and len(argv) == 6:
        _, sid, worker_id, side, msg_type, payload_json = argv
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError:
            print(f"invalid json payload: {payload_json[:80]}", file=sys.stderr)
            return 2
        # Worker writes to its OWN outbox (or orchestrator writes to a
        # worker's inbox). We do not infer sender — caller must set
        # accurate from/to in payload, or use the helpers below.
        env = {
            "ts": now_iso(),
            "from": payload.get("from", worker_id if side == "outbox" else "orch"),
            "to": payload.get("to", "orch" if side == "outbox" else worker_id),
            "type": msg_type,
            "payload": payload,
        }
        if msg_type not in VALID_TYPES:
            print(f"invalid type: {msg_type}", file=sys.stderr)
            return 2
        if side == "inbox":
            send_to_inbox(sid, worker_id, env)
        elif side == "outbox":
            send_to_outbox(sid, worker_id, env)
        else:
            print(f"side must be inbox or outbox, got {side}", file=sys.stderr)
            return 2
        return 0
    print(f"unknown command or arg count: {' '.join(argv)}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))
