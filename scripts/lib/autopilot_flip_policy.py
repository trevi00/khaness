"""autopilot_flip_policy — single-function indirection for AUTOPILOT_PARALLEL default.

Per debate-1778307906-23b7b3 D5 (gen 1 fast-path approved, 2026-05-09):
Flip = NEVER (permanent opt-in) for Phase 2.

Future flip MUST go through a NEW harness-debate citing debate-
1778307906-23b7b3 D5 as the deferral anchor. Do NOT edit
``current_default()`` to return 1 as a one-liner PR — the indirection
exists precisely so a future debate replaces ONE function rather than
sweeping every call site.

The companion telemetry counter (``log_parallel_run_outcome``) is
write-only OBSERVABILITY — no caller reads it for policy decisions.
A future flip debate can consult the counter as evidence, but cannot
reference it as an automatic trigger without a new design pass.

Resolution order at runtime (caller side, autopilot.md):

  1. ``AUTOPILOT_PARALLEL=1`` env override → parallel
  2. ``AUTOPILOT_PARALLEL=0`` env override → sequential
  3. Otherwise → ``current_default()``
"""
from __future__ import annotations

from typing import Any

from lib.logging import log_telemetry

_TELEMETRY_CATEGORY = "autopilot-parallel-runs"


def current_default() -> int:
    """Return the AUTOPILOT_PARALLEL default when env is unset.

    Locked to 0 (sequential) per debate-1778307906-23b7b3 D5. Future
    flips require a new debate; do NOT change this return value
    without one.
    """
    return 0


def log_parallel_run_outcome(
    *,
    sid: str,
    status: str,
    merge_conflicts: int = 0,
    pane_failures: int = 0,
    **extra: Any,
) -> None:
    """Write-only observability counter. NOT a flip trigger.

    Called from autopilot Phase 5 completion path when a run with
    ``AUTOPILOT_PARALLEL=1`` reaches a terminal state. Output goes to
    ``state/telemetry/<category>.jsonl`` via lib.logging.log_telemetry.
    """
    if not isinstance(sid, str) or not sid:
        raise ValueError("sid must be non-empty str")
    if not isinstance(status, str) or not status:
        raise ValueError("status must be non-empty str")
    record: dict[str, Any] = {
        "sid": sid,
        "status": status,
        "merge_conflicts": int(merge_conflicts),
        "pane_failures": int(pane_failures),
    }
    record.update(extra)
    log_telemetry(_TELEMETRY_CATEGORY, record)
