"""doc_classifier — classify loose ADR/PRD/SPEC docs into planning buckets (P2 D2).

Converged design: debate-1780870185-827a94 (ontology sha1 41c9cc8f...),
decision D2 "ingest-docs".

The single honest net-new ENGINE for greenfield-from-docs ingest. The existing
extractor registry ({convention, er, logical}) is Java/SQL-DDL-only and CANNOT
classify prose markdown — verified — so this fills a real gap as ONE new
extractor registered via the _REGISTRY_ORDER OCP hook (no edits to existing
extractors).

Classification is DETERMINISTIC (filename + section-heading heuristics), NEVER a
comparative verdict / ranking — preserving the kha-framework-selector neutrality
invariant. Buckets: {requirement, constraint, glossary, artifact}.

Two consumers:
- cli.ingest_docs (primary) — emits .planning/SPEC-seed.md + .planning/glossary.md.
- cli.reverse_engineer (registry walk) — would emit only the single registry
  target (.planning/SPEC-seed.md) IF can_extract fires. can_extract is therefore
  CONSERVATIVE (strong ADR/PRD/SPEC signals only) so a normal code-reverse run
  is not contaminated.
"""
from __future__ import annotations

import re
from pathlib import Path

from .base import ExtractionResult, safe_read

BUCKETS = ("requirement", "constraint", "glossary", "artifact")

# Priority order: first bucket whose keyword matches (filename beats content).
_BUCKET_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("glossary", ("glossary", "vocabulary", "terminology", "definitions", "용어")),
    ("requirement", ("requirement", "prd", "user-story", "user story",
                     "acceptance criteria", "요구사항", "기능요구")),
    ("constraint", ("constraint", "non-functional", "nfr", "sla",
                    "performance budget", "security requirement", "제약")),
    ("artifact", ("adr", "decision-record", "decision record", "architecture",
                  "design-doc", "design doc", "rfc", "spec", "설계")),
)

# Doc discovery — conservative: only files with strong spec/doc signals.
_DOC_DIRS = ("docs", "doc", "adr", "rfc", "spec", "requirements", "design")
_STRONG_NAME_RE = re.compile(
    r"(adr|prd|spec|rfc|requirement|glossary|architecture|decision|design)",
    re.IGNORECASE,
)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,3}\s+(.+?)\s*#*\s*$", re.MULTILINE)
# glossary term lines: "**term** — def" / "**term**: def" / "- term: def" / "term — def"
_TERM_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*(?P<t1>[^*]{1,60})\*\*|(?P<t2>[A-Za-z][\w ./-]{0,59}?))"
    r"\s*(?:—|--|:)\s+(?P<def>\S.{2,200}?)\s*$",
    re.MULTILINE,
)


_EXCLUDED_NAMES = frozenset(
    {"readme.md", "changelog.md", "contributing.md", "license.md"}
)


def find_doc_sources(root: Path, max_files: int = 200, *, liberal: bool = False) -> list[Path]:
    """Return prose .md docs to classify (bounded, sorted).

    Two modes:
    - CONSERVATIVE (default) — for can_extract / the reverse-engineer registry
      walk: only files under a doc dir (docs/, adr/, ...) OR whose name matches a
      strong spec keyword. Keeps a normal code repo from tripping can_extract.
    - LIBERAL — for explicit `/kha-ingest-docs --src <dir>`: the operator has
      pointed at a docs dir on purpose, so ingest EVERY .md under it (recursively)
      except the boilerplate set. This avoids dropping bucket-named files like
      `nfr.md` whose name is a classification keyword but not a discovery keyword.

    Either mode always excludes README/CHANGELOG/CONTRIBUTING/LICENSE.
    """
    out: list[Path] = []
    seen: set[Path] = set()

    def _consider(p: Path, eligible: bool) -> None:
        if p in seen or p.suffix.lower() != ".md":
            return
        if p.name.lower() in _EXCLUDED_NAMES:
            return
        if eligible:
            seen.add(p)
            out.append(p)

    if liberal:
        for p in root.rglob("*.md"):
            _consider(p, True)
            if len(out) >= max_files:
                break
        return sorted(out)

    for d in _DOC_DIRS:
        base = root / d
        if base.is_dir():
            for p in base.rglob("*.md"):
                _consider(p, True)
                if len(out) >= max_files:
                    return sorted(out)
    for p in root.glob("*.md"):
        _consider(p, bool(_STRONG_NAME_RE.search(p.stem)))
        if len(out) >= max_files:
            break
    return sorted(out)


def classify_doc(name: str, text: str) -> str:
    """Deterministically bucket one doc by filename then content keywords."""
    lname = name.lower()
    head = text[:1200].lower()
    for bucket, kws in _BUCKET_KEYWORDS:
        if any(kw in lname for kw in kws):
            return bucket
    for bucket, kws in _BUCKET_KEYWORDS:
        if any(kw in head for kw in kws):
            return bucket
    return "artifact"


def classify_doc_explained(name: str, text: str) -> dict:
    """classify_doc + WHY: {bucket, matched_by: 'filename'|'content'|'default',
    keyword}. Closes the kha-ingest-docs opacity gap ('heuristics not specified /
    classification opaque'). Mirrors classify_doc EXACTLY so the returned bucket is
    identical — this just additionally surfaces which heuristic fired."""
    lname = name.lower()
    head = text[:1200].lower()
    for bucket, kws in _BUCKET_KEYWORDS:
        for kw in kws:
            if kw in lname:
                return {"bucket": bucket, "matched_by": "filename", "keyword": kw}
    for bucket, kws in _BUCKET_KEYWORDS:
        for kw in kws:
            if kw in head:
                return {"bucket": bucket, "matched_by": "content", "keyword": kw}
    return {"bucket": "artifact", "matched_by": "default", "keyword": None}


def classify_explained(root: Path, *, liberal: bool = False) -> list[dict]:
    """Per-doc classification transparency report: a list of
    {path, bucket, matched_by, keyword, title}, deterministic + sorted by path. Lets
    the operator audit WHY each doc landed in its bucket and override mis-classifications
    before they propagate into SPEC-seed."""
    out: list[dict] = []
    for p in find_doc_sources(root, liberal=liberal):
        text = safe_read(p)
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            rel = p.name
        ex = classify_doc_explained(p.name, text)
        out.append({"path": rel, "bucket": ex["bucket"], "matched_by": ex["matched_by"],
                    "keyword": ex["keyword"], "title": _title(text, p.stem)})
    return sorted(out, key=lambda d: d["path"])


def _title(text: str, fallback: str) -> str:
    m = _HEADING_RE.search(text)
    return m.group(1).strip() if m else fallback


def classify(root: Path, *, liberal: bool = False) -> dict[str, list[dict[str, str]]]:
    """Classify every discovered doc into buckets.

    Returns {bucket: [{"path": rel, "title": str}]} plus a "_terms" key mapping
    to extracted glossary terms [{"term","def"}]. Deterministic + sorted.
    ``liberal`` is forwarded to find_doc_sources (True for explicit ingest).
    """
    buckets: dict[str, list[dict[str, str]]] = {b: [] for b in BUCKETS}
    terms: list[dict[str, str]] = []
    seen_terms: set[str] = set()
    for p in find_doc_sources(root, liberal=liberal):
        text = safe_read(p)
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            rel = p.name
        bucket = classify_doc(p.name, text)
        buckets[bucket].append({"path": rel, "title": _title(text, p.stem)})
        if bucket == "glossary":
            for m in _TERM_RE.finditer(text):
                term = (m.group("t1") or m.group("t2") or "").strip()
                definition = m.group("def").strip()
                key = term.lower()
                if term and key not in seen_terms:
                    seen_terms.add(key)
                    terms.append({"term": term, "def": definition})
    for b in BUCKETS:
        buckets[b].sort(key=lambda d: d["path"])
    terms.sort(key=lambda d: d["term"].lower())
    buckets["_terms"] = terms  # type: ignore[assignment]
    return buckets


def _section(title: str, items: list[dict[str, str]]) -> list[str]:
    lines = [f"## {title}", ""]
    if not items:
        lines.append("_(none classified)_")
    else:
        for it in items:
            lines.append(f"- {it['title']} — `{it['path']}`")
    lines.append("")
    return lines


def render_spec_seed(buckets: dict[str, list[dict[str, str]]]) -> str:
    """Render .planning/SPEC-seed.md from requirement/constraint/artifact buckets."""
    total = sum(len(buckets.get(b, [])) for b in BUCKETS)
    L = ["<!-- AUTO-GENERATED by kha-ingest-docs (P2 D2) — review and refine. -->",
         "", "# SPEC seed (ingested)", "",
         f"_Ingested {total} source doc(s) into deterministic buckets. "
         f"Run /harness-interview to close ambiguity before planning._", ""]
    L += _section("Requirements", buckets.get("requirement", []))
    L += _section("Constraints", buckets.get("constraint", []))
    L += _section("Source artifacts", buckets.get("artifact", []))
    return "\n".join(L) + "\n"


def render_glossary(buckets: dict[str, list[dict[str, str]]]) -> str:
    """Render .planning/glossary.md from the glossary bucket + extracted terms."""
    terms = buckets.get("_terms", [])  # type: ignore[assignment]
    docs = buckets.get("glossary", [])
    L = ["<!-- AUTO-GENERATED by kha-ingest-docs (P2 D2) — review and refine. -->",
         "", "# Glossary (ingested)", ""]
    if not terms:
        L.append("_(no glossary terms extracted)_")
    else:
        for t in terms:
            L.append(f"- **{t['term']}** — {t['def']}")
    L.append("")
    if docs:
        L += ["## Glossary sources", ""]
        for d in docs:
            L.append(f"- `{d['path']}`")
        L.append("")
    return "\n".join(L) + "\n"


class DocClassifier:
    name = "doc_classifier"
    target = ".planning/SPEC-seed.md"
    description = "Classify loose ADR/PRD/SPEC docs into planning buckets (greenfield ingest)"
    # Not a CODE extractor — registry consumers that walk all extractors
    # (cli.reverse_engineer default walk, cli.project_analyze preview) skip
    # this by default so a code-reverse run is never contaminated with a
    # .planning/SPEC-seed write. Invoke explicitly via cli.ingest_docs (primary)
    # or `cli.reverse_engineer --stage doc_classifier`. Existing code extractors
    # lack this attribute and default to code_extractor=True via getattr.
    code_extractor = False

    def can_extract(self, root: Path) -> bool:
        return bool(find_doc_sources(root, max_files=1))

    def extract(self, root: Path) -> ExtractionResult:
        buckets = classify(root)
        sources = sorted(
            it["path"] for b in BUCKETS for it in buckets.get(b, [])
        )
        signals = sum(1 for b in BUCKETS if buckets.get(b))
        confidence = 0.0 if not sources else min(0.4 + 0.1 * signals, 1.0)
        notes = [f"{b}={len(buckets.get(b, []))}" for b in BUCKETS]
        notes.append(f"terms={len(buckets.get('_terms', []))}")
        return ExtractionResult(
            extractor=self.name,
            target=self.target,
            content=render_spec_seed(buckets),
            confidence=round(confidence, 2),
            notes=notes,
            sources=sources,
        )


# Lazy-registry export (matches convention/er/logical pattern).
EXTRACTOR = DocClassifier
