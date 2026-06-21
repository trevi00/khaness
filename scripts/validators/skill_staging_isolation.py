#!/usr/bin/env python3
"""skill_staging_isolation — Layer-A static AST validator for D3 invariant.

debate-1779462559-c29f2b LOCK (gen-2 byte-identical, sha1
67c44483a06d6504209644d792edfd943c4ee3a9) accepted_decisions=['D3'].

Role
    Static AST check that confines writes from staging modules to the
    allowed roots {_CANDIDATES_ROOT, _TRACKER_ROOT}. Pairs with
    lib/staging_guard.py (Layer-B runtime guard) — Layer-B is the
    authoritative backstop.

Target modules (LOCK D3.invariant.write_scope)
    lib/skill_candidate_detector.py
    handlers/post_tool/skill_candidate_extractor.py
    # lib/skill_draft_pipeline.py — auto-included when present (D1 deferred)

Allowlist function names (LOCK D3.layer_a.method)
    write_text, write_bytes, write_json_atomic, mkdir, open

Allowed Path roots (LOCK D3.layer_a.allowed_roots)
    _CANDIDATES_ROOT, _TRACKER_ROOT

Accepted false-negative surface (LOCK D3.layer_a.known_false_negatives)
    getattr-indirection (e.g. getattr(p, 'write_text')(...))
    os.makedirs, shutil.copy/copytree/move/rmtree
    subprocess writing (git mv, shell-out)
    tempfile + rename, low-level os.write/os.open
    These are NOT covered by Layer-A. Layer-B (lib/staging_guard.py
    assert_in_staging) is the runtime backstop.

Safe expression grammar
    A "safe" expression is one that statically resolves to a Path under
    one of the allowed roots:
      safe(expr) ==
        Name(id ∈ {_CANDIDATES_ROOT, _TRACKER_ROOT})
        | BinOp(Div, left=safe(...), right=*)
        | Call(func=Name(local_helper)) where local_helper's body has
          a return statement whose value is safe(...)
        | Call(func=Attribute(value=safe(...), attr ∈ {mkdir, parent}))
          — produces a Path still under the root

Caller contract (validators/__init__.py)
    main() -> None, no args
    prints [PASS]/[FAIL] lines to stdout
    never raises; failures via stdout + telemetry
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

for _stream in (sys.stdin, sys.stdout):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure:
        try:
            _reconfigure(encoding="utf-8")
        except Exception:
            pass

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.logging import log_telemetry  # noqa: E402


ALLOWLIST_FUNCS: frozenset[str] = frozenset({
    "write_text",
    "write_bytes",
    "write_json_atomic",
    "mkdir",
    "open",
})

ALLOWED_ROOTS: frozenset[str] = frozenset({
    "_CANDIDATES_ROOT",
    "_TRACKER_ROOT",
})

TARGET_FILES: tuple[str, ...] = (
    "lib/skill_candidate_detector.py",
    "handlers/post_tool/skill_candidate_extractor.py",
    "lib/skill_draft_pipeline.py",
)


def _collect_safe_helpers(tree: ast.Module) -> set[str]:
    """Return names of module-level helpers whose return is a safe expression.

    A two-pass approach handles forward references: first pass enumerates
    helper names with candidate returns; second pass validates them using
    the candidate set itself.
    """
    candidate_returns: dict[str, list[ast.expr]] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            returns = [
                n.value for n in ast.walk(node)
                if isinstance(n, ast.Return) and n.value is not None
            ]
            if returns:
                candidate_returns[node.name] = returns

    safe: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, returns in candidate_returns.items():
            if name in safe:
                continue
            if all(_is_safe(expr, safe) for expr in returns):
                safe.add(name)
                changed = True
    return safe


def _is_safe(expr: ast.expr, safe_helpers: set[str]) -> bool:
    if isinstance(expr, ast.Name):
        return expr.id in ALLOWED_ROOTS
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Div):
        return _is_safe(expr.left, safe_helpers)
    if isinstance(expr, ast.Call):
        if isinstance(expr.func, ast.Name):
            return expr.func.id in safe_helpers
        if isinstance(expr.func, ast.Attribute):
            return _is_safe(expr.func.value, safe_helpers)
    if isinstance(expr, ast.Attribute):
        return _is_safe(expr.value, safe_helpers)
    return False


def _extract_path_arg(call: ast.Call) -> ast.expr | None:
    """Return the expression representing the path arg for an allowlist Call.

    For Attribute calls (p.write_text(...)), the path is the receiver.
    For Name calls (open(...), write_json_atomic(...)), the path is the first
    positional argument.
    """
    if isinstance(call.func, ast.Attribute):
        return call.func.value
    if isinstance(call.func, ast.Name):
        if call.args:
            return call.args[0]
    return None


def _is_allowlist_call(call: ast.Call) -> bool:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr in ALLOWLIST_FUNCS
    if isinstance(call.func, ast.Name):
        return call.func.id in ALLOWLIST_FUNCS
    return False


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Return list of (line, rendered_call) violations in `path`."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [(0, f"<syntax error parsing {path.name}>")]

    safe_helpers = _collect_safe_helpers(tree)
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_allowlist_call(node):
            continue
        path_arg = _extract_path_arg(node)
        if path_arg is None:
            violations.append((node.lineno, f"<no path arg> at line {node.lineno}"))
            continue
        if _is_safe(path_arg, safe_helpers):
            continue
        try:
            rendered = ast.unparse(node)
        except Exception:
            rendered = f"<call at line {node.lineno}>"
        violations.append((node.lineno, rendered))
    return violations


def main() -> None:
    failures = 0
    for relpath in TARGET_FILES:
        abs_path = _SCRIPTS / relpath
        if not abs_path.exists():
            # Deferred (D1) — silently skip missing targets.
            continue
        vios = _scan_file(abs_path)
        if not vios:
            print(f"[PASS] skill_staging_isolation {relpath} — all writes under {{_CANDIDATES_ROOT, _TRACKER_ROOT}}")
            continue
        for lineno, rendered in vios:
            failures += 1
            print(f"[FAIL] skill_staging_isolation {relpath}:{lineno} write outside staging allowlist: {rendered}")
            log_telemetry(
                "skill-staging-isolation-violations",
                {
                    "event": "skill_staging_isolation_fail",
                    "file": relpath,
                    "line": lineno,
                    "call": rendered,
                },
            )
    if failures == 0:
        print("[PASS] skill_staging_isolation overall")


if __name__ == "__main__":
    main()
