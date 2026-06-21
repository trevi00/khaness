#!/usr/bin/env python3
"""Tests for the skill_structure_depth bar (M21) — lib + advisory validator.
Validator-name test (run by run_all). main()->int.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.skill_structure_depth import passes_depth_bar, structure_depth_gaps  # noqa: E402
import validators.skill_structure_depth as vmod  # noqa: E402

_FULL = """---
name: x
---
## 의사결정 트리
- if A then do B
- else do C
## 가이드
Step 1: do the first thing here
Step 2: then the second thing
## Gotchas
- gotcha one is real
- gotcha two also
- gotcha three as well
## 9축 품질 체크
| axis | score |
| 기능 적합성 | 5 |
## Source
- https://example.com — establishes the pattern
- scripts/lib/x.py — local anchor
"""


def test_full_body_passes():
    assert structure_depth_gaps(_FULL) == []
    assert passes_depth_bar(_FULL) is True


def test_missing_section_flagged():
    body = _FULL.replace("## Source\n- https://example.com — establishes the pattern\n- scripts/lib/x.py — local anchor\n", "")
    gaps = structure_depth_gaps(body)
    assert any("missing section '## Source'" in g for g in gaps)


def test_hollow_section_flagged():
    # 가이드 header present but no content lines under it
    body = _FULL.replace("Step 1: do the first thing here\nStep 2: then the second thing\n", "")
    gaps = structure_depth_gaps(body)
    assert any("hollow section '## 가이드'" in g for g in gaps)


def test_gotchas_below_min_flagged():
    body = _FULL.replace("- gotcha two also\n- gotcha three as well\n", "")
    gaps = structure_depth_gaps(body)
    assert any("Gotchas" in g and "< 3" in g for g in gaps)


def test_empty_body():
    assert structure_depth_gaps("") == ["empty skill body"]
    assert structure_depth_gaps("   ") == ["empty skill body"]


def test_constants_match_skill_quality_axes():
    """lib mirrors the validators constants (lib may not import validators); this
    test layer cross-checks both so the mirror never drifts."""
    from lib.skill_structure_depth import MIN_GOTCHAS, REQUIRED_SECTIONS
    from validators.skill_quality_axes import (
        MIN_GOTCHAS as VA_MIN_GOTCHAS,
        REQUIRED_SECTIONS as VA_REQUIRED_SECTIONS,
    )
    assert REQUIRED_SECTIONS == VA_REQUIRED_SECTIONS
    assert MIN_GOTCHAS == VA_MIN_GOTCHAS


def test_validator_finds_hollow_candidate_skips_historical():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "skill-good.md").write_text(_FULL, encoding="utf-8")
        (d / "skill-hollow.md").write_text("---\nname: y\n---\n## 가이드\n## Source\n", encoding="utf-8")
        # historical files must be skipped
        (d / "skill-old.md.dismissed.123").write_text("## 가이드\n", encoding="utf-8")
        hollow = dict(vmod.find_hollow_candidates(d))
        assert "skill-hollow.md" in hollow and "skill-good.md" not in hollow
        assert all(".dismissed" not in n for n in hollow)


def test_validator_main_pass_on_empty_dir(capsys=None):
    import io
    from contextlib import redirect_stdout
    with tempfile.TemporaryDirectory() as td:
        from unittest import mock
        with mock.patch.object(vmod, "_candidates_dir", return_value=Path(td)):
            buf = io.StringIO()
            with redirect_stdout(buf):
                vmod.main()
            assert "[PASS]" in buf.getvalue()


def main() -> int:
    failed = 0
    n = 0
    for name, obj in list(globals().items()):
        if not name.startswith("test_"):
            continue
        n += 1
        try:
            obj()
            print(f"  [OK] {name}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [ERR] {name}: {e!r}")
    if failed:
        print(f"\n{failed}/{n} failed")
        return 1
    print(f"\n[OK] {n} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
