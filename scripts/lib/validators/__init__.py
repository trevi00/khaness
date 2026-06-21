"""lib.validators — orchestrator-side deterministic envelope validators (v15.10 D2).

Distinct from `scripts.validators` (project-tree CLI validators producing
PASS/FAIL/WARN lines). Modules here take a subagent output envelope plus
its spawn spec and return a typed `ValidationResult` for the orchestrator
to consume programmatically.

Per debate-1778946602-jj7vxk D2, validators in this package may ONLY
inspect deterministic ground truth (filesystem stat, structural schema
shape, declared tool allowlist). They MUST NOT call any LLM, embedder,
or semantic similarity engine — that work belongs to the Critic under
the configure-critic-policy gate.
"""
from __future__ import annotations

from .structural import (
    StructuralFailureMode,
    ValidationResult,
    validate,
)
from .semantic import (
    EvidenceBreakdown,
    SemanticResult,
    SemanticVerdict,
    check as semantic_check,
)
from .cross_ref import (
    CrossRefResult,
    CrossRefVerdict,
    check_cross_file_consensus,
    check_summary_vs_prompt,
)
from .boilerplate import (
    BoilerplateEntry,
    BoilerplateResult,
    BoilerplateVerdict,
    check as boilerplate_check,
)

__all__ = [
    "BoilerplateEntry",
    "BoilerplateResult",
    "BoilerplateVerdict",
    "CrossRefResult",
    "CrossRefVerdict",
    "EvidenceBreakdown",
    "SemanticResult",
    "SemanticVerdict",
    "StructuralFailureMode",
    "ValidationResult",
    "boilerplate_check",
    "check_cross_file_consensus",
    "check_summary_vs_prompt",
    "semantic_check",
    "validate",
]
