#!/usr/bin/env python3
"""Tests for lib.validators.structural (v15.10 D2).

Coverage map (every D2 contract clause hit):
  Layer 1 (schema):
    - clean object passing object schema
    - missing required property → SCHEMA_VIOLATION
    - type mismatch (string vs integer) → SCHEMA_VIOLATION
    - enum violation → SCHEMA_VIOLATION
    - additionalProperties=false rejects extras
    - nested array.items schema validates per-element
    - minLength / maxLength / minimum / maximum
    - missing spec.output_schema → layer 1 skipped (clean)
  Layer 2 (referential):
    - all evidence file_paths exist → clean
    - one missing file_path → FABRICATION
    - non-string file_path silently skipped (shape errors are layer 1)
    - no evidence array → clean (nothing to check)
  Layer 3 (tool manifest):
    - all tool_calls in allowlist → clean
    - one tool_call out of allowlist → TOOL_MISUSE
    - empty allowlist → layer 3 skipped
  Composition / precedence:
    - schema failure short-circuits layer 2/3
    - FABRICATION in layer 2 short-circuits layer 3
    - layer 1 + 2 + 3 all clean → ok=True
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.validators.structural import (  # noqa: E402
    StructuralFailureMode,
    ValidationResult,
    validate,
)


def _existing(tmp: Path, name: str = "f.txt") -> str:
    p = tmp / name
    p.write_text("ok", encoding="utf-8")
    return str(p)


# ---- Layer 1 — schema ------------------------------------------------------------

def test_clean_object_passes_schema():
    spec = {
        "output_schema": {
            "type": "object",
            "required": ["status", "count"],
            "properties": {
                "status": {"type": "string", "enum": ["ok", "fail"]},
                "count": {"type": "integer", "minimum": 0},
            },
            "additionalProperties": False,
        }
    }
    r = validate({"status": "ok", "count": 3}, spec)
    assert r.ok is True
    assert r.failure_mode is None
    assert r.errors == []


def test_missing_required_property_is_schema_violation():
    spec = {"output_schema": {"type": "object", "required": ["status"]}}
    r = validate({"other": 1}, spec)
    assert not r.ok
    assert r.failure_mode == StructuralFailureMode.SCHEMA_VIOLATION
    assert any("status" in e and "missing" in e for e in r.errors)


def test_type_mismatch_is_schema_violation():
    spec = {"output_schema": {"type": "object", "properties": {"n": {"type": "integer"}}}}
    r = validate({"n": "not-an-int"}, spec)
    assert not r.ok
    assert r.failure_mode == StructuralFailureMode.SCHEMA_VIOLATION


def test_enum_violation_is_schema_violation():
    spec = {"output_schema": {"type": "object", "properties": {"k": {"enum": ["a", "b"]}}}}
    r = validate({"k": "c"}, spec)
    assert not r.ok
    assert r.failure_mode == StructuralFailureMode.SCHEMA_VIOLATION


def test_additional_properties_false_rejects_extras():
    spec = {
        "output_schema": {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "additionalProperties": False,
        }
    }
    r = validate({"a": "x", "b": "y"}, spec)
    assert not r.ok
    assert any("unknown property" in e for e in r.errors)


def test_array_items_schema_validates_per_element():
    spec = {
        "output_schema": {
            "type": "array",
            "items": {"type": "integer"},
        }
    }
    r = validate([1, 2, "bad"], spec)
    assert not r.ok
    assert any("[2]" in e for e in r.errors)


def test_string_length_bounds():
    spec = {"output_schema": {"type": "string", "minLength": 2, "maxLength": 4}}
    assert validate("ab", spec).ok
    assert validate("abcd", spec).ok
    r = validate("a", spec)
    assert not r.ok and "minLength" in r.errors[0]
    r = validate("abcde", spec)
    assert not r.ok and "maxLength" in r.errors[0]


def test_numeric_bounds():
    spec = {"output_schema": {"type": "integer", "minimum": 0, "maximum": 10}}
    assert validate(5, spec).ok
    r = validate(-1, spec)
    assert not r.ok and "minimum" in r.errors[0]
    r = validate(11, spec)
    assert not r.ok and "maximum" in r.errors[0]


def test_missing_output_schema_skips_layer_1():
    # No output_schema in spec; layer 2/3 see nothing to check either → clean.
    r = validate({"anything": True}, {})
    assert r.ok


# ---- Layer 2 — referential -------------------------------------------------------

def test_all_evidence_paths_present_is_clean():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        output = {
            "evidence": [
                {"file_path": _existing(tmp, "a.txt")},
                {"file_path": _existing(tmp, "b.txt")},
            ]
        }
        assert validate(output, {}).ok


def test_missing_evidence_file_is_fabrication():
    output = {"evidence": [{"file_path": "C:/no/such/path__structural.txt"}]}
    r = validate(output, {})
    assert not r.ok
    assert r.failure_mode == StructuralFailureMode.EVIDENCE_FABRICATION
    assert any("not found" in e for e in r.errors)


def test_non_string_file_path_silently_skipped():
    output = {"evidence": [{"file_path": 42}, {"file_path": ""}, {}]}
    r = validate(output, {})
    assert r.ok  # nothing to check at layer 2; no spec → layer 1/3 skipped too


def test_no_evidence_array_is_clean():
    output = {"status": "ok"}
    assert validate(output, {}).ok


# ---- Layer 3 — tool manifest -----------------------------------------------------

def test_tool_calls_in_allowlist_is_clean():
    spec = {"tool_allowlist": ["Read", "Grep"]}
    output = {"tool_calls": [{"name": "Read"}, {"name": "Grep"}]}
    assert validate(output, spec).ok


def test_tool_call_out_of_allowlist_is_tool_misuse():
    spec = {"tool_allowlist": ["Read"]}
    output = {"tool_calls": [{"name": "Read"}, {"name": "Bash"}]}
    r = validate(output, spec)
    assert not r.ok
    assert r.failure_mode == StructuralFailureMode.TOOL_MISUSE
    assert any("Bash" in e for e in r.errors)


def test_empty_tool_allowlist_skips_layer_3():
    spec = {"tool_allowlist": []}
    output = {"tool_calls": [{"name": "Whatever"}]}
    assert validate(output, spec).ok


# ---- Composition / precedence ---------------------------------------------------

def test_schema_failure_short_circuits_layer_2():
    """Even when evidence path is missing, schema failure wins."""
    spec = {"output_schema": {"type": "object", "required": ["status"]}}
    output = {"evidence": [{"file_path": "C:/never/exists__struct_prec.txt"}]}
    r = validate(output, spec)
    assert not r.ok
    assert r.failure_mode == StructuralFailureMode.SCHEMA_VIOLATION


def test_fabrication_short_circuits_layer_3():
    """Layer 2 fabrication wins even when layer 3 would also fire."""
    spec = {
        "output_schema": {"type": "object"},
        "tool_allowlist": ["Read"],
    }
    output = {
        "evidence": [{"file_path": "C:/never/exists__struct_l3.txt"}],
        "tool_calls": [{"name": "Bash"}],
    }
    r = validate(output, spec)
    assert not r.ok
    assert r.failure_mode == StructuralFailureMode.EVIDENCE_FABRICATION


def test_all_layers_clean_returns_ok():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        spec = {
            "output_schema": {
                "type": "object",
                "required": ["status"],
                "properties": {"status": {"type": "string"}},
            },
            "tool_allowlist": ["Read"],
        }
        output = {
            "status": "ok",
            "evidence": [{"file_path": _existing(tmp, "x.txt")}],
            "tool_calls": [{"name": "Read"}],
        }
        r = validate(output, spec)
        assert r.ok
        assert r.failure_mode is None
        assert r.errors == []


def test_invalid_spec_shape_is_tolerated():
    """spec=None or non-dict → treated as empty, no exception."""
    r = validate({"anything": True}, None)
    assert r.ok


def test_validation_result_dataclass_shape():
    """Lock the public dataclass shape — extra fields = breaking change."""
    r = ValidationResult(ok=True)
    assert r.ok is True
    assert r.failure_mode is None
    assert r.errors == []
    # Ensure ordering of enum values is stable (used in JSONL ledger).
    assert StructuralFailureMode.SCHEMA_VIOLATION.value == "schema_violation"
    assert StructuralFailureMode.EVIDENCE_FABRICATION.value == "evidence_fabrication"
    assert StructuralFailureMode.TOOL_MISUSE.value == "tool_misuse"


TESTS = [
    test_clean_object_passes_schema,
    test_missing_required_property_is_schema_violation,
    test_type_mismatch_is_schema_violation,
    test_enum_violation_is_schema_violation,
    test_additional_properties_false_rejects_extras,
    test_array_items_schema_validates_per_element,
    test_string_length_bounds,
    test_numeric_bounds,
    test_missing_output_schema_skips_layer_1,
    test_all_evidence_paths_present_is_clean,
    test_missing_evidence_file_is_fabrication,
    test_non_string_file_path_silently_skipped,
    test_no_evidence_array_is_clean,
    test_tool_calls_in_allowlist_is_clean,
    test_tool_call_out_of_allowlist_is_tool_misuse,
    test_empty_tool_allowlist_skips_layer_3,
    test_schema_failure_short_circuits_layer_2,
    test_fabrication_short_circuits_layer_3,
    test_all_layers_clean_returns_ok,
    test_invalid_spec_shape_is_tolerated,
    test_validation_result_dataclass_shape,
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
