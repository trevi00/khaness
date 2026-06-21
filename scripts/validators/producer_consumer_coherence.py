#!/usr/bin/env python3
"""Producer↔consumer coherence auditor — catches the dead-seam class.

Converged design debate-1781768055-e7o7su (2 gen, ontology SHA-1 4cde80864c3e...).
Catches the 3-bug dead-seam class that bit the harness this session:
  - bug#1 dge_e2_cross_target: a marker KEY read with NO producer (write side missing)
  - bug#2 autopilot_parallel_enables: a telemetry FILE read whose writer targets a
    different category (reader-path vs writer-category mismatch)
  - bug#3 external_jury: a public symbol with 0 callers (built-but-unwired)

Mirrors validators/commit_layer_adjacency.py shape: flat AST, main()->stdout, NEVER
raises, [PASS]/[FAIL]/[WARN]/[INFO] lines. Ships ADVISORY (NOT in validators _BUILTIN);
graduation-branch-ready via graduation_scan_drift (HIGH drift only) but NOT in
lib.graduation.TRACKED yet — streak accrual deferred (operator decision). commit_layer_adjacency
checks import DIRECTION; this fills the empty REACHABILITY/COHERENCE slot.

## Three checks
- TELEMETRY_PATH_CHECK (HIGH): producer `log_telemetry('X')`->X.jsonl write-stems vs
  consumer `TELEMETRY_DIR / 'Y.jsonl'` literal read-stems. HIGH when a literal read-stem
  Y has no producing writer. Computed paths (`TELEMETRY_DIR / f'{c}.jsonl'`, non-literal)
  are NOT silently dropped — counted as [INFO] 'not statically resolvable'.
- MARKER_KEY_CHECK (HIGH/INFO): literal read-keys (`d.get('K')`, `d['K']`) vs literal
  write-keys (`d['K']=`, `{'K':..}`, `.update({'K':..})`, `.setdefault('K',..)`). A read-key
  with 0 literal writers anywhere is HIGH **only when the reading file has no dynamic
  writer** (`.update(<var>)`, `d[<var>]=`, `**spread`) — else [INFO] (per the converged
  self-doubt note: reserve HIGH for true literal asymmetry, downgrade dynamic-writer files).
- CALLER_GRAPH (MED): a module-level public def/class with 0 QUALIFIED references across
  .py + commands/*.md + skills/**/*.md + agents/*.md. Qualified = `from <mod> import <name>`,
  `<mod>.<name>`, `cli.<name>`/`python -m cli.<name>`, or a bare name in .md co-located with
  a wiring affordance (backtick / `python -m` / `cli.`). NOT bare \\bname\\b (that collides
  on common names like main/scan/run across ~250 files). MED runs --all/on-demand only.

## Allowlist
In-line `# coherence-ok: <reason>` on the flagged line (def/class line, read line) suppresses
a finding and echoes [WARN]. Empty reason => [FAIL] (local design choice; not a borrowed
noqa/PEP484 precedent).

## Output / integration
main()->None, stdout-only, never raises. `--all` adds the costly MED whole-tree caller scan;
default runs only the cheap HIGH checks (telemetry + marker-key). scan()->{'high','med','info'}
is the structured entry for graduation_scan_drift (tracks len(scan()['high'])).
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_HOME = _SCRIPTS.parent  # CLAUDE_HOME (commands/, skills/, agents/ live here)
_CODE_LAYERS = ("lib", "validators", "handlers", "engine", "cli")
_SKIP_PARTS = ("__pycache__", "tests")


# ---------- shared helpers ----------

def _coherence_ok(source_lines: list[str], lineno: int) -> tuple[bool, str] | None:
    """If line `lineno` (1-based) carries `# coherence-ok: <reason>`, return
    (has_reason, reason). None if no marker. Empty reason => (False, '')."""
    if lineno < 1 or lineno > len(source_lines):
        return None
    m = re.search(r"#\s*coherence-ok:(.*)$", source_lines[lineno - 1])
    if not m:
        return None
    reason = m.group(1).strip()
    return (bool(reason), reason)


def _code_py_files() -> list[Path]:
    """The AUDITED surface (def-inventory + consumer scan): the core API layers."""
    out: list[Path] = []
    for layer in _CODE_LAYERS:
        d = _SCRIPTS / layer
        if not d.is_dir():
            continue
        for p in d.rglob("*.py"):
            if any(part in _SKIP_PARTS for part in p.parts):
                continue
            out.append(p)
    return out


def _all_py_files() -> list[Path]:
    """The full REFERENCE/PRODUCER net: every scripts/**/*.py (incl cron/, root shims,
    entry-points) minus tests/__pycache__. A caller or a producer can live ANYWHERE —
    restricting the reference scan to the core layers falsely flags symbols called from
    cron/ (e.g. autopush <- cron/run_brain_push.py) as 0-caller."""
    out: list[Path] = []
    for p in _SCRIPTS.rglob("*.py"):
        if any(part in _SKIP_PARTS for part in p.parts):
            continue
        out.append(p)
    return out


def _safe_parse(path: Path) -> tuple[ast.AST | None, list[str]]:
    try:
        src = path.read_text(encoding="utf-8")
    except OSError:
        return None, []
    try:
        return ast.parse(src, filename=str(path)), src.splitlines()
    except SyntaxError:
        return None, src.splitlines()


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(_HOME).as_posix()
    except ValueError:
        return path.as_posix()


# ---------- TELEMETRY_PATH_CHECK (HIGH) ----------

def _module_str_consts(tree: ast.AST) -> dict[str, str]:
    """Map module-level `NAME = "literal"` constants -> value (resolves the
    `log_telemetry(_TELEMETRY_CATEGORY, ...)` case where the category is a constant,
    not a string literal — the bug#2 false-positive surfaced on the first live run)."""
    consts: dict[str, str] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    consts[t.id] = node.value.value
    return consts


def _telemetry_writers() -> set[str]:
    """All stems written via log_telemetry(X, ...) — X => X.jsonl. X may be a string
    literal OR a module-level string constant (resolved per-file)."""
    stems: set[str] = set()
    for path in _all_py_files():
        tree, _lines = _safe_parse(path)
        if tree is None:
            continue
        consts = _module_str_consts(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else None)
                if name == "log_telemetry" and node.args:
                    a0 = node.args[0]
                    if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                        stems.add(a0.value)
                    elif isinstance(a0, ast.Name) and a0.id in consts:
                        stems.add(consts[a0.id])
    return stems


def _is_telemetry_dir_read(node: ast.AST) -> tuple[str | None, bool]:
    """For a `TELEMETRY_DIR / <x>` BinOp, return (literal_stem_or_None, is_computed).
    literal_stem set when x is a '<stem>.jsonl' constant; is_computed when x is dynamic
    (f-string/var) — surfaced as [INFO], not flagged."""
    if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)):
        return None, False
    left = node.left
    if not (isinstance(left, ast.Name) and left.id == "TELEMETRY_DIR"):
        return None, False
    right = node.right
    if isinstance(right, ast.Constant) and isinstance(right.value, str) and right.value.endswith(".jsonl"):
        return right.value[:-len(".jsonl")], False
    return None, True  # TELEMETRY_DIR / f"{cat}.jsonl" or / var


def _telemetry_findings(writers: set[str]) -> tuple[list[str], list[str], list[str]]:
    """Returns (high, warn, info) lines."""
    high: list[str] = []
    warn: list[str] = []
    info_counts: dict[str, int] = {}
    for path in _code_py_files():
        tree, lines = _safe_parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            stem, computed = _is_telemetry_dir_read(node)
            if computed:
                info_counts[_rel(path)] = info_counts.get(_rel(path), 0) + 1
                continue
            if stem is None:
                continue
            if stem in writers:
                continue
            ok = _coherence_ok(lines, getattr(node, "lineno", 0))
            label = f"{_rel(path)}: HIGH telemetry-read '{stem}.jsonl' has no log_telemetry('{stem}') producer (line {node.lineno})"
            if ok is not None:
                has_reason, reason = ok
                if has_reason:
                    warn.append(f"[WARN] coherence-ok {label} :: {reason}")
                    continue
                high.append(f"[FAIL] {label} :: # coherence-ok marker has EMPTY reason")
                continue
            high.append(f"[FAIL] {label}")
    info = [f"[INFO] {f}: {n} telemetry path(s) not statically resolvable — outside v1 coverage"
            for f, n in sorted(info_counts.items())]
    return high, warn, info


# ---------- MARKER_KEY_CHECK (HIGH/INFO) ----------

def _literal_write_keys() -> set[str]:
    """Global set of string keys WRITTEN via a literal channel anywhere:
    d['K']=, {'K':..} dict-literal, .update({'K':..}), .setdefault('K',..).
    A marker is 'produced' if some producer sets it literally (cross-file)."""
    writes: set[str] = set()
    for path in _all_py_files():
        tree, _lines = _safe_parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
                k = node.slice
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    writes.add(k.value)
            if isinstance(node, ast.Dict):
                for key in node.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        writes.add(key.value)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "setdefault" and node.args:
                    a0 = node.args[0]
                    if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                        writes.add(a0.value)
    return writes


def _marker_findings() -> tuple[list[str], list[str], list[str]]:
    """MARKER_KEY_CHECK, NARROWED to the genuine marker CONVENTION (v1 high-signal):
    only string literals passed as a `marker_keys=(...)`/`[...]` keyword argument — the
    `lib._count_jsonl_records_with_marker(marker_keys=(...))` pattern that bug#1
    (cross_target_first_invocation) had. The first live run proved that flagging EVERY
    literal `.get('K')` floods on os.environ.get / external hook+API JSON payloads /
    LLM-produced keys (none of which have an internal writer by nature). The marker_keys=
    convention is the unambiguous 'this key is a consumed marker' signal, so HIGH here =
    a real never-produced marker, not an external read."""
    writes = _literal_write_keys()
    high: list[str] = []
    warn: list[str] = []
    info: list[str] = []
    for path in _code_py_files():
        tree, lines = _safe_parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg != "marker_keys":
                    continue
                elts = kw.value.elts if isinstance(kw.value, (ast.Tuple, ast.List)) else []
                for e in elts:
                    if not (isinstance(e, ast.Constant) and isinstance(e.value, str)):
                        info.append(f"[INFO] {_rel(path)}: non-literal marker_keys element (line {node.lineno}) — outside v1 coverage")
                        continue
                    k = e.value
                    if k in writes:
                        continue
                    ok = _coherence_ok(lines, getattr(node, "lineno", 0))
                    label = f"{_rel(path)}: HIGH marker-key '{k}' consumed (marker_keys=) but no literal producer writes it (line {node.lineno})"
                    if ok is not None:
                        has_reason, reason = ok
                        if has_reason:
                            warn.append(f"[WARN] coherence-ok {label} :: {reason}")
                        else:
                            high.append(f"[FAIL] {label} :: # coherence-ok marker has EMPTY reason")
                        continue
                    high.append(f"[FAIL] {label}")
    return high, warn, info


# ---------- CALLER_GRAPH (MED, --all/on-demand) ----------

def _public_defs() -> dict[str, tuple[Path, int]]:
    """name -> (defining_file, lineno) for module-level public def/class."""
    out: dict[str, tuple[Path, int]] = {}
    for path in _code_py_files():
        tree, _lines = _safe_parse(path)
        if tree is None:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not node.name.startswith("_"):
                    out.setdefault(node.name, (path, node.lineno))
    return out


def _ref_py_files() -> list[Path]:
    """Reference net for the 0-caller check — every scripts/**/*.py INCLUDING tests/
    (excl __pycache__). A symbol exercised only by its unit test is 'referenced': the
    high-confidence dead-capability signal is referenced NOWHERE (not prod, not test,
    not .md) — e.g. a convenience factory left only in __all__. Counting tests keeps the
    MED list focused on genuinely-orphaned exports instead of every tested helper."""
    return [p for p in _SCRIPTS.rglob("*.py") if "__pycache__" not in p.parts]


def _referenced_names() -> set[str]:
    """All names REFERENCED (used) across scripts incl tests: Name-load ids, Attribute
    attrs, and import aliases. A `def foo`/`class foo` is NOT a Name-load, so a symbol's
    own definition does not count — but every USE (intra-file calls, callbacks, decorators,
    test calls) does. Replaces the regex that excluded the whole def file (462 -> real)."""
    refs: set[str] = set()
    for path in _ref_py_files():
        tree, _lines = _safe_parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                refs.add(node.id)
            elif isinstance(node, ast.Attribute):
                refs.add(node.attr)
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    refs.add(a.name)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    refs.add(a.name.split(".")[-1])
    return refs


def _md_referenced(name: str) -> bool:
    """True if `name` appears in an orchestration .md (commands/skills/agents) line that
    ALSO carries a wiring affordance (backtick / `python -m` / `cli.` / call paren) — the
    markdown-orchestrated harness wires capabilities by name reference, so this clears
    .md-driven symbols (jury_advisory, log_verdict_event) a .py-only scan would miss."""
    for sub in ("commands", "skills", "agents"):
        d = _HOME / sub
        if not d.is_dir():
            continue
        for p in d.rglob("*.md"):
            try:
                txt = p.read_text(encoding="utf-8")
            except OSError:
                continue
            for line in txt.splitlines():
                if name in line and ("`" in line or "python -m" in line or "cli." in line or "(" in line):
                    return True
    return False


def _caller_findings() -> tuple[list[str], list[str]]:
    """MED 0-caller exports. Costly whole-tree — --all/on-demand only. A public def/class
    is flagged iff its name is referenced NOWHERE across code .py (AST use-sites) AND has
    no .md wiring reference. Lenient on same-name collisions (a same-named use clears it):
    v1 prefers fewer false positives over the Critic's false-negative concern — a noisy
    advisory gets ignored; the allowlist + INFO surface the residual."""
    defs = _public_defs()
    refs = _referenced_names()
    med: list[str] = []
    warn: list[str] = []
    for name, (def_file, lineno) in sorted(defs.items()):
        if name in refs:
            continue
        if _md_referenced(name):
            continue
        _tree, lines = _safe_parse(def_file)
        ok = _coherence_ok(lines, lineno)
        label = f"{_rel(def_file)}: MED 0-caller export '{name}' (line {lineno})"
        if ok is not None:
            has_reason, reason = ok
            if has_reason:
                warn.append(f"[WARN] coherence-ok {label} :: {reason}")
                continue
            med.append(f"[FAIL] {label} :: # coherence-ok marker has EMPTY reason")
            continue
        med.append(f"[FAIL] {label}")
    return med, warn


# ---------- public API ----------

def scan(include_med: bool = False) -> dict:
    """Structured entry for graduation_scan_drift + tests. {'high':[],'med':[],'info':[],'warn':[]}.
    HIGH = telemetry + marker-key (cheap, per-commit). MED = 0-caller (costly, --all only)."""
    writers = _telemetry_writers()
    t_high, t_warn, t_info = _telemetry_findings(writers)
    m_high, m_warn, m_info = _marker_findings()
    high = t_high + m_high
    warn = t_warn + m_warn
    info = t_info + m_info
    med: list[str] = []
    if include_med:
        med, c_warn = _caller_findings()
        warn = warn + c_warn
    return {"high": high, "med": med, "info": info, "warn": warn}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    include_med = "--all" in sys.argv
    r = scan(include_med=include_med)
    for line in r["info"]:
        print(line)
    for line in r["warn"]:
        print(line)
    for line in r["high"]:
        print(line)
    for line in r["med"]:
        print(line)
    mode = "full-tree (incl MED 0-caller)" if include_med else "HIGH-only (telemetry+marker)"
    n_high, n_med = len(r["high"]), len(r["med"])
    if n_high or n_med:
        print(f"[FAIL] producer_consumer_coherence: {n_high} HIGH + {n_med} MED seam(s) "
              f"({mode}, {len(r['info'])} INFO, {len(r['warn'])} allowlisted)")
    else:
        print(f"[PASS] producer_consumer_coherence: 0 HIGH"
              f"{' + 0 MED' if include_med else ''} seam(s) ({mode}, {len(r['info'])} INFO)")


if __name__ == "__main__":
    main()
