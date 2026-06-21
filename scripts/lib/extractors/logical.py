"""Reverse-engineer .claude/design/er/logical-design.md from DDL files.

Extracts:
- Per-table column list (name, type, nullability, key flags)
- PRIMARY KEY columns
- FOREIGN KEY columns (cross-references conceptual ER)
- INDEX statements (CREATE INDEX or KEY clauses inside CREATE TABLE)

Output passes validators/logical.py basic checks (table list + PK/FK/INDEX).
"""
from __future__ import annotations

import re
from pathlib import Path

from .base import ExtractionResult, find_sql_sources, safe_read


_CREATE_TABLE_RE = re.compile(
    # Body is everything up to the closing `)` followed by optional whitespace
    # then either `;` or table options like `ENGINE=...`. Greedy `.+` handles
    # nested parens inside column type declarations (e.g. VARCHAR(64)).
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?(\w+)[`\"]?\s*\((.+?)\)\s*(?:ENGINE|;|$)",
    re.IGNORECASE | re.DOTALL,
)
# column line: `name type ...constraints`. Crude — splits on top-level commas.
_PRIMARY_KEY_RE = re.compile(
    r"PRIMARY\s+KEY\s*\(\s*([^)]+?)\s*\)", re.IGNORECASE,
)
_INDEX_RE = re.compile(
    r"(?:UNIQUE\s+)?(?:KEY|INDEX)\s+[`\"]?(\w+)[`\"]?\s*\(([^)]+?)\)",
    re.IGNORECASE,
)
_CREATE_INDEX_RE = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+[`\"]?(\w+)[`\"]?\s+ON\s+[`\"]?(\w+)[`\"]?\s*\(([^)]+?)\)",
    re.IGNORECASE,
)
_COLUMN_LINE_RE = re.compile(
    r"^\s*[`\"]?(\w+)[`\"]?\s+(\w+\s*(?:\([^)]*\))?)\s*([^,\n]*?)\s*(?:,|$)",
    re.MULTILINE,
)


class LogicalExtractor:
    name = "logical"
    target = ".claude/design/er/logical-design.md"
    description = "Reverse-engineer logical design (columns + PK/FK/INDEX) from DDL"

    def can_extract(self, root: Path) -> bool:
        return bool(find_sql_sources(root, max_files=1))

    def parse_logical(self, root: Path) -> tuple[dict, list, list]:
        """Structured DDL parse: (tables{name:{columns,pk,indexes}},
        global_indexes[(idx,table,cols)], sources[]). Reused by extract() (markdown
        render) AND the spec_facets logical-facet converter (typed schema) so both
        share one parser. Empty if no DDL."""
        sql_files = find_sql_sources(root)
        if not sql_files:
            return {}, [], []
        sources = [p.relative_to(root).as_posix() for p in sql_files[:20]]
        tables: dict[str, dict] = {}
        global_indexes: list[tuple[str, str, str]] = []
        for f in sql_files:
            text = safe_read(f)
            for m in _CREATE_TABLE_RE.finditer(text):
                table = m.group(1)
                body = m.group(2)
                tables[table] = {
                    "columns": self._parse_columns(body),
                    "pk": self._parse_pk(body),
                    "indexes": self._parse_indexes(body),
                }
            for m in _CREATE_INDEX_RE.finditer(text):
                global_indexes.append((m.group(1), m.group(2), m.group(3)))
        return tables, global_indexes, sources

    def extract(self, root: Path) -> ExtractionResult:
        tables, global_indexes, sources = self.parse_logical(root)
        if not tables and not sources:
            return ExtractionResult(
                extractor=self.name, target=self.target,
                content="# Logical Design (no DDL found)\n",
                confidence=0.0, notes=["no .sql files"],
            )

        signals = (
            (1 if tables else 0)
            + (1 if any(t["pk"] for t in tables.values()) else 0)
            + (1 if any(t["indexes"] for t in tables.values()) or global_indexes else 0)
        )
        confidence = round(0.4 + 0.2 * signals, 2)

        notes = [
            f"tables={len(tables)}",
            f"global_indexes={len(global_indexes)}",
        ]
        if not tables:
            notes.append("no CREATE TABLE detected")

        content = self._render(tables, global_indexes)

        return ExtractionResult(
            extractor=self.name,
            target=self.target,
            content=content,
            confidence=min(confidence, 1.0),
            notes=notes,
            sources=sources,
        )

    def _parse_columns(self, body: str) -> list[tuple[str, str, str]]:
        out: list[tuple[str, str, str]] = []
        # Skip lines that start with table-level constraints
        seen_names: set[str] = set()
        for m in _COLUMN_LINE_RE.finditer(body):
            name = m.group(1)
            type_ = m.group(2)
            tail = m.group(3).strip()
            # Skip reserved keywords that look like column names
            if name.upper() in {
                "PRIMARY", "FOREIGN", "KEY", "INDEX", "UNIQUE",
                "CONSTRAINT", "CHECK",
            }:
                continue
            if name in seen_names:
                continue
            seen_names.add(name)
            out.append((name, type_, tail))
            if len(out) >= 80:
                break
        return out

    def _parse_pk(self, body: str) -> list[str]:
        m = _PRIMARY_KEY_RE.search(body)
        if not m:
            # inline PK: `id BIGINT PRIMARY KEY`
            inline = re.search(
                r"^\s*[`\"]?(\w+)[`\"]?\s+\w+[^,]*PRIMARY\s+KEY",
                body, re.MULTILINE | re.IGNORECASE,
            )
            if inline:
                return [inline.group(1)]
            return []
        return [c.strip().strip("`\"") for c in m.group(1).split(",")]

    def _parse_indexes(self, body: str) -> list[tuple[str, str]]:
        # _INDEX_RE requires `KEY|INDEX` followed by a `\w+` name, so it
        # cannot match `PRIMARY KEY (id)` (no name between KEY and `(`).
        # Therefore no extra filter needed.
        return [(m.group(1), m.group(2).strip()) for m in _INDEX_RE.finditer(body)]

    def _render(self, tables: dict, global_indexes: list[tuple[str, str, str]]) -> str:
        L = []
        L.append("<!-- AUTO-GENERATED by lib.extractors.logical — review and refine. -->")
        L.append("")
        L.append("# Logical Design")
        L.append("")
        L.append(f"_총 테이블: {len(tables)}_")
        L.append("")

        for table, info in tables.items():
            L.append(f"## {table}")
            L.append("")
            L.append("| 컬럼 | 타입 | 제약 | 키 |")
            L.append("|---|---|---|---|")
            pk_set = set(info["pk"])
            idx_cols: set[str] = set()
            for _idx_name, idx_def in info["indexes"]:
                for c in idx_def.split(","):
                    idx_cols.add(c.strip().strip("`\""))

            for name, type_, tail in info["columns"]:
                key_flags: list[str] = []
                if name in pk_set:
                    key_flags.append("PK")
                if name in idx_cols:
                    key_flags.append("INDEX")
                if "REFERENCES" in tail.upper() or "FOREIGN" in tail.upper():
                    key_flags.append("FK")
                key = ", ".join(key_flags) or "-"
                tail_clean = tail.replace("|", "\\|")
                L.append(f"| {name} | {type_} | {tail_clean} | {key} |")
            L.append("")

            if info["indexes"]:
                L.append("**Indexes:**")
                for idx_name, idx_def in info["indexes"]:
                    L.append(f"- `{idx_name}` ON ({idx_def})")
                L.append("")

        if global_indexes:
            L.append("## 전역 INDEX")
            L.append("")
            for idx_name, table, cols in global_indexes:
                L.append(f"- `{idx_name}` ON {table}({cols})")
            L.append("")

        return "\n".join(L) + "\n"


# Lazy-registry export (matches lib.providers PROVIDER / lib.workers MULTIPLEXER pattern).
EXTRACTOR = LogicalExtractor
