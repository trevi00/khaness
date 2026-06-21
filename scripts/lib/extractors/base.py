"""Extractor protocol + shared helpers.

Each extractor reads from project root and emits an ExtractionResult containing:
- the markdown/yaml content for the pipeline-stage document
- a confidence score (0.0..1.0) — how sure we are the extraction is faithful
- diagnostic notes (what was found, what was guessed)

Confidence semantics:
- 0.9+ : full AST-grade extraction (we have rich source signals)
- 0.6-0.9 : heuristic regex extraction with most fields present
- 0.3-0.6 : sparse signal — output is a skeleton, needs human review
- < 0.3   : not worth surfacing; can_extract should return False
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class ExtractionResult:
    extractor: str          # e.g. "convention"
    target: str             # e.g. ".claude/convention.md"
    content: str            # markdown / yaml body
    confidence: float       # 0.0..1.0
    notes: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)  # files we read


class Extractor(Protocol):
    """Reverse-engineer a single pipeline document from project state."""

    name: str
    target: str
    description: str

    def can_extract(self, root: Path) -> bool:
        """Cheap pre-check — do we have enough source material to attempt extraction?"""
        ...

    def extract(self, root: Path) -> ExtractionResult:
        """Full extraction. Caller should check `can_extract` first."""
        ...


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

# Strip Java-style comments (//, /* */) line-by-line. Crude but stable for
# the small surface we parse — class headers, annotations, simple fields.
_LINE_COMMENT_RE = re.compile(r"//.*$")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def strip_java_comments(text: str) -> str:
    text = _BLOCK_COMMENT_RE.sub("", text)
    return "\n".join(_LINE_COMMENT_RE.sub("", line) for line in text.split("\n"))


def safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def find_java_sources(root: Path, max_files: int = 500) -> list[Path]:
    """Return all .java files under src/main/java/. Bounded to avoid blowups."""
    src = root / "src" / "main" / "java"
    if not src.is_dir():
        return []
    out: list[Path] = []
    for p in src.rglob("*.java"):
        out.append(p)
        if len(out) >= max_files:
            break
    return sorted(out)


def find_sql_sources(root: Path, max_files: int = 200) -> list[Path]:
    """Return DDL .sql files under common locations."""
    candidates: list[Path] = []
    for base in ("sql", "src/main/resources/db", "src/main/resources/sql",
                 "db", "migrations", "src/main/resources"):
        d = root / base
        if d.is_dir():
            for p in d.rglob("*.sql"):
                candidates.append(p)
                if len(candidates) >= max_files:
                    return sorted(candidates)
    return sorted(candidates)
