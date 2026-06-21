#!/usr/bin/env python3
"""Unit tests for cli/skill_graph.py."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cli import skill_graph as sg  # noqa: E402


def _write_skill(skills_dir: Path, rel: str, frontmatter: dict, body: str = "# x\n") -> None:
    p = skills_dir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    fm_lines = ["---"]
    for k, v in frontmatter.items():
        if isinstance(v, list):
            fm_lines.append(f"{k}: {' '.join(v)}")
        else:
            fm_lines.append(f"{k}: {v}")
    fm_lines.append("---")
    fm_lines.append("")
    fm_lines.append(body)
    p.write_text("\n".join(fm_lines), encoding="utf-8")


# === _split_field ===

def test_split_field_space_separated():
    assert sg._split_field("foo bar baz") == ["foo", "bar", "baz"]


def test_split_field_comma_separated():
    assert sg._split_field("foo, bar, baz") == ["foo", "bar", "baz"]


def test_split_field_brackets_stripped():
    assert sg._split_field("[foo, bar]") == ["foo", "bar"]


def test_split_field_empty():
    assert sg._split_field("") == []
    assert sg._split_field("   ") == []


# === _subtree_for ===

def test_subtree_top_level():
    with tempfile.TemporaryDirectory() as td:
        skills = Path(td)
        sg.SKILLS_DIR = skills
        f = skills / "foo.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.touch()
        assert sg._subtree_for(f) == "."


def test_subtree_one_deep():
    with tempfile.TemporaryDirectory() as td:
        skills = Path(td)
        sg.SKILLS_DIR = skills
        f = skills / "_common" / "foo.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.touch()
        assert sg._subtree_for(f) == "_common"


def test_subtree_two_deep_combined():
    with tempfile.TemporaryDirectory() as td:
        skills = Path(td)
        sg.SKILLS_DIR = skills
        f = skills / "java" / "springboot-3.2" / "foo.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.touch()
        assert sg._subtree_for(f) == "java/springboot-3.2"


# === build_graph end-to-end ===

def test_build_graph_with_explicit_requires():
    with tempfile.TemporaryDirectory() as td:
        skills = Path(td)
        original = sg.SKILLS_DIR
        try:
            sg.SKILLS_DIR = skills
            _write_skill(skills, "_common/a.md",
                         {"name": "a", "description": "alpha",
                          "keywords": "x y z", "requires": "b"})
            _write_skill(skills, "_common/b.md",
                         {"name": "b", "description": "beta",
                          "keywords": "x y z"})
            g = sg.build_graph()
            names = [n.name for n in g.nodes]
            assert "a" in names and "b" in names
            requires_edges = [e for e in g.edges if e.kind == "requires"]
            assert any(e.source == "a" and e.target == "b" for e in requires_edges)
        finally:
            sg.SKILLS_DIR = original


def test_build_graph_skips_underscore_files():
    with tempfile.TemporaryDirectory() as td:
        skills = Path(td)
        original = sg.SKILLS_DIR
        try:
            sg.SKILLS_DIR = skills
            _write_skill(skills, "_template.md", {"name": "_template", "description": "t"})
            _write_skill(skills, "_common/_meta.md", {"name": "_meta", "description": "m"})
            _write_skill(skills, "_common/real.md",
                         {"name": "real", "description": "r", "keywords": "k"})
            g = sg.build_graph()
            names = {n.name for n in g.nodes}
            assert "real" in names
            assert "_template" not in names
            assert "_meta" not in names
        finally:
            sg.SKILLS_DIR = original


def test_build_graph_related_edges_3plus_keyword_overlap():
    with tempfile.TemporaryDirectory() as td:
        skills = Path(td)
        original = sg.SKILLS_DIR
        try:
            sg.SKILLS_DIR = skills
            _write_skill(skills, "_common/a.md",
                         {"name": "a", "description": "x",
                          "keywords": "shared1 shared2 shared3 only_a"})
            _write_skill(skills, "_common/b.md",
                         {"name": "b", "description": "x",
                          "keywords": "shared1 shared2 shared3 only_b"})
            _write_skill(skills, "_common/c.md",
                         {"name": "c", "description": "x",
                          "keywords": "shared1 only_c"})
            g = sg.build_graph()
            related = [e for e in g.edges if e.kind == "related"]
            ab = any({e.source, e.target} == {"a", "b"} for e in related)
            ac = any({e.source, e.target} == {"a", "c"} for e in related)
            assert ab, "a-b shares 3 keywords → must have related edge"
            assert not ac, "a-c shares only 1 keyword → no related edge"
        finally:
            sg.SKILLS_DIR = original


def test_build_graph_sibling_edges_opt_in():
    with tempfile.TemporaryDirectory() as td:
        skills = Path(td)
        original = sg.SKILLS_DIR
        try:
            sg.SKILLS_DIR = skills
            _write_skill(skills, "java/lang/a.md", {"name": "a", "description": "x"})
            _write_skill(skills, "java/lang/b.md", {"name": "b", "description": "x"})
            g_off = sg.build_graph(include_sibling=False)
            g_on = sg.build_graph(include_sibling=True)
            siblings_off = [e for e in g_off.edges if e.kind == "sibling"]
            siblings_on = [e for e in g_on.edges if e.kind == "sibling"]
            assert siblings_off == []
            assert any({e.source, e.target} == {"a", "b"} for e in siblings_on)
        finally:
            sg.SKILLS_DIR = original


# === to_json / to_markdown ===

def test_to_json_round_trip():
    with tempfile.TemporaryDirectory() as td:
        skills = Path(td)
        original = sg.SKILLS_DIR
        try:
            sg.SKILLS_DIR = skills
            _write_skill(skills, "_common/a.md",
                         {"name": "a", "description": "alpha", "keywords": "k"})
            g = sg.build_graph()
            payload = json.loads(sg.to_json(g))
            assert payload["skill_count"] == 1
            assert payload["nodes"][0]["name"] == "a"
        finally:
            sg.SKILLS_DIR = original


def test_to_markdown_contains_mermaid_block():
    with tempfile.TemporaryDirectory() as td:
        skills = Path(td)
        original = sg.SKILLS_DIR
        try:
            sg.SKILLS_DIR = skills
            _write_skill(skills, "_common/a.md", {"name": "a", "description": "alpha"})
            md = sg.to_markdown(sg.build_graph())
            assert "```mermaid" in md
            assert "graph LR" in md
            assert "**Skills**" in md
        finally:
            sg.SKILLS_DIR = original


def test_to_html_contains_mermaid_script():
    with tempfile.TemporaryDirectory() as td:
        skills = Path(td)
        original = sg.SKILLS_DIR
        try:
            sg.SKILLS_DIR = skills
            _write_skill(skills, "_common/a.md", {"name": "a", "description": "alpha"})
            html = sg.to_html(sg.build_graph())
            assert "mermaid" in html.lower()
            assert "<title>Harness Skill Graph</title>" in html
            assert '"name": "a"' in html
        finally:
            sg.SKILLS_DIR = original


def test_empty_skills_dir_returns_empty_graph():
    with tempfile.TemporaryDirectory() as td:
        original = sg.SKILLS_DIR
        try:
            sg.SKILLS_DIR = Path(td) / "does-not-exist"
            g = sg.build_graph()
            assert g.skill_count == 0
            assert g.edges == []
        finally:
            sg.SKILLS_DIR = original


def main() -> int:
    tests = [
        test_split_field_space_separated,
        test_split_field_comma_separated,
        test_split_field_brackets_stripped,
        test_split_field_empty,
        test_subtree_top_level,
        test_subtree_one_deep,
        test_subtree_two_deep_combined,
        test_build_graph_with_explicit_requires,
        test_build_graph_skips_underscore_files,
        test_build_graph_related_edges_3plus_keyword_overlap,
        test_build_graph_sibling_edges_opt_in,
        test_to_json_round_trip,
        test_to_markdown_contains_mermaid_block,
        test_to_html_contains_mermaid_script,
        test_empty_skills_dir_returns_empty_graph,
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
