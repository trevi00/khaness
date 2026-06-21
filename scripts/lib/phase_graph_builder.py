"""phase_graph_builder — deterministic typed-edge phase-graph projection (P2 D1).

Converged design: debate-1780870185-827a94 (3 gen, ontology sha1
41c9cc8f448577adbaa9a3db3468c0e151a93aa2), decision D1 "graphify".

Absorbs gsd-core's `graphify` concept as a DETERMINISTIC projection over the
already-written kha planning artifacts. Net-new vs the sub-Atlas's flat untyped
`links:` frontmatter list: this emits a QUERYABLE, TYPED-EDGE graph (edge kind +
direction + node typing) answering traversal queries like "which phases
DEPEND-ON phase-3".

Governance (locked):
- Emit target is .planning/_graph/phase-graph.json — INSIDE kha-planner's
  declared expects_paths ('.planning/'); no sandbox/Atlas-governance breach,
  no settings.json mutation, never written into the sub-Atlas note-vault.
- Pure projection — NO judge, NO comparative verdict. Runs as a kha-plan-phase
  ORCHESTRATOR post-step / lib builder (this module), NOT inside the
  context-pressured kha-planner LLM agent.

Schema (locked):
    {
      "nodes": [{"id": str, "kind": "phase"|"decision"|"artifact", "ref": str}],
      "edges": [{"from": str, "to": str,
                 "kind": "depends-on"|"realizes"|"supersedes"|"blocks",
                 "provenance": str}]
    }

Sources:
- ROADMAP.md  -> phase nodes; depends-on / blocks / supersedes edges between
  phases (the explicit `Depends on:` / `Blocks:` / `Supersedes:` fields
  maintained by kha-analyze-dependencies).
- *-PLAN.md   -> artifact nodes; `realizes` edge (artifact realizes its phase).

Requirements lines (`Requirements: AUTH-01, ...`) are intentionally NOT modeled
as nodes — the locked node-kind set is {phase, decision, artifact} only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

NODE_KINDS = ("phase", "decision", "artifact")
EDGE_KINDS = ("depends-on", "realizes", "supersedes", "blocks")

# `## Phase 2: Authentication` / `Phase 2 - Auth` / `Phase 2 — Auth` (em/en dash)
# / `**Phase 2: Auth**` (bold) / `### Phase 72.1: hotfix`
_SEP = r"[:.)–—\-]?"  # colon / dot / paren / en-dash / em-dash / hyphen
_PHASE_HEADER_RE = re.compile(
    r"^[ \t]{0,3}#{0,4}[ \t]*(?:\*\*)?Phase[ \t]+(\d+(?:\.\d+)?)[ \t]*" + _SEP +
    r"[ \t]*(.*?)[ \t]*(?:\*\*)?[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)
# Fields tolerate an optional leading bullet ("- Depends on: ...").
_BULLET = r"(?:[-*][ \t]*)?"
_DEPENDS_RE = re.compile(rf"^[ \t]*{_BULLET}Depends[ \t]+on[ \t]*:[ \t]*(.+?)[ \t]*$",
                         re.MULTILINE | re.IGNORECASE)
_BLOCKS_RE = re.compile(rf"^[ \t]*{_BULLET}Blocks[ \t]*:[ \t]*(.+?)[ \t]*$",
                        re.MULTILINE | re.IGNORECASE)
_SUPERSEDES_RE = re.compile(rf"^[ \t]*{_BULLET}Supersedes[ \t]*:[ \t]*(.+?)[ \t]*$",
                            re.MULTILINE | re.IGNORECASE)
# phase reference inside a field value, e.g. "Phase 1, Phase 2" or "1, 2"
_PHASE_REF_RE = re.compile(r"(\d+(?:\.\d+)?)")
# "none" / "-" / "없음" / "n/a" — explicit no-dependency markers
_NONE_RE = re.compile(r"^\s*(none|n/?a|-+|없음|tbd)\s*$", re.IGNORECASE)
# leading integer group in a plan filename, e.g. "02-1-auth-PLAN.md" -> "02"
_PLAN_PHASE_RE = re.compile(r"(\d+(?:\.\d+)?)")


def normalize_phase_id(raw: str) -> str:
    """Canonical node id for a phase number: '02' -> 'phase-2', '72.10' -> 'phase-72.10'.

    Leading zeros are stripped per dotted segment; the fractional segment keeps
    its own significance ('72.10' != '72.1') so decimal hotfix phases stay
    distinct.
    """
    raw = raw.strip()
    if "." in raw:
        head, _, tail = raw.partition(".")
        head_n = str(int(head)) if head.isdigit() else head
        return f"phase-{head_n}.{tail}"
    return f"phase-{int(raw)}" if raw.isdigit() else f"phase-{raw}"


def _parse_phase_refs(value: str) -> list[str]:
    """Extract canonical phase ids from a field value; [] for none/empty markers."""
    if not value or _NONE_RE.match(value):
        return []
    return [normalize_phase_id(m) for m in _PHASE_REF_RE.findall(value)]


def _iter_phase_blocks(roadmap_text: str):
    """Yield (phase_num_raw, title, block_text) for each phase header in order."""
    matches = list(_PHASE_HEADER_RE.finditer(roadmap_text))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(roadmap_text)
        yield m.group(1), m.group(2).strip(), roadmap_text[start:end]


def build_graph(
    roadmap_text: str,
    *,
    plan_files: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Project ROADMAP text (+ optional plan file map) into the locked graph schema.

    ``plan_files`` maps a plan path/name (e.g. ``"phases/02-1-auth-PLAN.md"``)
    to its content (content currently unused for edges — the phase is inferred
    from the filename — but accepted for forward compatibility). Each plan
    becomes an ``artifact`` node with a ``realizes`` edge to its phase.

    Deterministic: same input -> byte-identical output (nodes/edges sorted).
    """
    nodes: dict[str, dict[str, str]] = {}
    edges: list[dict[str, str]] = []

    def add_node(node_id: str, kind: str, ref: str) -> None:
        if node_id not in nodes:
            nodes[node_id] = {"id": node_id, "kind": kind, "ref": ref}

    def add_edge(frm: str, to: str, kind: str, provenance: str) -> None:
        edges.append({"from": frm, "to": to, "kind": kind, "provenance": provenance})

    blocks = list(_iter_phase_blocks(roadmap_text))
    # Pass 1: register every declared phase node WITH its title, so a
    # forward-referenced phase (e.g. "Blocks: Phase 5" before Phase 5's header)
    # does not get shadowed by a placeholder ref.
    for raw_num, title, _block in blocks:
        pid = normalize_phase_id(raw_num)
        add_node(pid, "phase", title or pid)
    # Pass 2: edges (placeholder nodes only for refs that have no header).
    for raw_num, _title, block in blocks:
        pid = normalize_phase_id(raw_num)
        for dep in _parse_phase_refs(_first(_DEPENDS_RE, block)):
            add_node(dep, "phase", dep)
            add_edge(pid, dep, "depends-on", "ROADMAP.md:Depends on")
        for blocked in _parse_phase_refs(_first(_BLOCKS_RE, block)):
            add_node(blocked, "phase", blocked)
            add_edge(pid, blocked, "blocks", "ROADMAP.md:Blocks")
        for sup in _parse_phase_refs(_first(_SUPERSEDES_RE, block)):
            add_node(sup, "phase", sup)
            add_edge(pid, sup, "supersedes", "ROADMAP.md:Supersedes")

    for plan_path in sorted((plan_files or {}).keys()):
        stem = Path(plan_path).stem
        aid = f"artifact-{stem}"
        add_node(aid, "artifact", plan_path)
        m = _PLAN_PHASE_RE.search(Path(plan_path).name)
        if m:
            pid = normalize_phase_id(m.group(1))
            add_node(pid, "phase", pid)
            add_edge(aid, pid, "realizes", f"plan:{plan_path}")

    return {
        "nodes": sorted(nodes.values(), key=lambda n: n["id"]),
        "edges": sorted(edges, key=lambda e: (e["from"], e["kind"], e["to"])),
    }


def _first(rx: re.Pattern[str], text: str) -> str:
    m = rx.search(text)
    return m.group(1) if m else ""


def _discover_plan_files(planning_root: Path) -> dict[str, str]:
    """Map *-PLAN.md paths (relative to planning_root) to '' (content not needed)."""
    out: dict[str, str] = {}
    for p in sorted(planning_root.rglob("*-PLAN.md")):
        try:
            rel = p.relative_to(planning_root).as_posix()
        except ValueError:
            rel = p.name
        out[rel] = ""
    return out


def write_graph(planning_root: str | Path) -> Path:
    """Read .planning/ROADMAP.md (+ *-PLAN.md), build the graph, write the JSON.

    Returns the written path: ``<planning_root>/_graph/phase-graph.json``.
    Raises FileNotFoundError if ROADMAP.md is absent (caller surfaces it — the
    orchestrator post-step should only run after planning produced a ROADMAP).
    """
    root = Path(planning_root)
    roadmap = root / "ROADMAP.md"
    if not roadmap.exists():
        raise FileNotFoundError(f"ROADMAP.md not found under {root}")
    graph = build_graph(
        roadmap.read_text(encoding="utf-8"),
        plan_files=_discover_plan_files(root),
    )
    out_dir = root / "_graph"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "phase-graph.json"
    out_path.write_text(
        json.dumps(graph, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out_path
