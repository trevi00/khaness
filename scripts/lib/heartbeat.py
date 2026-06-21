"""heartbeat — long-running agent liveness signal (v15.22 K / v15.9 P1).

Temporal-style heartbeat pattern. agent가 주기적으로 emit하면 orchestrator가
session 활성 여부를 점검. 누락 (stale) → operator visibility.

Storage: state/heartbeats/<sid>.json
  {"last_ts": <iso8601>, "agent_type": <str>, "count": <int>}

Public API:
- DEFAULT_STALE_SEC: int (300 = 5분)
- emit(sid, agent_type, *, base_dir) → updates file
- last_seen(sid, *, base_dir) → ts | None
- stale(sid, *, max_age_sec, base_dir) → bool
- list_active(max_age_sec, *, base_dir) → list[(sid, agent_type, last_ts)]
- prune(*, older_than_sec, base_dir) → count

본 lib는 inspection helper만 제공. emit 자동화는 follow-up cycle (agent
spawn loop가 주기적으로 호출 — handler 또는 background thread).
"""
from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path
from typing import Iterator

from .atomic_json import read_json, write_json_atomic
from .paths import STATE_DIR


DEFAULT_STALE_SEC: int = 300  # 5분


def _heartbeat_dir(base_dir: Path | None = None) -> Path:
    return (base_dir or STATE_DIR) / "heartbeats"


def _heartbeat_path(sid: str, *, base_dir: Path | None = None) -> Path:
    if not sid:
        raise ValueError("sid must be non-empty")
    safe = "".join(c for c in sid if c.isalnum() or c in "._-")
    if not safe:
        raise ValueError(f"sid contains no safe chars: {sid!r}")
    return _heartbeat_dir(base_dir) / f"{safe}.json"


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _now_epoch() -> float:
    """Indirection for test monkey-patch."""
    return _dt.datetime.now(_dt.timezone.utc).timestamp()


def emit(sid: str, agent_type: str, *, base_dir: Path | None = None) -> dict:
    """Update heartbeat for (sid, agent_type). count++."""
    if not agent_type:
        raise ValueError("agent_type must be non-empty")
    path = _heartbeat_path(sid, base_dir=base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    current = read_json(path, default={"count": 0})
    if not isinstance(current, dict):
        current = {"count": 0}
    current["last_ts"] = _now_iso()
    current["agent_type"] = agent_type
    current["count"] = int(current.get("count", 0) or 0) + 1
    write_json_atomic(path, current)
    return current


def last_seen(sid: str, *, base_dir: Path | None = None) -> str | None:
    """Return last_ts string, or None if no heartbeat recorded."""
    path = _heartbeat_path(sid, base_dir=base_dir)
    rec = read_json(path, default={})
    if not isinstance(rec, dict):
        return None
    ts = rec.get("last_ts")
    return ts if isinstance(ts, str) and ts else None


def _ts_to_epoch(ts: str) -> float | None:
    """ISO8601 → epoch float; None on parse failure."""
    try:
        # support trailing 'Z' (UTC) and offset
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return _dt.datetime.fromisoformat(ts).timestamp()
    except (ValueError, TypeError):
        return None


def stale(
    sid: str,
    *,
    max_age_sec: int = DEFAULT_STALE_SEC,
    base_dir: Path | None = None,
) -> bool:
    """True iff no heartbeat OR last heartbeat older than max_age_sec.

    No record → True (stale by default — caller must initialize).
    """
    ts = last_seen(sid, base_dir=base_dir)
    if ts is None:
        return True
    epoch = _ts_to_epoch(ts)
    if epoch is None:
        return True
    age = _now_epoch() - epoch
    return age > max_age_sec


def list_active(
    *,
    max_age_sec: int = DEFAULT_STALE_SEC,
    base_dir: Path | None = None,
) -> list[tuple[str, str, str]]:
    """Yield (sid, agent_type, last_ts) for all non-stale heartbeats."""
    base = _heartbeat_dir(base_dir)
    if not base.exists():
        return []
    out: list[tuple[str, str, str]] = []
    now_e = _now_epoch()
    for p in sorted(base.glob("*.json")):
        rec = read_json(p, default={})
        if not isinstance(rec, dict):
            continue
        ts = rec.get("last_ts")
        if not isinstance(ts, str):
            continue
        epoch = _ts_to_epoch(ts)
        if epoch is None:
            continue
        if now_e - epoch <= max_age_sec:
            out.append((p.stem, str(rec.get("agent_type", "")), ts))
    return out


def prune(
    *,
    older_than_sec: int = DEFAULT_STALE_SEC * 24,  # 5분 * 24 = 2시간
    base_dir: Path | None = None,
) -> int:
    """Remove heartbeats older than threshold. Returns count removed."""
    base = _heartbeat_dir(base_dir)
    if not base.exists():
        return 0
    now_e = _now_epoch()
    removed = 0
    for p in list(base.glob("*.json")):
        rec = read_json(p, default={})
        if not isinstance(rec, dict):
            continue
        ts = rec.get("last_ts")
        if not isinstance(ts, str):
            continue
        epoch = _ts_to_epoch(ts)
        if epoch is None:
            continue
        if now_e - epoch > older_than_sec:
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    return removed


__all__ = [
    "DEFAULT_STALE_SEC",
    "emit",
    "last_seen",
    "list_active",
    "prune",
    "stale",
]
