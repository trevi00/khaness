"""ingest_docs — greenfield .planning bootstrap from loose docs (P2 D2).

Converged design: debate-1780870185-827a94 (ontology sha1 41c9cc8f...).

Thin invocation wrapper over the ONE net-new engine lib.extractors.doc_classifier
(the engine is the classifier; this CLI only collects + emits, mirroring how
cli.reverse_engineer wraps the code extractors). Emits BOTH locked targets:
.planning/SPEC-seed.md + .planning/glossary.md.

Usage (from ~/.claude/scripts):
    python -m cli.ingest_docs --src <docs-dir> --out .planning            # write
    python -m cli.ingest_docs --src <docs-dir> --out .planning --dry-run  # preview counts

Deterministic. NO judge, NO comparative verdict. After ingest, run
/harness-interview to close ambiguity before /kha-plan-phase.

Exit codes: 0 success; 1 no classifiable docs found under --src; 2 bad args.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.extractors import doc_classifier as dc  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ingest_docs", description="Greenfield .planning bootstrap from loose docs (P2 D2).")
    ap.add_argument("--src", required=True, help="source dir holding loose ADR/PRD/SPEC docs")
    ap.add_argument("--out", default=".planning", help="output planning root (default: .planning)")
    ap.add_argument("--dry-run", action="store_true", help="report bucket counts without writing")
    args = ap.parse_args(argv)

    src = Path(args.src)
    if not src.is_dir():
        print(f"[error] ingest_docs: --src not a directory: {src}", file=sys.stderr)
        return 2

    # Explicit invocation: the operator pointed --src at a docs dir on purpose,
    # so ingest liberally (every .md under it), unlike the conservative
    # can_extract gate used by the reverse-engineer registry walk.
    buckets = dc.classify(src, liberal=True)
    counts = {b: len(buckets.get(b, [])) for b in dc.BUCKETS}
    n_terms = len(buckets.get("_terms", []))
    total = sum(counts.values())
    if total == 0:
        print(f"[error] ingest_docs: no classifiable ADR/PRD/SPEC docs under {src}", file=sys.stderr)
        return 1

    summary = ", ".join(f"{b}={counts[b]}" for b in dc.BUCKETS) + f", terms={n_terms}"
    # Transparency report (closes the 'classification opaque' gap): per-doc bucket +
    # which heuristic fired, so the operator can audit/override mis-classifications.
    report = dc.classify_explained(src, liberal=True)
    if args.dry_run:
        print(f"[dry-run] ingest_docs: {summary}")
        for r in report:
            kw = f" via {r['matched_by']}:{r['keyword']!r}" if r["keyword"] else " (default)"
            print(f"    {r['path']} -> {r['bucket']}{kw}")
        return 0

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    spec = out_root / "SPEC-seed.md"
    gloss = out_root / "glossary.md"
    spec.write_text(dc.render_spec_seed(buckets), encoding="utf-8")
    gloss.write_text(dc.render_glossary(buckets), encoding="utf-8")
    (out_root / ".ingest-classifier-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] ingest_docs: {spec} + {gloss} + .ingest-classifier-report.json ({summary})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
