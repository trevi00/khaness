"""phase_graph_query — query helper for the typed-edge phase graph (P2 D1).

Converged design: debate-1780870185-827a94 (ontology sha1 41c9cc8f...).
Reads the graph emitted by lib.phase_graph_builder.write_graph and answers
typed traversal queries the sub-Atlas flat `links:` list cannot — e.g.
"which phases DEPEND-ON phase-3" (kind='depends-on', node='phase-3',
direction='in').

Pure read-only — no judge, no ranking, no comparative verdict.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DIRECTIONS = ("in", "out", "both")


def load(path: str | Path) -> dict[str, Any]:
    """Load a graph JSON. Returns {'nodes':[], 'edges':[]} for a missing file."""
    p = Path(path)
    if not p.exists():
        return {"nodes": [], "edges": []}
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"nodes": [], "edges": []}
    data.setdefault("nodes", [])
    data.setdefault("edges", [])
    return data


def query(
    graph: dict[str, Any],
    *,
    kind: str | None = None,
    node: str | None = None,
    direction: str = "both",
) -> list[dict[str, str]]:
    """Return edges matching the filters.

    - ``kind``: keep only edges of this edge-kind (depends-on/realizes/...).
    - ``node`` + ``direction``: keep edges touching ``node``; ``out`` = edges
      FROM node, ``in`` = edges TO node, ``both`` = either. ``direction`` is
      ignored when ``node`` is None.

    Invalid ``direction`` falls back to ``both`` (defensive — never raises on a
    query helper). Results preserve the graph's stored edge order.
    """
    if direction not in _DIRECTIONS:
        direction = "both"
    edges = [e for e in graph.get("edges", []) if isinstance(e, dict)]
    out: list[dict[str, str]] = []
    for e in edges:
        if kind is not None and e.get("kind") != kind:
            continue
        if node is not None:
            frm, to = e.get("from"), e.get("to")
            if direction == "out" and frm != node:
                continue
            if direction == "in" and to != node:
                continue
            if direction == "both" and node not in (frm, to):
                continue
        out.append(e)
    return out


def neighbors(
    graph: dict[str, Any],
    node: str,
    *,
    kind: str | None = None,
    direction: str = "out",
) -> list[str]:
    """Return the set of node ids reachable from/to ``node`` (one hop), sorted.

    ``direction='out'`` -> targets of edges from ``node``; ``'in'`` -> sources
    of edges into ``node``; ``'both'`` -> the union of the other endpoints.
    """
    found: set[str] = set()
    for e in query(graph, kind=kind, node=node, direction=direction):
        frm, to = e.get("from"), e.get("to")
        if direction == "out":
            found.add(to)
        elif direction == "in":
            found.add(frm)
        else:
            found.add(to if frm == node else frm)
    found.discard(node)
    return sorted(x for x in found if x)
