#!/usr/bin/env python3
"""Unit tests for lib/extractors/* — convention + er + logical."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.extractors import (  # noqa: E402
    REGISTRY,
    get_extractor,
    iter_extractors,
    list_extractors,
)
from lib.extractors.convention import ConventionExtractor  # noqa: E402
from lib.extractors.er import ErExtractor  # noqa: E402
from lib.extractors.logical import LogicalExtractor  # noqa: E402


# ===== shared helpers =====

def _write_java(root: Path, package: str, class_name: str, body: str) -> Path:
    pkg_dir = root / "src" / "main" / "java" / Path(*package.split("."))
    pkg_dir.mkdir(parents=True, exist_ok=True)
    p = pkg_dir / f"{class_name}.java"
    p.write_text(f"package {package};\n\n{body}\n", encoding="utf-8")
    return p


def _write_sql(root: Path, content: str, name: str = "schema.sql") -> Path:
    sql_dir = root / "sql"
    sql_dir.mkdir(parents=True, exist_ok=True)
    p = sql_dir / name
    p.write_text(content, encoding="utf-8")
    return p


# ===== ConventionExtractor =====

def test_convention_can_extract_requires_java_source():
    ex = ConventionExtractor()
    with tempfile.TemporaryDirectory() as td:
        assert ex.can_extract(Path(td)) is False
        _write_java(Path(td), "com.ex", "Foo", "public class Foo {}")
        assert ex.can_extract(Path(td)) is True


def test_convention_extracts_packages_from_multiple_files():
    ex = ConventionExtractor()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_java(root, "com.shop.user", "User", "public class User {}")
        _write_java(root, "com.shop.user", "UserController", "public class UserController {}")
        _write_java(root, "com.shop.order", "Order", "public class Order {}")
        result = ex.extract(root)
        assert "com.shop.user" in result.content or "com.shop" in result.content


def test_convention_extracts_url_prefixes():
    ex = ConventionExtractor()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_java(root, "com.ex", "FooController",
                    '@RestController\n'
                    '@RequestMapping("/api/foo")\n'
                    'public class FooController {}')
        result = ex.extract(root)
        assert "FooController" in result.content
        assert "/api/foo" in result.content


def test_convention_extracts_error_codes_enum_form():
    ex = ConventionExtractor()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_java(root, "com.ex.errors", "ErrorCode",
                    'public enum ErrorCode {\n'
                    '  USER_NOT_FOUND(40401, "사용자 없음"),\n'
                    '  PERMISSION_DENIED(40301, "권한 없음");\n'
                    '}')
        result = ex.extract(root)
        assert "USER_NOT_FOUND" in result.content
        assert "사용자 없음" in result.content
        assert "PERMISSION_DENIED" in result.content


def test_convention_response_wrapper_detection():
    ex = ConventionExtractor()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_java(root, "com.ex", "ApiResponse", "public class ApiResponse {}")
        _write_java(root, "com.ex", "PagingResponse", "public class PagingResponse {}")
        result = ex.extract(root)
        assert "ApiResponse" in result.content
        assert "PagingResponse" in result.content


def test_convention_confidence_scales_with_signals():
    ex = ConventionExtractor()
    with tempfile.TemporaryDirectory() as td:
        # Bare project: only one Java file with no signals
        root = Path(td)
        _write_java(root, "com.ex", "Foo", "public class Foo {}")
        bare = ex.extract(root)
    with tempfile.TemporaryDirectory() as td2:
        # Rich project: 4/4 signals
        root = Path(td2)
        _write_java(root, "com.ex", "FooController",
                    '@RestController\n@RequestMapping("/api/foo")\npublic class FooController {}')
        _write_java(root, "com.ex", "ApiResponse", "public class ApiResponse {}")
        _write_java(root, "com.ex.errors", "ErrorCode",
                    'public enum ErrorCode { USER(1234, "x"); }')
        rich = ex.extract(root)
    assert rich.confidence > bare.confidence


# ===== ErExtractor =====

def test_er_can_extract_requires_sql():
    ex = ErExtractor()
    with tempfile.TemporaryDirectory() as td:
        assert ex.can_extract(Path(td)) is False
        _write_sql(Path(td), "CREATE TABLE x (id INT);")
        assert ex.can_extract(Path(td)) is True


def test_er_extracts_entities_from_create_table():
    ex = ErExtractor()
    with tempfile.TemporaryDirectory() as td:
        _write_sql(Path(td),
                   "CREATE TABLE users (id BIGINT NOT NULL, name VARCHAR(64));\n"
                   "CREATE TABLE orders (id BIGINT NOT NULL, user_id BIGINT);\n")
        result = ex.extract(Path(td))
        assert "users" in result.content
        assert "orders" in result.content


def test_er_extracts_explicit_foreign_key():
    ex = ErExtractor()
    with tempfile.TemporaryDirectory() as td:
        _write_sql(Path(td),
                   "CREATE TABLE users (id BIGINT PRIMARY KEY);\n"
                   "CREATE TABLE orders (\n"
                   "  id BIGINT PRIMARY KEY,\n"
                   "  user_id BIGINT NOT NULL,\n"
                   "  FOREIGN KEY (user_id) REFERENCES users(id)\n"
                   ");\n")
        result = ex.extract(Path(td))
        assert "FOREIGN KEY" in result.content or "user_id" in result.content
        assert "orders" in result.content
        assert "users" in result.content


# ===== LogicalExtractor =====

def test_logical_extracts_columns_and_pk():
    ex = LogicalExtractor()
    with tempfile.TemporaryDirectory() as td:
        _write_sql(Path(td),
                   "CREATE TABLE users (\n"
                   "  id BIGINT NOT NULL AUTO_INCREMENT,\n"
                   "  name VARCHAR(64) NOT NULL,\n"
                   "  email VARCHAR(255),\n"
                   "  PRIMARY KEY (id)\n"
                   ");\n")
        result = ex.extract(Path(td))
        assert "users" in result.content
        assert "id" in result.content
        assert "PK" in result.content


def test_logical_extracts_indexes():
    ex = LogicalExtractor()
    with tempfile.TemporaryDirectory() as td:
        _write_sql(Path(td),
                   "CREATE TABLE orders (\n"
                   "  id BIGINT NOT NULL,\n"
                   "  user_id BIGINT,\n"
                   "  PRIMARY KEY (id),\n"
                   "  KEY idx_user_id (user_id)\n"
                   ");\n")
        result = ex.extract(Path(td))
        assert "idx_user_id" in result.content
        assert "INDEX" in result.content or "idx_user_id" in result.content


def test_logical_handles_create_index_global():
    ex = LogicalExtractor()
    with tempfile.TemporaryDirectory() as td:
        _write_sql(Path(td),
                   "CREATE TABLE x (id BIGINT, status VARCHAR(20));\n"
                   "CREATE INDEX idx_x_status ON x(status);\n")
        result = ex.extract(Path(td))
        assert "idx_x_status" in result.content


def test_logical_no_sql_returns_zero_confidence():
    ex = LogicalExtractor()
    with tempfile.TemporaryDirectory() as td:
        result = ex.extract(Path(td))
        assert result.confidence == 0.0


# ===== Registry =====

def test_registry_has_p1_extractors():
    names = [c().name for c in REGISTRY]
    assert "convention" in names
    assert "er" in names
    assert "logical" in names


def test_list_extractors_canonical_order():
    """list_extractors returns names in registry order."""
    assert list_extractors() == ["convention", "er", "logical", "doc_classifier"]


def test_get_extractor_by_canonical_name():
    ex = get_extractor("convention")
    assert isinstance(ex, ConventionExtractor)
    assert ex.name == "convention"


def test_get_extractor_case_insensitive():
    """Canonical name lookup is case-insensitive."""
    assert isinstance(get_extractor("ER"), ErExtractor)
    assert isinstance(get_extractor("Logical"), LogicalExtractor)


def test_get_extractor_unknown_raises_keyerror():
    try:
        get_extractor("nonexistent")
    except KeyError as e:
        assert "nonexistent" in str(e)
        assert "convention" in str(e)  # known list shown
    else:
        raise AssertionError("expected KeyError")


def test_iter_extractors_yields_in_registry_order():
    instances = list(iter_extractors())
    names = [ex.name for ex in instances]
    assert names == ["convention", "er", "logical", "doc_classifier"]


def test_iter_extractors_yields_fresh_instances():
    """Each call produces fresh instances (no shared state)."""
    a = list(iter_extractors())
    b = list(iter_extractors())
    # Different instances, same class
    assert a[0] is not b[0]
    assert type(a[0]) is type(b[0])


def test_registry_attr_lazy_resolves_classes():
    """REGISTRY backward-compat returns class objects in registry order."""
    classes = REGISTRY
    assert ConventionExtractor in classes
    assert ErExtractor in classes
    assert LogicalExtractor in classes


def test_module_unknown_attr_raises():
    """__getattr__ rejects typos, doesn't silently return None."""
    import lib.extractors as ext_mod
    try:
        _ = ext_mod.NONEXISTENT_ATTR
    except AttributeError:
        pass
    else:
        raise AssertionError("expected AttributeError")


def main() -> int:
    tests = [
        test_convention_can_extract_requires_java_source,
        test_convention_extracts_packages_from_multiple_files,
        test_convention_extracts_url_prefixes,
        test_convention_extracts_error_codes_enum_form,
        test_convention_response_wrapper_detection,
        test_convention_confidence_scales_with_signals,
        test_er_can_extract_requires_sql,
        test_er_extracts_entities_from_create_table,
        test_er_extracts_explicit_foreign_key,
        test_logical_extracts_columns_and_pk,
        test_logical_extracts_indexes,
        test_logical_handles_create_index_global,
        test_logical_no_sql_returns_zero_confidence,
        test_registry_has_p1_extractors,
        test_list_extractors_canonical_order,
        test_get_extractor_by_canonical_name,
        test_get_extractor_case_insensitive,
        test_get_extractor_unknown_raises_keyerror,
        test_iter_extractors_yields_in_registry_order,
        test_iter_extractors_yields_fresh_instances,
        test_registry_attr_lazy_resolves_classes,
        test_module_unknown_attr_raises,
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
