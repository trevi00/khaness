#!/usr/bin/env python3
"""Tests for lib/phase_graph_query.py — typed-edge query helper (P2 D1)."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import phase_graph_query as q  # noqa: E402

_GRAPH = {
    "nodes": [
        {"id": "phase-1", "kind": "phase", "ref": "Setup"},
        {"id": "phase-2", "kind": "phase", "ref": "Auth"},
        {"id": "phase-3", "kind": "phase", "ref": "Content"},
        {"id": "artifact-02-1-PLAN", "kind": "artifact", "ref": "phases/02-1-PLAN.md"},
    ],
    "edges": [
        {"from": "phase-2", "to": "phase-1", "kind": "depends-on", "provenance": "ROADMAP.md:Depends on"},
        {"from": "phase-3", "to": "phase-1", "kind": "depends-on", "provenance": "ROADMAP.md:Depends on"},
        {"from": "phase-3", "to": "phase-2", "kind": "depends-on", "provenance": "ROADMAP.md:Depends on"},
        {"from": "artifact-02-1-PLAN", "to": "phase-2", "kind": "realizes", "provenance": "plan:..."},
    ],
}


def test_query_by_kind():
    deps = q.query(_GRAPH, kind="depends-on")
    assert len(deps) == 3, deps
    assert all(e["kind"] == "depends-on" for e in deps)


def test_query_node_in_which_phases_depend_on_phase1():
    # "which phases DEPEND-ON phase-1" -> edges INTO phase-1 of kind depends-on
    res = q.query(_GRAPH, kind="depends-on", node="phase-1", direction="in")
    froms = {e["from"] for e in res}
    assert froms == {"phase-2", "phase-3"}, froms


def test_query_node_out():
    res = q.query(_GRAPH, kind="depends-on", node="phase-3", direction="out")
    tos = {e["to"] for e in res}
    assert tos == {"phase-1", "phase-2"}, tos


def test_query_node_both():
    res = q.query(_GRAPH, node="phase-2", direction="both")
    # phase-2 -> phase-1 (out), phase-3 -> phase-2 (in), artifact -> phase-2 (in)
    assert len(res) == 3, res


def test_invalid_direction_falls_back_to_both():
    res = q.query(_GRAPH, node="phase-2", direction="sideways")
    assert len(res) == 3, res


def test_neighbors_out():
    n = q.neighbors(_GRAPH, "phase-3", kind="depends-on", direction="out")
    assert n == ["phase-1", "phase-2"], n


def test_neighbors_in():
    n = q.neighbors(_GRAPH, "phase-1", kind="depends-on", direction="in")
    assert n == ["phase-2", "phase-3"], n


def test_load_missing_file_returns_empty():
    with tempfile.TemporaryDirectory() as td:
        g = q.load(Path(td) / "nope.json")
        assert g == {"nodes": [], "edges": []}, g


def test_load_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "g.json"
        p.write_text(json.dumps(_GRAPH), encoding="utf-8")
        g = q.load(p)
        assert len(g["edges"]) == 4


def test_no_filters_returns_all_edges():
    assert len(q.query(_GRAPH)) == 4


def main() -> int:
    tests = [
        test_query_by_kind,
        test_query_node_in_which_phases_depend_on_phase1,
        test_query_node_out,
        test_query_node_both,
        test_invalid_direction_falls_back_to_both,
        test_neighbors_out,
        test_neighbors_in,
        test_load_missing_file_returns_empty,
        test_load_roundtrip,
        test_no_filters_returns_all_edges,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    if failed == 0:
        print(f"[OK] {len(tests)} tests passed")
        return 0
    print(f"[FAIL] {failed}/{len(tests)} tests failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
