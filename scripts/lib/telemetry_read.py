"""Read-side helpers for ~/.claude/telemetry/<name>.jsonl files.

Counterpart to lib/logging.py (write-side: log_telemetry, jsonl_append). Kept
in a separate module so lib/logging.py preserves its append-only contract.

Used by handlers/session/init.py advisory and engine/trigger_summary.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from .paths import TELEMETRY_DIR


def iter_events(name: str) -> Iterator[dict]:
    """Yield decoded JSON records from telemetry/<name>.jsonl. Skip malformed lines.

    Returns empty iterator if the file is missing or unreadable. Never raises.
    """
    path: Path = TELEMETRY_DIR / f"{name}.jsonl"
    if not path.is_file():
        return
    try:
        with path.open(encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def count_unreviewed_triggers() -> int:
    """Count strict_design=True debate triggers minus user-acknowledged ones.

    Acknowledgements live in the strict_design AdvisoryAck store (Wave 19);
    without this filter the advisory grew monotonically and clean-state
    was unreachable.
    """
    from .advisory_ack import REGISTRY
    ack = REGISTRY["strict_design"].load()
    return sum(
        1 for r in iter_events("debate-triggers")
        if r.get("strict_design") is True and r.get("ts") not in ack
    )
