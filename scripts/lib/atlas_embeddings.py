"""atlas_embeddings — TF-IDF semantic search for Atlas vault notes.

Backend choice: sklearn TfidfVectorizer with char_wb n-grams (2-5) — multilingual
(Korean + English) friendly, no torch/transformers dependency, deterministic.

For ~100-1000 note vaults the quality is acceptable (lexical-aware semantic
similarity). For >10k notes or higher recall, swap to a neural embedding
backend (sentence-transformers, codex embeddings) at the SearchIndex constructor.

Pluggable interface — subclass `BaseSearchIndex` + override
`_fit_vectors` and `_score_query` to swap backends.

Storage: `~/.claude/state/atlas-search-index.npz` (sparse TF-IDF matrix
+ doc metadata + vectorizer pickle). Mtime-based lazy rebuild.

Public surface (used by cli/atlas_index.py):
    build_index(force: bool = False) -> SearchIndex
    SearchIndex.search(query: str, top_k: int = 5) -> list[SearchHit]
    SearchIndex.invalidate() -> None

Cross-ref: doc-writer / dge-cycle / atlas-system 도메인 의 atom retrieval
의 ground-truth alternative to grep.
"""
from __future__ import annotations

import hashlib
import json
import pickle
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.paths import ATLAS_DIR, STATE_DIR


SEARCH_INDEX_PATH: Path = STATE_DIR / "atlas-search-index.pkl"
SEARCH_META_PATH: Path = STATE_DIR / "atlas-search-meta.json"

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)", re.DOTALL)
_ID_LINE_RE = re.compile(r"^id:\s*(\S+)\s*$", re.MULTILINE)


@dataclass
class SearchHit:
    """One search result."""
    note_id: str
    path: str
    score: float
    snippet: str


@dataclass
class _DocMeta:
    note_id: str
    rel_path: str
    mtime_ns: int
    sha256: str


def _content_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _extract_id_and_body(text: str) -> tuple[str | None, str]:
    """Parse frontmatter, return (id, full_indexable_text).

    Indexable text = frontmatter values (id/description/tags) + body.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None, text
    fm_block = m.group(1)
    body = m.group(2)
    id_match = _ID_LINE_RE.search(fm_block)
    note_id = id_match.group(1) if id_match else None
    # Indexable: include frontmatter (description/tags are searchable signal)
    indexable = fm_block + "\n" + body
    return note_id, indexable


def _scan_vault() -> list[tuple[Path, _DocMeta, str]]:
    """Walk ATLAS_DIR, return [(path, meta, indexable_text)]."""
    out: list[tuple[Path, _DocMeta, str]] = []
    if not ATLAS_DIR.is_dir():
        return out
    for path in sorted(ATLAS_DIR.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        note_id, indexable = _extract_id_and_body(text)
        if not note_id:
            # Skip notes without id (validator catches these separately)
            continue
        stat = path.stat()
        meta = _DocMeta(
            note_id=note_id,
            rel_path=str(path.relative_to(ATLAS_DIR)).replace("\\", "/"),
            mtime_ns=stat.st_mtime_ns,
            sha256=_content_sha(text),
        )
        out.append((path, meta, indexable))
    return out


def _load_meta() -> list[_DocMeta] | None:
    if not SEARCH_META_PATH.exists():
        return None
    try:
        raw = json.loads(SEARCH_META_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return [_DocMeta(**rec) for rec in raw]


def _save_meta(metas: list[_DocMeta]) -> None:
    SEARCH_META_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {"note_id": m.note_id, "rel_path": m.rel_path,
         "mtime_ns": m.mtime_ns, "sha256": m.sha256}
        for m in metas
    ]
    SEARCH_META_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _is_index_stale(current_metas: list[_DocMeta]) -> bool:
    """True if vault changed since last index build."""
    cached = _load_meta()
    if cached is None or not SEARCH_INDEX_PATH.exists():
        return True
    if len(cached) != len(current_metas):
        return True
    # sha256-based check (mtime alone can race; sha is authoritative)
    cached_map = {m.rel_path: m.sha256 for m in cached}
    for m in current_metas:
        if cached_map.get(m.rel_path) != m.sha256:
            return True
    return False


class SearchIndex:
    """TF-IDF char-ngram search index over Atlas vault."""

    def __init__(self, vectorizer, matrix, metas: list[_DocMeta]) -> None:
        self._vectorizer = vectorizer
        self._matrix = matrix  # sparse csr_matrix shape (N, F)
        self._metas = metas

    def search(self, query: str, top_k: int = 5) -> list[SearchHit]:
        """Return top-k hits by cosine similarity (TF-IDF L2-normalized)."""
        from sklearn.metrics.pairwise import linear_kernel
        if not query.strip():
            return []
        q_vec = self._vectorizer.transform([query])
        # TF-IDF default is L2-normalized → linear_kernel == cosine
        sims = linear_kernel(q_vec, self._matrix).ravel()
        # Top-k indices (descending score)
        if top_k >= len(sims):
            order = sims.argsort()[::-1]
        else:
            # argpartition is faster than full sort for top-k
            part = sims.argpartition(-top_k)[-top_k:]
            order = part[sims[part].argsort()[::-1]]
        out: list[SearchHit] = []
        for idx in order[:top_k]:
            score = float(sims[idx])
            if score <= 0:
                continue
            meta = self._metas[int(idx)]
            snippet = self._make_snippet(meta, query)
            out.append(SearchHit(
                note_id=meta.note_id,
                path=meta.rel_path,
                score=score,
                snippet=snippet,
            ))
        return out

    def _make_snippet(self, meta: _DocMeta, query: str) -> str:
        """Best-effort snippet — first window containing any query token."""
        try:
            text = (ATLAS_DIR / meta.rel_path).read_text(encoding="utf-8")
        except OSError:
            return ""
        # Strip frontmatter for snippet
        m = _FRONTMATTER_RE.match(text)
        body = m.group(2) if m else text
        body_lower = body.lower()
        tokens = [t for t in re.split(r"\W+", query.lower()) if t]
        for tok in tokens:
            idx = body_lower.find(tok)
            if idx >= 0:
                start = max(0, idx - 60)
                end = min(len(body), idx + 120)
                snippet = body[start:end].replace("\n", " ").strip()
                return snippet + ("…" if end < len(body) else "")
        # Fallback: first 180 chars
        return body[:180].replace("\n", " ").strip()


def build_index(force: bool = False) -> SearchIndex:
    """Build (or rebuild if stale) the search index.

    Persistence: pickled vectorizer + sparse matrix + JSON metadata.
    Mtime+sha-based invalidation — fast no-op if vault unchanged.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer

    scanned = _scan_vault()
    if not scanned:
        raise RuntimeError(
            f"ATLAS_DIR ({ATLAS_DIR}) empty or absent — no notes to index."
        )

    metas = [meta for (_p, meta, _t) in scanned]

    if not force and not _is_index_stale(metas) and SEARCH_INDEX_PATH.exists():
        # Load cached
        with SEARCH_INDEX_PATH.open("rb") as f:
            vectorizer, matrix = pickle.load(f)
        return SearchIndex(vectorizer, matrix, metas)

    # Rebuild
    texts = [t for (_p, _m, t) in scanned]
    vectorizer = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(2, 5),
        min_df=1,
        max_df=0.95,
        sublinear_tf=True,
        norm="l2",
    )
    matrix = vectorizer.fit_transform(texts)

    SEARCH_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SEARCH_INDEX_PATH.open("wb") as f:
        pickle.dump((vectorizer, matrix), f, protocol=pickle.HIGHEST_PROTOCOL)
    _save_meta(metas)

    return SearchIndex(vectorizer, matrix, metas)


def invalidate() -> None:
    """Force next build_index() to rebuild from scratch."""
    for p in (SEARCH_INDEX_PATH, SEARCH_META_PATH):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
