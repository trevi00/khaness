"""axis_scores_log — D6 per-axis variance event log per debate-1778248254-0b7092.

Append-only JSONL at state/evaluator/<sid>/axis_scores.jsonl. Mirrors the
event-sourcing pattern used by orchestrator events.jsonl + writeback
applied.jsonl: O_APPEND single-write per line, fsync, schema_version
REQUIRED on every event.

Per debate D6 condition C6:
  - schema_version field on every event line (REQUIRED — missing → ValueError)
  - 30-day cleanup convention WIRED INTO existing retention sweep,
    NOT a separate cron. This module exposes `gc_old_axis_scores()`
    that the SessionStart hook (handlers/session/init.py) calls
    alongside cleanup_terminal_sessions + gc_old_sidecars.

Public surface:
  - SCHEMA_VERSION (current = '1')
  - DEFAULT_RETENTION_DAYS (= 30)
  - log_dir(sid) -> Path
  - log_axis_event(sid, event) -> bool
  - read_axis_events(sid) -> list[dict]
  - has_cross_target_marker(sid) -> bool
  - log_verdict_event(sid, event, *, cross_target=True) -> bool
  - gc_old_axis_scores(now=None, retention_days=30) -> int

## Cross-target metric write side (2026-06-18)

`operational_metrics.get_dge_e2_cross_target_count` counts axis records
carrying ``cross_target_first_invocation=True`` — but neither
``/harness-evaluate`` step 6 nor autopilot Phase 4 ever emitted that
marker, so the metric's READ side existed while its WRITE side was
absent (the metric was unreachable through normal operation). The
``log_verdict_event`` helper below closes that seam: a genuine LLM E2
verdict on a NON-evaluator (generator) artifact is marked exactly once
per sid (idempotent — re-evaluations within ``PER_PHASE_EVAL_LIMIT``,
clamp events, and fallback events never re-count). The marker semantic
is the load-bearing self-validation-paradox avoidance from
debate-1778248254-0b7092: it records that the evaluator was applied to
something OTHER than itself.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


SCHEMA_VERSION: str = "1"
DEFAULT_RETENTION_DAYS: int = 30

# PIPE_BUF cap reused (same convention as writeback_store)
_PIPE_BUF_CAP_BYTES: int = 4096


def log_dir(sid: str) -> Path:
    """Lazy STATE_DIR resolution (test-fixture-compatible).

    state/evaluator/<sid>/ — one dir per super-session.
    """
    if not isinstance(sid, str) or not sid:
        raise ValueError(f"sid must be non-empty str, got {sid!r}")
    from .paths import STATE_DIR
    d = STATE_DIR / "evaluator" / sid
    d.mkdir(parents=True, exist_ok=True)
    return d


def _axis_scores_path(sid: str) -> Path:
    return log_dir(sid) / "axis_scores.jsonl"


def log_axis_event(sid: str, event: dict) -> bool:
    """Append `event` to state/evaluator/<sid>/axis_scores.jsonl.

    Mutates `event` to inject schema_version='1' if absent. Returns
    True on success, False on I/O failure or oversize line.

    Raises ValueError if `event` is not a dict or sid is empty.
    """
    if not isinstance(event, dict):
        raise ValueError(f"event must be dict, got {type(event).__name__}")

    payload = dict(event)
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("ts", time.time())

    line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    encoded = line.encode("utf-8")

    if len(encoded) > _PIPE_BUF_CAP_BYTES:
        # Mirror writeback_store oversize policy: reject (no silent truncation)
        return False

    path = _axis_scores_path(sid)
    fd = None
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        os.write(fd, encoded)
        try:
            os.fsync(fd)
        except OSError:
            pass
        return True
    except OSError:
        return False
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def read_axis_events(sid: str) -> list[dict]:
    """Read all events. Skips malformed lines. Lines missing
    schema_version are skipped + logged (W19.1.2 D6 condition).
    """
    if not isinstance(sid, str) or not sid:
        return []
    path = _axis_scores_path(sid)
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            # schema_version is REQUIRED — caller can't trust event without it
            if "schema_version" not in rec:
                continue
            out.append(rec)
    except OSError:
        return []
    return out


def has_cross_target_marker(sid: str) -> bool:
    """True iff some prior axis event for `sid` already carries
    ``cross_target_first_invocation=True``.

    Used by `log_verdict_event` to mark exactly the FIRST cross-target
    verdict per sid — so `operational_metrics.get_dge_e2_cross_target_count`
    counts one genuine evaluation session, not every re-eval/clamp/fallback
    line. Fail-soft: a missing log reads as no marker (returns False).
    """
    for rec in read_axis_events(sid):
        if rec.get("cross_target_first_invocation") is True:
            return True
    return False


def log_verdict_event(sid: str, event: dict, *, cross_target: bool = True) -> bool:
    """Append a verdict event, setting the cross-target marker when due.

    Closes the previously-absent WRITE side of the ``dge_e2_cross_target``
    operational metric (read side = `get_dge_e2_cross_target_count`). The
    marker ``cross_target_first_invocation=True`` is added iff BOTH hold:

      - ``cross_target`` is True — the evaluator genuinely ran (an LLM
        verdict, NOT a legacy fallback) on a NON-evaluator generator
        artifact. Callers pass ``cross_target=(fallback_reason is None)``
        so a validators+units fallback never counts as a real E2.
      - this is the FIRST such record for ``sid`` (`has_cross_target_marker`
        is False) — re-evaluations within ``PER_PHASE_EVAL_LIMIT``, clamp
        events, and fallback events do not re-count.

    Pass ``cross_target=False`` whenever the evaluator is pointed at
    evaluator-family output (the self-validation paradox the metric
    explicitly excludes).

    Persistence delegates to `log_axis_event` (schema_version + ts
    auto-injected). Do NOT pass an explicit ``ts`` in ``event`` — the
    server stamp keeps the autopilot iteration-freshness floor (B4)
    trustworthy. Returns log_axis_event's bool; raises ValueError on a
    non-dict event or empty sid (same contract as log_axis_event).
    """
    if not isinstance(event, dict):
        raise ValueError(f"event must be dict, got {type(event).__name__}")
    payload = dict(event)
    if cross_target and not has_cross_target_marker(sid):
        payload["cross_target_first_invocation"] = True
    return log_axis_event(sid, payload)


def gc_old_axis_scores(now: float | None = None,
                       retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Delete state/evaluator/<sid>/ directories whose axis_scores.jsonl
    mtime is older than retention_days. Returns count of dirs removed.

    Same SessionStart-amortized pattern as cleanup_terminal_sessions /
    gc_old_sidecars. retention_days <= 0 → return 0.

    Fail-soft per-dir.
    """
    cur = time.time() if now is None else now
    if retention_days <= 0:
        return 0
    cutoff = cur - retention_days * 86400

    from .paths import STATE_DIR
    base = STATE_DIR / "evaluator"
    if not base.exists():
        return 0

    removed = 0
    for sid_dir in base.iterdir():
        if not sid_dir.is_dir():
            continue
        jsonl = sid_dir / "axis_scores.jsonl"
        if not jsonl.exists():
            # Empty session dir — leave alone (operator may still write)
            continue
        try:
            mtime = jsonl.stat().st_mtime
        except OSError:
            continue
        if mtime > cutoff:
            continue
        # Delete entire session dir (jsonl + any sidecars)
        try:
            for child in sid_dir.iterdir():
                try:
                    child.unlink()
                except OSError:
                    pass
            sid_dir.rmdir()
            removed += 1
        except OSError:
            pass
    return removed
