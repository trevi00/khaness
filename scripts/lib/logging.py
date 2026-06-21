"""Structured JSONL logger for hooks and engine.

Append-only JSONL records. Used by telemetry and event_store.
Also exposes the `@timed` decorator for hook latency observability.
"""
from __future__ import annotations

import functools
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

from .paths import TELEMETRY_DIR, TELEMETRY_ROTATE_BYTES, ensure_dir

F = TypeVar("F", bound=Callable[..., Any])


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def jsonl_append(path: Path, record: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    stamped = {"ts": now_iso(), **record}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(stamped, ensure_ascii=False) + "\n")


def log_telemetry(category: str, record: dict[str, Any]) -> None:
    """Append a telemetry record to TELEMETRY_DIR/<category>.jsonl.

    After append, if file size >= TELEMETRY_ROTATE_BYTES, rotate to .1
    (best-effort; Windows lock errors fall through via log_stderr).

    Fail-open contract (B fix, fixplan-meta debate Gen3+): all I/O exceptions
    are caught and routed through log_stderr; this function NEVER raises and
    always returns None. Stdout is left untouched so test runners (run_all.py
    D5 regex) cannot misread telemetry failure as test failure.
    """
    try:
        ensure_dir(TELEMETRY_DIR)
        path = TELEMETRY_DIR / f"{category}.jsonl"
        jsonl_append(path, record)
        _rotate_if_needed(path)
    except Exception as e:
        log_stderr(f"[log_telemetry] {category} append failed: {type(e).__name__}: {e}")


def _rotate_if_needed(path: Path) -> None:
    """Rotate <path> -> <path>.1 if size exceeds threshold. Non-fatal on failure.

    D4 implementation_minor: Windows PermissionError (concurrent file lock) is
    caught and reported via log_stderr; rotation is retried on next call.
    """
    try:
        if path.stat().st_size < TELEMETRY_ROTATE_BYTES:
            return
    except OSError:
        return  # stat failed — file gone or unreadable, skip silently
    rotated = path.with_suffix(path.suffix + ".1")
    try:
        if rotated.exists():
            rotated.unlink()
        path.rename(rotated)
    except (PermissionError, OSError) as e:
        log_stderr(f"[rotate_telemetry] {path.name} rotation failed: {type(e).__name__}: {e}")


def log_stderr(msg: str) -> None:
    try:
        print(msg, file=sys.stderr)
    except Exception:
        pass


def timed(name: str) -> Callable[[F], F]:
    """Decorator: measure function duration and log to telemetry/hook-latency.jsonl.

    Telemetry write failures are caught and reported via log_stderr; the wrapped
    function's return value/exception is always propagated unchanged. This
    preserves hook reliability over telemetry completeness.

    Usage:
        @timed("pre_tool.guard")
        def main(): ...
    """
    def deco(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            t0 = time.perf_counter()
            status = "ok"
            error_type: str | None = None
            try:
                return fn(*args, **kwargs)
            except BaseException as exc:
                status = "error"
                error_type = type(exc).__name__
                raise
            finally:
                duration_ms = (time.perf_counter() - t0) * 1000.0
                record: dict[str, Any] = {
                    "name": name,
                    "duration_ms": round(duration_ms, 3),
                    "status": status,
                }
                if error_type is not None:
                    record["error_type"] = error_type
                try:
                    log_telemetry("hook-latency", record)
                except Exception as e:
                    log_stderr(f"[timed] telemetry append failed for {name!r}: {e}")
        return wrapper  # type: ignore[return-value]
    return deco
