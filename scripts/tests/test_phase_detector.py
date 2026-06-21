#!/usr/bin/env python3
"""Tests for lib/phase_detector.py — prompt phase classification + strict-design gate."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def test_empty_prompt_no_phases():
    from lib.phase_detector import detect_phase
    assert detect_phase("") == set()


def test_korean_plan_signal_detected():
    from lib.phase_detector import detect_phase
    assert "plan" in detect_phase("이 시스템 설계 좀 봐줘")


def test_english_plan_signal_detected():
    from lib.phase_detector import detect_phase
    assert "plan" in detect_phase("How should we design this architecture")


def test_implement_signal():
    from lib.phase_detector import detect_phase
    assert "implement" in detect_phase("이 함수 구현해줘")


def test_review_signal():
    from lib.phase_detector import detect_phase
    assert "review" in detect_phase("Please review my changes")


def test_deploy_signal():
    from lib.phase_detector import detect_phase
    assert "deploy" in detect_phase("ready to ship to production")


def test_debug_signal():
    from lib.phase_detector import detect_phase
    assert "debug" in detect_phase("이 버그 좀 고쳐줘")


def test_multiple_phases_can_match():
    from lib.phase_detector import detect_phase
    phases = detect_phase("design and implement the new module")
    assert "plan" in phases
    assert "implement" in phases


def test_ascii_word_boundary_avoids_substring_match():
    """`how` must not match `however`."""
    from lib.phase_detector import detect_phase
    assert "plan" not in detect_phase("however,")


def test_strict_design_keyword_architecture():
    from lib.phase_detector import is_strict_design_intent
    assert is_strict_design_intent("Should we change the architecture") is True


def test_strict_design_keyword_korean_refactor():
    from lib.phase_detector import is_strict_design_intent
    assert is_strict_design_intent("이 모듈 리팩토링 해야겠다") is True


def test_strict_design_excludes_casual_how():
    """Critic C-1: 'how do I rename X' must not fire strict-design."""
    from lib.phase_detector import is_strict_design_intent
    assert is_strict_design_intent("how do I rename this variable") is False


def test_strict_design_empty_returns_false():
    from lib.phase_detector import is_strict_design_intent
    assert is_strict_design_intent("") is False


def test_strict_design_keyword_set_locked():
    """The keyword set is load-bearing for debate trigger — pin its membership."""
    from lib.phase_detector import STRICT_DESIGN_KEYWORDS
    assert "architecture" in STRICT_DESIGN_KEYWORDS
    assert "아키텍처" in STRICT_DESIGN_KEYWORDS
    assert "설계" in STRICT_DESIGN_KEYWORDS
    assert "refactor" in STRICT_DESIGN_KEYWORDS
    assert "리팩토링" in STRICT_DESIGN_KEYWORDS
    # 'how' explicitly excluded — Critic C-1 mitigation
    assert "how" not in STRICT_DESIGN_KEYWORDS
    assert "어떻게" not in STRICT_DESIGN_KEYWORDS


def test_phase_signals_keys_complete():
    from lib.phase_detector import PHASE_SIGNALS
    assert set(PHASE_SIGNALS) == {"plan", "implement", "review", "deploy", "debug"}


TESTS = [
    test_empty_prompt_no_phases,
    test_korean_plan_signal_detected,
    test_english_plan_signal_detected,
    test_implement_signal,
    test_review_signal,
    test_deploy_signal,
    test_debug_signal,
    test_multiple_phases_can_match,
    test_ascii_word_boundary_avoids_substring_match,
    test_strict_design_keyword_architecture,
    test_strict_design_keyword_korean_refactor,
    test_strict_design_excludes_casual_how,
    test_strict_design_empty_returns_false,
    test_strict_design_keyword_set_locked,
    test_phase_signals_keys_complete,
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
