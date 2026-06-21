"""Replay constants (v15.10 D1 implementation note 4).

REPLAY_BACKOFF_SEC: seconds to sleep between the two replay attempts in the
N=2 arm of `lib.observers.evidence_fab.detect`. Extracted to a named constant
so calibration cycles can tune it without grepping inline literals.

Default 5s — matches debate-1778946602-jj7vxk D1 spec verbatim. Tests
monkey-patch this to 0 to keep the suite fast; production callers should
not import it as a mutable knob (re-bind only at process start, never
inside a hot loop).
"""
from __future__ import annotations

# Default backoff between consecutive replay attempts (D1 arm b).
# Test suites override via `lib.replay.constants.REPLAY_BACKOFF_SEC = 0`
# at module-set time; do NOT mutate from inside detect() itself.
REPLAY_BACKOFF_SEC: float = 5.0
