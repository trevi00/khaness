#!/usr/bin/env python3
"""doc_code_drift — ADVISORY validator: detect doc↔code drift in the harness.

Checks atlas artifact cards' `## Public surface` claims against the cited
module's AST, plus backtick-wrapped repo file-path references against the
filesystem. Generalises skill_source_liveness's advisory+injectable pattern.

Default ADVISORY tier; GRADUATES advisory->blocking via the graduate-validator
token. Graduation state is DYNAMIC (do not hardcode it here — it drifts; check
`validators.is_graduated('doc_code_drift')` / membership in VALIDATOR_NAMES at
runtime). When graduated, main()->1 on drift>0 (blocking); ungraduated it is
WARN-only (main()->0). Graduation/demotion is a separate gated decision.

SAFETY: NEVER imports/execs target modules — `ast.parse(source)` on the read
text only. No network, no clock, no random (deterministic + hermetic).

Design: debate-1780493323-a3b99f (간이 토론 Planner+Critic), recorded in
state/allsolution/1780493323-self-verifying-harness.md (F1-F9). Motivated by
audit wf_14bad0ab-01a: glob-activated artifact cards were injecting false API
(non-existent function/type names) into agent context.

Invocation:
    python -m validators.doc_code_drift
    python validators/doc_code_drift.py
"""
from __future__ import annotations

import ast
import re
import sys
import warnings
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # cp949 console safety (Windows)

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.frontmatter import parse_frontmatter  # noqa: E402
from lib.paths import ATLAS_DIR, SCRIPTS_DIR  # noqa: E402
# Shared hermetic reader + path-token regex + section slicer (extracted D0,
# debate-1780540387-7a5009). Tests inject via doc_drift_common._module_reader.
from lib.doc_drift_common import (  # noqa: E402
    _PATH_TOKEN_RE,
    _read_source,
    _section_body,
)

# Type tokens that are stdlib/builtin and need no module definition.
_KNOWN_TYPES = frozenset({
    "dict", "list", "str", "int", "bool", "float", "bytes", "set", "tuple",
    "None", "Any", "Optional", "Path", "Callable", "Iterable", "Iterator",
    "Sequence", "Mapping", "Type", "object", "frozenset", "Union", "Tuple",
    "List", "Dict", "Set", "FrozenSet",
})

_DEF_RE = re.compile(r"(?:^|\n)\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(")
_CLASS_RE = re.compile(r"(?:^|\n)\s*class\s+([A-Za-z_]\w*)")
_BACKTICK_CALL_RE = re.compile(r"`([A-Za-z_]\w*)\s*\(")
_FENCED_LINE_CALL_RE = re.compile(r"(?:^|\n)\s*([a-z_][A-Za-z0-9_]*)\s*\(")
_FENCE_RE = re.compile(r"```[a-zA-Z]*\n(.*?)```", re.S)
# TitleCase token in a RETURN position only (-> Foo, -> list[Foo]). `:`-position
# (param annotations) is excluded — it false-positives on prose colons ("Note: Foo").
_TYPE_RE = re.compile(r"->\s*(?:[A-Za-z_][\w.]*\[)*\s*([A-Z][A-Za-z0-9_]*)")


def collect_module_symbols(source: str) -> tuple[set[str], set[str]]:
    """Parse module source via AST. Return (callables, types).
    callables = top-level def/async-def names + class names + methods +
    ImportFrom aliases + __all__ literals (re-export aware).
    types = class names + imported names (for type-existence checks)."""
    callables: set[str] = set()
    types: set[str] = set()
    try:
        with warnings.catch_warnings():  # target modules may have their own SyntaxWarnings
            warnings.simplefilter("ignore")
            tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return callables, types
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            callables.add(node.name)
        elif isinstance(node, ast.ClassDef):
            callables.add(node.name)
            types.add(node.name)
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                name = a.asname or a.name
                callables.add(name)
                types.add(name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                name = a.asname or a.name.split(".")[0]
                callables.add(name)
                types.add(name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        for el in node.value.elts:
                            if isinstance(el, ast.Constant) and isinstance(el.value, str):
                                callables.add(el.value)
    return callables, types


def extract_card_claims(card_text: str) -> tuple[set[str], set[str]]:
    """From the `## Public surface` block return (call_claims, type_claims).
    Dual-format: fenced ```python blocks (def/method/class lines) AND prose
    backtick-calls. The #1 FP risk is prose — only `ident(` shapes are claims."""
    block = _section_body(card_text, "public surface")
    if not block:
        return set(), set()
    calls: set[str] = set(_DEF_RE.findall(block))
    calls |= set(_BACKTICK_CALL_RE.findall(block))
    classes: set[str] = set(_CLASS_RE.findall(block))
    # Fenced code blocks: line-leading method-style calls (e.g. `append(entry: dict)`).
    for fenced in _FENCE_RE.findall(block):
        calls |= set(_FENCED_LINE_CALL_RE.findall(fenced))
    types: set[str] = set(_TYPE_RE.findall(block)) - _KNOWN_TYPES
    # class names are declarations, not missing-claims; fold into calls existence-set
    calls |= classes
    # python soft keywords / noise that can appear line-leading in fences
    calls -= {"def", "class", "async", "return", "if", "for", "while", "with"}
    return calls, types


def resolve_module(frontmatter: dict, card_text: str) -> Path | None:
    """Resolve the cited module via `## Path` (primary) then globs[0] (fallback).
    Returns a path under SCRIPTS_DIR or None."""
    # Primary: ## Path line (a backtick-wrapped ~/.claude/scripts/... path).
    path_body = _section_body(card_text, "## path".replace("## ", "")) or _section_body(card_text, "path")
    m = re.search(r"`(?:~/\.claude/)?(?:scripts/)?([A-Za-z0-9_./-]+\.py)`", path_body)
    if m:
        return SCRIPTS_DIR / m.group(1)
    # Fallback: first glob like **/lib/strike_dispatcher* -> scripts/lib/strike_dispatcher.py
    globs = frontmatter.get("globs") or []
    for g in globs:
        if not isinstance(g, str):
            continue
        rem = g.lstrip("*/").rstrip("*")
        if "/" in rem and rem.split("/")[0] in {"lib", "validators", "handlers", "engine", "cli", "cron"}:
            cand = SCRIPTS_DIR / (rem + ".py")
            if cand.exists():
                return cand
    return None


def check_card(card_path: Path, card_text: str, frontmatter: dict) -> list[str]:
    """Return WARN strings for an artifact card. [] if clean / out of scope."""
    if frontmatter.get("type") != "artifact":
        return []
    if str(frontmatter.get("status", "")).lower() in {"deprecated", "superseded"}:
        return []
    warns: list[str] = []
    mod_path = resolve_module(frontmatter, card_text)
    rel = card_path.name
    if mod_path is None:
        return []  # no cited in-repo module; name-checks skipped (D5)
    if not mod_path.exists():
        # module missing => one file WARN, skip name-checks (don't spray phantoms)
        return [f"[WARN] {rel}: cited module {mod_path.name} does not exist"]
    source = _read_source(mod_path)
    if source is None:
        return [f"[WARN] {rel}: cited module {mod_path.name} unreadable"]
    callables, types = collect_module_symbols(source)
    call_claims, type_claims = extract_card_claims(card_text)
    for name in sorted(call_claims):
        if name.startswith("_"):
            continue
        if name not in callables:
            warns.append(f"[WARN] {rel}: Public surface claims `{name}()` — absent from {mod_path.name} AST")
    for tname in sorted(type_claims):
        if tname not in types:
            warns.append(f"[WARN] {rel}: Public surface claims type `{tname}` — absent from {mod_path.name}")
    return warns


def check_path_refs(note_path: Path, note_text: str) -> list[str]:
    """Backtick-wrapped repo file-path references must resolve. Runs on ALL
    atlas notes (phantom-file refs live in concept/decision notes too).
    Backtick-wrapping is the FP guard (intentional code reference, not prose)."""
    warns: list[str] = []
    seen: set[str] = set()
    for rel in _PATH_TOKEN_RE.findall(note_text):
        if rel in seen:
            continue
        seen.add(rel)
        if not (SCRIPTS_DIR / rel).exists():
            warns.append(f"[WARN] {note_path.name}: path ref `{rel}` does not resolve under scripts/")
    return warns


def scan() -> dict:
    """Walk the atlas vault; return {artifact_cards, notes, name_warns, path_warns}.
    parse_frontmatter takes a PATH and returns (fm, body) | None — body holds the
    `## ` sections this validator parses (frontmatter already stripped)."""
    result = {"artifact_cards": 0, "notes": 0, "name_warns": [], "path_warns": []}
    if not ATLAS_DIR.is_dir():
        return result
    for md in sorted(ATLAS_DIR.rglob("*.md")):
        parsed = parse_frontmatter(md)
        if parsed is None:
            continue
        fm, body = parsed
        result["notes"] += 1
        result["path_warns"].extend(check_path_refs(md, body))
        if fm.get("type") == "artifact":
            result["artifact_cards"] += 1
            result["name_warns"].extend(check_card(md, body, fm))
    return result


def _is_graduated() -> bool:
    """True iff this validator has graduated advisory→blocking (Track 1
    debate-1780722434-e5h19n). Guarded + fail-soft: a missing/garbled
    graduation state keeps us advisory. Lazy import keeps scan() hermetic."""
    try:
        from lib.graduation import is_graduated
        return is_graduated("doc_code_drift")
    except Exception:
        return False


def main() -> int:
    r = scan()
    for w in r["name_warns"]:
        print(w)
    for w in r["path_warns"]:
        print(w)
    total = len(r["name_warns"]) + len(r["path_warns"])
    tier = "blocking" if _is_graduated() else "advisory"
    summary = (
        f"doc_code_drift — {r['artifact_cards']} artifact cards + {r['notes']} notes scanned, "
        f"{len(r['name_warns'])} name/type drift + {len(r['path_warns'])} path-ref drift "
        f"({total} total, {tier})"
    )
    # C8 part-2: in graduated (blocking) mode, drift FAILs run_all; advisory
    # mode stays exit-0 (WARN-only) exactly as before. CLEAN := total==0.
    if tier == "blocking" and total > 0:
        print(f"[FAIL] {summary}")
        return 1
    print(f"[PASS] {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
