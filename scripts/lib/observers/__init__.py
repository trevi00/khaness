"""observers — orchestrator-side deterministic failure-mode detectors (v15.10 D1).

Per debate-1778946602-jj7vxk D1, failure_mode_taxonomy is observer-split:

  Orchestrator-observed (deterministic, no LLM) — implemented here:
    - schema_violation       (lib.validators.structural handles output_schema)
    - tool_misuse            (lib.validators.structural handles tool_allowlist)
    - evidence_fabrication   (this package — lib.observers.evidence_fab)
    - timeout_or_crash       (handled at spawn boundary, not here)

  Critic-observed (LLM-graded) — NOT in this package, lives under the
  configure-critic-policy gate:
    - hallucination_suspected
    - off_task_drift
    - capability_mismatch

The split is load-bearing for the judge_generator_separation invariant:
orchestrator code in this package must never grade semantics — only
inspect deterministic ground truth (os.stat, subprocess returncode).
"""
from __future__ import annotations

from .evidence_fab import EvidenceVerdict, detect

__all__ = ["EvidenceVerdict", "detect"]
