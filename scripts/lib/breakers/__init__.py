"""breakers — circuit-breaker primitives (v15.10 D3).

Per debate-1778946602-jj7vxk D3, the breaker unit is a `(agent_type,
failure_mode)` composite key, deliberately more sensitive than Hystrix
(3/10 vs 50% rate) and dual-calibrated with a single-probe close in
half-open. Storage is project-scoped JSON per key under
`state/breakers/<project_id>/<agent_type>__<failure_mode>.json`.

Public surface (lock):
  - State (Enum): CLOSED, OPEN, HALF_OPEN
  - BreakerSnapshot (dataclass): inspection of one record without mutation
  - CompositeBreaker (class): record_failure / record_success / try_acquire

The breaker emits `team.escalation`-style events via a caller-supplied
emit_fn (default = no-op) to preserve the runtime_policy_gate invariant:
open-state action is OPERATOR VISIBILITY, never automatic substitution
of another agent.
"""
from __future__ import annotations

from .composite import (
    BreakerSnapshot,
    CompositeBreaker,
    State,
)

__all__ = ["BreakerSnapshot", "CompositeBreaker", "State"]
