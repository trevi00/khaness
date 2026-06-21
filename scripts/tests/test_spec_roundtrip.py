#!/usr/bin/env python3
"""Tests for validators/spec_roundtrip.py — @id round-trip coverage (잔여-3)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _make_bundle(root: Path, *, scenario_ids: list[str]) -> None:
    """Write a minimal Spec Bundle with one domain feature carrying the given @ids."""
    spec = root / ".claude" / "spec"
    (spec / "domain").mkdir(parents=True)
    (spec / "manifest.yaml").write_text(
        "schema_version: '1'\nsource_mode: reverse\ndomains: [order]\n", encoding="utf-8")
    lines = ["@order", "Feature: Orders"]
    for i, sid in enumerate(scenario_ids):
        lines += [f"  @id:{sid}", f"  Scenario: s{i}", "    Given a", "    Then b"]
    (spec / "domain" / "order.feature").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_test_feature(root: Path, rel: str, scenario_ids: list[str]) -> None:
    fp = root / rel
    fp.parent.mkdir(parents=True, exist_ok=True)
    lines = ["@order", "Feature: Orders"]
    for i, sid in enumerate(scenario_ids):
        lines += [f"  @id:{sid}", f"  Scenario: t{i}", "    Given a", "    Then b"]
    fp.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_no_bundle_returns_clean():
    from validators.spec_roundtrip import check_roundtrip
    with tempfile.TemporaryDirectory() as td:
        assert check_roundtrip(td) == []   # no .claude/spec -> nothing to check


def test_scaffold_only_spine_returns_clean():
    """A bundle whose features carry NO @id (scaffold not authored) yields nothing
    to cover — not a false 'missing' storm."""
    from validators.spec_roundtrip import check_roundtrip
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        spec = root / ".claude" / "spec" / "domain"
        spec.mkdir(parents=True)
        (root / ".claude" / "spec" / "manifest.yaml").write_text(
            "schema_version: '1'\ndomains: [order]\n", encoding="utf-8")
        (spec / "order.feature").write_text(
            "Feature: Orders\n  Scenario: no id\n    Given a\n", encoding="utf-8")
        assert check_roundtrip(root) == []


def test_full_coverage_is_clean():
    from validators.spec_roundtrip import check_roundtrip, coverage_report
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_bundle(root, scenario_ids=["create", "cancel"])
        _write_test_feature(root, "src/test/resources/features/order.feature", ["create", "cancel"])
        assert check_roundtrip(root) == []
        rt = coverage_report(root)
        assert rt is not None and rt.coverage_pct == 100.0


def test_missing_test_is_flagged():
    from validators.spec_roundtrip import check_roundtrip
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_bundle(root, scenario_ids=["create", "cancel"])
        # only 'create' covered by a test
        _write_test_feature(root, "tests/features/order.feature", ["create"])
        problems = check_roundtrip(root)
        assert any("'cancel'" in p and "no backing test" in p for p in problems)
        assert not any("'create'" in p for p in problems)


def test_orphan_test_is_flagged():
    from validators.spec_roundtrip import check_roundtrip
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_bundle(root, scenario_ids=["create"])
        # test covers 'create' plus a stray 'legacy' with no spec backing
        _write_test_feature(root, "test/features/order.feature", ["create", "legacy"])
        problems = check_roundtrip(root)
        assert any("'legacy'" in p and "drift" in p for p in problems)


def test_spec_domain_features_not_counted_as_tests():
    """The bundle's own domain/*.feature must NOT be mistaken for a test feature —
    that would mask every missing-test gap as covered."""
    from validators.spec_roundtrip import check_roundtrip
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_bundle(root, scenario_ids=["create", "cancel"])
        # NO test features written -> both scenarios are uncovered
        problems = check_roundtrip(root)
        assert any("'create'" in p for p in problems)
        assert any("'cancel'" in p for p in problems)


def test_main_forward_looking_pass(capsys=None):
    """In the harness repo (no spec bundle), main() prints a forward-looking PASS."""
    import io
    import contextlib
    from validators import spec_roundtrip
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        spec_roundtrip.main()
    out = buf.getvalue()
    assert "[PASS]" in out and "spec_roundtrip" in out


def main() -> int:
    tests = [
        test_no_bundle_returns_clean,
        test_scaffold_only_spine_returns_clean,
        test_full_coverage_is_clean,
        test_missing_test_is_flagged,
        test_orphan_test_is_flagged,
        test_spec_domain_features_not_counted_as_tests,
        test_main_forward_looking_pass,
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
