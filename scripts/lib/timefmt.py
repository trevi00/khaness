"""timefmt — canonical best-effort ISO-8601 -> epoch parser.

Extracted 2026-06-21 (harness-full-review rank 4) from three byte-divergent
`_iso_to_epoch` copies in cli/observe.py, cli/action_evolver.py,
cli/sensor_anomaly.py. The copies had DIFFERENT format lists — observe.py
lacked the `%z` (timezone-offset) shapes, so it silently returned None on the
`+00:00` timestamps the harness itself emits (lib/heartbeat, operator_ledger,
rlm_codex), falling back to file mtime and discarding the writer's explicit ts.

This canonical parser is the UNION of all three lists (every T-separated and
space-separated shape, with/without fractional seconds, with/without tz offset),
so each caller is a strict superset of its former behavior — no format regresses
and observe.py gains the missing `%z` shapes.

Semantics preserved verbatim from the originals:
  - non-str / empty -> None
  - leading/trailing 'Z' stripped (rstrip('Z')) before parsing
  - NAIVE datetimes use .timestamp() (local-tz assumption) exactly as before;
    tz-aware (`%z`) shapes yield the absolute epoch
  - any unparseable shape -> None (never raises)
"""
from __future__ import annotations

from datetime import datetime

# Most-specific first; strptime is strict so a tz-aware fmt fails fast on a
# naive string and falls through. Union of observe/action_evolver/sensor_anomaly.
_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f%z",
    "%Y-%m-%d %H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
)


def iso_to_epoch(ts_str: str) -> float | None:
    """Best-effort ISO-8601 -> epoch float. None on parse failure (never raises)."""
    if not isinstance(ts_str, str) or not ts_str:
        return None
    s = ts_str.rstrip("Z")
    for fmt in _FORMATS:
        try:
            return datetime.strptime(s, fmt).timestamp()
        except ValueError:
            continue
    return None
