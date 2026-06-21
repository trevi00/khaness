"""autopilot_worktree_probe — OneDrive detection for autopilot Phase 1.

Per debate-1778302432-1ce6ea (4-gen converged 2026-05-09) D1:

  is_onedrive_path(repo_root: Path) -> tuple[bool, str | None]

Returns ``(ok, reason)`` where ``ok=True`` means "safe to proceed"
(no OneDrive risk for this run) and ``ok=False`` means "OneDrive detected
— caller should HALT autopilot Phase 1 parallel branching" (auto-fallback
policy is Phase-2 D5, intentionally NOT here — caller in orchestrator/CLI
decides abort).

Detection signals (Critic counter-proposal at gen-3, byte-locked gen-4):

  1. ``AUTOPILOT_SKIP_ONEDRIVE_PROBE=1`` env escape hatch — returns
     ``(True, "skipped_via_env")`` short-circuit. Required because D5
     (override mechanism) is DEFERRED_TO_PHASE2.
  2. Case-insensitive substring ``\\\\onedrive\\\\`` match against
     ``str(Path(repo_root).resolve())`` — PRIMARY signal. Survives
     detached-pane env loss (psmux workers spawned with ``detached=True``
     do not always inherit the launching shell's OneDrive vars) and
     IO_REPARSE_TAG_CLOUD junction unwrap (resolve() does not unwind
     cloud-files placeholders).
  3. ``OneDrive``/``OneDriveCommercial``/``OneDriveConsumer`` env-var
     check — SECONDARY signal. See MS Learn KFM contract:
     https://learn.microsoft.com/en-us/onedrive/redirect-known-folders
  4. Windows guard — ``platform.system() == "Windows"``. Non-Windows
     returns ``(True, "non_windows")`` (no OneDrive concept on POSIX).

The function NEVER raises SystemExit (lib layer discipline — only
top-level CLIs may sys.exit). Caller composes with autopilot Phase 1
entry to emit a ``worktree_probe_failed`` event and abort gracefully.
"""
from __future__ import annotations

import os
import platform
from pathlib import Path

_SKIP_ENV = "AUTOPILOT_SKIP_ONEDRIVE_PROBE"
_ONEDRIVE_VARS = ("OneDrive", "OneDriveCommercial", "OneDriveConsumer")
_PATH_PREFIX = "onedrive"


def _path_has_onedrive_segment(resolved: str) -> bool:
    """Check whether any path segment starts with ``onedrive`` (case-insensitive).

    Captures the spec's ``\\onedrive\\`` substring AND real-world variants like
    ``OneDrive - Personal``, ``OneDrive - <Org>``, ``OneDrive Backup`` —
    Microsoft's default folder names for KFM/business accounts.
    """
    norm = resolved.replace("/", "\\").lower()
    return any(seg.startswith(_PATH_PREFIX) for seg in norm.split("\\") if seg)


def is_onedrive_path(repo_root: Path) -> tuple[bool, str | None]:
    if os.environ.get(_SKIP_ENV) == "1":
        return (True, "skipped_via_env")
    if platform.system() != "Windows":
        return (True, "non_windows")

    try:
        resolved = str(Path(repo_root).resolve())
    except (OSError, ValueError):
        resolved = str(repo_root)

    if _path_has_onedrive_segment(resolved):
        return (False, "onedrive_path_match")

    for var in _ONEDRIVE_VARS:
        od = os.environ.get(var)
        if not od:
            continue
        try:
            od_resolved = Path(od).resolve()
            if Path(resolved).is_relative_to(od_resolved):
                return (False, f"onedrive_env_match:{var}")
        except (OSError, ValueError):
            continue

    return (True, None)
