"""Engine registry — declarative metadata for debate/ralph and future engines.

Created in W14 (fixplan-meta debate Gen4 follow-through). Pre-emptive vs YAGNI:
- Trigger from `state/decisions/defer.md` M9 was "3rd engine variant lands".
- Currently 2 engines (debate, ralph). User explicitly requested completing
  every deferred item, so the registry is added now as a *documented hook
  point* rather than an active dispatch surface. inventory_scan and cli
  remain debate-specific; they consult this module only to enrich output.

Adding a new engine:
1. Implement under `engine/<name>.py` (or `engine/<name>/`).
2. Append a new `EngineMeta` to `ENGINE_REGISTRY` below — single source of truth.
3. inventory_scan automatically picks up its session directory in the report.

NO orchestration logic lives here — providers/workers/event_store own that.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .paths import STATE_DIR


@dataclass(frozen=True)
class EngineMeta:
    name: str           # registry key — kebab-case
    state_subdir: str   # path under STATE_DIR for session storage
    session_prefix: str # filename prefix for new sessions
    description: str    # one-line summary; surfaces in inventory output


ENGINE_REGISTRY: tuple[EngineMeta, ...] = (
    EngineMeta(
        name="debate",
        state_subdir="debates",
        session_prefix="debate-",
        description="Planner-Critic-Architect 3-agent design debate (4-gen hard cap)",
    ),
    EngineMeta(
        name="ralph",
        state_subdir="ralph",
        session_prefix="ralph-",
        description="Verify/fix persistence loop — validators → executor on FAIL → re-validate",
    ),
)


def list_engines() -> tuple[EngineMeta, ...]:
    """Return all registered engine metadata. Pure read."""
    return ENGINE_REGISTRY


def state_dir_for(name: str) -> Path | None:
    """Return STATE_DIR/<state_subdir> for the named engine, or None if unknown."""
    for meta in ENGINE_REGISTRY:
        if meta.name == name:
            return STATE_DIR / meta.state_subdir
    return None
