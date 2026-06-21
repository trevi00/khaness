"""replay — subagent envelope replay primitives (v15.10 D1).

Shared constants and helpers used by `lib.observers.evidence_fab` and any
later consumer that needs to re-run a claimed test_result to detect
fabrication.

Kept as a standalone subpackage (rather than a single constants module on
lib/) so future arms (replay runners, sandbox harnesses) compose under one
namespace without forcing existing call sites to chase moves.
"""
from __future__ import annotations

from .constants import REPLAY_BACKOFF_SEC

__all__ = ["REPLAY_BACKOFF_SEC"]
