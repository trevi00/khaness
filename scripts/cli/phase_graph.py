"""phase_graph — CLI for the typed-edge phase graph (P2 D1).

Converged design: debate-1780870185-827a94 (ontology sha1 41c9cc8f...).

This is the DETERMINISTIC orchestrator post-step entry referenced by the
kha-plan-phase locked design — it runs OVER the already-written planning
artifacts, NOT inside the kha-planner LLM agent.

Usage (from ~/.claude/scripts):
    # refresh the graph after plans land (kha-plan-phase post-step)
    python -m cli.phase_graph build --root .planning

    # query: which phases DEPEND-ON phase-3?
    python -m cli.phase_graph query --root .planning --kind depends-on \
        --node phase-3 --direction in

Exit codes:
    0 success
    1 ROADMAP.md not found under --root
    2 bad arguments / query on a missing graph with --strict
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.phase_graph_builder import write_graph  # noqa: E402
from lib import phase_graph_query as pgq  # noqa: E402


def _cmd_build(args: argparse.Namespace) -> int:
    try:
        out = write_graph(args.root)
    except FileNotFoundError as e:
        print(f"[error] phase_graph build: {e}", file=sys.stderr)
        return 1
    graph = pgq.load(out)
    print(
        f"[done] phase_graph build: {out} "
        f"(nodes={len(graph['nodes'])} edges={len(graph['edges'])})"
    )
    return 0


def _cmd_query(args: argparse.Namespace) -> int:
    graph_path = Path(args.root) / "_graph" / "phase-graph.json"
    if args.strict and not graph_path.exists():
        print(f"[error] phase_graph query: no graph at {graph_path}", file=sys.stderr)
        return 2
    graph = pgq.load(graph_path)
    edges = pgq.query(graph, kind=args.kind, node=args.node, direction=args.direction)
    print(json.dumps(edges, indent=2, ensure_ascii=False))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="phase_graph", description="Typed-edge phase graph (P2 D1).")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="project ROADMAP.md + *-PLAN.md -> _graph/phase-graph.json")
    b.add_argument("--root", default=".planning", help="planning root (default: .planning)")
    b.set_defaults(func=_cmd_build)

    q = sub.add_parser("query", help="query typed edges")
    q.add_argument("--root", default=".planning", help="planning root (default: .planning)")
    q.add_argument("--kind", default=None, choices=[None, "depends-on", "realizes", "supersedes", "blocks"])
    q.add_argument("--node", default=None, help="node id, e.g. phase-3")
    q.add_argument("--direction", default="both", choices=["in", "out", "both"])
    q.add_argument("--strict", action="store_true", help="exit 2 if the graph file is missing")
    q.set_defaults(func=_cmd_query)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
