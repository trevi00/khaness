#!/usr/bin/env python3
"""Meta-tests for lib.l2_promoter eligibility set integrity (W17 D3 amendment).

Per converged debate session debate-1779376939-ff5cbe (sha1
f570e213a9f92403dc7ed68516f2dd331727248e):

  (a) test_l2_eligible_meta_check — module-load-time guard exists and is
      a runtime check (NOT `assert`, which is stripped under `python -O`)
  (b) test_l2_reserved_not_consulted — `_eligible()` source does NOT
      reference `_RESERVED_FUTURE_CLASSES` (substring scan via inspect)
  (c) test_l2_state_path_uses_lib_paths — positive AST allow-list:
      `lib/l2_promoter.py` imports STATE_DIR from `lib.paths` ONLY if it
      needs a state-dir symbol at all; never references the fabricated
      `lib.project_paths.state_dir` (Critic gen-2 C1).

These tests guard the W17 D3 amendment invariants at a layer the
existing test_l2_promoter.py suite does not cover (those tests exercise
the algorithm; these test the eligibility contract surface itself).
"""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _load_promoter_source() -> str:
    path = _SCRIPTS / "lib" / "l2_promoter.py"
    return path.read_text(encoding="utf-8")


def test_l2_eligible_meta_check_uses_runtime_raise_not_assert():
    """W17 D3_AMEND_TESTS — guard must be `if ... raise`, NOT `assert`.

    `assert` is removed under PYTHONOPTIMIZE / `python -O`; the meta-check
    that sentinel never leaks into _ELIGIBLE_EVENT_TYPES must survive
    optimized runs.
    """
    src = _load_promoter_source()
    # Sentinel literal must appear
    assert "__test_only_never_eligible__" in src, (
        "sentinel literal '__test_only_never_eligible__' missing from l2_promoter.py"
    )
    # Must use raise RuntimeError, NOT assert. The sentinel reference may
    # be a literal Constant OR a Name binding to the literal.
    tree = ast.parse(src)
    # Collect names bound to the sentinel literal (e.g. _TEST_SENTINEL = "__test_only_never_eligible__")
    bound_names_to_sentinel: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if (
                isinstance(node.value, ast.Constant)
                and node.value.value == "__test_only_never_eligible__"
            ):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        bound_names_to_sentinel.add(tgt.id)
        if isinstance(node, ast.AnnAssign):
            if (
                node.value is not None
                and isinstance(node.value, ast.Constant)
                and node.value.value == "__test_only_never_eligible__"
            ):
                if isinstance(node.target, ast.Name):
                    bound_names_to_sentinel.add(node.target.id)

    def _refs_sentinel(expr: ast.AST) -> bool:
        for sub in ast.walk(expr):
            if isinstance(sub, ast.Constant) and sub.value == "__test_only_never_eligible__":
                return True
            if isinstance(sub, ast.Name) and sub.id in bound_names_to_sentinel:
                return True
        return False

    sentinel_in_assert_test = False
    sentinel_in_if_test_with_raise = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert) and _refs_sentinel(node.test):
            sentinel_in_assert_test = True
        if isinstance(node, ast.If) and _refs_sentinel(node.test):
            # Must have a Raise inside the body
            for sub in ast.walk(node):
                if isinstance(sub, ast.Raise):
                    sentinel_in_if_test_with_raise = True
                    break
    assert not sentinel_in_assert_test, (
        "sentinel guard uses `assert`; must use `if ... raise RuntimeError` "
        "to survive `python -O` (W17 D3_AMEND_TESTS condition #3)"
    )
    assert sentinel_in_if_test_with_raise, (
        "sentinel guard not found as `if ... raise`; "
        "expected module-load-time runtime check"
    )


def test_l2_reserved_not_consulted_by_eligible_function():
    """W17 condition #1 — `_eligible()` MUST NOT reference _RESERVED_FUTURE_CLASSES.

    Uses `inspect.getsource(_eligible)` to enforce the separation: the
    eligibility predicate is the single source of truth for what gets
    promoted; the RESERVED set is documentary ONLY.
    """
    from lib import l2_promoter
    fn_src = inspect.getsource(l2_promoter._eligible)
    assert "_RESERVED_FUTURE_CLASSES" not in fn_src, (
        f"_eligible() source contains '_RESERVED_FUTURE_CLASSES' reference — "
        f"RESERVED set must be documentary only, never consulted by eligibility predicate. "
        f"Source:\n{fn_src}"
    )
    # Belt-and-suspenders: ensure _eligible only consults _ELIGIBLE_EVENT_TYPES
    assert "_ELIGIBLE_EVENT_TYPES" in fn_src, (
        f"_eligible() does not reference _ELIGIBLE_EVENT_TYPES — eligibility "
        f"contract broken. Source:\n{fn_src}"
    )


def test_l2_promoter_state_path_uses_lib_paths_only():
    """W17 condition #5 — state-dir symbol MUST come from `lib.paths.STATE_DIR`.

    Positive allow-list (S2 polish per Architect gen-3 edit_note): assert
    that IF lib/l2_promoter.py imports any state-path symbol, it imports
    `STATE_DIR` from `lib.paths`. Never `lib.project_paths.state_dir`
    (Critic gen-2 C1 fabrication). AST scan, not string-grep.
    """
    src = _load_promoter_source()
    tree = ast.parse(src)
    forbidden_modules = {"lib.project_paths", "project_paths"}
    state_dir_imports: list[tuple[str, str]] = []  # (module, name)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                if mod in forbidden_modules:
                    raise AssertionError(
                        f"lib/l2_promoter.py imports from forbidden module "
                        f"{mod!r}; use `from lib.paths import STATE_DIR` instead "
                        f"(W17 condition #5; paths.py:28)"
                    )
                if alias.name == "STATE_DIR" or alias.name == "state_dir":
                    state_dir_imports.append((mod, alias.name))
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in forbidden_modules:
                    raise AssertionError(
                        f"lib/l2_promoter.py imports forbidden module "
                        f"{alias.name!r}; use lib.paths.STATE_DIR instead"
                    )
    # If any state-dir symbol is imported, it must be STATE_DIR from lib.paths
    for mod, name in state_dir_imports:
        assert name == "STATE_DIR", (
            f"state-dir symbol must be `STATE_DIR` (constant), not {name!r}"
        )
        assert mod in ("lib.paths", ".paths"), (
            f"STATE_DIR must come from `lib.paths` (paths.py:28), got {mod!r}"
        )


def test_l2_reserved_classes_are_disjoint_from_eligible():
    """Defense-in-depth — even though _eligible doesn't consult RESERVED,
    ensure the two sets share no members. A class cannot be ACTIVE and
    RESERVED simultaneously.
    """
    from lib.l2_promoter import _ELIGIBLE_EVENT_TYPES, _RESERVED_FUTURE_CLASSES
    overlap = _ELIGIBLE_EVENT_TYPES & _RESERVED_FUTURE_CLASSES
    assert overlap == set(), (
        f"_ELIGIBLE_EVENT_TYPES and _RESERVED_FUTURE_CLASSES overlap on "
        f"{sorted(overlap)} — a class cannot be both ACTIVE and RESERVED"
    )


def test_l2_active_set_matches_m25_amendment():
    """M25 D3 amendment (debate-1781649830-m25a01, LOCK d42ac5e3) — ACTIVE set is
    {skill_candidate, orchestrator}. orchestrator was promoted from RESERVED because
    the M25 D2/D4 re-key drops correlation_id from _group_key, dissolving the W17
    'needs multi-session correlation_id' blocker (the paired group_key change the W17
    RESERVED rationale demanded).
    """
    from lib.l2_promoter import _ELIGIBLE_EVENT_TYPES
    assert _ELIGIBLE_EVENT_TYPES == frozenset({"skill_candidate", "orchestrator"}), (
        f"M25 D3 LOCK: ACTIVE set must be {{'skill_candidate','orchestrator'}}, got "
        f"{sorted(_ELIGIBLE_EVENT_TYPES)}."
    )


def test_l2_reserved_set_matches_m25_amendment():
    """M25 D3 amendment — RESERVED set drops orchestrator (now ACTIVE) and adds
    work_unit_digest (its only repeating cluster is single-session, suppressed by the
    distinct_session>=2 gate, so admitting it = dead eligibility).
    """
    from lib.l2_promoter import _RESERVED_FUTURE_CLASSES
    expected = frozenset({"wonder", "debate", "evaluator", "learner", "work_unit_digest"})
    assert _RESERVED_FUTURE_CLASSES == expected, (
        f"M25 D3 LOCK: RESERVED set must be {sorted(expected)}, got "
        f"{sorted(_RESERVED_FUTURE_CLASSES)}"
    )


TESTS = [
    test_l2_eligible_meta_check_uses_runtime_raise_not_assert,
    test_l2_reserved_not_consulted_by_eligible_function,
    test_l2_promoter_state_path_uses_lib_paths_only,
    test_l2_reserved_classes_are_disjoint_from_eligible,
    test_l2_active_set_matches_m25_amendment,
    test_l2_reserved_set_matches_m25_amendment,
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
