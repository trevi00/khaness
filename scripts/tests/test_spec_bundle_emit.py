#!/usr/bin/env python3
"""Tests for cli/spec_bundle_emit.py — deterministic Spec Bundle scaffold (D-INT)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _make_project(td: Path) -> Path:
    root = td / "proj"
    java = root / "src" / "main" / "java" / "kr" / "demo" / "identity"
    java.mkdir(parents=True)
    (java / "IdentityController.java").write_text(
        "package kr.demo.identity;\n@RestController\n@RequestMapping(\"/api/v1/me\")\n"
        "public class IdentityController {\n  @GetMapping public void getMe() {}\n}\n", encoding="utf-8")
    shop = root / "src" / "main" / "java" / "kr" / "demo" / "shop"
    shop.mkdir(parents=True)
    (shop / "ShopController.java").write_text(
        "package kr.demo.shop;\n@RestController public class ShopController{}\n", encoding="utf-8")
    db = root / "src" / "main" / "resources" / "db"
    db.mkdir(parents=True)
    (db / "V1.sql").write_text(
        "CREATE TABLE users (id BIGSERIAL PRIMARY KEY, nickname VARCHAR(16));\n"
        "CREATE TABLE shops (\n id BIGSERIAL PRIMARY KEY, owner_id BIGINT,\n"
        " FOREIGN KEY (owner_id) REFERENCES users(id)\n);\n", encoding="utf-8")
    return root


def test_detect_domains_from_controllers():
    from cli.spec_bundle_emit import detect_domains
    with tempfile.TemporaryDirectory() as td:
        root = _make_project(Path(td))
        assert detect_domains(root) == ["identity", "shop"]


def test_emit_produces_valid_bundle_scaffold():
    from cli.spec_bundle_emit import emit
    with tempfile.TemporaryDirectory() as td:
        root = _make_project(Path(td))
        out = Path(td) / "out"
        res = emit(root, out)
        spec = out / ".claude" / "spec"
        # manifest + facets + per-domain feature scaffolds
        assert (spec / "manifest.yaml").is_file()
        assert (spec / "facets" / "logical.schema").is_file()
        assert (spec / "facets" / "er.schema").is_file()
        assert (spec / "domain" / "identity.feature").is_file()
        assert (spec / "domain" / "shop.feature").is_file()
        assert res["domains"] == ["identity", "shop"]
        assert res["logical_tables"] == 2 and res["logical_valid"]
        assert res["er_entities"] == 2 and res["er_valid"]
        # class + api facets emitted from Java source (D1-2 잔여-2)
        assert (spec / "facets" / "class.schema").is_file()
        assert (spec / "facets" / "api.schema").is_file()
        assert res["class_count"] == 2          # IdentityController + ShopController
        assert res["api_endpoints"] == 1        # GET /api/v1/me
        assert set(res["facets_written"]) == {"logical", "er", "class", "api"}
        # scaffold features carry a valid @id (so the bundle validates structurally)
        assert res["validator_problems"] == []


def test_emit_is_read_only_on_source():
    from cli.spec_bundle_emit import emit
    with tempfile.TemporaryDirectory() as td:
        root = _make_project(Path(td))
        before = sorted(p.name for p in root.rglob("*"))
        emit(root, Path(td) / "out")
        after = sorted(p.name for p in root.rglob("*"))
        assert before == after, "emit must not write into the source project"


def test_emit_does_not_clobber_authored_feature_on_rerun():
    from cli.spec_bundle_emit import emit
    with tempfile.TemporaryDirectory() as td:
        root = _make_project(Path(td))
        out = Path(td) / "out"
        emit(root, out)
        authored = out / ".claude" / "spec" / "domain" / "identity.feature"
        authored.write_text("@identity\nFeature: real\n  @id:login\n  Scenario: x\n    Given a\n",
                            encoding="utf-8")
        emit(root, out)  # re-run
        assert "@id:login" in authored.read_text(encoding="utf-8"), "re-run must not clobber authored scenarios"


def test_forward_mode_explicit_domains_no_ddl():
    """Forward greenfield: explicit --domains, no code/DDL yet -> manifest
    (source_mode=forward) + behavioral scaffolds, NO facets emitted."""
    from cli.spec_bundle_emit import emit
    import yaml
    with tempfile.TemporaryDirectory() as td:
        proj = Path(td) / "greenfield"
        proj.mkdir()
        res = emit(proj, proj, source_mode="forward", domains=["order", "payment"])
        spec = proj / ".claude" / "spec"
        assert res["source_mode"] == "forward"
        assert res["domains"] == ["order", "payment"]
        assert res["facets_written"] == []            # no DDL -> no facets
        assert not (spec / "facets" / "logical.schema").exists()
        assert (spec / "domain" / "order.feature").exists()
        assert (spec / "domain" / "payment.feature").exists()
        man = yaml.safe_load((spec / "manifest.yaml").read_text(encoding="utf-8"))
        assert man["source_mode"] == "forward"
        assert res["validator_problems"] == []


def test_forward_then_facets_added_after_ddl():
    """Idempotent: a forward bundle re-emitted after the DB stage produced DDL gains
    facets while preserving authored .feature scenarios."""
    from cli.spec_bundle_emit import emit
    with tempfile.TemporaryDirectory() as td:
        proj = Path(td) / "proj"
        proj.mkdir()
        emit(proj, proj, source_mode="forward", domains=["order"])
        authored = proj / ".claude" / "spec" / "domain" / "order.feature"
        authored.write_text("@order\nFeature: Order\n  @id:place\n  Scenario: x\n    Given a\n", encoding="utf-8")
        # DB stage produces DDL
        db = proj / "src" / "main" / "resources" / "db"
        db.mkdir(parents=True)
        (db / "V1.sql").write_text("CREATE TABLE orders (id BIGSERIAL PRIMARY KEY);\n", encoding="utf-8")
        res = emit(proj, proj, source_mode="forward", domains=["order"])
        assert "logical" in res["facets_written"]
        assert (proj / ".claude" / "spec" / "facets" / "logical.schema").exists()
        assert "@id:place" in authored.read_text(encoding="utf-8")   # authored preserved


def main() -> int:
    tests = [
        test_detect_domains_from_controllers,
        test_emit_produces_valid_bundle_scaffold,
        test_emit_is_read_only_on_source,
        test_emit_does_not_clobber_authored_feature_on_rerun,
        test_forward_mode_explicit_domains_no_ddl,
        test_forward_then_facets_added_after_ddl,
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
