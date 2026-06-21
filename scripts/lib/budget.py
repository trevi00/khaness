"""budget — per-session approximate token budget (v15.20 B / v15.9 P0 #1).

v15.9 P0 #1 — Anthropic "15x token multiplier" 위험. agent dispatch가 폭주
하면 한 session에서 수 백K~수 백만 token 소비. 운영자가 사전 경고를 받도록
char-based budget tracker.

정직한 한계:
- Claude API의 정확한 token count는 LLM provider에서 제공 (Agent tool은
  response text만 제공). char-based 추정.
- 추정: roughly chars / 4 (English-heavy), chars / 1.5 (CJK-heavy).
  본 lib는 raw chars만 누적, 추정 비율은 caller가 결정.
- advisory only (block 안 함, breaker trip 안 함). exceed → telemetry warning
  + event_emit. 운영자가 budget cap 직접 결정.

Storage:
- state/budgets/<sid>.json: {"total_chars": int, "invocation_count": int, "last_ts": iso8601}
- sid = ORCH_SID env 또는 caller가 명시.

Public API:
- DEFAULT_SESSION_CHAR_BUDGET: int (default 2_000_000 ≈ 500K tokens English)
- record_invocation(sid, response_text, *, base_dir)
- get_total_chars(sid, *, base_dir) -> int
- exceeded(sid, *, cap, base_dir) -> bool
- reset(sid, *, base_dir)
"""
from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path

from .atomic_json import read_json, write_json_atomic
from .paths import STATE_DIR


DEFAULT_SESSION_CHAR_BUDGET: int = 2_000_000  # ≈ 500K English tokens / 1.3M CJK


def _budget_dir(base_dir: Path | None = None) -> Path:
    return (base_dir or STATE_DIR) / "budgets"


def _budget_path(sid: str, *, base_dir: Path | None = None) -> Path:
    if not sid:
        raise ValueError("sid must be non-empty")
    # path-traversal guard: charset (mirror subagent_invocation_log 패턴)
    safe = "".join(c for c in sid if c.isalnum() or c in "._-")
    if not safe:
        raise ValueError(f"sid contains no safe chars: {sid!r}")
    return _budget_dir(base_dir) / f"{safe}.json"


def record_invocation(
    sid: str,
    response_text: str,
    *,
    base_dir: Path | None = None,
) -> dict:
    """누적 char count + invocation count. response_text가 None/non-str면 0으로 처리."""
    if not isinstance(response_text, str):
        response_text = ""
    chars = len(response_text)
    path = _budget_path(sid, base_dir=base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    current = read_json(path, default={"total_chars": 0, "invocation_count": 0})
    if not isinstance(current, dict):
        current = {"total_chars": 0, "invocation_count": 0}
    current["total_chars"] = int(current.get("total_chars", 0) or 0) + chars
    current["invocation_count"] = int(current.get("invocation_count", 0) or 0) + 1
    current["last_ts"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    write_json_atomic(path, current)
    return current


def get_total_chars(sid: str, *, base_dir: Path | None = None) -> int:
    """현재 누적 chars. 없으면 0."""
    path = _budget_path(sid, base_dir=base_dir)
    rec = read_json(path, default={})
    if not isinstance(rec, dict):
        return 0
    return int(rec.get("total_chars", 0) or 0)


def get_invocation_count(sid: str, *, base_dir: Path | None = None) -> int:
    """현재 누적 invocation count."""
    path = _budget_path(sid, base_dir=base_dir)
    rec = read_json(path, default={})
    if not isinstance(rec, dict):
        return 0
    return int(rec.get("invocation_count", 0) or 0)


def exceeded(
    sid: str,
    *,
    cap: int = DEFAULT_SESSION_CHAR_BUDGET,
    base_dir: Path | None = None,
) -> bool:
    """누적 chars가 cap 초과 여부."""
    return get_total_chars(sid, base_dir=base_dir) >= cap


def reset(sid: str, *, base_dir: Path | None = None) -> None:
    """budget tracker 초기화 (운영자 명시 reset 용도)."""
    path = _budget_path(sid, base_dir=base_dir)
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass


def check_and_emit_exceeded(
    sid: str,
    *,
    emit_fn,
    cap: int = DEFAULT_SESSION_CHAR_BUDGET,
    base_dir: Path | None = None,
) -> bool:
    """v15.24 — exceeded 시 'budget.exceeded' event emit. once-per-cap-crossing.

    record file에 `exceeded_emitted` flag로 once 보장 (cap 한 번 crossing 시
    한 번만 emit, 그 후 reset 또는 cap 상향 전까지 silent).

    Returns True iff emit이 발생.
    """
    path = _budget_path(sid, base_dir=base_dir)
    rec = read_json(path, default={})
    if not isinstance(rec, dict):
        return False
    total = int(rec.get("total_chars", 0) or 0)
    if total < cap:
        # 아직 미달 — 만약 이전에 emitted=True였다면 reset (cap 상향 또는 reset 후 재누적)
        if rec.get("exceeded_emitted"):
            rec["exceeded_emitted"] = False
            write_json_atomic(path, rec)
        return False
    if rec.get("exceeded_emitted"):
        return False  # already emitted for this crossing
    try:
        emit_fn("budget.exceeded", {
            "session_id": sid,
            "total_chars": total,
            "cap": cap,
            "invocation_count": int(rec.get("invocation_count", 0) or 0),
        })
    except Exception:
        pass
    rec["exceeded_emitted"] = True
    write_json_atomic(path, rec)
    return True


__all__ = [
    "DEFAULT_SESSION_CHAR_BUDGET",
    "check_and_emit_exceeded",
    "exceeded",
    "get_invocation_count",
    "get_total_chars",
    "record_invocation",
    "reset",
]
