"""spec_facets — typed STRUCTURAL facets of the Spec Bundle (unified-pipeline D1-2).

The Spec Bundle's spine is BEHAVIORAL Gherkin (lib.spec_bundle). Structural design
— ER, logical schema, class model, API contract — is NOT behavior and must NOT be
forced through the Gherkin spine (debate-1781665033-4f39ca, B4 category-error).
It lives in separate TYPED facets under `spec/facets/<kind>.schema` (YAML), each
element carrying a stable field-level `@id` (never a prose hash), so the forward
generator and the reverse extractor can agree on the same element identity.

Facet schema (generic across kinds):
    facet: er | logical | class | api
    schema_version: '1'
    elements:
      - id: <stable-slug>        # e.g. table/entity name — the @id
        kind: table | entity | class | endpoint
        <fields...>              # kind-specific (columns, pk, indexes, relationships…)

This module is the read/parse/validate half plus DETERMINISTIC converters from Java
source — DDL -> logical/er (reusing lib.extractors), and source -> class/api
(Spring controllers + class structure). Proven on the real example_service backend (43
tables, 137 classes, 92 endpoints across 21 controllers). It does NOT write into a
source project.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_VALID_KINDS = ("er", "logical", "class", "api")

# ── Java structural regexes (class + api facets) ──
# Reuse the same surface the convention extractor parses, kept local so a facet
# build never depends on the extractor's rendering internals.
_PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
# class/interface/enum header with its preceding annotations (rough, sufficient
# for layer classification — the layer annotation token survives truncation).
_CLASS_DECL_RE = re.compile(
    r"((?:@\w+(?:\([^)]*\))?\s*)*)"
    r"\bpublic\s+(?:final\s+|abstract\s+)?(class|interface|enum)\s+(\w+)",
    re.MULTILINE,
)
# class-level base path (first @RequestMapping string literal in the file)
_CLASS_REQUEST_MAPPING_RE = re.compile(r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?"([^"]+)"')
# handler mapping annotation + its full arg list (path extracted separately so
# value=/path=/positional all work)
_HANDLER_RE = re.compile(r"@(Get|Post|Put|Delete|Patch)Mapping\b(?:\s*\(([^)]*)\))?")
_FIRST_STR_RE = re.compile(r'"([^"]*)"')
# the handler method name following the mapping annotation (skip other annotations)
_METHOD_NAME_RE = re.compile(r"(?:public|protected|private)\s+[\w<>,.\[\]?\s]+?\s+(\w+)\s*\(")


@dataclass
class FacetElement:
    id: str
    kind: str = ""
    data: dict = field(default_factory=dict)   # kind-specific fields


@dataclass
class Facet:
    kind: str
    schema_version: str = "1"
    elements: list[FacetElement] = field(default_factory=list)

    def element_ids(self) -> list[str]:
        return [e.id for e in self.elements]

    def to_yaml_doc(self) -> dict:
        return {
            "facet": self.kind,
            "schema_version": self.schema_version,
            "elements": [{"id": e.id, "kind": e.kind, **e.data} for e in self.elements],
        }


def parse_facet(text: str) -> Facet | None:
    """Parse a facet `.schema` (YAML). Returns None on a non-facet/garbled doc."""
    try:
        data = yaml.safe_load(text)
    except Exception:
        return None
    if not isinstance(data, dict) or "facet" not in data:
        return None
    f = Facet(kind=str(data.get("facet", "")),
              schema_version=str(data.get("schema_version", "1")))
    for raw in data.get("elements") or []:
        if not isinstance(raw, dict) or "id" not in raw:
            continue
        eid = str(raw["id"])
        ekind = str(raw.get("kind", ""))
        rest = {k: v for k, v in raw.items() if k not in ("id", "kind")}
        f.elements.append(FacetElement(id=eid, kind=ekind, data=rest))
    return f


def validate_facet(facet: Facet) -> list[str]:
    """Return a list of problems (empty = valid). Pure. Checks: known kind,
    non-empty + unique element @ids (the round-trip contract)."""
    problems: list[str] = []
    if facet.kind not in _VALID_KINDS:
        problems.append(f"unknown facet kind {facet.kind!r} (expected one of {_VALID_KINDS})")
    seen: set[str] = set()
    for e in facet.elements:
        if not e.id:
            problems.append("element with empty @id")
            continue
        if e.id in seen:
            problems.append(f"duplicate element @id {e.id!r} — ids must be unique")
        seen.add(e.id)
    return problems


def load_facet(path: Path) -> Facet | None:
    try:
        return parse_facet(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ── deterministic converter: Java DDL (lib.extractors.logical) -> logical facet ──
def logical_facet_from_project(root: str | Path) -> Facet:
    """Build a typed `logical` facet from a project's DDL, reusing the existing
    logical extractor's parser. Each table -> one element (@id = table name) with
    columns/pk/indexes. Deterministic, read-only. Proven on the example_service backend."""
    from .extractors.logical import LogicalExtractor
    tables, global_indexes, _sources = LogicalExtractor().parse_logical(Path(root))
    # attach global CREATE INDEX rows to their table
    gidx: dict[str, list] = {}
    for idx_name, table, cols in global_indexes:
        gidx.setdefault(table, []).append({"name": idx_name, "columns": cols})

    facet = Facet(kind="logical")
    for name in sorted(tables):
        t = tables[name]
        columns = [{"name": c[0], "type": c[1], "modifiers": c[2]} for c in t.get("columns", [])]
        inline_idx = [{"name": i[0], "columns": i[1]} for i in t.get("indexes", [])]
        facet.elements.append(FacetElement(
            id=name, kind="table",
            data={
                "columns": columns,
                "pk": t.get("pk", []),
                "indexes": inline_idx + gidx.get(name, []),
            },
        ))
    return facet


def er_facet_from_project(root: str | Path) -> Facet:
    """Build a typed `er` facet from a project's DDL, reusing the existing er
    extractor's parser. Each entity -> one element (@id = entity name) carrying its
    outgoing relationships (fk_col -> dst.dst_col). Deterministic, read-only."""
    from .extractors.er import ErExtractor
    entities, relationships, _sources = ErExtractor().parse_er(Path(root))
    rels_by_src: dict[str, list] = {}
    for src, fk_col, dst, dst_col in relationships:
        rels_by_src.setdefault(src, []).append(
            {"column": fk_col, "references": f"{dst}.{dst_col}"})
    facet = Facet(kind="er")
    for name in entities:
        facet.elements.append(FacetElement(
            id=name, kind="entity",
            data={"relationships": rels_by_src.get(name, [])}))
    return facet


# ── deterministic converters: Java source -> class + api facets ──
def _classify_layer(annotations: str, name: str, package: str = "") -> str:
    """Map a class to its architectural layer from its annotations, then its name
    suffix, then its package segment. Layer is the structural role the round-trip
    cares about. Annotation is the strongest signal (a @Service is a service no
    matter its name); name suffix is the next intent signal; package location is the
    fallback for un-annotated POJOs (a class in `...dto` is a dto)."""
    for token, layer in (("@RestController", "controller"), ("@Controller", "controller"),
                         ("@Service", "service"), ("@Repository", "repository"),
                         ("@Mapper", "mapper"), ("@Configuration", "config"),
                         ("@RestControllerAdvice", "advice"), ("@ControllerAdvice", "advice")):
        if token in annotations:
            return layer
    for suf, layer in (("Controller", "controller"), ("Service", "service"),
                       ("Repository", "repository"), ("Mapper", "mapper"),
                       ("Config", "config"), ("Request", "dto"), ("Response", "dto"),
                       ("Dto", "dto"), ("Exception", "exception")):
        if name.endswith(suf):
            return layer
    pkg_segs = package.split(".")
    for seg, layer in (("controller", "controller"), ("service", "service"),
                       ("repository", "repository"), ("mapper", "mapper"),
                       ("dto", "dto"), ("config", "config"), ("exception", "exception"),
                       ("entity", "entity"), ("domain", "domain")):
        if seg in pkg_segs:
            return layer
    return "other"


def class_facet_from_project(root: str | Path) -> Facet:
    """Build a typed `class` facet from Java source. Each class/interface/enum -> one
    element, @id = fully-qualified name (`package.Class`, stable + collision-free),
    data = {type, name, package, layer}. Deterministic, read-only."""
    from .extractors.base import find_java_sources, safe_read, strip_java_comments
    facet = Facet(kind="class")
    seen: set[str] = set()
    for f in find_java_sources(Path(root)):
        text = strip_java_comments(safe_read(f))
        pm = _PACKAGE_RE.search(text)
        pkg = pm.group(1) if pm else ""
        for ann, ctype, name in _CLASS_DECL_RE.findall(text):
            fqn = f"{pkg}.{name}" if pkg else name
            if fqn in seen:
                continue
            seen.add(fqn)
            facet.elements.append(FacetElement(
                id=fqn, kind="class",
                data={"type": ctype, "name": name, "package": pkg,
                      "layer": _classify_layer(ann, name, pkg)}))
    return facet


def _join_path(base: str, sub: str) -> str:
    b = base.rstrip("/")
    s = sub.strip()
    if not s:
        return b or "/"
    if not s.startswith("/"):
        s = "/" + s
    return (b + s) or "/"


def _endpoint_id(method: str, path: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", path).strip("-").lower()
    return f"{method.lower()}-{slug}" if slug else method.lower()


def api_facet_from_project(root: str | Path) -> Facet:
    """Build a typed `api` facet from Spring controllers. Each handler endpoint ->
    one element, @id = `<method>-<path-slug>` (the round-trip key), data =
    {method, path, handler, controller}. Class-level @RequestMapping supplies the
    base path; @{Get,Post,Put,Delete,Patch}Mapping supplies the verb + sub-path.
    Method-level @RequestMapping(method=...) handlers are out of scope (documented).
    Deterministic, read-only."""
    from .extractors.base import find_java_sources, safe_read, strip_java_comments
    facet = Facet(kind="api")
    seen: set[str] = set()
    for f in find_java_sources(Path(root)):
        text = strip_java_comments(safe_read(f))
        if "@RestController" not in text and "@Controller" not in text:
            continue
        cm = _CLASS_DECL_RE.search(text)
        controller = cm.group(3) if cm else f.stem
        base_m = _CLASS_REQUEST_MAPPING_RE.search(text)
        base = base_m.group(1) if base_m else ""
        for m in _HANDLER_RE.finditer(text):
            method = m.group(1).upper()
            args = m.group(2) or ""
            sm = _FIRST_STR_RE.search(args)
            path = _join_path(base, sm.group(1) if sm else "")
            tail = text[m.end():m.end() + 400]
            nm = _METHOD_NAME_RE.search(tail)
            handler = nm.group(1) if nm else ""
            eid = _endpoint_id(method, path)
            if eid in seen:
                continue
            seen.add(eid)
            facet.elements.append(FacetElement(
                id=eid, kind="endpoint",
                data={"method": method, "path": path,
                      "handler": handler, "controller": controller}))
    return facet


def write_facet(facet: Facet, out_path: Path) -> None:
    """Write a facet to <out_path> as YAML (machine-generated). Caller chooses the
    location — typically <output>/.claude/spec/facets/<kind>.schema, NEVER inside a
    read-only source project."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        f"# {facet.kind}.schema — typed structural facet (unified-pipeline D1-2).\n"
        f"# Machine-generated; element @id = stable identity for round-trip.\n"
        + yaml.safe_dump(facet.to_yaml_doc(), allow_unicode=True, sort_keys=False, width=1000),
        encoding="utf-8")
