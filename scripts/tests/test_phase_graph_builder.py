#!/usr/bin/env python3
"""Tests for lib/phase_graph_builder.py — ROADMAP/-PLAN -> typed-edge graph (P2 D1)."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import phase_graph_builder as b  # noqa: E402

_ROADMAP = """# ROADMAP

## Phase 1: Setup
Goal: scaffolding
Depends on: none
Requirements: SETUP-01

## Phase 2: Authentication
Goal: secure access
Depends on: Phase 1
Requirements: AUTH-01, AUTH-02

## Phase 3: Content
Depends on: Phase 1, Phase 2
Blocks: Phase 5
"""


def _ids(nodes):
    return {n["id"] for n in nodes}


def _edge_tuples(edges):
    return {(e["from"], e["kind"], e["to"]) for e in edges}


def test_phase_nodes_and_titles():
    g = b.build_graph(_ROADMAP)
    assert {"phase-1", "phase-2", "phase-3", "phase-5"} <= _ids(g["nodes"])
    titles = {n["id"]: n["ref"] for n in g["nodes"]}
    assert titles["phase-1"] == "Setup", titles["phase-1"]
    assert titles["phase-2"] == "Authentication", titles["phase-2"]
    # phase-5 is only referenced (no header) -> placeholder ref
    assert titles["phase-5"] == "phase-5", titles["phase-5"]
    assert all(n["kind"] == "phase" for n in g["nodes"])


def test_depends_on_edges():
    g = b.build_graph(_ROADMAP)
    et = _edge_tuples(g["edges"])
    assert ("phase-2", "depends-on", "phase-1") in et
    assert ("phase-3", "depends-on", "phase-1") in et
    assert ("phase-3", "depends-on", "phase-2") in et


def test_none_depends_yields_no_edge():
    g = b.build_graph(_ROADMAP)
    # Phase 1 'Depends on: none' -> phase-1 has no outgoing depends-on edge
    out = [e for e in g["edges"] if e["from"] == "phase-1" and e["kind"] == "depends-on"]
    assert out == [], out


def test_blocks_edge():
    g = b.build_graph(_ROADMAP)
    assert ("phase-3", "blocks", "phase-5") in _edge_tuples(g["edges"])


def test_supersedes_edge():
    g = b.build_graph("## Phase 72.1: hotfix\nSupersedes: Phase 72\n")
    et = _edge_tuples(g["edges"])
    assert ("phase-72.1", "supersedes", "phase-72") in et


def test_decimal_phase_id():
    g = b.build_graph("## Phase 72.1: hotfix\nDepends on: none\n")
    assert "phase-72.1" in _ids(g["nodes"])


def test_leading_zero_normalized():
    g = b.build_graph("## Phase 02: Auth\nDepends on: Phase 01\n")
    assert "phase-2" in _ids(g["nodes"])
    assert ("phase-2", "depends-on", "phase-1") in _edge_tuples(g["edges"])


def test_plan_artifact_realizes():
    g = b.build_graph(_ROADMAP, plan_files={"phases/02-1-auth-PLAN.md": ""})
    assert "artifact-02-1-auth-PLAN" in _ids(g["nodes"])
    art = next(n for n in g["nodes"] if n["id"] == "artifact-02-1-auth-PLAN")
    assert art["kind"] == "artifact"
    assert ("artifact-02-1-auth-PLAN", "realizes", "phase-2") in _edge_tuples(g["edges"])


def test_node_kinds_within_schema():
    g = b.build_graph(_ROADMAP, plan_files={"01-PLAN.md": ""})
    for n in g["nodes"]:
        assert n["kind"] in b.NODE_KINDS, n
    for e in g["edges"]:
        assert e["kind"] in b.EDGE_KINDS, e


def test_deterministic_output():
    g1 = b.build_graph(_ROADMAP, plan_files={"a-PLAN.md": "", "b-PLAN.md": ""})
    g2 = b.build_graph(_ROADMAP, plan_files={"b-PLAN.md": "", "a-PLAN.md": ""})
    assert json.dumps(g1, sort_keys=True) == json.dumps(g2, sort_keys=True)


def test_write_graph_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / ".planning"
        (root).mkdir(parents=True)
        (root / "ROADMAP.md").write_text(_ROADMAP, encoding="utf-8")
        phases = root / "phases"
        phases.mkdir()
        (phases / "02-1-auth-PLAN.md").write_text("# plan\n", encoding="utf-8")
        out = b.write_graph(root)
        assert out == root / "_graph" / "phase-graph.json"
        data = json.loads(out.read_text(encoding="utf-8"))
        assert ("phase-2", "depends-on", "phase-1") in _edge_tuples(data["edges"])
        assert any(n["id"] == "artifact-02-1-auth-PLAN" for n in data["nodes"])


def test_emdash_header():
    g = b.build_graph("## Phase 2 — Authentication\nDepends on: Phase 1\n")
    titles = {n["id"]: n["ref"] for n in g["nodes"]}
    assert titles.get("phase-2") == "Authentication", titles
    assert ("phase-2", "depends-on", "phase-1") in _edge_tuples(g["edges"])


def test_bold_header():
    g = b.build_graph("**Phase 3: Content**\nDepends on: Phase 2\n")
    titles = {n["id"]: n["ref"] for n in g["nodes"]}
    assert titles.get("phase-3") == "Content", titles


def test_bullet_prefixed_depends():
    g = b.build_graph("## Phase 2: Auth\n- Depends on: Phase 1\n- Blocks: Phase 5\n")
    et = _edge_tuples(g["edges"])
    assert ("phase-2", "depends-on", "phase-1") in et
    assert ("phase-2", "blocks", "phase-5") in et


def test_write_graph_missing_roadmap_raises():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / ".planning"
        root.mkdir(parents=True)
        try:
            b.write_graph(root)
        except FileNotFoundError:
            return
        raise AssertionError("expected FileNotFoundError for missing ROADMAP.md")


def main() -> int:
    tests = [
        test_phase_nodes_and_titles,
        test_depends_on_edges,
        test_none_depends_yields_no_edge,
        test_blocks_edge,
        test_supersedes_edge,
        test_decimal_phase_id,
        test_leading_zero_normalized,
        test_plan_artifact_realizes,
        test_node_kinds_within_schema,
        test_deterministic_output,
        test_emdash_header,
        test_bold_header,
        test_bullet_prefixed_depends,
        test_write_graph_roundtrip,
        test_write_graph_missing_roadmap_raises,
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
