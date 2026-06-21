"""autopilot_pane_events — per-pane lifecycle event emission for Phase 1.

Per debate-1778302432-1ce6ea (4-gen converged 2026-05-09) D6:

Pane subprocesses MUST write to ``sid_dir / "panes" / f"{pane_id}.jsonl"``
(per-pane shard) — NEVER to the canonical ``sid_dir / "events.jsonl"``.
This avoids Windows concurrent-append corruption: ``lib/logging.py``
``jsonl_append`` uses a plain ``open("a")`` with no msvcrt/fcntl lock,
so N panes + the orchestrator process appending concurrently to the same
file would interleave partial JSON lines and break the replay loop in
``engine.orchestrator.list_sessions`` and ``current_iteration``.

team_mailbox uses per-worker outbox files for the same reason; this
module mirrors that pattern.

Serial aggregation of per-pane shards into the canonical events.jsonl is
intentionally OUT OF SCOPE here — it lives in the orchestrator process
which can serialize writes (no concurrent contention).

Invocation contract: when imported from a pane subprocess, callers MUST
invoke as ``python -m lib.autopilot_pane_events`` (matches the
``team_runtime`` pattern at ``lib/team_runtime.py`` for
``lib.team_worker_loop``). Direct script execution
(``python lib/autopilot_pane_events.py``) is NOT supported because the
absolute import below requires ``scripts/`` to be on ``sys.path``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from lib.logging import jsonl_append


def _pane_jsonl(sid_dir: Path, pane_id: str) -> Path:
    if not pane_id or "/" in pane_id or "\\" in pane_id or ".." in pane_id:
        raise ValueError(f"invalid pane_id: {pane_id!r}")
    return sid_dir / "panes" / f"{pane_id}.jsonl"


def emit_pane_started(
    sid_dir: Path,
    pane_id: str,
    **fields: Any,
) -> None:
    record = {"type": "pane_started", "pane_id": pane_id, **fields}
    jsonl_append(_pane_jsonl(sid_dir, pane_id), record)


def emit_pane_status(
    sid_dir: Path,
    pane_id: str,
    *,
    status: str,
    exit_code: int | None = None,
    **fields: Any,
) -> None:
    record = {
        "type": "pane_status",
        "pane_id": pane_id,
        "status": status,
        "exit_code": exit_code,
        **fields,
    }
    jsonl_append(_pane_jsonl(sid_dir, pane_id), record)


def read_pane_events(sid_dir: Path, pane_id: str) -> list[dict[str, Any]]:
    import json

    path = _pane_jsonl(sid_dir, pane_id)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def list_pane_ids(sid_dir: Path) -> list[str]:
    panes_dir = sid_dir / "panes"
    if not panes_dir.is_dir():
        return []
    return sorted(p.stem for p in panes_dir.glob("*.jsonl"))
