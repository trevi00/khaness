#!/usr/bin/env python3
"""Skill graph generator — DAG of cross-skill dependencies.

Walks `~/.claude/skills/**/*.md`, parses each skill's frontmatter, and emits
machine + human readable graphs:

- `state/skill-graph.json`  — structured DAG (nodes + edges) for tooling
- `state/skill-graph.md`    — markdown index grouped by subtree, with mermaid
                              graph fragments per subtree
- `--html` (optional)       — single-page HTML site with embedded mermaid
                              renderer for browser exploration

Edge sources:
- `requires:` frontmatter field (explicit forward dep)
- name/keyword overlap between skills (implicit "related" edge)
- subtree co-membership (sibling edge inside `_common/`, `java/lang/`, etc.)

Usage:
    cd ~/.claude/scripts
    python -m cli.skill_graph                       # write json + md
    python -m cli.skill_graph --html out/graph.html # also write static HTML
    python -m cli.skill_graph --check               # exit 1 if graph drift vs git
    python -m cli.skill_graph --json                # print JSON to stdout

Exit code: 0 unless --check detects drift.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.frontmatter import parse_frontmatter  # noqa: E402
from lib.paths import SKILLS_DIR, STATE_DIR  # noqa: E402


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SkillNode:
    name: str               # filename stem
    path: str               # relative to SKILLS_DIR (forward slashes)
    subtree: str            # top-level dir under SKILLS_DIR (e.g. "_common", "java/springboot-3.2")
    description: str
    keywords: list[str]
    requires: list[str]     # parsed from `requires:` field
    phase: list[str]
    intent: list[str]


@dataclass
class SkillEdge:
    source: str             # source skill name
    target: str             # target skill name
    kind: str               # "requires" | "related" | "sibling"
    weight: float           # 1.0 for explicit, 0.0..1.0 for derived


@dataclass
class SkillGraph:
    nodes: list[SkillNode] = field(default_factory=list)
    edges: list[SkillEdge] = field(default_factory=list)
    generated_at: str = ""
    skill_count: int = 0
    edge_count: int = 0
    subtrees: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _split_field(value: str) -> list[str]:
    """Split frontmatter field — supports comma OR space separated."""
    if not value:
        return []
    raw = value.strip().strip("[]")
    if "," in raw:
        parts = [p.strip().strip('"').strip("'") for p in raw.split(",")]
    else:
        parts = [p.strip() for p in raw.split()]
    return [p for p in parts if p]


def _subtree_for(skill_path: Path) -> str:
    """Top-level subtree under SKILLS_DIR. e.g. skills/java/springboot-3.2/x.md → 'java/springboot-3.2'."""
    rel = skill_path.relative_to(SKILLS_DIR)
    parts = rel.parts
    if len(parts) == 1:
        return "."  # skill at SKILLS_DIR root
    if len(parts) == 2:
        return parts[0]
    # nested: take first 2 segments (e.g. java/springboot-3.2)
    return "/".join(parts[:2])


def _parse_skill(filepath: Path) -> SkillNode | None:
    parsed = parse_frontmatter(filepath)
    if parsed is None:
        return None
    meta, _ = parsed
    name = filepath.stem
    if name.startswith("_"):
        return None  # _template.md, _meta.md — not skills

    description = (meta.get("description") or "").strip().strip('"').strip("'")
    return SkillNode(
        name=name,
        path=filepath.relative_to(SKILLS_DIR).as_posix(),
        subtree=_subtree_for(filepath),
        description=description,
        keywords=_split_field(meta.get("keywords", "")),
        requires=_split_field(meta.get("requires", "")),
        phase=_split_field(meta.get("phase", "")),
        intent=_split_field(meta.get("intent", "")),
    )


def _scan_skills() -> list[SkillNode]:
    if not SKILLS_DIR.is_dir():
        return []
    nodes: list[SkillNode] = []
    seen_names: set[str] = set()
    for filepath in sorted(SKILLS_DIR.rglob("*.md")):
        # Skip non-skill files (_template.md, _meta.md, README.md, CHANGELOG.md)
        stem = filepath.stem
        if stem.startswith("_") or stem in {"README", "CHANGELOG"}:
            continue
        node = _parse_skill(filepath)
        if node is None:
            continue
        if node.name in seen_names:
            continue  # first occurrence wins (matches collect_skill_files semantics)
        seen_names.add(node.name)
        nodes.append(node)
    return nodes


# ---------------------------------------------------------------------------
# Edge derivation
# ---------------------------------------------------------------------------

def _build_explicit_edges(nodes: list[SkillNode]) -> list[SkillEdge]:
    """Edges from explicit `requires:` field. weight=1.0."""
    by_name = {n.name: n for n in nodes}
    out: list[SkillEdge] = []
    for n in nodes:
        for req in n.requires:
            if req in by_name and req != n.name:
                out.append(SkillEdge(source=n.name, target=req, kind="requires", weight=1.0))
    return out


def _build_related_edges(nodes: list[SkillNode]) -> list[SkillEdge]:
    """Implicit related-edges from keyword overlap. Threshold: ≥3 shared keywords."""
    out: list[SkillEdge] = []
    nodes_kw = [(n, set(k.lower() for k in n.keywords if len(k) > 1)) for n in nodes]
    for i, (a, ka) in enumerate(nodes_kw):
        for b, kb in nodes_kw[i + 1:]:
            if not ka or not kb:
                continue
            shared = ka & kb
            if len(shared) >= 3:
                weight = min(1.0, len(shared) / 10.0)
                out.append(SkillEdge(source=a.name, target=b.name, kind="related", weight=round(weight, 2)))
    return out


def _build_sibling_edges(nodes: list[SkillNode]) -> list[SkillEdge]:
    """Sibling edges within the same subtree. weight=0.5."""
    by_subtree: dict[str, list[SkillNode]] = defaultdict(list)
    for n in nodes:
        by_subtree[n.subtree].append(n)
    out: list[SkillEdge] = []
    for subtree, members in by_subtree.items():
        if len(members) <= 1:
            continue
        # All-pairs siblings (undirected, but we emit one direction by sort)
        members_sorted = sorted(members, key=lambda x: x.name)
        for i, a in enumerate(members_sorted):
            for b in members_sorted[i + 1:]:
                out.append(SkillEdge(source=a.name, target=b.name, kind="sibling", weight=0.5))
    return out


def build_graph(include_sibling: bool = False, include_related: bool = True) -> SkillGraph:
    nodes = _scan_skills()
    edges = _build_explicit_edges(nodes)
    if include_related:
        edges.extend(_build_related_edges(nodes))
    if include_sibling:
        edges.extend(_build_sibling_edges(nodes))
    g = SkillGraph(
        nodes=nodes,
        edges=edges,
        generated_at="",  # filled by emit (deterministic across runs)
        skill_count=len(nodes),
        edge_count=len(edges),
        subtrees=sorted({n.subtree for n in nodes}),
    )
    return g


# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------

def to_json(g: SkillGraph) -> str:
    payload = {
        "skill_count": g.skill_count,
        "edge_count": g.edge_count,
        "subtrees": g.subtrees,
        "nodes": [asdict(n) for n in g.nodes],
        "edges": [asdict(e) for e in g.edges],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def to_markdown(g: SkillGraph) -> str:
    """Markdown index grouped by subtree, with mermaid graph fragments."""
    by_subtree: dict[str, list[SkillNode]] = defaultdict(list)
    for n in g.nodes:
        by_subtree[n.subtree].append(n)

    explicit_edges = [e for e in g.edges if e.kind == "requires"]

    lines = [
        "<!-- AUTO-GENERATED by scripts/cli/skill_graph.py — do not edit by hand. -->",
        "<!-- Regenerate: `python -m cli.skill_graph` -->",
        "",
        "# Skill Graph",
        "",
        f"- **Skills**: {g.skill_count}",
        f"- **Edges**: {g.edge_count} (explicit `requires:` = {len(explicit_edges)})",
        f"- **Subtrees**: {len(g.subtrees)}",
        "",
        "## Explicit `requires:` graph",
        "",
        "```mermaid",
        "graph LR",
    ]
    if explicit_edges:
        for e in explicit_edges:
            lines.append(f"  {e.source} --> {e.target}")
    else:
        lines.append("  noop[no explicit requires edges]")
    lines.append("```")
    lines.append("")

    lines.append("## Skills by subtree")
    lines.append("")
    for subtree in g.subtrees:
        members = sorted(by_subtree.get(subtree, []), key=lambda n: n.name)
        if not members:
            continue
        lines.append(f"### `{subtree}/` ({len(members)} skills)")
        lines.append("")
        for n in members:
            desc = n.description or "(no description)"
            desc_one = desc.split("\n")[0][:120]
            lines.append(f"- **{n.name}** — {desc_one}")
            if n.requires:
                lines.append(f"  - requires: {', '.join(n.requires)}")
        lines.append("")

    return "\n".join(lines) + "\n"


def to_html(g: SkillGraph) -> str:
    """Single-page HTML site with embedded mermaid for browser exploration."""
    explicit_edges = [e for e in g.edges if e.kind == "requires"]
    mermaid_lines = ["graph LR"]
    if explicit_edges:
        for e in explicit_edges:
            mermaid_lines.append(f"  {e.source} --> {e.target}")
    else:
        mermaid_lines.append("  noop[no explicit requires edges]")

    nodes_json = json.dumps([asdict(n) for n in g.nodes], ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>Harness Skill Graph</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         max-width: 1200px; margin: 0 auto; padding: 2rem; }}
  h1, h2, h3 {{ color: #1a1a1a; }}
  .stats {{ background: #f5f5f5; padding: 1rem; border-radius: 8px; }}
  .skill {{ padding: 0.5rem 0; border-bottom: 1px solid #eee; }}
  .skill-name {{ font-weight: bold; color: #0066cc; }}
  .skill-desc {{ color: #555; font-size: 0.9em; }}
  .subtree {{ margin: 2rem 0; }}
  details {{ margin: 0.5rem 0; }}
  summary {{ cursor: pointer; font-weight: bold; }}
  input[type=text] {{ width: 100%; padding: 0.5rem; margin: 1rem 0;
                       font-size: 1rem; border: 1px solid #ccc; border-radius: 4px; }}
</style>
</head>
<body>
<h1>Harness Skill Graph</h1>
<div class="stats">
  <p><strong>Skills:</strong> {g.skill_count} ·
     <strong>Edges:</strong> {g.edge_count}
     (explicit requires: {len(explicit_edges)}) ·
     <strong>Subtrees:</strong> {len(g.subtrees)}</p>
</div>
<input type="text" id="search" placeholder="filter skills by name / keyword / description...">

<h2>Explicit <code>requires:</code> graph</h2>
<pre class="mermaid">
{chr(10).join(mermaid_lines)}
</pre>

<h2>Skills</h2>
<div id="skills"></div>

<script>
const NODES = {nodes_json};
const root = document.getElementById('skills');
const search = document.getElementById('search');

function render(filter) {{
  const f = (filter || '').toLowerCase();
  const bySubtree = {{}};
  for (const n of NODES) {{
    if (f && !(n.name + ' ' + n.description + ' ' + n.keywords.join(' ')).toLowerCase().includes(f)) continue;
    if (!bySubtree[n.subtree]) bySubtree[n.subtree] = [];
    bySubtree[n.subtree].push(n);
  }}
  root.innerHTML = '';
  for (const subtree of Object.keys(bySubtree).sort()) {{
    const members = bySubtree[subtree];
    const det = document.createElement('details');
    det.open = true;
    const sum = document.createElement('summary');
    sum.textContent = `${{subtree}}/  (${{members.length}})`;
    det.appendChild(sum);
    members.sort((a,b)=>a.name.localeCompare(b.name));
    for (const n of members) {{
      const div = document.createElement('div');
      div.className = 'skill';
      div.innerHTML = `<span class="skill-name">${{n.name}}</span> ` +
                      `<span class="skill-desc">${{(n.description||'').slice(0,200)}}</span>`;
      det.appendChild(div);
    }}
    root.appendChild(det);
  }}
}}
search.addEventListener('input', e => render(e.target.value));
render('');

if (window.mermaid) {{ mermaid.initialize({{startOnLoad: true}}); }}
</script>
</body>
</html>
"""
    return html


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate skill graph from ~/.claude/skills/")
    ap.add_argument("--json", action="store_true", help="emit JSON to stdout")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if regenerated graph differs from on-disk state/skill-graph.json")
    ap.add_argument("--html", help="also write a single-page HTML site to PATH")
    ap.add_argument("--include-sibling", action="store_true",
                    help="include sibling edges (same-subtree co-membership)")
    args = ap.parse_args(argv)

    g = build_graph(include_sibling=args.include_sibling)

    if args.json:
        print(to_json(g))
        return 0

    json_path = STATE_DIR / "skill-graph.json"
    md_path = STATE_DIR / "skill-graph.md"
    new_json = to_json(g)
    new_md = to_markdown(g)

    if args.check:
        existing_json = json_path.read_text(encoding="utf-8") if json_path.is_file() else ""
        existing_md = md_path.read_text(encoding="utf-8") if md_path.is_file() else ""
        if _hash(existing_json) != _hash(new_json) or _hash(existing_md) != _hash(new_md):
            print(f"[FAIL] skill-graph drift detected — regenerate via `python -m cli.skill_graph`")
            return 1
        print(f"[PASS] skill-graph in sync ({g.skill_count} skills, {g.edge_count} edges)")
        return 0

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(new_json, encoding="utf-8")
    md_path.write_text(new_md, encoding="utf-8")
    print(f"[OK] wrote {json_path} ({g.skill_count} skills)")
    print(f"[OK] wrote {md_path} ({g.edge_count} edges)")

    if args.html:
        html_path = Path(args.html)
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(to_html(g), encoding="utf-8")
        print(f"[OK] wrote {html_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
