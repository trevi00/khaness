"""path_denylist — Windows-safe path canonicalization + self-modification guard.

Per debate-1778230575-aebdd3 D4 (locked: denylist=path_normcase_denylist).

Canonicalization pipeline (CLAUDE.md env: Windows 11 native, not WSL):
  1. os.path.realpath  — resolve symlinks/junctions
  2. GetLongPathNameW  — defeat 8.3 short-name bypass (Windows-only, stdlib ctypes)
  3. os.path.normcase  — case-fold

Fail-closed semantics (per Architect addendum 3): on GetLongPathNameW failure
(ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND, or non-zero GetLastError), treat
the path as DENIED — DO NOT silently degrade to short-form match. This avoids
TOCTOU between resolution and check.

Reserved denylist (DENY_PREFIXES) — paths the writeback subsystem must NEVER
modify, including itself:
  - ~/.claude/skills/_meta/         (skill-meta directory)
  - ~/.claude/agents/harness-       (any harness-* agent definition)
  - ~/.claude/scripts/lib/writeback_*  (this subsystem)
  - ~/.claude/scripts/handlers/prompt/debate_trigger.py  (advisory channel host)
  - ~/.claude/CLAUDE.md             (top-level operating doc)

Public surface:
  - canonicalize(path: str) -> str | None
  - is_denied(path: str) -> bool
  - DENY_PREFIXES: tuple[str, ...]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


# Reserved prefixes (canonicalize-then-startswith). Each entry is itself
# canonicalized at module load to ensure comparison consistency.
_RAW_DENY_PREFIXES: tuple[str, ...] = (
    str(Path.home() / ".claude" / "skills" / "_meta"),
    str(Path.home() / ".claude" / "agents" / "harness-"),
    str(Path.home() / ".claude" / "scripts" / "lib" / "writeback_"),
    str(Path.home() / ".claude" / "scripts" / "lib" / "path_denylist.py"),
    str(Path.home() / ".claude" / "scripts" / "handlers" / "prompt" / "debate_trigger.py"),
    str(Path.home() / ".claude" / "CLAUDE.md"),
)


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _windows_long_path(p: str) -> str | None:
    """Resolve 8.3 short names to long form via GetLongPathNameW.

    Returns the long form on success, None on any failure. Caller must
    treat None as denied (fail-closed per addendum 3).
    """
    if not _is_windows():
        return p  # POSIX has no 8.3 alias; skip
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        GetLongPathNameW = kernel32.GetLongPathNameW
        GetLongPathNameW.argtypes = [
            wintypes.LPCWSTR,  # short path
            wintypes.LPWSTR,   # buffer
            wintypes.DWORD,    # buffer length
        ]
        GetLongPathNameW.restype = wintypes.DWORD

        buffer_size = wintypes.DWORD(260 * 4)  # 4 * MAX_PATH (defensive)
        buf = ctypes.create_unicode_buffer(buffer_size.value)
        result = GetLongPathNameW(p, buf, buffer_size)
        if result == 0:
            # GetLastError != 0 — fail-closed
            return None
        if result > buffer_size.value:
            # Buffer too small; retry with returned size
            buf = ctypes.create_unicode_buffer(result + 1)
            result2 = GetLongPathNameW(p, buf, result + 1)
            if result2 == 0:
                return None
        return buf.value
    except Exception:
        # ctypes import / windll missing / unexpected error → fail-closed
        return None


def canonicalize(path: str) -> str | None:
    """Return the canonical form of `path` for denylist comparison.

    Pipeline:
      1. expanduser + expandvars
      2. realpath (resolves symlinks/junctions; idempotent on POSIX)
      3. If path EXISTS on Windows: GetLongPathNameW (defeats 8.3 short-name
         bypass). If the resolution fails despite the file existing, return
         None (fail-closed per addendum 3).
      4. If path does NOT exist: skip GetLongPathNameW — 8.3 aliases only
         apply to extant filesystem entries. Use normcase(realpath) directly
         for prefix-comparison purposes. This prevents the denylist from
         spuriously denying every not-yet-created legitimate target.
      5. normcase the result for case-insensitive comparison.

    Returns None ONLY when canonicalization is structurally impossible
    (empty input, OSError on realpath, or extant-file 8.3 resolution
    failed). Callers should treat None as DENIED (fail-closed).
    """
    if not isinstance(path, str) or not path:
        return None
    try:
        expanded = os.path.expandvars(os.path.expanduser(path))
        real = os.path.realpath(expanded)
    except (OSError, ValueError):
        return None

    if _is_windows() and os.path.exists(real):
        long_form = _windows_long_path(real)
        if long_form is None:
            # File exists but GetLongPathNameW couldn't resolve it →
            # genuine error; fail-closed.
            return None
        return os.path.normcase(long_form)

    # Path doesn't exist (or POSIX): no 8.3 alias possible; normcase(realpath)
    # is the canonical form.
    return os.path.normcase(real)


# Pre-canonicalize the deny prefixes at module load. If any prefix fails
# canonicalization (e.g., the file doesn't exist yet), keep its raw normcase
# form as a best-effort match — but the caller still fail-closes on its own
# canonicalize() returning None.
def _build_canonical_prefixes() -> tuple[str, ...]:
    out: list[str] = []
    for raw in _RAW_DENY_PREFIXES:
        c = canonicalize(raw)
        if c is not None:
            out.append(c)
        else:
            # File may not exist yet (e.g., writeback_*.py not yet created).
            # Use normcase of the expanded form so future check still matches.
            try:
                expanded = os.path.expanduser(raw)
                out.append(os.path.normcase(os.path.normpath(expanded)))
            except Exception:
                continue
    return tuple(out)


DENY_PREFIXES: tuple[str, ...] = _build_canonical_prefixes()


def is_denied(path: str) -> bool:
    """True if `path` resolves under any DENY_PREFIXES entry.

    Fail-closed: canonicalize() returning None → True (denied). Empty/None
    input → True. This biases toward over-denial, which is the correct
    side for a self-modification guard.
    """
    canonical = canonicalize(path)
    if canonical is None:
        return True
    for prefix in DENY_PREFIXES:
        if canonical.startswith(prefix):
            return True
    return False
