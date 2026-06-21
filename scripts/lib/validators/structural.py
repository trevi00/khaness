"""structural validator — deterministic post-output check (v15.10 D2).

Three independent layers, evaluated in order; layer N runs only if 1..N-1
report clean:

  Layer 1 — schema conformance:
    A pure-Python subset of JSON Schema:
      - 'type': str | list[str] in {object, array, string, integer, number,
        boolean, null}
      - 'required': list[str] (object only)
      - 'properties': dict[str, subschema] (object only)
      - 'additionalProperties': bool (default True; false = unknown keys fail)
      - 'items': subschema (array only — applied to every element)
      - 'enum': list[Any] (any leaf type)
      - 'minLength' / 'maxLength': int (string only)
      - 'minimum' / 'maximum': int | float (number/integer only)
    Reported failure_mode = SCHEMA_VIOLATION.

  Layer 2 — referential integrity:
    For every entry in output.evidence[*] with a non-empty string file_path,
    os.stat(file_path) must succeed (no FileNotFoundError). Other OSErrors
    (PermissionError, etc.) are routed to SCHEMA_VIOLATION rather than
    FABRICATION because they reflect env brokenness, not a fake claim.
    Reported failure_mode = EVIDENCE_FABRICATION on FileNotFoundError.

  Layer 3 — tool-call manifest vs spawn allowlist:
    For every entry in output.tool_calls[*].name, the name must be a member
    of spec.tool_allowlist. Empty allowlist disables the layer (back-compat).
    Reported failure_mode = TOOL_MISUSE on out-of-list call.

Each layer accumulates ALL violations (not short-circuit within the layer)
so callers see the full diagnostic list per pass; but the overall pass
short-circuits between layers — there is no point reporting a
referential-integrity failure on an output whose top-level shape is
already wrong.

Public API (lock):
    StructuralFailureMode  : Enum {SCHEMA_VIOLATION, EVIDENCE_FABRICATION, TOOL_MISUSE}
    ValidationResult       : dataclass {ok, failure_mode, errors: list[str]}
    validate(output, spec) : ValidationResult

The validator is intentionally tolerant of partial specs:
  - spec={} or no output_schema key → layer 1 skipped, only layer 2/3 run
  - spec.tool_allowlist empty / missing → layer 3 skipped
  - output evidence missing or non-list → layer 2 finds nothing, reports clean
This is consistent with the "structural baseline, not semantic policing"
principle from the D2 verdict.

NO writes, NO network, NO LLM, NO embedder. os.stat is the only side
effect, and it is read-only.

Reference: debate-1778946602-jj7vxk D2, ontology fields_sha1
b14e7fbeee2d914da049d3b8001031a190ceea6f.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StructuralFailureMode(str, Enum):
    """D1 orchestrator-observed failure modes producible by this validator.

    str-Enum for JSONL ledger serialization. Other D1 modes
    (timeout_or_crash) are produced at the spawn boundary, not here.
    """

    SCHEMA_VIOLATION = "schema_violation"
    EVIDENCE_FABRICATION = "evidence_fabrication"
    TOOL_MISUSE = "tool_misuse"


@dataclass
class ValidationResult:
    """Outcome of structural.validate.

    `ok`           : True iff every layer reported clean.
    `failure_mode` : First non-clean layer's mode (None if ok). Layers run
                     in order so the earliest layer wins precedence.
    `errors`       : All accumulated error strings across the layers that
                     actually ran. Empty iff ok.
    """

    ok: bool
    failure_mode: StructuralFailureMode | None = None
    errors: list[str] = field(default_factory=list)


# ---- Layer 1 — JSON-Schema subset ------------------------------------------------

_TYPE_PREDICATES: dict[str, Any] = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def _check_type(value: Any, type_decl: Any, path: str, errors: list[str]) -> bool:
    """True iff value matches type_decl (str or list[str])."""
    if type_decl is None:
        return True
    types = type_decl if isinstance(type_decl, list) else [type_decl]
    for t in types:
        predicate = _TYPE_PREDICATES.get(t)
        if predicate is None:
            errors.append(f"{path}: unknown type {t!r} in schema")
            return False
        if predicate(value):
            return True
    errors.append(
        f"{path}: type mismatch — expected {type_decl!r}, got {type(value).__name__}"
    )
    return False


def _check_schema(value: Any, schema: dict, path: str, errors: list[str]) -> None:
    """Recursive subset-of-JSON-Schema check. Accumulates errors in-place."""
    if not isinstance(schema, dict):
        errors.append(f"{path}: schema node must be a dict, got {type(schema).__name__}")
        return

    if "type" in schema and not _check_type(value, schema["type"], path, errors):
        return  # type wrong → don't bother with property/items/etc.

    if "enum" in schema:
        enum_vals = schema["enum"]
        if isinstance(enum_vals, list) and value not in enum_vals:
            errors.append(f"{path}: value {value!r} not in enum {enum_vals!r}")

    if isinstance(value, str):
        min_len = schema.get("minLength")
        max_len = schema.get("maxLength")
        if isinstance(min_len, int) and len(value) < min_len:
            errors.append(f"{path}: length {len(value)} < minLength {min_len}")
        if isinstance(max_len, int) and len(value) > max_len:
            errors.append(f"{path}: length {len(value)} > maxLength {max_len}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(f"{path}: value {value} < minimum {minimum}")
        if isinstance(maximum, (int, float)) and value > maximum:
            errors.append(f"{path}: value {value} > maximum {maximum}")

    if isinstance(value, dict):
        required = schema.get("required")
        if isinstance(required, list):
            for key in required:
                if key not in value:
                    errors.append(f"{path}: missing required property {key!r}")
        props = schema.get("properties")
        if isinstance(props, dict):
            for key, sub_schema in props.items():
                if key in value:
                    _check_schema(value[key], sub_schema, f"{path}.{key}", errors)
        if schema.get("additionalProperties") is False and isinstance(props, dict):
            extra = set(value.keys()) - set(props.keys())
            for k in sorted(extra):
                errors.append(f"{path}: unknown property {k!r} (additionalProperties=false)")

    if isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(value):
                _check_schema(item, item_schema, f"{path}[{i}]", errors)


def _layer_schema(output: Any, spec: dict) -> list[str]:
    """Layer 1 result — empty list iff clean."""
    schema = spec.get("output_schema") if isinstance(spec, dict) else None
    if not isinstance(schema, dict):
        return []
    errors: list[str] = []
    _check_schema(output, schema, "$", errors)
    return errors


# ---- Layer 2 — referential integrity ---------------------------------------------

def _iter_evidence_paths(output: Any):
    """Yield (index, file_path) pairs from output.evidence[*] (tolerant)."""
    if not isinstance(output, dict):
        return
    evidence = output.get("evidence")
    if not isinstance(evidence, list):
        return
    for i, entry in enumerate(evidence):
        if not isinstance(entry, dict):
            continue
        fp = entry.get("file_path")
        if isinstance(fp, str) and fp:
            yield i, fp


def _layer_referential(output: Any) -> tuple[list[str], StructuralFailureMode | None]:
    """Layer 2 — returns (errors, dominant_failure_mode).

    Splits errors between FileNotFoundError (FABRICATION) and other OSError
    (SCHEMA_VIOLATION). If both present, FABRICATION wins precedence because
    it's the stronger claim.
    """
    fab_errors: list[str] = []
    other_errors: list[str] = []
    for i, fp in _iter_evidence_paths(output):
        try:
            os.stat(fp)
        except FileNotFoundError:
            fab_errors.append(f"evidence[{i}].file_path={fp!r}: file not found")
        except OSError as e:
            other_errors.append(
                f"evidence[{i}].file_path={fp!r}: os.stat failed ({type(e).__name__})"
            )
    if fab_errors:
        return fab_errors + other_errors, StructuralFailureMode.EVIDENCE_FABRICATION
    if other_errors:
        return other_errors, StructuralFailureMode.SCHEMA_VIOLATION
    return [], None


# ---- Layer 3 — tool-call manifest ------------------------------------------------

def _layer_tool_manifest(output: Any, spec: dict) -> list[str]:
    """Layer 3 — every output.tool_calls[*].name must be in spec.tool_allowlist."""
    if not isinstance(spec, dict):
        return []
    allowlist = spec.get("tool_allowlist")
    if not isinstance(allowlist, (list, tuple, set)) or not allowlist:
        return []
    allowed = set(allowlist)
    if not isinstance(output, dict):
        return []
    calls = output.get("tool_calls")
    if not isinstance(calls, list):
        return []
    errors: list[str] = []
    for i, call in enumerate(calls):
        if not isinstance(call, dict):
            errors.append(f"tool_calls[{i}]: entry is not a dict")
            continue
        name = call.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"tool_calls[{i}]: missing or non-string name")
            continue
        if name not in allowed:
            errors.append(
                f"tool_calls[{i}].name={name!r} not in tool_allowlist "
                f"(allowed: {sorted(allowed)})"
            )
    return errors


# ---- Public entry ----------------------------------------------------------------

def validate(output: Any, spec: Any) -> ValidationResult:
    """Run layers 1→2→3, return first-failing layer's mode + all errors.

    `output` is the subagent envelope (a dict in the canonical case);
    `spec`   is the spawn spec dict — only the `output_schema` and
             `tool_allowlist` keys are consulted. Missing/empty spec
             keys simply skip that layer.
    """
    if not isinstance(spec, dict):
        spec = {}

    schema_errors = _layer_schema(output, spec)
    if schema_errors:
        return ValidationResult(
            ok=False,
            failure_mode=StructuralFailureMode.SCHEMA_VIOLATION,
            errors=schema_errors,
        )

    ref_errors, ref_mode = _layer_referential(output)
    if ref_errors:
        return ValidationResult(ok=False, failure_mode=ref_mode, errors=ref_errors)

    tool_errors = _layer_tool_manifest(output, spec)
    if tool_errors:
        return ValidationResult(
            ok=False,
            failure_mode=StructuralFailureMode.TOOL_MISUSE,
            errors=tool_errors,
        )

    return ValidationResult(ok=True, failure_mode=None, errors=[])
