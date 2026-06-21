#!/usr/bin/env python3
"""Tests for lib/spec_bundle.py — the Gherkin behavioral spine parser (D1-1)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_SAMPLE = """\
@order @id:order-domain
Feature: Order creation
  As a customer
  I want to place orders

  Background:
    Given the catalog is loaded

  @id:create-valid-order
  Scenario: Create a valid order
    Given a customer with 2 items in the cart
    When they submit the order
    Then an order id is returned
    And the cart is emptied

  @id:reject-empty-cart
  Scenario: Reject an empty cart
    Given a customer with an empty cart
    When they submit the order
    Then a 400 validation error is returned

  @id:price-table
  Scenario Outline: Price by tier
    Given a <tier> customer
    Then the discount is <pct>
    Examples:
      | tier | pct |
      | gold | 10  |
      | none | 0   |
"""


def test_parse_feature_basic():
    from lib.spec_bundle import parse_feature
    f = parse_feature(_SAMPLE)
    assert f.name == "Order creation"
    assert "@order" in f.tags and "@id:order-domain" in f.tags
    assert "customer" in f.description
    assert len(f.background) == 1 and f.background[0].keyword == "Given"
    assert len(f.scenarios) == 3


def test_scenario_id_from_explicit_tag():
    from lib.spec_bundle import parse_feature
    f = parse_feature(_SAMPLE)
    ids = [s.id for s in f.scenarios]
    assert ids == ["create-valid-order", "reject-empty-cart", "price-table"]
    # round-trip key set
    assert f.scenario_ids() == ["create-valid-order", "reject-empty-cart", "price-table"]


def test_scenario_id_none_when_no_tag_never_hashes():
    """A scenario with no @id has id None — NEVER a prose hash (debate C-STABLE-ID)."""
    from lib.spec_bundle import parse_feature
    f = parse_feature("Feature: X\n  Scenario: untagged\n    Given a\n    Then b\n")
    assert f.scenarios[0].id is None


def test_steps_parsed_with_keywords():
    from lib.spec_bundle import parse_feature
    f = parse_feature(_SAMPLE)
    s = f.scenarios[0]
    assert [st.keyword for st in s.steps] == ["Given", "When", "Then", "And"]
    assert s.steps[0].text == "a customer with 2 items in the cart"
    assert s.steps[3].text == "the cart is emptied"


def test_scenario_outline_examples():
    from lib.spec_bundle import parse_feature
    f = parse_feature(_SAMPLE)
    outline = f.scenarios[2]
    assert outline.is_outline is True
    assert outline.examples == [{"tier": "gold", "pct": "10"}, {"tier": "none", "pct": "0"}]


def test_parse_failsoft_on_garbage():
    from lib.spec_bundle import parse_feature
    f = parse_feature("\n\n# just a comment\nnonsense line without keyword\n")
    assert f.name == "" and f.scenarios == []


def test_load_bundle_reads_manifest_and_features():
    from lib.spec_bundle import load_bundle
    with tempfile.TemporaryDirectory() as td:
        spec = Path(td) / ".claude" / "spec"
        (spec / "domain").mkdir(parents=True)
        (spec / "manifest.yaml").write_text(
            "schema_version: '1'\nsource_mode: reverse\n"
            "domains: [order, catalog]\npersonas:\n  - {id: customer, name: 고객}\n",
            encoding="utf-8")
        (spec / "domain" / "order.feature").write_text(_SAMPLE, encoding="utf-8")
        b = load_bundle(td)
        assert b is not None
        assert b.schema_version == "1" and b.source_mode == "reverse"
        assert b.domains == ["order", "catalog"]
        assert b.personas[0]["id"] == "customer"
        assert "order" in b.features
        assert b.features["order"].name == "Order creation"
        assert "create-valid-order" in b.all_scenario_ids()


def test_load_bundle_none_when_absent():
    from lib.spec_bundle import load_bundle
    with tempfile.TemporaryDirectory() as td:
        assert load_bundle(td) is None


# ── validator (validators/spec_bundle.py) integrity checks ──
def _make_bundle(td: Path, manifest: str, features: dict[str, str],
                 facets: dict[str, str] | None = None) -> Path:
    spec = td / ".claude" / "spec"
    (spec / "domain").mkdir(parents=True)
    (spec / "manifest.yaml").write_text(manifest, encoding="utf-8")
    for name, body in features.items():
        (spec / "domain" / f"{name}.feature").write_text(body, encoding="utf-8")
    if facets:
        (spec / "facets").mkdir(parents=True)
        for name, body in facets.items():
            (spec / "facets" / f"{name}.schema").write_text(body, encoding="utf-8")
    return spec


def test_validator_clean_bundle_no_problems():
    from validators.spec_bundle import check_bundle_dir
    with tempfile.TemporaryDirectory() as td:
        spec = _make_bundle(Path(td),
            "schema_version: '1'\nsource_mode: reverse\ndomains: [order]\n",
            {"order": _SAMPLE},
            {"logical": "facet: logical\nschema_version: '1'\nelements:\n  - {id: orders, kind: table}\n"})
        assert check_bundle_dir(spec) == []


def test_validator_flags_missing_and_duplicate_id():
    from validators.spec_bundle import check_bundle_dir
    with tempfile.TemporaryDirectory() as td:
        # one scenario with no @id, plus a duplicate @id across two features
        feat_a = "Feature: A\n  @id:dup\n  Scenario: s1\n    Given a\n  Scenario: untagged\n    Given b\n"
        feat_b = "Feature: B\n  @id:dup\n  Scenario: s2\n    Given c\n"
        spec = _make_bundle(Path(td),
            "schema_version: '1'\ndomains: [a, b]\n",
            {"a": feat_a, "b": feat_b})
        problems = check_bundle_dir(spec)
        assert any("no @id" in p for p in problems), problems
        assert any("duplicate scenario @id 'dup'" in p for p in problems), problems


def test_validator_flags_manifest_domain_mismatch_and_bad_facet():
    from validators.spec_bundle import check_bundle_dir
    with tempfile.TemporaryDirectory() as td:
        spec = _make_bundle(Path(td),
            "schema_version: '1'\ndomains: [order, ghost]\n",   # ghost has no feature
            {"order": _SAMPLE},
            {"logical": "facet: logical\nelements:\n  - {id: t1}\n  - {id: t1}\n"})  # dup element id
        problems = check_bundle_dir(spec)
        assert any("ghost" in p and "no domain" in p for p in problems), problems
        assert any("duplicate element @id 't1'" in p for p in problems), problems


def test_validator_main_runs_clean_forward_looking():
    """The harness tree has no spec/ bundle -> [PASS], never raises."""
    from validators import spec_bundle as v
    v.main()  # must not raise


def main() -> int:
    tests = [
        test_parse_feature_basic,
        test_scenario_id_from_explicit_tag,
        test_scenario_id_none_when_no_tag_never_hashes,
        test_steps_parsed_with_keywords,
        test_scenario_outline_examples,
        test_parse_failsoft_on_garbage,
        test_load_bundle_reads_manifest_and_features,
        test_load_bundle_none_when_absent,
        test_validator_clean_bundle_no_problems,
        test_validator_flags_missing_and_duplicate_id,
        test_validator_flags_manifest_domain_mismatch_and_bad_facet,
        test_validator_main_runs_clean_forward_looking,
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
