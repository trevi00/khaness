#!/usr/bin/env python3
"""atlas_index — operator surface for Atlas vault inspection + INDEX maintenance.

Subcommands (read-only):
  list [--domain D] [--type T] [--json]
    List all notes (id, type, domain, path). Optional filters.

  stats
    Count summary per domain × type.

  table
    Emit markdown domain table (drop-in for INDEX.md "등록된 도메인" section).

  orphans
    Concepts not referenced from any MOC README or other concept's `links:`.

  broken-links
    Notes whose `links:` field references an id not found in the vault.

Usage:
  python -m cli.atlas_index list --tail 20
  python -m cli.atlas_index stats
  python -m cli.atlas_index table > /tmp/new-table.md
  python -m cli.atlas_index orphans
  python -m cli.atlas_index broken-links

Exit code: 0 on success, 1 on lookup error or broken-links/orphans found.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.frontmatter import parse_frontmatter  # noqa: E402
from lib.paths import ATLAS_DIR, STATE_DIR  # noqa: E402


_SEARCH_LOG_PATH: Path = STATE_DIR / "atlas-search-log.jsonl"


_LIST_VAL_RE = re.compile(r"\[([^\]]*)\]")


def _parse_list_field(raw: str) -> list[str]:
    """`[a, b, c]` -> ['a', 'b', 'c']. Empty/missing -> []."""
    if not raw:
        return []
    m = _LIST_VAL_RE.search(raw)
    if not m:
        return []
    return [x.strip() for x in m.group(1).split(",") if x.strip()]


def _collect_notes() -> list[dict[str, object]]:
    """Walk ATLAS_DIR, parse frontmatter from each .md, return note records."""
    out: list[dict[str, object]] = []
    if not ATLAS_DIR.is_dir():
        return out
    for path in sorted(ATLAS_DIR.rglob("*.md")):
        rel = path.relative_to(ATLAS_DIR)
        parts = rel.parts
        domain = parts[0] if len(parts) > 1 and not parts[0].startswith("_") and parts[0] != "99-archive" else "(root)"
        result = parse_frontmatter(path)
        if result is None:
            continue
        meta, _body = result
        out.append({
            "path": str(rel).replace("\\", "/"),
            "domain": domain,
            "id": (meta.get("id") or "").strip(),
            "type": (meta.get("type") or "").strip(),
            "activation": (meta.get("activation") or "").strip(),
            "description": (meta.get("description") or "").strip(),
            "links": _parse_list_field(meta.get("links") or ""),
            "tags": _parse_list_field(meta.get("tags") or ""),
            "status": (meta.get("status") or "").strip(),
        })
    return out


def _cmd_list(args: argparse.Namespace) -> int:
    notes = _collect_notes()
    if args.domain:
        notes = [n for n in notes if n["domain"] == args.domain]
    if args.type:
        notes = [n for n in notes if n["type"] == args.type]
    if args.tail and args.tail > 0:
        notes = notes[-args.tail:]
    if args.json:
        json.dump(notes, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    if not notes:
        print("(no notes)")
        return 0
    for n in notes:
        print(f"  {n['domain']:24} {n['type']:9} {n['id']:48} {n['path']}")
    print(f"\n[{len(notes)} notes]")
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    notes = _collect_notes()
    by_domain_type: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for n in notes:
        by_domain_type[str(n["domain"])][str(n["type"])] += 1
    types = ["moc", "concept", "decision", "artifact", "journal", "meta"]
    header = f"{'domain':24} | " + " | ".join(f"{t:8}" for t in types) + " | total"
    print(header)
    print("-" * len(header))
    grand_total = 0
    for domain in sorted(by_domain_type):
        counts = by_domain_type[domain]
        total = sum(counts.values())
        grand_total += total
        row = f"{domain:24} | " + " | ".join(f"{counts.get(t, 0):8}" for t in types) + f" | {total}"
        print(row)
    print("-" * len(header))
    print(f"{'TOTAL':24} | " + " | ".join(" " * 8 for _ in types) + f" | {grand_total}")
    return 0


def _cmd_table(args: argparse.Namespace) -> int:
    """Emit markdown table for INDEX.md `등록된 도메인` section."""
    notes = _collect_notes()
    # Group by domain, find MOC + first concept + counts
    by_domain: dict[str, list[dict[str, object]]] = defaultdict(list)
    for n in notes:
        by_domain[str(n["domain"])].append(n)
    print("| # | 도메인 | MOC | starter concept | counts (c/d/a/j) |")
    print("|---|--------|-----|------------------|------------------|")
    skip = {"(root)"}
    idx = 0
    for domain in sorted(by_domain):
        if domain in skip:
            continue
        idx += 1
        items = by_domain[domain]
        moc = next((n for n in items if n["type"] == "moc"), None)
        first_concept = next((n for n in items if n["type"] == "concept"), None)
        c = sum(1 for n in items if n["type"] == "concept")
        d = sum(1 for n in items if n["type"] == "decision")
        a = sum(1 for n in items if n["type"] == "artifact")
        j = sum(1 for n in items if n["type"] == "journal")
        moc_link = f"[README]({moc['path']})" if moc else "—"
        concept_link = f"[{first_concept['id']}]({first_concept['path']})" if first_concept else "—"
        print(f"| {idx} | {domain} | {moc_link} | {concept_link} | {c}/{d}/{a}/{j} |")
    return 0


def _cmd_orphans(args: argparse.Namespace) -> int:
    """Concept notes never referenced by any MOC or other note's links."""
    notes = _collect_notes()
    all_ids = {str(n["id"]) for n in notes if n["id"]}
    referenced: set[str] = set()
    for n in notes:
        # MOC READMEs reference concepts via markdown body (not just frontmatter links:)
        # — but at minimum we honor frontmatter links: as the formal cross-ref.
        for link_id in n["links"]:  # type: ignore[union-attr]
            if link_id in all_ids:
                referenced.add(link_id)
    # Also parse MOC README body for markdown links to concepts (best-effort)
    for n in notes:
        if n["type"] != "moc":
            continue
        path = ATLAS_DIR / str(n["path"])
        try:
            body = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for other in notes:
            if other["type"] not in ("concept", "decision", "artifact"):
                continue
            stem = Path(str(other["path"])).stem
            if stem in body or str(other["id"]) in body:
                referenced.add(str(other["id"]))
    orphans = [n for n in notes if n["type"] in ("concept", "decision", "artifact")
               and n["id"] and n["id"] not in referenced]
    if not orphans:
        print("[PASS] no orphans (all concepts/decisions/artifacts referenced)")
        return 0
    for o in orphans:
        print(f"  orphan: {o['domain']}/{o['type']}: {o['id']}  ({o['path']})")
    print(f"\n[{len(orphans)} orphans]")
    return 1


def _cmd_broken_links(args: argparse.Namespace) -> int:
    notes = _collect_notes()
    all_ids = {str(n["id"]) for n in notes if n["id"]}
    broken: list[tuple[str, str, str]] = []  # (source_id, source_path, missing_target)
    for n in notes:
        for target in n["links"]:  # type: ignore[union-attr]
            if target not in all_ids:
                broken.append((str(n["id"]), str(n["path"]), target))
    if not broken:
        print(f"[PASS] all links resolve ({len(notes)} notes scanned)")
        return 0
    for src_id, src_path, target in broken:
        print(f"  broken: {src_id} ({src_path}) -> {target}")
    print(f"\n[{len(broken)} broken links]")
    return 1


_MERMAID_TYPE_SHAPE = {
    # mermaid v10+ syntax: id["label"] = rect (default), id(("label")) = circle,
    # id{{"label"}} = hexagon, id[/"label"/] = parallelogram, id>"label"] = flag
    "moc": '{0}[/"{1}"/]',          # parallelogram — MOC entry
    "concept": '{0}(("{1}"))',       # circle — atomic concept
    "decision": '{0}{{{{"{1}"}}}}',  # hexagon — debate LOCK
    "artifact": '{0}["{1}"]',        # rect — code card
    "procedure": '{0}>"{1}"]',        # flag — runbook
    "journal": '{0}[("{1}")]',       # cylinder — timeline
    "meta": '{0}["{1}"]',
}


def _md_id_safe(s: str) -> str:
    """Mermaid id-safe: alphanumeric only, hyphens to underscores."""
    return re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_")


def _cmd_graph(args: argparse.Namespace) -> int:
    """Emit cross-domain link graph (mermaid|dot|json) for visualization."""
    notes = _collect_notes()
    if args.domain:
        notes = [n for n in notes if n["domain"] == args.domain]
    if not notes:
        print("(no notes to graph)", file=sys.stderr)
        return 1
    all_ids = {str(n["id"]): n for n in notes if n["id"]}

    # Collect edges from frontmatter links: field
    edges: list[tuple[str, str]] = []  # (source_id, target_id)
    for n in notes:
        src = str(n["id"])
        if not src:
            continue
        for target in n["links"]:  # type: ignore[union-attr]
            if target in all_ids:
                edges.append((src, target))

    if args.format == "json":
        json.dump(
            {
                "nodes": [
                    {"id": str(n["id"]), "type": str(n["type"]),
                     "domain": str(n["domain"]), "path": str(n["path"])}
                    for n in notes if n["id"]
                ],
                "edges": [{"from": s, "to": t} for s, t in edges],
            },
            sys.stdout, ensure_ascii=False, indent=2,
        )
        sys.stdout.write("\n")
        return 0

    if args.format == "dot":
        print("digraph atlas {")
        print('  rankdir=LR;')
        print('  node [fontsize=10];')
        by_domain: dict[str, list[dict]] = defaultdict(list)
        for n in notes:
            if n["id"]:
                by_domain[str(n["domain"])].append(n)
        for domain, items in sorted(by_domain.items()):
            print(f'  subgraph cluster_{_md_id_safe(domain)} {{')
            print(f'    label="{domain}";')
            for n in items:
                nid = _md_id_safe(str(n["id"]))
                short = str(n["id"])[:40]
                print(f'    {nid} [label="{short}\\n[{n["type"]}]"];')
            print('  }')
        for s, t in edges:
            print(f"  {_md_id_safe(s)} -> {_md_id_safe(t)};")
        print("}")
        return 0

    # mermaid (default)
    print("```mermaid")
    print("graph LR")
    by_domain: dict[str, list[dict]] = defaultdict(list)
    for n in notes:
        if n["id"]:
            by_domain[str(n["domain"])].append(n)
    for domain, items in sorted(by_domain.items()):
        sub_id = _md_id_safe(domain)
        print(f"  subgraph {sub_id}[{domain}]")
        for n in items:
            nid = _md_id_safe(str(n["id"]))
            short = str(n["id"])[:40].replace('"', "'")
            t = str(n["type"])
            tpl = _MERMAID_TYPE_SHAPE.get(t, '{0}["{1}"]')
            print(f"    {tpl.format(nid, short)}")
        print("  end")
    print()
    for s, t in edges:
        print(f"  {_md_id_safe(s)} --> {_md_id_safe(t)}")
    # Type legend
    print()
    print("  classDef concept fill:#e1f5ff,stroke:#0288d1;")
    print("  classDef decision fill:#fff3e0,stroke:#f57c00;")
    print("  classDef artifact fill:#f3e5f5,stroke:#7b1fa2;")
    print("  classDef procedure fill:#e8f5e9,stroke:#388e3c;")
    print("  classDef moc fill:#fce4ec,stroke:#c2185b;")
    print("  classDef journal fill:#f5f5f5,stroke:#616161;")
    for n in notes:
        if n["id"] and n["type"] in _MERMAID_TYPE_SHAPE:
            print(f"  class {_md_id_safe(str(n['id']))} {n['type']};")
    print("```")
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    """Semantic search via TF-IDF (lib/atlas_embeddings)."""
    try:
        from lib.atlas_embeddings import build_index, invalidate
    except ImportError as e:
        print(f"[error] sklearn not installed (required for search): {e}",
              file=sys.stderr)
        return 1
    if args.rebuild:
        invalidate()
    try:
        index = build_index(force=False)
    except RuntimeError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1
    hits = index.search(args.query, top_k=args.top_k)
    # Telemetry: opt-out via --no-log. Append-only JSONL.
    if hits and not args.no_log:
        _append_search_log(args.query, hits)
    if args.json:
        json.dump(
            [{"note_id": h.note_id, "path": h.path,
              "score": h.score, "snippet": h.snippet} for h in hits],
            sys.stdout, ensure_ascii=False, indent=2,
        )
        sys.stdout.write("\n")
        return 0
    if not hits:
        print("(no hits)")
        return 0
    for h in hits:
        print(f"  [{h.score:.3f}] {h.note_id}")
        print(f"          path: {h.path}")
        print(f"          snippet: {h.snippet}")
        print()
    print(f"[{len(hits)} hits]")
    return 0


def _append_search_log(query: str, hits) -> None:
    """Append (ts, query, top-3 hits) to search-log JSONL. Fail-open."""
    try:
        _SEARCH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts_unix_ms": int(time.time() * 1000),
            "query": query,
            "top_hits": [
                {"note_id": h.note_id, "score": round(h.score, 4)}
                for h in hits[:3]
            ],
        }
        with _SEARCH_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass  # fail-open — telemetry must not break search


def _cmd_promotion_candidates(args: argparse.Namespace) -> int:
    """Scan sub-brain projects for promotion candidates (3-axes pre-check).

    Algorithm:
    1. Walk each --scan-root for `atlas/<domain>/<type>/*.md`
    2. Parse frontmatter id + type + debate_sid + tags
    3. Group notes by `(stem-without-debate-prefix, type)` similarity key
    4. Filter clusters: ≥3 distinct project paths (A-axis)
    5. Cross-check Core Atlas: drop clusters whose id already in Core (not new)
    6. Annotate B-axis (debate_sid present in any cluster member)
    7. Annotate C-axis (git log age via subprocess, best-effort)
    8. Rank by axes_met count + cluster size
    """
    scan_roots: list[Path] = [Path(r).expanduser().resolve() for r in args.scan_root]
    if not scan_roots:
        print("[error] --scan-root <path> required (at least one project root)",
              file=sys.stderr)
        return 1

    # Collect Core ids first (these are NOT candidates — already promoted).
    core_ids: set[str] = set()
    if ATLAS_DIR.is_dir():
        for path in ATLAS_DIR.rglob("*.md"):
            result = parse_frontmatter(path)
            if result is None:
                continue
            meta, _body = result
            nid = (meta.get("id") or "").strip()
            if nid:
                core_ids.add(nid)

    # Scan each root's atlas/ dir.
    # records: (project_name, atlas_relpath, note_id, type, debate_sid, body_hash)
    records: list[dict] = []
    for root in scan_roots:
        atlas_dir = root / "atlas"
        if not atlas_dir.is_dir():
            continue
        project_name = root.name
        for path in atlas_dir.rglob("*.md"):
            result = parse_frontmatter(path)
            if result is None:
                continue
            meta, body = result
            nid = (meta.get("id") or "").strip()
            if not nid:
                continue
            records.append({
                "project": project_name,
                "rel_path": str(path.relative_to(atlas_dir)).replace("\\", "/"),
                "note_id": nid,
                "type": (meta.get("type") or "").strip(),
                "debate_sid": (meta.get("debate_sid") or "").strip(),
                "body_hash": hashlib.sha256(body.encode("utf-8")).hexdigest()[:12],
            })

    if not records:
        print(f"[info] no sub-brain notes found under {[str(r) for r in scan_roots]}")
        return 0

    # Cluster by note_id (identical id across projects = same concept).
    by_id: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        by_id[rec["note_id"]].append(rec)

    candidates: list[dict] = []
    for nid, recs in by_id.items():
        if nid in core_ids:
            continue  # already in Core, not a candidate
        distinct_projects = {r["project"] for r in recs}
        if len(distinct_projects) < args.min_projects:
            continue
        # A-axis: distinct projects ≥ min_projects
        axes_met = ["A"]
        # B-axis: any cluster member has debate_sid in frontmatter
        if any(r["debate_sid"] for r in recs):
            axes_met.append("B")
        # C-axis: best-effort git age (oldest mtime among cluster members)
        oldest_mtime = min(
            (Path(scan_roots[0].parent / r["project"] / "atlas" / r["rel_path"]).stat().st_mtime
             for r in recs
             if (scan_roots[0].parent / r["project"] / "atlas" / r["rel_path"]).exists()),
            default=time.time(),
        )
        age_days = (time.time() - oldest_mtime) / 86400.0
        if age_days >= 30:
            axes_met.append("C")
        candidates.append({
            "note_id": nid,
            "type": recs[0]["type"],
            "distinct_projects": sorted(distinct_projects),
            "project_count": len(distinct_projects),
            "axes_met": axes_met,
            "age_days": round(age_days, 1),
            "recs": [{"project": r["project"], "path": r["rel_path"]}
                     for r in recs],
        })

    # Sort: axes_met count desc, then cluster size desc
    candidates.sort(key=lambda c: (-len(c["axes_met"]), -c["project_count"]))

    if args.json:
        json.dump({"scan_roots": [str(r) for r in scan_roots],
                   "core_ids_count": len(core_ids),
                   "candidates": candidates},
                  sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    print(f"# Promotion candidates")
    print(f"# scan_roots: {len(scan_roots)} ({', '.join(r.name for r in scan_roots)})")
    print(f"# Core ids known: {len(core_ids)}")
    print(f"# Sub-brain records scanned: {len(records)}")
    print(f"# Candidates (A-axis ≥{args.min_projects} projects): {len(candidates)}\n")
    if not candidates:
        print("(no candidates — need ≥{} distinct sub-brain projects with shared note ids)".format(args.min_projects))
        print("\nWhen ready: HARNESS_MUTATION_TOKEN=promote-to-core python -m cli.promote_atlas_note ...")
        return 0
    for c in candidates:
        marker = "✓" if "C" in c["axes_met"] and "B" in c["axes_met"] else "•"
        print(f"  {marker} {c['note_id']}  [{c['type']}]")
        print(f"          axes: {''.join(c['axes_met']):3}  projects: {c['project_count']}  age: {c['age_days']}d")
        for r in c["recs"]:
            print(f"          - {r['project']}/{r['path']}")
        print()
    print(f"[{len(candidates)} candidates]")
    return 0


def _cmd_history(args: argparse.Namespace) -> int:
    """Git-history for a note (via id or relative path). Renames followed."""
    target = args.target
    if not target:
        print("[error] history requires <note-id or path>", file=sys.stderr)
        return 1
    # Resolve id → path
    notes = _collect_notes()
    note_path: Path | None = None
    if "/" in target or target.endswith(".md"):
        # treat as relative path under ATLAS_DIR
        candidate = ATLAS_DIR / target
        if candidate.exists():
            note_path = candidate
    if note_path is None:
        for n in notes:
            if str(n["id"]) == target:
                note_path = ATLAS_DIR / str(n["path"])
                break
    if note_path is None:
        print(f"[error] target {target!r} not found (try `atlas_index list`)",
              file=sys.stderr)
        return 1
    try:
        result = subprocess.run(
            ["git", "log", "--follow",
             "--pretty=format:%h|%ai|%an|%s",
             "--", str(note_path)],
            cwd=ATLAS_DIR.parent,
            capture_output=True, text=True, encoding="utf-8",
        )
    except FileNotFoundError:
        print("[error] git not on PATH", file=sys.stderr)
        return 1
    if result.returncode != 0:
        print(f"[error] git log failed: {result.stderr.strip()}", file=sys.stderr)
        return 1
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    if not lines:
        print(f"  (no git history — file may not be committed yet: {note_path.relative_to(ATLAS_DIR)})")
        return 0
    if args.json:
        records = []
        for ln in lines:
            parts = ln.split("|", 3)
            if len(parts) == 4:
                records.append({"sha": parts[0], "date": parts[1],
                                "author": parts[2], "subject": parts[3]})
        json.dump(records, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    print(f"# History for {note_path.relative_to(ATLAS_DIR)}")
    print(f"# {len(lines)} commits (newest first)\n")
    for ln in lines[:args.limit]:
        parts = ln.split("|", 3)
        if len(parts) == 4:
            sha, date, author, subject = parts
            print(f"  {sha}  {date[:19]}  {author:20}  {subject}")
    if len(lines) > args.limit:
        print(f"\n  ... ({len(lines) - args.limit} earlier commits — use --limit N)")
    return 0


def _cmd_utilization(args: argparse.Namespace) -> int:
    """Aggregate search-log JSONL: which notes get hit most often."""
    if not _SEARCH_LOG_PATH.exists():
        print(f"(no search log yet at {_SEARCH_LOG_PATH})")
        print("Run `atlas_index search <query>` a few times to accumulate data.")
        return 0
    hit_counts: dict[str, int] = defaultdict(int)
    query_count = 0
    try:
        with _SEARCH_LOG_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                query_count += 1
                for hit in rec.get("top_hits", []):
                    if isinstance(hit, dict) and hit.get("note_id"):
                        hit_counts[hit["note_id"]] += 1
    except OSError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1
    if not hit_counts:
        print("(no hits aggregated)")
        return 0
    # Top-N + bottom-N (cold notes) view
    sorted_hits = sorted(hit_counts.items(), key=lambda kv: -kv[1])
    if args.json:
        json.dump(
            {"total_queries": query_count,
             "hit_counts": dict(sorted_hits[:args.top_k])},
            sys.stdout, ensure_ascii=False, indent=2,
        )
        sys.stdout.write("\n")
        return 0
    print(f"# Atlas utilization (from {query_count} search queries)\n")
    print(f"## Top {args.top_k} most-hit notes\n")
    for note_id, count in sorted_hits[:args.top_k]:
        print(f"  {count:4d}  {note_id}")
    # Cold notes: in vault but never hit
    notes = _collect_notes()
    all_ids = {str(n["id"]) for n in notes if n["id"]}
    cold = sorted(all_ids - set(hit_counts.keys()))
    print(f"\n## Cold notes ({len(cold)} never hit by search)")
    for note_id in cold[:args.top_k]:
        print(f"        {note_id}")
    if len(cold) > args.top_k:
        print(f"        ... ({len(cold) - args.top_k} more)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="atlas_index")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list all notes")
    p_list.add_argument("--domain", help="filter by domain name")
    p_list.add_argument("--type", help="filter by type (concept/decision/artifact/procedure/journal/meta/moc)")
    p_list.add_argument("--tail", type=int, default=0, help="show last N entries")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(fn=_cmd_list)

    p_stats = sub.add_parser("stats", help="count per domain × type")
    p_stats.set_defaults(fn=_cmd_stats)

    p_table = sub.add_parser("table", help="emit markdown domain table for INDEX.md")
    p_table.set_defaults(fn=_cmd_table)

    p_orph = sub.add_parser("orphans", help="concepts/decisions/artifacts not referenced anywhere")
    p_orph.set_defaults(fn=_cmd_orphans)

    p_bl = sub.add_parser("broken-links", help="links: targets that do not exist in vault")
    p_bl.set_defaults(fn=_cmd_broken_links)

    p_graph = sub.add_parser("graph", help="emit link graph (mermaid|dot|json) for visualization")
    p_graph.add_argument("--format", choices=("mermaid", "dot", "json"),
                         default="mermaid", help="output format")
    p_graph.add_argument("--domain", help="filter to single domain (subgraph view)")
    p_graph.set_defaults(fn=_cmd_graph)

    p_search = sub.add_parser("search", help="semantic search via TF-IDF char-ngram (sklearn)")
    p_search.add_argument("query", help="search query (Korean/English mixed OK)")
    p_search.add_argument("--top-k", type=int, default=5, help="number of hits")
    p_search.add_argument("--rebuild", action="store_true",
                          help="force rebuild of search index")
    p_search.add_argument("--no-log", action="store_true",
                          help="skip telemetry append (atlas-search-log.jsonl)")
    p_search.add_argument("--json", action="store_true")
    p_search.set_defaults(fn=_cmd_search)

    p_hist = sub.add_parser("history", help="git log for a note (--follow rename-safe)")
    p_hist.add_argument("target", help="note id OR relative path under ATLAS_DIR")
    p_hist.add_argument("--limit", type=int, default=20, help="max commits to show")
    p_hist.add_argument("--json", action="store_true")
    p_hist.set_defaults(fn=_cmd_history)

    p_util = sub.add_parser("utilization", help="aggregate search-log: hot/cold notes")
    p_util.add_argument("--top-k", type=int, default=10, help="rank size")
    p_util.add_argument("--json", action="store_true")
    p_util.set_defaults(fn=_cmd_utilization)

    p_pc = sub.add_parser("promotion-candidates",
                          help="scan sub-brain projects for promotion candidates (3-axes)")
    p_pc.add_argument("--scan-root", action="append", default=[],
                      help="project root containing `atlas/` (repeat for N roots)")
    p_pc.add_argument("--min-projects", type=int, default=3,
                      help="A-axis threshold (default 3 per promotion-policy)")
    p_pc.add_argument("--json", action="store_true")
    p_pc.set_defaults(fn=_cmd_promotion_candidates)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
