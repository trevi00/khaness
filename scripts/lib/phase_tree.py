"""Phase tree convention codification (HANDOFF.md L52-66).

Pure logic for the autonomous orchestrator's phase block tree. No I/O,
no event store dependency — caller persists by writing the rendered
output to HANDOFF.md / phase-tree.md.

Lives under `lib/` (not `engine/`) so handlers + cli can reuse it without
violating the lib->validators->handlers->engine adjacency rule (W21+
relocation; previously at engine/phase_tree.py).

Convention (locked Wave 19.1.1, debate-1778161608-713bdc gen 4 byte-identical):
- Naming: `parent.child` (e.g., designer-automation.step_4_validation)
- Promotion: step >= 5 AND any step has sub_step >= 3 -> promote to child
- Transition: children all DONE -> parent DONE; any in_progress -> parent in_progress;
  any deferred (not all DONE) -> parent in_progress or partial_done (NOT blocked)
- Pruning: child DONE + 6mo unreferenced -> archive to migration-progress.md

This module provides:
  - Status enum
  - Phase dataclass (round-trippable via yaml)
  - should_promote(steps) — promotion rule
  - transition_status(children) — children -> parent rule
  - render_tree_markdown(root) — ASCII visualization
  - render_yaml(root) / parse_yaml(text) — round-trip persistence

Intended callers:
  - scripts/engine/orchestrator.py (resumable super-session)
  - scripts/lib/handoff_drift.py (HANDOFF.md drift detection)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import yaml


class Status(str, Enum):
    """Phase / step lifecycle. Strings serialize cleanly to yaml."""
    IN_PROGRESS = "in_progress"
    DONE = "done"
    DEFERRED = "deferred"
    PENDING = "pending"
    BLOCKED = "blocked"


@dataclass
class Phase:
    """Phase tree node. `sub_phases` for children, `steps` for flat step list.

    A phase is in one of two shapes:
      (a) leaf phase with `steps` dict (step_name -> status_or_description)
      (b) parent phase with `sub_phases` list (each sub_phase is itself a Phase)

    Promotion converts shape (a) -> (b) when convention threshold is met.
    """
    id: str
    status: Status = Status.IN_PROGRESS
    goal: str | None = None
    next_action: str | None = None
    exit_condition: str | None = None
    parent_id: str | None = None
    trigger: str | None = None
    sub_phases: list["Phase"] = field(default_factory=list)
    steps: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


# ---------- Convention rules ----------

PROMOTION_STEP_THRESHOLD: int = 5
PROMOTION_SUB_STEP_THRESHOLD: int = 3


def deepest_in_progress(root: "Phase") -> "Phase | None":
    """Return the DEEPEST node whose status == IN_PROGRESS, or None if none is
    (debate-1781493074-c16jtw W3). `transition_status` propagates IN_PROGRESS up to
    ancestors, so the root is almost always IN_PROGRESS; descend to the deepest
    in_progress leaf for the actionable node. Among in_progress siblings, the FIRST
    in `sub_phases` list order wins (deterministic — no tie ambiguity). A pure
    read-only tree walk (no I/O, no mutation)."""
    if root.status != Status.IN_PROGRESS:
        return None
    node = root
    while True:
        nxt = next((c for c in node.sub_phases if c.status == Status.IN_PROGRESS), None)
        if nxt is None:
            return node
        node = nxt


def should_promote(phase: Phase) -> bool:
    """Apply the promotion rule from HANDOFF.md Phase Tree Convention.

    Returns True when:
      - phase has >= 5 steps, AND
      - at least one step looks nested (string contains a sub-step marker
        like `step_X_...` or carries an embedded list/dict in yaml shape).

    Sub-step nesting in our flat dict is detected by counting tokens that
    start with `sub_` or by the step value itself being a multi-line block.
    Conservative: returns False unless both conditions clearly satisfied.
    """
    if len(phase.steps) < PROMOTION_STEP_THRESHOLD:
        return False
    nested_count = 0
    for value in phase.steps.values():
        # Sub-step heuristic: value contains 3+ semicolons / commas (list-like)
        # or the key chain shows nested step naming.
        if isinstance(value, str):
            if value.count(";") >= PROMOTION_SUB_STEP_THRESHOLD - 1:
                nested_count += 1
            elif value.count(",") >= PROMOTION_SUB_STEP_THRESHOLD:
                nested_count += 1
    return nested_count >= 1


def transition_status(children: list[Status]) -> Status:
    """Compute parent status from children statuses (HANDOFF.md L62-66).

    Rules:
      - all DONE -> DONE
      - any IN_PROGRESS -> IN_PROGRESS
      - else (mix of DONE/DEFERRED/PENDING with no in_progress) -> IN_PROGRESS
        (partial_done is rendered as in_progress per convention; never BLOCKED
         just from deferred children)
    """
    if not children:
        return Status.IN_PROGRESS
    if all(c == Status.DONE for c in children):
        return Status.DONE
    if any(c == Status.IN_PROGRESS for c in children):
        return Status.IN_PROGRESS
    if any(c == Status.BLOCKED for c in children):
        return Status.BLOCKED
    return Status.IN_PROGRESS


# ---------- Markdown tree visualization ----------

_TREE_BRANCH = "├─ "
_TREE_LAST = "└─ "
_TREE_VERTICAL = "│  "
_TREE_SPACE = "   "


def _render_node(
    phase: Phase,
    prefix: str = "",
    is_last: bool = True,
    is_root: bool = False,
) -> list[str]:
    """Recursive helper for ASCII tree rendering.

    `is_root` is the depth-0 caller signal — root has no connector and its
    children's prefix is empty (so depth-1 connectors sit at column 0).
    Below depth 1, prefix accumulates `│  ` / `   ` per ancestor.
    """
    connector = _TREE_LAST if is_last else _TREE_BRANCH
    label = f"{phase.id}"
    suffix = f"  [{phase.status.value}"
    if phase.steps:
        done_count = sum(1 for v in phase.steps.values()
                         if isinstance(v, str) and v.upper().startswith("DONE"))
        suffix += f" {done_count}/{len(phase.steps)}"
    suffix += "]"
    if phase.trigger:
        suffix += f" trigger={phase.trigger[:40]}"

    if is_root:
        lines = [f"{label}{suffix}"]
        children_prefix = ""
    else:
        lines = [f"{prefix}{connector}{label}{suffix}"]
        children_prefix = prefix + (_TREE_SPACE if is_last else _TREE_VERTICAL)

    # Render flat steps as leaf children
    step_items = list(phase.steps.items())
    sub_items = phase.sub_phases
    total_children = len(step_items) + len(sub_items)

    for i, (step_name, step_value) in enumerate(step_items):
        is_step_last = (i == total_children - 1) and not sub_items
        step_connector = _TREE_LAST if is_step_last else _TREE_BRANCH
        step_status = "DONE" if (isinstance(step_value, str) and
                                  step_value.upper().startswith("DONE")) else "pending"
        lines.append(f"{children_prefix}{step_connector}{step_name}  [{step_status}]")

    for j, child in enumerate(sub_items):
        is_child_last = (j == len(sub_items) - 1)
        lines.extend(_render_node(child, children_prefix, is_child_last, is_root=False))

    return lines


def render_tree_markdown(root: Phase) -> str:
    """Render phase tree as ASCII tree (HANDOFF.md visualization style)."""
    return "\n".join(_render_node(root, prefix="", is_last=True, is_root=True))


# ---------- YAML round-trip ----------

def render_yaml(root: Phase) -> str:
    """Serialize phase tree to yaml. Inverse of parse_yaml."""
    return yaml.safe_dump(_phase_to_dict(root), allow_unicode=True, sort_keys=False)


def _phase_to_dict(phase: Phase) -> dict[str, Any]:
    out: dict[str, Any] = {"id": phase.id, "status": phase.status.value}
    if phase.goal:
        out["goal"] = phase.goal
    if phase.next_action:
        out["next_action"] = phase.next_action
    if phase.exit_condition:
        out["exit_condition"] = phase.exit_condition
    if phase.parent_id:
        out["parent_id"] = phase.parent_id
    if phase.trigger:
        out["trigger"] = phase.trigger
    if phase.steps:
        out["steps"] = dict(phase.steps)
    if phase.sub_phases:
        out["sub_phases"] = [_phase_to_dict(c) for c in phase.sub_phases]
    if phase.notes:
        out["notes"] = list(phase.notes)
    if phase.evidence:
        out["evidence"] = list(phase.evidence)
    return out


def parse_yaml(text: str) -> Phase:
    """Parse yaml text to Phase. Inverse of render_yaml."""
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"phase yaml must be a mapping, got {type(data).__name__}")
    return _dict_to_phase(data)


_STATUS_ALIASES: dict[str, str] = {
    "partial": "in_progress",
    "partial_done": "in_progress",
    "wip": "in_progress",
    "todo": "pending",
    "skip": "deferred",
    "skipped": "deferred",
}


def _dict_to_phase(data: dict[str, Any]) -> Phase:
    # Convention uses UPPERCASE status (DONE/PENDING) + aliases (PARTIAL) but the
    # enum values are lowercase — normalize case + aliases so a `status: DONE` block
    # parses as Status.DONE, not the silent IN_PROGRESS default (debate-1781493074
    # follow-up: this default broke work-tree current-node selection on real data).
    raw = str(data.get("status", "in_progress")).strip().lower()
    raw = _STATUS_ALIASES.get(raw, raw)
    try:
        status = Status(raw)
    except ValueError:
        status = Status.IN_PROGRESS

    sub_data = data.get("sub_phases") or []
    children = [_dict_to_phase(d) for d in sub_data if isinstance(d, dict)]

    return Phase(
        id=str(data.get("id", "unknown")),
        status=status,
        goal=data.get("goal"),
        next_action=data.get("next_action"),
        exit_condition=data.get("exit_condition"),
        parent_id=data.get("parent_id"),
        trigger=data.get("trigger"),
        sub_phases=children,
        steps=dict(data.get("steps") or {}),
        notes=list(data.get("notes") or []),
        evidence=list(data.get("evidence") or []),
    )
