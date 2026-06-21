"""atomic_json — safe JSON read + atomic JSON write.

Two siblings of `lib/logging.jsonl_append`:
- `read_json(path, default)`: try/except wrapper with type-checked fallback.
- `write_json_atomic(path, data)`: temp-file + os.replace, race-safe.

Replaces duplicated patterns in `lib/repeat_error_tracker._load/_save` and
`lib/ratio_tracker.load_counts/save_counts`. The `os.replace` step is atomic
on POSIX and Windows when source/dest live on the same filesystem (always
true here since the temp file is a sibling of the destination).

Concurrency note: multiple hooks fire on the same turn (UserPromptSubmit +
PostToolUse + Stop) so non-atomic `open("w")` could leave a partial file
visible to the next reader. Atomic rename is the cheapest fix that works on
Windows without needing a lock file.

This module is intentionally tiny and dependency-free so any handler/lib
can import without circular-import risk.
"""
from __future__ import annotations

import json
import os
from typing import Any


def read_json(path: str | os.PathLike, default: Any = None) -> Any:
    """Read JSON from `path`. On any failure (missing, malformed, IOError)
    return `default`. Caller decides the empty-state shape.

    Type-safety: if the parsed value's type does not match `default`'s type
    (when default is dict or list), `default` is returned. This guards against
    a corrupted file holding e.g. a string where a dict was expected.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return default
    if default is not None and not isinstance(data, type(default)):
        return default
    return data


def write_json_atomic(
    path: str | os.PathLike,
    data: Any,
    *,
    ensure_ascii: bool = False,
) -> bool:
    """Write `data` to `path` via temp-file + os.replace.

    Returns True on success, False on any failure. Failures are silent (caller
    decides whether to warn) — this matches the existing repeat_error_tracker
    behavior where atomic-write was best-effort.

    The temp file is `<path>.<pid>.<rand>.tmp` so neither concurrent processes
    NOR same-process concurrent writers (threads) clobber each other's tmp file
    — PID alone is insufficient for in-process concurrency (deep-audit pass-2
    rank 7). On failure the tmp file is unlinked best-effort.
    """
    path_str = os.fspath(path)
    tmp_path = f"{path_str}.{os.getpid()}.{os.urandom(4).hex()}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=ensure_ascii)
            # fsync before replace so a crash mid-swap leaves either the old file
            # or the fully-flushed new one — atomic-on-content alone is not
            # crash-DURABLE (deep-audit pass-2 rank 6; sibling writeback_store
            # already fsyncs). Fail-soft: a platform without fsync must not break.
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_path, path_str)
        return True
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return False
