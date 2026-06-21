#!/usr/bin/env python3
"""test_import_layering — lib/ → engine/ → handlers/ single-direction guard (v15.26).

v15.26 Ouroboros migration C-γ' (tests-first commit, debate-1778987814-41b475 D3):
- Lands FIRST with `pytestmark = mark.skip` placeholder so suite stays green.
- C-α/β add lib/seed_lock.py + lib/ac_tree.py + lib/wonder.py + lib/reflect_feedback.py.
- C-δ REMOVES skip marker → test becomes active + enforces import layering.

Layering invariant (CLAUDE.md ~/.claude/scripts/ 4-layer):
  lib/       (pure utils — no inward imports from engine/, handlers/, validators/)
  validators/ (uses lib/)
  handlers/  (uses lib/, validators/, engine/)
  engine/    (uses lib/)

Disallowed:
  lib/*.py → from engine.*
  lib/*.py → from handlers.*
  lib/*.py → from validators.*
  engine/*.py → from handlers.*

Test mechanism: AST import scan of every lib/*.py file. No subprocess.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

# v15.26 C-δ activated — skip-marker removed (foundation lib/seed_lock + lib/ac_tree
# in C-α and consumers lib/wonder + lib/reflect_feedback in C-β are now landed).
import pytest  # noqa: E402

# pytestmark removed in C-δ — test active.


_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


_DISALLOWED_LIB_IMPORTS: frozenset[str] = frozenset({
    "engine",
    "handlers",
    "validators",  # lib/validators is OK (subpackage); top-level scripts/validators is not
})

_DISALLOWED_ENGINE_IMPORTS: frozenset[str] = frozenset({
    "handlers",
})


def _collect_imports(py_file: Path) -> set[str]:
    """Return top-level package names imported by this file."""
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    pkgs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                pkgs.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                pkgs.add(node.module.split(".")[0])
    return pkgs


def _violations(layer_dir: Path, disallowed: frozenset[str]) -> list[tuple[str, str]]:
    """Return list of (file_relpath, violating_import) pairs."""
    out: list[tuple[str, str]] = []
    for py in layer_dir.rglob("*.py"):
        if py.name == "__init__.py":
            continue
        imports = _collect_imports(py)
        for bad in imports & disallowed:
            # lib/validators is OK (subpackage of lib) — distinguish from top-level scripts/validators
            if layer_dir.name == "lib" and bad == "validators":
                # Check if this is a `from lib.validators import ...` (allowed) or `from validators import ...` (not)
                # AST already returned bare "validators" — if file is in lib/ and uses lib.validators internally,
                # the top-level name we collected is "validators" only if the import path was `validators.*`
                # not `lib.validators.*`. Both register as "validators" via split[0], so be lenient:
                # check raw text for `^from validators` or `^import validators` at start of line.
                text = py.read_text(encoding="utf-8")
                if not any(
                    line.strip().startswith(("from validators", "import validators"))
                    for line in text.splitlines()
                ):
                    continue
            out.append((str(py.relative_to(_SCRIPTS)), bad))
    return out


def test_lib_no_engine_handlers_validators_imports():
    """lib/*.py must not import from engine/, handlers/, top-level validators/."""
    lib_dir = _SCRIPTS / "lib"
    violations = _violations(lib_dir, _DISALLOWED_LIB_IMPORTS)
    assert not violations, f"lib layering violations: {violations}"


def test_engine_no_handlers_imports():
    """engine/*.py must not import from handlers/."""
    engine_dir = _SCRIPTS / "engine"
    violations = _violations(engine_dir, _DISALLOWED_ENGINE_IMPORTS)
    assert not violations, f"engine layering violations: {violations}"


TESTS = [
    test_lib_no_engine_handlers_validators_imports,
    test_engine_no_handlers_imports,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"  [OK] {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  [ERROR] {fn.__name__}: {type(e).__name__}: {e}")
    if failed:
        print(f"\n[FAIL] {failed}/{len(TESTS)} tests failed")
        return 1
    print(f"\n[OK] {len(TESTS)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
