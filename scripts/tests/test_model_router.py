#!/usr/bin/env python3
"""Tests for lib/model_router.py — complexity-based tier router."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def test_empty_prompt_returns_haiku():
    from lib.model_router import classify_complexity
    c = classify_complexity("")
    assert c.tier == "haiku"
    assert "empty" in c.reasons


def test_whitespace_only_returns_haiku():
    from lib.model_router import classify_complexity
    c = classify_complexity("   \t\n   ")
    assert c.tier == "haiku"


def test_greeting_classified_haiku():
    from lib.model_router import classify_complexity
    c = classify_complexity("hi!")
    assert c.tier == "haiku"
    assert "greeting" in c.reasons


def test_typo_fix_classified_haiku():
    from lib.model_router import classify_complexity
    c = classify_complexity("rename foo to bar")
    assert c.tier == "haiku"
    assert "trivial" in c.reasons


def test_implement_alone_classified_sonnet():
    from lib.model_router import classify_complexity
    c = classify_complexity("implement a CSV parser")
    assert c.tier == "sonnet"
    assert "implement" in c.reasons


def test_architecture_classified_at_least_sonnet():
    from lib.model_router import classify_complexity
    c = classify_complexity("redesign the architecture for high-throughput ingest")
    assert c.tier in ("sonnet", "opus")
    assert "design-class" in c.reasons


def test_security_classified_at_least_sonnet():
    from lib.model_router import classify_complexity
    c = classify_complexity("audit this code for vulnerability")
    assert c.tier in ("sonnet", "opus")
    assert "security-sensitive" in c.reasons


def test_architecture_plus_implement_reaches_opus():
    """design-class (3) + implement (1) = 4 hits OPUS_FLOOR."""
    from lib.model_router import classify_complexity
    c = classify_complexity("implement a refactor of the architecture")
    assert c.tier == "opus"


def test_long_design_prompt_reaches_opus():
    """design-class (3) + medium-prompt (1) = 4 hits OPUS_FLOOR."""
    from lib.model_router import classify_complexity
    text = "redesign the architecture: " + ("detail " * 100)  # >500 chars
    c = classify_complexity(text)
    assert c.tier == "opus"


def test_korean_design_classified_at_least_sonnet():
    from lib.model_router import classify_complexity
    c = classify_complexity("이 시스템 아키텍처 재구성하자")
    assert c.tier in ("sonnet", "opus")


def test_long_prompt_escalates_score():
    from lib.model_router import classify_complexity
    long_text = "implement " + ("a" * 3000)
    c = classify_complexity(long_text)
    assert any("long-prompt" in r for r in c.reasons)
    assert c.score >= 3  # implement (1) + long-prompt-3k (2)


def test_medium_prompt_escalates_score():
    from lib.model_router import classify_complexity
    text = "implement " + ("a" * 600)
    c = classify_complexity(text)
    assert any("medium-prompt" in r for r in c.reasons)


def test_resolve_model_id_anthropic_haiku():
    from lib.model_router import resolve_model_id
    m = resolve_model_id("anthropic", "haiku")
    assert m and "haiku" in m


def test_resolve_model_id_anthropic_opus():
    from lib.model_router import resolve_model_id
    m = resolve_model_id("anthropic", "opus")
    assert m and "opus" in m


def test_resolve_model_id_openai_sonnet():
    from lib.model_router import resolve_model_id
    m = resolve_model_id("openai", "sonnet")
    assert m == "gpt-5-codex"


def test_resolve_model_id_unknown_provider_returns_none():
    from lib.model_router import resolve_model_id
    assert resolve_model_id("nonexistent-provider", "haiku") is None


def test_classification_is_frozen():
    from lib.model_router import classify_complexity
    c = classify_complexity("implement a parser")
    try:
        c.tier = "opus"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("Classification must be frozen dataclass")


def test_reasons_is_tuple_not_list():
    from lib.model_router import classify_complexity
    c = classify_complexity("implement a parser")
    assert isinstance(c.reasons, tuple)


TESTS = [
    test_empty_prompt_returns_haiku,
    test_whitespace_only_returns_haiku,
    test_greeting_classified_haiku,
    test_typo_fix_classified_haiku,
    test_implement_alone_classified_sonnet,
    test_architecture_classified_at_least_sonnet,
    test_security_classified_at_least_sonnet,
    test_architecture_plus_implement_reaches_opus,
    test_long_design_prompt_reaches_opus,
    test_korean_design_classified_at_least_sonnet,
    test_long_prompt_escalates_score,
    test_medium_prompt_escalates_score,
    test_resolve_model_id_anthropic_haiku,
    test_resolve_model_id_anthropic_opus,
    test_resolve_model_id_openai_sonnet,
    test_resolve_model_id_unknown_provider_returns_none,
    test_classification_is_frozen,
    test_reasons_is_tuple_not_list,
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
