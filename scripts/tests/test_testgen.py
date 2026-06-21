#!/usr/bin/env python3
"""Tests for lib/testgen.py — Gherkin @id -> stack test stubs + round-trip (D4)."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_FEATURE = """\
@order
Feature: Orders
  Background:
    Given the catalog is loaded
  @id:create-order
  Scenario: Create order
    Given a customer with items
    When they submit the order
    Then an order id is returned
    And the cart is emptied
  @id:tiered-price
  Scenario Outline: Tiered price
    Given a <tier> customer
    Then the discount is <pct>
    Examples:
      | tier | pct |
      | gold | 10  |
"""


def _feat():
    from lib.spec_bundle import parse_feature
    return parse_feature(_FEATURE)


def test_cucumber_jvm_generates_feature_and_stepdefs():
    from lib.testgen import generate
    arts = generate(_feat(), framework="cucumber-jvm", domain="order", package="kr.x.spec")
    paths = list(arts)
    assert any(p.endswith("order.feature") for p in paths)
    java = next(c for p, c in arts.items() if p.endswith(".java"))
    assert "package kr.x.spec;" in java
    assert "@Given(\"a customer with items\")" in java
    assert "@When(\"they submit the order\")" in java
    assert "@Then(\"an order id is returned\")" in java
    # And the cart is emptied -> And normalizes to the preceding Then
    assert "@Then(\"the cart is emptied\")" in java
    assert "PendingException" in java
    # background step present once
    assert java.count('"the catalog is loaded"') == 1


def test_scenario_outline_param_becomes_cucumber_placeholder():
    from lib.testgen import generate
    java = next(c for p, c in generate(_feat(), framework="cucumber-jvm",
                                       domain="order", package="p").items()
                if p.endswith(".java"))
    # <tier> -> {string} placeholder + a String param
    assert '@Given("a {string} customer")' in java
    assert "String tier" in java


def test_rendered_feature_preserves_ids_for_roundtrip():
    from lib.testgen import generate
    from lib.spec_bundle import parse_feature
    feat_text = next(c for p, c in generate(_feat(), framework="cucumber-jvm",
                                            domain="order", package="p").items()
                     if p.endswith(".feature"))
    reparsed = parse_feature(feat_text)
    assert reparsed.scenario_ids() == ["create-order", "tiered-price"]
    assert reparsed.scenarios[1].is_outline
    assert reparsed.scenarios[1].examples == [{"tier": "gold", "pct": "10"}]


def test_flutter_gherkin_dispatch():
    from lib.testgen import generate
    arts = generate(_feat(), framework="flutter_gherkin", domain="order")
    assert any(p.endswith("order_steps.dart") for p in arts)
    dart = next(c for p, c in arts.items() if p.endswith(".dart"))
    assert "flutter_gherkin" in dart and "UnimplementedError" in dart


def test_cucumber_rs_dispatch():
    from lib.testgen import generate
    arts = generate(_feat(), framework="cucumber-rs", domain="order")
    assert any(p.endswith("order_steps.rs") for p in arts)
    assert any(p.endswith("tests/features/order.feature") for p in arts)
    rs = next(c for p, c in arts.items() if p.endswith(".rs"))
    assert "use cucumber::{given, when, then, World};" in rs
    assert "struct OrderWorld {}" in rs
    assert '#[given(expr = "a customer with items")]' in rs
    assert '#[when(expr = "they submit the order")]' in rs
    assert '#[then(expr = "an order id is returned")]' in rs
    # And the cart is emptied -> And normalizes to the preceding Then
    assert '#[then(expr = "the cart is emptied")]' in rs
    # Scenario Outline <tier> -> {string} expr + trailing String arg
    assert '#[given(expr = "a {string} customer")]' in rs
    assert "tier: String" in rs
    assert 'OrderWorld::run("tests/features/order.feature")' in rs
    assert 'todo!("pending step")' in rs


def test_cucumber_rs_self_roundtrip_is_100pct():
    """The rust generator's rendered .feature re-parses to the same @id set."""
    from lib.testgen import generate, roundtrip_coverage
    from lib.spec_bundle import parse_feature
    feat = _feat()
    arts = generate(feat, framework="cucumber-rs", domain="order")
    gen_feature = next(c for p, c in arts.items() if p.endswith(".feature"))
    test_ids = parse_feature(gen_feature).scenario_ids()
    rt = roundtrip_coverage(feat.scenario_ids(), test_ids)
    assert rt.coverage_pct == 100.0 and rt.missing == []


def test_unknown_framework_returns_empty():
    from lib.testgen import generate
    assert generate(_feat(), framework="nope", domain="order") == {}


def test_roundtrip_coverage_full_and_gaps():
    from lib.testgen import roundtrip_coverage
    # full
    rt = roundtrip_coverage(["a", "b", "c"], ["a", "b", "c"])
    assert rt.coverage_pct == 100.0 and rt.missing == [] and rt.orphan == []
    # missing (spec scenario with no test) + orphan (test with no spec)
    rt = roundtrip_coverage(["a", "b", "c"], ["a", "z"])
    assert rt.matched == ["a"]
    assert rt.missing == ["b", "c"]
    assert rt.orphan == ["z"]
    assert rt.coverage_pct == round(100 / 3, 1)
    # empty spec
    assert roundtrip_coverage([], ["x"]).coverage_pct == 0.0


def test_end_to_end_self_roundtrip_is_100pct():
    """A spec's own generated test re-parses to the same @id set — 100% round-trip."""
    from lib.testgen import generate, roundtrip_coverage
    from lib.spec_bundle import parse_feature
    feat = _feat()
    arts = generate(feat, framework="cucumber-jvm", domain="order", package="p")
    gen_feature = next(c for p, c in arts.items() if p.endswith(".feature"))
    test_ids = parse_feature(gen_feature).scenario_ids()
    rt = roundtrip_coverage(feat.scenario_ids(), test_ids)
    assert rt.coverage_pct == 100.0 and rt.missing == []


def main() -> int:
    tests = [
        test_cucumber_jvm_generates_feature_and_stepdefs,
        test_scenario_outline_param_becomes_cucumber_placeholder,
        test_rendered_feature_preserves_ids_for_roundtrip,
        test_flutter_gherkin_dispatch,
        test_cucumber_rs_dispatch,
        test_cucumber_rs_self_roundtrip_is_100pct,
        test_unknown_framework_returns_empty,
        test_roundtrip_coverage_full_and_gaps,
        test_end_to_end_self_roundtrip_is_100pct,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            import traceback
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failed += 1
    if failed == 0:
        print(f"[OK] {len(tests)} tests passed")
        return 0
    print(f"[FAIL] {failed}/{len(tests)} tests failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
