"""subagent_invocation_log — append-only audit trail for subagent dispatches.

Closes the platform-level OS-isolation residual surfaced at debate-1778302432-
1ce6ea: claude-code's Agent tool has no OS-enforced subagent isolation, so the
harness's defense relies on detection rather than prevention. Five layers
(LEAK_PATTERN_REGEX / tools allowlist / <forbidden> rules / env sanitization /
codex sandbox) cover ingress and egress, but operators had no way to query
"who invoked harness-critic in the last 24h, with what tools claimed?" — that
audit trail surface was missing.

This module provides the audit log:

- ``record_invocation(sid, agent_name, tools, ...)`` writes one JSONL record
  to ``state/subagent_invocations/<sid>.jsonl`` per dispatch.
- ``list_invocations(sid)`` replays one session.
- ``list_sessions()`` returns every recorded sid (sorted) — operator
  forensics primitive ("how many sessions did we run last week?").
- ``search_by_agent(agent_name, since_ts=..., until_ts=...)`` greps across
  all sessions — enables retrospective forensics ("did anyone call
  harness-evaluator with fewer tools than declared?").

The append is best-effort fail-soft (jsonl_append handles I/O errors). This
log is purely observability — no policy enforcement here. Pair with
``agent_tool_audit.classify_severity`` for verdict-time decisions.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from lib.logging import jsonl_append, now_iso
from lib.paths import STATE_DIR, ensure_dir

_INVOCATIONS_SUBDIR = "subagent_invocations"

# sid format guard — must match the harness convention to prevent path
# traversal and reject obviously malformed inputs. Mirrors the validation
# pattern used by agent_tool_audit._agent_file.
_VALID_SID_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# Origin enum (E8 closure 2026-05-10). The string literal was scattered
# across hook + commands directives; centralizing here prevents typos
# (e.g., "directve" / "hookk") from silently splitting the audit trail.
ORIGIN_HOOK = "hook"
ORIGIN_DIRECTIVE = "directive"
ORIGIN_MANUAL = "manual"
ORIGIN_VALUES = frozenset({ORIGIN_HOOK, ORIGIN_DIRECTIVE, ORIGIN_MANUAL})


def _invocations_dir() -> Path:
    return STATE_DIR / _INVOCATIONS_SUBDIR


def _validate_sid(sid: str) -> None:
    if not sid or not _VALID_SID_RE.match(sid):
        raise ValueError(f"invalid sid: {sid!r}")


def _validate_agent_name(name: str) -> None:
    if not name:
        raise ValueError("agent_name must be non-empty")
    if "/" in name or "\\" in name or ".." in name:
        raise ValueError(f"invalid agent_name: {name!r}")


def session_log_path(sid: str) -> Path:
    """Return the JSONL path for ``sid``; raises ValueError on bad input."""
    _validate_sid(sid)
    return _invocations_dir() / f"{sid}.jsonl"


def record_invocation(
    sid: str,
    agent_name: str,
    tools: Iterable[str] | None,
    *,
    generation: int | None = None,
    role: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Append one invocation record to the session's JSONL audit log.

    Required: ``sid`` (caller-minted session id), ``agent_name`` (e.g.
    ``"harness-critic"``), ``tools`` (the tools the caller passed/claimed
    when dispatching the agent — record-as-claimed, not authoritative).

    ``tools`` accepts ``None`` (E12 closure 2026-05-10) for the
    PostToolUse hook path where ``expected_tools()`` returned an empty
    set — the hook treats both empty-set and missing-frontmatter as
    semantically identical (no tools claimed). ``None`` is normalized
    to ``[]`` before write.

    Optional: ``generation`` (debate gen number), ``role`` (planner/critic/
    architect/evaluator/researcher/...), ``extra`` (free-form payload).
    When ``extra`` carries an ``origin`` field it MUST be one of the
    ``ORIGIN_*`` constants — otherwise ``ValueError``.

    Returns the path written. Caller should treat the write as fire-and-
    forget — jsonl_append's I/O errors propagate; the caller decides
    whether to log_stderr.
    """
    _validate_sid(sid)
    _validate_agent_name(agent_name)
    if tools is None:
        tools_iter: Iterable[str] = ()
    else:
        tools_iter = tools
    tools_list = sorted({t.strip() for t in tools_iter if t and t.strip()})
    record: dict[str, Any] = {
        "sid": sid,
        "agent": agent_name,
        "tools": tools_list,
    }
    if generation is not None:
        record["generation"] = int(generation)
    if role:
        record["role"] = role
    if extra:
        if "origin" in extra and extra["origin"] not in ORIGIN_VALUES:
            raise ValueError(
                f"invalid origin: {extra['origin']!r} "
                f"(must be one of {sorted(ORIGIN_VALUES)})"
            )
        record["extra"] = extra
    path = session_log_path(sid)
    ensure_dir(path.parent)
    jsonl_append(path, record)
    return path


def list_sessions() -> list[str]:
    """Return every sid that has at least one recorded invocation, sorted.

    Operator forensics primitive — pair with ``list_invocations(sid)`` for
    per-session replay or ``search_by_agent`` for cross-session grep. The
    return is the file-stem list under ``state/subagent_invocations/``;
    sids whose JSONL file was unlinked by GC are omitted by construction.

    Empty list when the dir does not exist (clean install / pre-first-
    invocation). Never raises.
    """
    root = _invocations_dir()
    if not root.exists():
        return []
    return sorted(p.stem for p in root.glob("*.jsonl"))


def list_invocations(sid: str) -> list[dict[str, Any]]:
    """Replay one session's invocation log; corrupt lines are skipped."""
    path = session_log_path(sid)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def search_by_agent(
    agent_name: str,
    *,
    since_ts: str | None = None,
    until_ts: str | None = None,
    origin: str | None = None,
) -> list[dict[str, Any]]:
    """Find every invocation of ``agent_name`` across all sessions.

    ``since_ts`` and ``until_ts`` are ISO8601 timestamps (e.g.
    ``"2026-05-10T00:00:00Z"``) defining a half-open time window. A record
    is included when ``since_ts <= ts < until_ts``. Either bound may be
    ``None`` (no lower / upper limit). Comparison is lexicographic on the
    canonical "Z" UTC format produced by ``now_iso()``; do not pass
    timezone-offset strings.

    If both bounds are provided and ``since_ts >= until_ts``, no record
    can satisfy the window — returns an empty list (defensive; mirrors
    SQL ``BETWEEN`` with empty range).

    ``origin`` (E5 closure 2026-05-10) filters by ``extra.origin`` —
    typically one of ``ORIGIN_HOOK`` / ``ORIGIN_DIRECTIVE`` /
    ``ORIGIN_MANUAL``. Records lacking an ``extra.origin`` field never
    match a non-None filter (defensive — caller must opt in to seeing
    untagged legacy records by passing ``origin=None``).

    Returns records in (sid, line-order) sequence; sids themselves are
    sorted alphabetically for determinism.
    """
    _validate_agent_name(agent_name)
    if since_ts is not None and until_ts is not None and since_ts >= until_ts:
        return []
    if origin is not None and origin not in ORIGIN_VALUES:
        raise ValueError(
            f"invalid origin filter: {origin!r} "
            f"(must be one of {sorted(ORIGIN_VALUES)})"
        )
    root = _invocations_dir()
    if not root.exists():
        return []
    out: list[dict[str, Any]] = []
    for jsonl in sorted(root.glob("*.jsonl")):
        try:
            text = jsonl.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            if rec.get("agent") != agent_name:
                continue
            rec_ts = rec.get("ts", "")
            if since_ts is not None and rec_ts < since_ts:
                continue
            if until_ts is not None and rec_ts >= until_ts:
                continue
            if origin is not None:
                rec_origin = (rec.get("extra") or {}).get("origin")
                if rec_origin != origin:
                    continue
            out.append(rec)
    return out


def sids_in_window(
    *,
    since_ts: str | None = None,
    until_ts: str | None = None,
) -> list[str]:
    """Return sids that have at least one invocation within the window.

    E6 closure 2026-05-10. Complements ``list_sessions()`` (every recorded
    sid regardless of when) with a time-bounded variant for retention
    surveys ("which sessions had activity last week?"). Uses the same
    lexicographic ``ts`` comparison as ``search_by_agent``.

    Empty list when dir missing OR when no record falls in the window
    (degenerate empty-window case is also handled — when both bounds
    given AND ``since_ts >= until_ts``, returns empty without scanning).
    """
    if since_ts is not None and until_ts is not None and since_ts >= until_ts:
        return []
    root = _invocations_dir()
    if not root.exists():
        return []
    out: set[str] = set()
    for jsonl in sorted(root.glob("*.jsonl")):
        try:
            text = jsonl.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            rec_ts = rec.get("ts", "")
            if since_ts is not None and rec_ts < since_ts:
                continue
            if until_ts is not None and rec_ts >= until_ts:
                continue
            sid = rec.get("sid")
            if isinstance(sid, str) and sid:
                out.add(sid)
                break  # one match per file is enough; advance to next jsonl
        # If we broke out of the inner loop, sid is recorded; otherwise
        # this jsonl had no in-window records.
    return sorted(out)


def gc_old_logs(now: float | None = None, retention_days: int = 30) -> int:
    """Reclaim stale per-session JSONL logs whose mtime is older than retention.

    Mirrors ``lib.writeback_store.gc_old_sidecars`` for the same operational
    reason: ``state/subagent_invocations/<sid>.jsonl`` is append-only per
    session, and a long-running harness installation accumulates one file per
    debate / autopilot / team session. Without GC the directory grows
    unbounded. Forensics window is bounded by ``retention_days``; older files
    are reclaimed once a session is well past the actionable window.

    Returns the count of files unlinked. ``retention_days<=0`` returns 0 with
    no scan (defensive). Individual ``unlink`` failures are skipped (fail-soft
    matches the rest of this module).
    """
    if retention_days <= 0:
        return 0
    import time
    root = _invocations_dir()
    if not root.exists():
        return 0
    cutoff = (now if now is not None else time.time()) - retention_days * 86400
    removed = 0
    for jsonl in root.glob("*.jsonl"):
        try:
            mtime = jsonl.stat().st_mtime
        except OSError:
            continue
        if mtime >= cutoff:
            continue
        try:
            jsonl.unlink()
            removed += 1
        except OSError:
            continue
    return removed
