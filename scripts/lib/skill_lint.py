"""Skill .md frontmatter shape classifier — telemetry-only P0.

Records frontmatter shape distribution to telemetry/skill_lint.jsonl.
NEVER emits advisory text. The no_advisory_invariant is structural:
no public function in this module returns a non-None value that could
be injected into hookSpecificOutput.additionalContext.

Convergence reference: debate-1777963974-4e8915
ontology_snapshot 833f75770125 (gen 2/3 stable)
P0 scope: telemetry_only_no_advisory
P1 entry: 7day_baseline_AND_upstream_schema_ge_30pct_AND_mixed_eq_0pct
"""
from __future__ import annotations

from pathlib import Path
from typing import Final

from .frontmatter import parse_frontmatter
from .logging import log_telemetry

# Shape enum — P0 4-way + P0.1 5th enum.
# P0.1 patch (2026-05-05): baseline showed _common mixed=71.7% (38/53), the
# legitimate dual-schema case. Architect's implementation_note approved adding
# `harness_extended` when mixed >60%. mixed is now reserved for genuine
# transitional state (partial upstream keys only).
SHAPE_UPSTREAM: Final[str] = "has_upstream_schema"
SHAPE_HARNESS: Final[str] = "has_harness_schema"
SHAPE_HARNESS_EXTENDED: Final[str] = "harness_extended"
SHAPE_MIXED: Final[str] = "mixed"
SHAPE_NONE: Final[str] = "none"

# Upstream Claude Code skill schema requires these two keys.
_UPSTREAM_KEYS = {"name", "description"}
# Harness-custom schema keys — any of these without upstream means harness-only.
_HARNESS_KEYS = {
    "keywords", "intent", "paths", "patterns",
    "phase", "min_score", "tech-stack", "requires",
}


def classify_shape(frontmatter_dict: dict[str, str] | None) -> str:
    """Classify frontmatter into one of 5 shape enums (presence-only).

    Decision tree:
      - empty / null              → none
      - all upstream keys present + harness keys → harness_extended (intentional dual)
      - any upstream key + harness keys, partial → mixed (transitional)
      - any upstream key, no harness keys → has_upstream_schema
      - any harness key, no upstream keys → has_harness_schema
      - neither → none

    Validity (empty string, null value) deferred to P1 per ontology field
    edge_case_empty_or_null=presence_false_validity_deferred_to_p1.
    """
    if not frontmatter_dict:
        return SHAPE_NONE
    keys = {k.lower() for k in frontmatter_dict.keys()}
    has_harness = bool(keys & _HARNESS_KEYS)
    upstream_hits = keys & _UPSTREAM_KEYS
    has_full_upstream = upstream_hits == _UPSTREAM_KEYS
    has_partial_upstream = bool(upstream_hits) and not has_full_upstream

    if has_full_upstream and has_harness:
        return SHAPE_HARNESS_EXTENDED
    if has_partial_upstream and has_harness:
        return SHAPE_MIXED
    if upstream_hits:
        return SHAPE_UPSTREAM
    if has_harness:
        return SHAPE_HARNESS
    return SHAPE_NONE


def is_skill_file(path: str) -> bool:
    """True iff path is a skill .md file under any skills/ tree."""
    if not path or not path.endswith(".md"):
        return False
    norm = path.replace("\\", "/")
    return "/skills/" in norm


def emit_telemetry(
    path: str,
    shape: str,
    name_present: bool,
    description_present: bool,
    *,
    session_id: str | None = None,
    file_size_bytes: int | None = None,
) -> None:
    """Append one telemetry record to TELEMETRY_DIR/skill_lint.jsonl.

    Always returns None. NEVER raises. NEVER produces advisory text.
    Schema fields locked at telemetry_schema=
        ts, session_id, path, shape, name_present, description_present, file_size_bytes
    (ts auto-prepended by log_telemetry's now_iso() in UTC.)
    """
    record = {
        "session_id": session_id,
        "path": path,
        "shape": shape,
        "name_present": name_present,
        "description_present": description_present,
        "file_size_bytes": file_size_bytes,
    }
    log_telemetry("skill_lint", record)


def lint_skill_file(path: str, *, session_id: str | None = None) -> None:
    """Convenience entry: parse + classify + emit. Fail-open."""
    try:
        result = parse_frontmatter(path)
        meta: dict[str, str] = result[0] if result else {}
        shape = classify_shape(meta)
        name_present = bool(meta.get("name", "").strip())
        description_present = bool(meta.get("description", "").strip())
        try:
            size: int | None = Path(path).stat().st_size
        except OSError:
            size = None
        emit_telemetry(
            path, shape, name_present, description_present,
            session_id=session_id, file_size_bytes=size,
        )
    except Exception:
        # Fail-open: telemetry must never break the post_tool hook.
        pass
