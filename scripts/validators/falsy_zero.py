#!/usr/bin/env python3
"""falsy_zero — advisory lint for the `X or default` falsy-zero antipattern.

`X or default` silently uses `default` whenever X is 0 / '' / [] / False — not only
when X is "missing". In a NUMERIC context (X could legitimately be 0) this is a
latent bug: a valid 0 falls through to the fallback. The sharpest form is when the
fallback is NON-DETERMINISTIC (wall-clock / random / uuid): a falsy guard then makes
a supposedly pure function depend on the clock — exactly the bug that flaked
lib.l2_promoter ~1/30 (`earliest_ts or int(time.time()*1000)` with earliest_ts==0).
See [[reference_falsy_zero_breaks_determinism]].

AST-based (not regex) for precision. Two rules over each `A or B [or C ...]`:
  - HIGH  falsy-zero-nondeterministic: a NUMERIC guard `or` a fallback whose subtree
          contains time.time()/monotonic/now()/random.*/uuid.uuid*  (determinism risk)
  - MED   falsy-zero-numeric: a NUMERIC guard `or` any fallback (a valid 0 is masked)
A "numeric guard" is min/max/sum/len/abs/int/float/round/ord(...), d.get(k, <num>),
a numeric-only arithmetic op (a-b, a%b, a//b, a**b, bitwise/shift), OR a name
assigned from one of those somewhere in the same file (coarse intra-file dataflow).

ADVISORY ([WARN]); graduates to blocking via the graduate-validator token. Scans the
production tree (lib/validators/handlers/engine/cli); tests/ is skipped (it exercises
the pattern by design). Suppress an intentional use with a trailing `# falsy-zero-ok`
(or `# noqa`) on the `or` line. Caller contract: main()->None.
"""
from __future__ import annotations

import ast
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

for _s in (sys.stdin, sys.stdout):
    _r = getattr(_s, "reconfigure", None)
    if _r:
        try:
            _r(encoding="utf-8")
        except Exception:
            pass

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_NUMERIC_FUNCS = frozenset({"min", "max", "sum", "len", "abs", "int", "float", "round", "ord"})
# Arithmetic ops that yield a number where 0 is a common, legitimate result.
# Add/Mult/Div are EXCLUDED — '+'/'*' are overloaded for str/list, so they are not
# reliable numeric signals (avoids flagging `name or "default"` on a string concat).
_NUMERIC_ARITH_OPS = (ast.Sub, ast.Mod, ast.FloorDiv, ast.Pow,
                      ast.LShift, ast.RShift, ast.BitAnd, ast.BitOr, ast.BitXor)
# (module, attr) wall-clock / monotonic sources + bare datetime now/utcnow.
_TIME_CALLS = frozenset({("time", "time"), ("time", "monotonic"), ("time", "time_ns"),
                         ("time", "perf_counter"), ("time", "perf_counter_ns")})
_NOW_ATTRS = frozenset({"now", "utcnow"})

# Suppression markers on the physical `or` line.
_SUPPRESS = ("# falsy-zero-ok", "# noqa")

# Production subtrees to scan; tests/ is intentionally excluded.
_SCAN_DIRS = ("lib", "validators", "handlers", "engine", "cli")


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    col: int
    severity: str        # "high" | "medium"
    rule: str
    guard: str           # short description of the numeric guard
    fallback: str        # short description of the masking fallback
    snippet: str


def _is_numeric_call(node: ast.AST) -> str | None:
    """Return a label if `node` is a call that produces a number where 0 is valid."""
    if not isinstance(node, ast.Call):
        return None
    f = node.func
    if isinstance(f, ast.Name) and f.id in _NUMERIC_FUNCS:
        return f"{f.id}()"
    if isinstance(f, ast.Attribute) and f.attr == "get" and len(node.args) >= 2:
        d = node.args[1]
        if isinstance(d, ast.Constant) and isinstance(d.value, (int, float)) and not isinstance(d.value, bool):
            return ".get(…, <num>)"
    return None


def _is_numeric_arith(node: ast.AST) -> str | None:
    if isinstance(node, ast.BinOp) and isinstance(node.op, _NUMERIC_ARITH_OPS):
        return type(node.op).__name__
    return None


def _nondeterministic_in(node: ast.AST) -> str | None:
    """Walk a fallback subtree for a non-deterministic source call."""
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            attr = n.func.attr
            base = n.func.value
            base_name = base.id if isinstance(base, ast.Name) else None
            if base_name == "random":
                return f"random.{attr}"
            if base_name == "uuid" and attr.startswith("uuid"):
                return f"uuid.{attr}"
            if base_name and (base_name, attr) in _TIME_CALLS:
                return f"{base_name}.{attr}"
            if attr in _NOW_ATTRS:                 # datetime.now()/utcnow() (any base)
                return f"{attr}()"
    return None


def _collect_numeric_names(tree: ast.AST) -> set[str]:
    """Names assigned at least once from a numeric source anywhere in the file.
    Coarse (no per-scope isolation) — acceptable for an advisory linter; collisions
    are rare and suppressible. Catches the `t = min(...); … t or clock()` shape that
    the inline-only check would miss (the l2_promoter bug)."""
    names: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and (_is_numeric_call(n.value) or _is_numeric_arith(n.value)):
            for tgt in n.targets:
                if isinstance(tgt, ast.Name):
                    names.add(tgt.id)
        elif isinstance(n, ast.AnnAssign) and n.value is not None \
                and (_is_numeric_call(n.value) or _is_numeric_arith(n.value)):
            if isinstance(n.target, ast.Name):
                names.add(n.target.id)
    return names


def _numeric_guard(node: ast.AST, numeric_names: set[str]) -> str | None:
    """Describe `node` if it is a numeric guard (0 is a legitimate value)."""
    return (
        _is_numeric_call(node)
        or _is_numeric_arith(node)
        or (f"`{node.id}`" if isinstance(node, ast.Name) and node.id in numeric_names else None)
    )


def _is_falsy_constant(node: ast.AST) -> bool:
    """True if `node` is a literal whose value is itself falsy (0, 0.0, '', [], {},
    (), False, None). `X or <falsy-constant>` masks nothing meaningful — it just
    normalizes a falsy X to the same kind of falsy, the common defensive None->0
    idiom. Not a bug; excluded from the medium rule."""
    if isinstance(node, ast.Constant):
        return not node.value
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return not node.elts
    if isinstance(node, ast.Dict):
        return not node.keys
    return False


def _short(node: ast.AST) -> str:
    try:
        return ast.unparse(node)[:60]
    except Exception:
        return type(node).__name__


def scan_source(source: str, filename: str = "<src>") -> list[Finding]:
    """Return falsy-zero findings for one Python source string. Pure; fail-soft on
    SyntaxError (returns [])."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")   # scanned files' own SyntaxWarnings (\s etc.)
            tree = ast.parse(source)
    except SyntaxError:
        return []
    numeric_names = _collect_numeric_names(tree)
    lines = source.splitlines()
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)):
            continue
        ln = getattr(node, "lineno", 0)
        phys = lines[ln - 1] if 0 < ln <= len(lines) else ""
        if any(mark in phys for mark in _SUPPRESS):
            continue
        values = node.values
        guards = values[:-1]
        fallbacks = values[1:]
        guard_desc = next((g for v in guards if (g := _numeric_guard(v, numeric_names))), None)
        if guard_desc is None:
            continue   # no numeric guard -> not a falsy-zero risk (avoids None-default FPs)
        nondet = next((d for fb in fallbacks if (d := _nondeterministic_in(fb))), None)
        if nondet:
            sev, rule, fb_desc = "high", "falsy-zero-nondeterministic", nondet
        else:
            meaningful = [fb for fb in fallbacks if not _is_falsy_constant(fb)]
            if not meaningful:
                continue   # `X or 0` / `X or ''` — harmless normalization, masks nothing
            sev, rule, fb_desc = "medium", "falsy-zero-numeric", _short(meaningful[0])
        findings.append(Finding(
            file=filename, line=ln, col=getattr(node, "col_offset", 0),
            severity=sev, rule=rule, guard=guard_desc, fallback=fb_desc,
            snippet=phys.strip()[:100]))
    return findings


def scan_file(path: Path) -> list[Finding]:
    try:
        src = path.read_text(encoding="utf-8")
    except Exception:
        return []
    return scan_source(src, filename=str(path))


def scan_tree(root: Path) -> list[Finding]:
    """Scan the production subtrees under `root` (skips tests/ and __pycache__)."""
    out: list[Finding] = []
    for d in _SCAN_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for fp in sorted(base.rglob("*.py")):
            if "__pycache__" in fp.parts:
                continue
            out.extend(scan_file(fp))
    return out


def main() -> None:
    findings = scan_tree(_SCRIPTS)
    if not findings:
        print("[PASS] falsy_zero: no `X or default` falsy-zero antipatterns in the production tree")
        return
    high = [f for f in findings if f.severity == "high"]
    med = [f for f in findings if f.severity == "medium"]
    for f in (high + med)[:20]:
        rel = Path(f.file)
        try:
            rel = rel.relative_to(_SCRIPTS)
        except ValueError:
            pass
        tag = "HIGH" if f.severity == "high" else "MED "
        print(f"[WARN] falsy_zero {tag} {rel}:{f.line} — numeric guard {f.guard} "
              f"`or` {f.fallback}: a valid {'0/falsy' if f.severity=='medium' else 'falsy guard -> nondeterministic'} "
              f"is masked. ({f.rule}; suppress with `# falsy-zero-ok`)")
    print(f"[WARN] falsy_zero: {len(high)} high + {len(med)} medium advisory finding(s) "
          f"(advisory — graduate-validator gates blocking)")


if __name__ == "__main__":
    main()
