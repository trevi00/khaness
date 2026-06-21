#!/usr/bin/env python3
"""exit_contract_coverage — documented-exit-contract test-coverage advisory (M32).

The bounded, honest slice of the AutoForge "tool-doc -> verifiable env" idea (the full
DAG-tool-seq environment synthesis is research-grade and out of scope). A CLI that
DOCUMENTS a SEMANTIC exit code (3/4/5 — a converged/escalate/skip signal, not the
ubiquitous 0 or the argparse-2) is making a behavioral CONTRACT; if no test asserts that
code, the contract is unverified — the same surface≠real gap test_depth (M26) flags for
assertion-free tests, applied to CLI exit contracts. This is the M26 sibling.

Honest scope (measured 2026-06-16): all 3 CLIs currently documenting a semantic exit code
have it 100% test-covered — there are ZERO real gaps today. This validator is therefore a
FORWARD-LOOKING regression guard, not a bug finder: it stays [PASS] until someone ships a
CLI documenting an exit 3/4/5 with no asserting test. It is NOT a dead guard (it CAN fire
on a realistic future mistake) and is deliberately CONSERVATIVE on both sides — it only
counts a code as "documented" on a high-confidence pattern, and only flags it as uncovered
when no test (literal digit OR resolved EXIT_* constant) asserts it — so it does not defame
a correctly-tested CLI. ADVISORY ([WARN], does not trip run_all's failure regex); graduates
to blocking only via the `graduate-validator` token (roadmap M32: advisory->graduate).

Caller contract (validators/__init__.py): main() -> None, prints [PASS]/[WARN], never raises.
"""
from __future__ import annotations

import ast
import re
import sys
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

_CLI_DIR = _SCRIPTS / "cli"
_TESTS_DIR = _SCRIPTS / "tests"

SEMANTIC_CODES: frozenset[int] = frozenset({3, 4, 5})

# Inline "exit 3" / "exit code 3" / "exit codes: 3".
_INLINE_EXIT_RE = re.compile(r"exit[\s_]*(?:code[s]?)?[:\s=]*([3-5])\b", re.IGNORECASE)
# Contract-enumeration line "  3 = CONVERGED" / "3 = ...". Only trusted inside a docstring
# that also mentions "exit" (context guard against bare arithmetic prose).
_ENUM_LINE_RE = re.compile(r"^\s*([3-5])\s*=\s*\S", re.MULTILINE)
# Test-side assertion of an exit code: `code == 3`, `rc == 4`, `e.code == 5`, `code2 == 3`.
_TEST_INT_ASSERT_RE = re.compile(r"(?:code|rc|exit|status|e\.code)\w*\s*==\s*([0-9])", re.IGNORECASE)
# Test-side assertion via a named constant: `== EXIT_CONVERGED` / `== cli.EXIT_ERROR`.
_TEST_CONST_ASSERT_RE = re.compile(r"==\s*(?:[\w]+\.)?(EXIT_[A-Z_]+)")


def documented_semantic_codes(docstring: str) -> set[int]:
    """High-confidence set of semantic exit codes (3/4/5) a module docstring documents."""
    if not docstring:
        return set()
    codes = {int(x) for x in _INLINE_EXIT_RE.findall(docstring)}
    if "exit" in docstring.lower():
        codes |= {int(x) for x in _ENUM_LINE_RE.findall(docstring)}
    return codes & SEMANTIC_CODES


def _int_constants(source: str) -> dict[str, int]:
    """Module-level NAME = <int literal> assignments (e.g. EXIT_CONVERGED = 3)."""
    out: dict[str, int] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    for node in tree.body:  # module-level only
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, int):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value.value
    return out


def codes_asserted_in_tests(cli_stem: str, cli_constmap: dict[str, int],
                            test_texts: dict[str, str]) -> set[int]:
    """Exit codes asserted by any test that references this CLI module by stem.

    Resolves named EXIT_* constants (via the CLI's own constant map) so a test
    asserting `== EXIT_CONVERGED` counts as covering the integer value.
    """
    found: set[int] = set()
    for text in test_texts.values():
        if cli_stem not in text:
            continue
        found |= {int(x) for x in _TEST_INT_ASSERT_RE.findall(text)}
        for const in _TEST_CONST_ASSERT_RE.findall(text):
            if const in cli_constmap:
                found.add(cli_constmap[const])
    return found


def find_exit_contract_gaps(cli_dir: Path, tests_dir: Path) -> list[tuple[str, list[int]]]:
    """Return [(cli_file, [uncovered semantic codes])] — pure, testable.

    A gap = a semantic exit code (3/4/5) the CLI docstring documents but that NO test
    asserts (neither as a literal digit nor via a resolved EXIT_* constant).
    """
    out: list[tuple[str, list[int]]] = []
    if not cli_dir.is_dir():
        return out
    test_texts: dict[str, str] = {}
    if tests_dir.is_dir():
        for tf in sorted(tests_dir.glob("test_*.py")):
            try:
                test_texts[tf.name] = tf.read_text(encoding="utf-8")
            except OSError:
                continue
    for cf in sorted(cli_dir.glob("*.py")):
        if cf.name == "__init__.py":
            continue
        try:
            source = cf.read_text(encoding="utf-8")
            ds = ast.get_docstring(ast.parse(source)) or ""
        except (OSError, SyntaxError):
            continue
        documented = documented_semantic_codes(ds)
        if not documented:
            continue
        asserted = codes_asserted_in_tests(cf.stem, _int_constants(source), test_texts)
        missing = sorted(documented - asserted)
        if missing:
            out.append((cf.name, missing))
    return out


def main() -> None:
    gaps = find_exit_contract_gaps(_CLI_DIR, _TESTS_DIR)
    if not gaps:
        print("[PASS] exit_contract_coverage: every documented semantic exit code (3/4/5) "
              "has an asserting test")
        return
    for cli_file, codes in gaps:
        codes_str = ", ".join(str(c) for c in codes)
        print(f"[WARN] exit_contract_coverage: {cli_file} documents semantic exit code(s) "
              f"{codes_str} that NO test asserts — the documented contract is unverified "
              f"(surface, not real). Add a test asserting each exit code.")
    try:
        from lib.logging import log_telemetry
        log_telemetry("exit-contract-coverage-gap", {
            "count": len(gaps),
            "samples": [f"{f}:{c}" for f, c in gaps[:10]],
        })
    except Exception:
        pass


if __name__ == "__main__":
    main()
