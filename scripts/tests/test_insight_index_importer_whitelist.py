#!/usr/bin/env python3
"""Tests for validators.insight_index_importer_whitelist (S2 PR-tests).

debate-1779267594-edb2a2 D7_enforcement LOCK — AST coverage of:
  - relative imports (`from .insight_index import append` within lib/)
  - aliased imports (`from lib import insight_index as ii` + `import lib.insight_index as ii`)
  - module-attribute access (`ii.append(...)`)
  - bare `import lib.insight_index` + `lib.insight_index.X` attribute path
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from validators.insight_index_importer_whitelist import (  # noqa: E402
    _InsightIndexUseVisitor,
    _is_forbidden,
    _references_target,
    _resolve_relative,
)


def test_absolute_import_from():
    tree = ast.parse("from lib.insight_index import append")
    v = _InsightIndexUseVisitor("engine.debate.test")
    v.visit(tree)
    assert any("from lib.insight_index" in desc for _, desc in v.hits)


def test_aliased_from_lib_import():
    tree = ast.parse("from lib import insight_index as ii\nii.append({})")
    v = _InsightIndexUseVisitor("engine.debate.test")
    v.visit(tree)
    # Both the import line AND the attribute access should be flagged.
    descs = [desc for _, desc in v.hits]
    assert any("from lib import insight_index" in d for d in descs), descs
    assert any("ii.append" in d for d in descs), descs


def test_bare_import_then_attribute():
    tree = ast.parse("import lib.insight_index\nlib.insight_index.append({})")
    v = _InsightIndexUseVisitor("engine.debate.test")
    v.visit(tree)
    descs = [desc for _, desc in v.hits]
    assert any("import lib.insight_index" in d for d in descs)


def test_relative_import_within_lib():
    """from .insight_index import append (level=1) resolves to lib.insight_index."""
    resolved = _resolve_relative(level=1, module="insight_index",
                                 importer_pkg=["lib"])
    assert resolved == "lib.insight_index"

    tree = ast.parse("from .insight_index import append")
    v = _InsightIndexUseVisitor("lib.evaluator_dispatcher")
    v.visit(tree)
    assert v.hits, "relative-from import must be detected"


def test_relative_import_grandparent():
    """from ..insight_index import X within a hypothetical lib.subpkg.module."""
    resolved = _resolve_relative(level=2, module="insight_index",
                                 importer_pkg=["lib", "subpkg"])
    assert resolved == "lib.insight_index"


def test_unaffected_module_no_hit():
    """Unrelated imports must produce no hits."""
    tree = ast.parse("import os\nfrom pathlib import Path")
    v = _InsightIndexUseVisitor("engine.orchestrator")
    v.visit(tree)
    assert v.hits == []


def test_forbidden_set_matches_engine_debate_subtree():
    assert _is_forbidden("engine.debate") is True
    assert _is_forbidden("engine.debate.proposer") is True
    assert _is_forbidden("engine.debate.deeply.nested.module") is True
    assert _is_forbidden("lib.evaluator_dispatcher") is True
    # Allowed modules must NOT match (false-positive check):
    assert _is_forbidden("engine.orchestrator") is False
    assert _is_forbidden("lib.insight_index") is False
    assert _is_forbidden("handlers.stop.learner") is False


def test_references_target_picks_subattribute_paths():
    assert _references_target("lib.insight_index") is True
    assert _references_target("lib.insight_index.append") is True
    assert _references_target("lib.insight_indexicator") is False
    assert _references_target("lib") is False
    assert _references_target(None) is False


def test_full_validator_run_passes_clean_tree():
    """End-to-end: invoking the validator main() on the current scripts/ tree
    must not raise and must emit a [PASS] line (no current-tree violations)."""
    import io
    import contextlib
    from validators import get_validator
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        get_validator("insight_index_importer_whitelist")()
    out = buf.getvalue()
    assert "[PASS]" in out, f"expected [PASS], got: {out}"
    assert "[FAIL]" not in out, f"unexpected [FAIL]: {out}"


TESTS = [
    test_absolute_import_from,
    test_aliased_from_lib_import,
    test_bare_import_then_attribute,
    test_relative_import_within_lib,
    test_relative_import_grandparent,
    test_unaffected_module_no_hit,
    test_forbidden_set_matches_engine_debate_subtree,
    test_references_target_picks_subattribute_paths,
    test_full_validator_run_passes_clean_tree,
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
