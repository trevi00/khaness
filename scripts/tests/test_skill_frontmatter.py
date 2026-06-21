#!/usr/bin/env python3
"""Smoke tests for validators/skill_frontmatter.py — uses module-level SKILLS_DIR.

Strategy: monkey-patch SKILLS_DIR to a temp dir for empty/synthetic cases so
the test does not depend on real production skill state.
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from validators import skill_frontmatter as sf  # noqa: E402


def test_missing_skills_dir_passes():
    saved = sf.SKILLS_DIR
    with tempfile.TemporaryDirectory() as td:
        sf.SKILLS_DIR = Path(td) / "does-not-exist"
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                sf.main()
            out = buf.getvalue()
            assert "[PASS]" in out, f"expected [PASS] when SKILLS_DIR missing, got: {out[:200]}"
        finally:
            sf.SKILLS_DIR = saved


def test_empty_skills_dir_passes():
    saved = sf.SKILLS_DIR
    with tempfile.TemporaryDirectory() as td:
        sf.SKILLS_DIR = Path(td)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                sf.main()
            out = buf.getvalue()
            assert "[PASS]" in out, f"expected [PASS] on empty skills dir, got: {out[:200]}"
        finally:
            sf.SKILLS_DIR = saved


def test_valid_skill_passes():
    saved = sf.SKILLS_DIR
    with tempfile.TemporaryDirectory() as td:
        sf.SKILLS_DIR = Path(td)
        sample = sf.SKILLS_DIR / "_common" / "sample.md"
        sample.parent.mkdir(parents=True, exist_ok=True)
        sample.write_text(
            "---\n"
            "name: sample\n"
            "description: smoke test skill\n"
            "keywords: [test]\n"
            "---\n\n"
            "# Sample\n",
            encoding="utf-8",
        )
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                sf.main()
            out = buf.getvalue()
            assert "[PASS]" in out, f"expected [PASS] for valid skill, got: {out[:200]}"
        finally:
            sf.SKILLS_DIR = saved


def test_namespace_violation_emits_fail():
    """harness-* skill under skills/ → [FAIL] (namespace reserved for commands/)."""
    saved = sf.SKILLS_DIR
    with tempfile.TemporaryDirectory() as td:
        sf.SKILLS_DIR = Path(td)
        bad = sf.SKILLS_DIR / "harness-evil" / "skill.md"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text(
            "---\n"
            "name: harness-evil\n"
            "description: violates namespace\n"
            "keywords: [bad]\n"
            "---\n\n"
            "# Bad\n",
            encoding="utf-8",
        )
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                sf.main()
            out = buf.getvalue()
            assert "[FAIL]" in out, f"expected [FAIL] for harness-* skill, got: {out[:300]}"
            assert "namespace violation" in out, f"expected 'namespace violation' message, got: {out[:300]}"
        finally:
            sf.SKILLS_DIR = saved


def main() -> int:
    tests = [
        test_missing_skills_dir_passes,
        test_empty_skills_dir_passes,
        test_valid_skill_passes,
        test_namespace_violation_emits_fail,
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
