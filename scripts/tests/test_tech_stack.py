#!/usr/bin/env python3
"""Unit tests for lib/tech_stack.py.

Covers:
- Flat schema (CLAUDE.md spec): top-level `stack:` block
- Nested multi-stack schema: `backend:` + `frontend:` + `mobile:` blocks
- Candidate path emission (most-specific to least-specific)
- read_language across both schemas
- extensions list opt-in
- File missing / cwd None edge cases
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.tech_stack import (  # noqa: E402
    _candidate_paths,
    load_tech_stack,
    read_language,
)


def _write_yaml(cwd: Path, content: str) -> None:
    cdir = cwd / ".claude"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "tech-stack.yaml").write_text(content, encoding="utf-8")


# === _candidate_paths unit tests ===

def test_candidates_full_triple():
    out = _candidate_paths("java", "springboot", "3.2")
    assert out[0] == "java/springboot-3.2", f"most-specific first, got {out}"
    assert "java/springboot" in out
    assert "java/lang" in out
    assert "java" in out


def test_candidates_lang_only():
    out = _candidate_paths("dart", "", "")
    assert out == ["dart/lang", "dart"], f"lang-only got {out}"


def test_candidates_lang_framework_no_version():
    out = _candidate_paths("typescript", "react", "")
    assert "typescript/react" in out
    assert "typescript/react-" not in "".join(out), "no empty-version suffix"


def test_candidates_major_version_xform():
    """Numeric major version 18 → also emits 18.x for kotlin/1.9.x-style trees."""
    out = _candidate_paths("typescript", "", "5")
    assert "typescript/5" in out
    assert "typescript/5.x" in out, f"major-only version should emit .x variant, got {out}"


def test_candidates_dedupe():
    out = _candidate_paths("ts", "ts", "ts")
    # ts/ts-ts then ts/ts then ts/ts then ts/lang then ts — middle dupes drop
    assert out.count("ts/ts") == 1
    assert out.count("ts") == 1


# === load_tech_stack flat schema ===

def test_flat_schema_full():
    with tempfile.TemporaryDirectory() as td:
        _write_yaml(Path(td),
                    "stack:\n"
                    "  language: java\n"
                    '  framework: springboot\n'
                    '  version: "3.2"\n')
        paths = load_tech_stack(td)
        assert paths is not None
        assert "_common" in paths
        assert "java/springboot-3.2" in paths
        assert "java/springboot" in paths


def test_flat_schema_with_extensions():
    with tempfile.TemporaryDirectory() as td:
        _write_yaml(Path(td),
                    "stack:\n  language: java\n"
                    '  framework: springboot\n  version: "3.2"\n'
                    "extensions:\n"
                    "  - flutter/example_app-agent\n"
                    "  - kotlin/android\n")
        paths = load_tech_stack(td)
        assert "flutter/example_app-agent" in paths
        assert "kotlin/android" in paths


# === load_tech_stack nested schema (the F1 fix) ===

def test_nested_backend_only():
    with tempfile.TemporaryDirectory() as td:
        _write_yaml(Path(td),
                    "backend:\n"
                    "  language: java\n"
                    "  framework: springboot\n"
                    '  version: "3.5"\n')
        paths = load_tech_stack(td)
        assert "java/springboot-3.5" in paths


def test_nested_backend_plus_frontend_ecommerce_v2_shape():
    """Reproduces ecommerce-v2/.claude/tech-stack.yaml multi-stack form."""
    with tempfile.TemporaryDirectory() as td:
        _write_yaml(Path(td),
                    "backend:\n"
                    "  language: java\n"
                    "  framework: springboot\n"
                    '  version: "3.2"\n'
                    "database:\n"
                    "  type: mysql\n"
                    '  version: "5.7"\n'
                    "frontend:\n"
                    "  language: typescript\n"
                    "  framework: react\n"
                    '  version: "18"\n')
        paths = load_tech_stack(td)
        # Backend block contributes
        assert "java/springboot-3.2" in paths
        assert "java/springboot" in paths
        # Frontend block contributes (the F1 regression case)
        assert "typescript/react" in paths
        assert "typescript/react-18" in paths
        # _common always first
        assert paths[0] == "_common"


def test_nested_with_mobile_block():
    with tempfile.TemporaryDirectory() as td:
        _write_yaml(Path(td),
                    "mobile:\n"
                    "  language: kotlin\n"
                    "  framework: android\n")
        paths = load_tech_stack(td)
        assert "kotlin/android" in paths


def test_nested_block_order_preserved():
    """stack > backend > frontend > mobile per _LANG_BLOCKS order."""
    with tempfile.TemporaryDirectory() as td:
        _write_yaml(Path(td),
                    "frontend:\n  language: typescript\n  framework: react\n"
                    "backend:\n  language: java\n  framework: springboot\n")
        paths = load_tech_stack(td)
        java_idx = paths.index("java/springboot")
        ts_idx = paths.index("typescript/react")
        assert java_idx < ts_idx, f"backend must precede frontend in candidate set, got {paths}"


# === read_language ===

def test_read_language_flat():
    with tempfile.TemporaryDirectory() as td:
        _write_yaml(Path(td), "stack:\n  language: java\n")
        assert read_language(td) == "java"


def test_read_language_nested_backend():
    with tempfile.TemporaryDirectory() as td:
        _write_yaml(Path(td),
                    "backend:\n  language: java\n"
                    "frontend:\n  language: typescript\n")
        # _LANG_BLOCKS order: stack → backend → frontend, so java wins
        assert read_language(td) == "java"


def test_read_language_nested_frontend_only():
    with tempfile.TemporaryDirectory() as td:
        _write_yaml(Path(td),
                    "frontend:\n  language: typescript\n  framework: react\n")
        assert read_language(td) == "typescript"


# === edge cases ===

def test_missing_file_returns_none():
    with tempfile.TemporaryDirectory() as td:
        # no .claude/tech-stack.yaml written
        assert load_tech_stack(td) is None
        assert read_language(td) is None


def test_empty_cwd_returns_none():
    assert load_tech_stack(None) is None
    assert load_tech_stack("") is None


def test_no_language_anywhere_returns_none():
    """tech-stack.yaml exists but has no language → returns None (caller falls back)."""
    with tempfile.TemporaryDirectory() as td:
        _write_yaml(Path(td),
                    "database:\n  type: mysql\n  version: \"5.7\"\n")
        assert load_tech_stack(td) is None


def main() -> int:
    tests = [
        # _candidate_paths
        test_candidates_full_triple,
        test_candidates_lang_only,
        test_candidates_lang_framework_no_version,
        test_candidates_major_version_xform,
        test_candidates_dedupe,
        # flat schema
        test_flat_schema_full,
        test_flat_schema_with_extensions,
        # nested schema (F1 fix)
        test_nested_backend_only,
        test_nested_backend_plus_frontend_ecommerce_v2_shape,
        test_nested_with_mobile_block,
        test_nested_block_order_preserved,
        # read_language
        test_read_language_flat,
        test_read_language_nested_backend,
        test_read_language_nested_frontend_only,
        # edges
        test_missing_file_returns_none,
        test_empty_cwd_returns_none,
        test_no_language_anywhere_returns_none,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    if failed == 0:
        print(f"[OK] {len(tests)} tests passed")
        return 0
    print(f"[FAIL] {failed}/{len(tests)} tests failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
