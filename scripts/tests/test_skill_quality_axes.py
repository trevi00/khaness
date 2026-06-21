#!/usr/bin/env python3
"""Smoke tests for validators/skill_quality_axes.py — 9게이트 회귀.

Strategy: monkey-patch SKILLS_DIR to a temp dir for synthetic cases.
Enforce 트리거: prefix 화이트리스트(data/, infra/, ml/) OR frontmatter
`quality_axes_enforced: true` (위치 무관 opt-in).
"""
from __future__ import annotations

import io
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from validators import skill_quality_axes as sqa  # noqa: E402


_FM = """\
---
name: sample
description: smoke test skill for 9axis gate
keywords: sample test
intent: smoke
paths:
patterns:
requires: db-design
phase: plan
tech-stack: any
min_score: 1
---

"""

_BODY = """\
# Sample

> One-liner principle.

## 의사결정 트리

### IF 신규 (Plan)
1. step
2. step

## 가이드

- guide line.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | check |
| 성능 효율성 | check |
| 호환성 | check |
| 사용성 | check |
| 신뢰성 | check |
| 보안 | check |
| 유지보수성 | check |
| 이식성 | check |
| 확장성 | check |

## Gotchas

### G1
text 1.

### G2
text 2.

### G3
text 3.

## Source

- https://example.com/spec — verbatim quote, 조회 2026-05-10
"""


def _write_skill(d: Path, rel: str, content: str) -> Path:
    p = d / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def _seed_target(d: Path, stem: str) -> None:
    """G9 cross-ref target 존재 보장."""
    _write_skill(d, f"_common/{stem}.md", "---\nname: " + stem + "\n---\n# " + stem + "\n")


def _run() -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        sqa.main()
    return buf.getvalue()


def test_missing_dir_passes():
    saved = sqa.SKILLS_DIR
    with tempfile.TemporaryDirectory() as td:
        sqa.SKILLS_DIR = Path(td) / "missing"
        try:
            assert "[PASS]" in _run()
        finally:
            sqa.SKILLS_DIR = saved


def test_legacy_subtree_skipped():
    saved = sqa.SKILLS_DIR
    with tempfile.TemporaryDirectory() as td:
        sqa.SKILLS_DIR = Path(td)
        _write_skill(sqa.SKILLS_DIR, "_common/legacy.md", _FM + "# Legacy\n")
        try:
            out = _run()
            assert "[PASS]" in out and "[FAIL]" not in out
        finally:
            sqa.SKILLS_DIR = saved


def test_mandatory_complete_passes():
    saved = sqa.SKILLS_DIR
    with tempfile.TemporaryDirectory() as td:
        sqa.SKILLS_DIR = Path(td)
        _seed_target(sqa.SKILLS_DIR, "db-design")
        _write_skill(sqa.SKILLS_DIR, "data/full.md", _FM + _BODY)
        try:
            out = _run()
            assert "[PASS]" in out, out[:600]
            assert "[FAIL]" not in out
        finally:
            sqa.SKILLS_DIR = saved


def test_mandatory_missing_sections_fails():
    saved = sqa.SKILLS_DIR
    with tempfile.TemporaryDirectory() as td:
        sqa.SKILLS_DIR = Path(td)
        _seed_target(sqa.SKILLS_DIR, "db-design")
        _write_skill(sqa.SKILLS_DIR, "data/bare.md", _FM + "# bare\n")
        try:
            out = _run()
            assert "G4-usability" in out, out[:400]
        finally:
            sqa.SKILLS_DIR = saved


def test_g6_security_http_insecure():
    saved = sqa.SKILLS_DIR
    with tempfile.TemporaryDirectory() as td:
        sqa.SKILLS_DIR = Path(td)
        _seed_target(sqa.SKILLS_DIR, "db-design")
        body = _BODY.replace("https://example.com/spec", "http://example.com/spec")
        _write_skill(sqa.SKILLS_DIR, "data/insecure.md", _FM + body)
        try:
            assert "G6-security" in _run()
        finally:
            sqa.SKILLS_DIR = saved


def test_g7_missing_axis_label():
    saved = sqa.SKILLS_DIR
    with tempfile.TemporaryDirectory() as td:
        sqa.SKILLS_DIR = Path(td)
        _seed_target(sqa.SKILLS_DIR, "db-design")
        body = _BODY.replace("| 확장성 | check |\n", "")
        _write_skill(sqa.SKILLS_DIR, "data/missing_axis.md", _FM + body)
        try:
            out = _run()
            assert "G7-maintainability" in out and "확장성" in out
        finally:
            sqa.SKILLS_DIR = saved


def test_g8_unknown_stack():
    saved = sqa.SKILLS_DIR
    with tempfile.TemporaryDirectory() as td:
        sqa.SKILLS_DIR = Path(td)
        _seed_target(sqa.SKILLS_DIR, "db-design")
        bad_fm = _FM.replace("tech-stack: any", "tech-stack: martian-lang")
        _write_skill(sqa.SKILLS_DIR, "data/bad_stack.md", bad_fm + _BODY)
        try:
            assert "G8-portability" in _run()
        finally:
            sqa.SKILLS_DIR = saved


def test_g9_orphan_requires():
    saved = sqa.SKILLS_DIR
    with tempfile.TemporaryDirectory() as td:
        sqa.SKILLS_DIR = Path(td)
        bad_fm = _FM.replace("requires: db-design", "requires: nonexistent-skill")
        _write_skill(sqa.SKILLS_DIR, "data/orphan.md", bad_fm + _BODY)
        try:
            assert "G9-extensibility" in _run()
        finally:
            sqa.SKILLS_DIR = saved


def test_enforce_via_flag_outside_prefix():
    """`_common/` 위치 + `quality_axes_enforced: true` → enforce."""
    saved = sqa.SKILLS_DIR
    with tempfile.TemporaryDirectory() as td:
        sqa.SKILLS_DIR = Path(td)
        _seed_target(sqa.SKILLS_DIR, "db-design")
        opted_in_fm = _FM.replace(
            "min_score: 1\n", "min_score: 1\nquality_axes_enforced: true\n"
        )
        _write_skill(sqa.SKILLS_DIR, "_common/opt_in.md", opted_in_fm + "# bare\n")
        try:
            assert "G4-usability" in _run()
        finally:
            sqa.SKILLS_DIR = saved


def main() -> int:
    tests = [
        test_missing_dir_passes,
        test_legacy_subtree_skipped,
        test_mandatory_complete_passes,
        test_mandatory_missing_sections_fails,
        test_g6_security_http_insecure,
        test_g7_missing_axis_label,
        test_g8_unknown_stack,
        test_g9_orphan_requires,
        test_enforce_via_flag_outside_prefix,
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
