"""insight_index — L1 Insight Index store (S2, debate-1779267594-edb2a2 LOCK sha1 ac40cc972219d3374d8f08893719e7a89b495465).

Public surface (api/lib_public_surface ontology field):
  append(entry: dict) -> str            — write entry, return generated id
  query(**filters) -> list[dict]        — read entries, optionally filtered
  retract(entry_id: str, *, reason: str) -> bool   — append-only retraction record

Path constants (_INDEX_PATH, _RETRACTIONS_PATH, _MEMORY_DIR) are module-internal
underscore (D8 lib_public_surface — "no path constants exported"). Callers MUST
NOT import them. AST whitelist validator (validators/insight_index_importer_whitelist.py)
enforces the forbidden set engine/debate/*, lib/evaluator_dispatcher.py per D6
forbidden_set (judge-generator isolation, debate-1778248254-0b7092).

Inner shape (D1_inner_shape_field_count=10):
  id              — <event_type>-<ts_unix_ms>-<6hex secrets.token_hex(3)>
  schema_version  — string "1" (JSON-safe, semver-compatible; D1_summary_max_chars footnote)
  ts_unix_ms      — int (idempotent recompute disallowed; caller supplies on append)
  event_type      — short slug (e.g., 'wonder', 'debate', 'evaluator')
  summary         — <=280 chars; overflow → InsightIndexSummaryOverflowError + rejection event
  correlation_id  — opaque str (reflection_fingerprint 16-hex per D5_W2 LOCK)
  source_module   — fully-qualified writer module name (cross-check vs whitelist)
  axis            — optional evaluator axis (str | None)
  tags            — list[str] (sorted on read for stability)
  body_ref        — optional pointer to richer body (path or url); None for inline-only

Errors:
  InsightIndexSummaryOverflowError — summary > 280 chars; rejection event written
  InsightIndexCollisionError       — 6th id collision after 5 LRU retries

Collision policy (D3_collision_policy):
  regenerate 6hex suffix up to 5 retries on collision (in-memory LRU of last 1024 ids);
  6th failure raises InsightIndexCollisionError.

Test contract (D3 enforcement):
  tests/run_units.py::test_insight_index_query_p99_under_50ms ensures p99 < 50ms @ 5k entries.

L2 (Global Facts) execution is DEFERRED — see cron/check_l2_promotion.py for the trigger.
"""
from __future__ import annotations

import inspect
import json
import os
import secrets
import sys
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from lib.jsonl_cache import load_jsonl_cached


SCHEMA_VERSION = "1"
SUMMARY_MAX_CHARS = 280
ID_COLLISION_RETRIES = 5
ID_LRU_SIZE = 1024


# D2 writer whitelist (debate-1780268884-1di5gw, gen 4 converged sha1
# 78f09503a8894f02cff45ed53a3ea07d26a5fddf). Module-load-time frozenset of the
# 3 ratified writers from D5_writer_count=3 LOCK (atlas debate-1779267594-l1-
# insight-index.md:47,78). append() rejects entries whose source_module is not
# in this set via _emit_rejection('writer_not_whitelisted', ...) and returns
# None (no exception raised) — honors silent-swallow at:
#   handlers/stop/learner.py:139-141
#   engine/orchestrator.py:600-602
#   lib/skill_candidate_detector.py:27-28
# Tests widen this set via monkeypatch.setattr in scripts/tests/conftest.py.
#
# ── L1 writer-auth model (debate-1781937446-1281b5 D1) ──────────────────────
# IMPORTANT — the _ALLOWED_WRITER_SOURCES check in append() below is an ADVISORY
# runtime gate, NOT a spoof-resistant boundary: it compares the caller-SUPPLIED
# entry['source_module'] STRING (see append, ~:285), not the real calling frame,
# so it cannot stop a caller that passes a whitelisted name. That is acceptable
# because the REAL writer perimeter is the STATIC AST importer-whitelist
# validators/insight_index_importer_whitelist.py (registered + blocking in
# run_all), which bounds WHICH modules may import lib.insight_index at all.
# Contrast lib/l2_facts.py, which fails CLOSED on the real ModuleSpec.name frame
# (L2 needs runtime frame-auth; L1 leans on the static perimeter instead). A
# runtime frame cross-check for L1 was DEBATED and REJECTED as theater: all 3
# production writers pass literal co-located source_module constants (zero drift),
# so a frame check would catch zero real cases. Do not add one without new evidence.
_ALLOWED_WRITER_SOURCES: frozenset[str] = frozenset({
    "handlers.stop.learner",
    "engine.orchestrator",
    "lib.skill_candidate_detector",
})


# D7_enforcement runtime layer (ontology LOCK):
#   Static AST whitelist lives in validators/insight_index_importer_whitelist.py.
#   Runtime assert below uses inspect.getmodule(caller_frame).__spec__.name —
#   reading the IMMUTABLE ModuleSpec (NOT frame-globals __name__, which the
#   gen-3 Critic B1 caught as vacuous since __name__ can be reassigned). The
#   forbidden set blocks judge-generator coupling per debate-1778248254-0b7092.
#
#   Documented limitation (D7_enforcement value): dynamic-import bypass
#   (importlib.import_module, __import__) is OUT-OF-SCOPE. A determined caller
#   can re-import via importlib; policy is advisory, not airtight. Layered
#   sys.modules audit hook deferred to follow-up PR per architect self_doubt.

_FORBIDDEN_MODULE_PREFIXES: tuple[str, ...] = (
    "engine.debate.",
    "engine.debate",  # exact-match for engine/debate/__init__.py
    "lib.evaluator_dispatcher",
)


def _assert_caller_allowed(public_fn_name: str) -> None:
    """Runtime gate for D6_forbidden_set / D7_enforcement.

    Reads the caller's ModuleSpec.name (immutable per CPython import system).
    Raises RuntimeError when the caller belongs to the forbidden set.

    Failure mode: if we cannot determine the caller's module spec (e.g.,
    REPL, frozen module, eval'd code), we fail OPEN — the static AST
    validator catches imports at audit time, so runtime fail-open here is
    acceptable per architect self_doubt note (policy is advisory).
    """
    try:
        frame = sys._getframe(2)  # 2: skip this fn + the public api fn
    except ValueError:
        return
    mod = inspect.getmodule(frame)
    if mod is None:
        return
    spec = getattr(mod, "__spec__", None)
    if spec is None:
        return
    name = getattr(spec, "name", None)
    if not isinstance(name, str):
        return
    for prefix in _FORBIDDEN_MODULE_PREFIXES:
        if name == prefix or name.startswith(prefix + "."):
            raise RuntimeError(
                f"insight_index.{public_fn_name}() blocked: caller module "
                f"{name!r} is in forbidden set (D6 judge-generator isolation). "
                f"See debate-1778248254-0b7092 for policy rationale."
            )


class InsightIndexSummaryOverflowError(ValueError):
    """Raised when entry['summary'] exceeds SUMMARY_MAX_CHARS.

    A structured rejection event is appended to state/insight-index-rejections.jsonl
    before this is raised — never silent drop (D1_summary_max_chars LOCK).
    """


class InsightIndexCollisionError(RuntimeError):
    """Raised when 6 consecutive 6hex secrets.token_hex(3) attempts collide
    against the in-memory LRU of last ID_LRU_SIZE generated ids.

    Practically unreachable (24-bit space, LRU=1024) but typed so callers can
    distinguish from corrupt-store ValueError.
    """


def _claude_home() -> Path:
    env = os.environ.get("CLAUDE_HOME")
    if env:
        return Path(env)
    up = os.environ.get("USERPROFILE")
    if up:
        return Path(up) / ".claude"
    return Path.home() / ".claude"


def _memory_dir() -> Path:
    p = _claude_home() / "memory"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _state_dir() -> Path:
    p = _claude_home() / "state"
    p.mkdir(parents=True, exist_ok=True)
    return p


# Module-internal path constants (underscore — NOT exported, D8 ontology LOCK).
def _INDEX_PATH() -> Path:
    return _memory_dir() / "insight-index.jsonl"


def _RETRACTIONS_PATH() -> Path:
    return _memory_dir() / "insight-index-retractions.jsonl"


def _REJECTIONS_PATH() -> Path:
    return _state_dir() / "insight-index-rejections.jsonl"


# LRU of last ID_LRU_SIZE generated ids (collision retry guard, D3).
_ID_LRU: OrderedDict[str, None] = OrderedDict()

# Parsed-entries cache to honor the D3 p99 < 50ms @ 5k SLO. Keyed by
# (file path, mtime_ns, size). Cache invalidates whenever the file
# changes (atomic-append model — readers don't need locks). Sized for
# index + retractions; ~50KB per entry × 5k = ~250MB worst-case kept
# warm in memory, which is acceptable for L1 (DEFERRED to L2 if budget
# proves problematic — see cron/check_l2_promotion.py trigger c).
_PARSE_CACHE: dict[Path, tuple[tuple[int, int], list[dict]]] = {}


def _lru_remember(entry_id: str) -> None:
    _ID_LRU[entry_id] = None
    while len(_ID_LRU) > ID_LRU_SIZE:
        _ID_LRU.popitem(last=False)


def _lru_contains(entry_id: str) -> bool:
    return entry_id in _ID_LRU


def _gen_id(event_type: str, ts_unix_ms: int) -> str:
    """Generate <event_type>-<ts_unix_ms>-<6hex>; retry 5x on LRU collision."""
    safe_type = "".join(c for c in event_type if c.isalnum() or c in "-_") or "event"
    for _ in range(ID_COLLISION_RETRIES + 1):
        suffix = secrets.token_hex(3)
        candidate = f"{safe_type}-{ts_unix_ms}-{suffix}"
        if not _lru_contains(candidate):
            _lru_remember(candidate)
            return candidate
    raise InsightIndexCollisionError(
        f"id collision after {ID_COLLISION_RETRIES} retries for "
        f"event_type={event_type!r} ts={ts_unix_ms}"
    )


def _emit_rejection(reason: str, payload: dict) -> None:
    """Append structured rejection event. Never silent drop (D1 LOCK)."""
    rec = {
        "ts_unix_ms": int(time.time() * 1000),
        "reason": reason,
        "payload": payload,
    }
    try:
        path = _REJECTIONS_PATH()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _validate_inner_shape(entry: dict) -> None:
    if not isinstance(entry, dict):
        raise ValueError(f"entry must be dict, got {type(entry).__name__}")
    required = {
        "event_type",
        "summary",
        "ts_unix_ms",
        "correlation_id",
        "source_module",
    }
    missing = required - entry.keys()
    if missing:
        raise ValueError(f"entry missing required keys: {sorted(missing)}")
    if not isinstance(entry["event_type"], str) or not entry["event_type"]:
        raise ValueError("entry['event_type'] must be non-empty str")
    if not isinstance(entry["summary"], str):
        raise ValueError("entry['summary'] must be str")
    if not isinstance(entry["ts_unix_ms"], int) or entry["ts_unix_ms"] < 0:
        raise ValueError("entry['ts_unix_ms'] must be non-negative int")
    if not isinstance(entry["correlation_id"], str) or not entry["correlation_id"]:
        raise ValueError("entry['correlation_id'] must be non-empty str")
    if not isinstance(entry["source_module"], str) or not entry["source_module"]:
        raise ValueError("entry['source_module'] must be non-empty str")
    axis = entry.get("axis")
    if axis is not None and not isinstance(axis, str):
        raise ValueError("entry['axis'] must be str or None")
    tags = entry.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise ValueError("entry['tags'] must be list[str]")
    body_ref = entry.get("body_ref")
    if body_ref is not None and not isinstance(body_ref, str):
        raise ValueError("entry['body_ref'] must be str or None")


def append(entry: dict) -> str | None:
    """Append entry to insight-index.jsonl. Return generated id, or None when
    the entry's source_module fails the D2 writer whitelist (silent-swallow
    contract; rejection event emitted to insight-index-rejections.jsonl).

    Validation order:
      1. caller in D6 forbidden set → RuntimeError (D7_enforcement)
      2. inner-shape required keys + types → ValueError on missing/wrong shape
      3. D2 writer whitelist (entry['source_module'] in _ALLOWED_WRITER_SOURCES)
         → on miss: _emit_rejection('writer_not_whitelisted', ...) + return None
      4. summary <= SUMMARY_MAX_CHARS (overflow → rejection event + raise)
      5. id generation w/ 5-retry LRU collision guard
    """
    _assert_caller_allowed("append")
    _validate_inner_shape(entry)
    # D2 writer whitelist gate (debate-1780268884-1di5gw). Runs AFTER shape
    # validation so callers with malformed entries see ValueError (not silent
    # None) — schema error is operator-fix territory, whitelist miss is policy.
    source_module = entry["source_module"]
    if source_module not in _ALLOWED_WRITER_SOURCES:
        _emit_rejection("writer_not_whitelisted", {
            "source_module": source_module,
            "event_type": entry.get("event_type"),
        })
        return None
    summary = entry["summary"]
    if len(summary) > SUMMARY_MAX_CHARS:
        _emit_rejection("summary_overflow", {
            "event_type": entry["event_type"],
            "summary_length": len(summary),
            "limit": SUMMARY_MAX_CHARS,
            "correlation_id": entry["correlation_id"],
        })
        raise InsightIndexSummaryOverflowError(
            f"summary length {len(summary)} exceeds {SUMMARY_MAX_CHARS}"
        )
    entry_id = _gen_id(entry["event_type"], entry["ts_unix_ms"])
    record = {
        "id": entry_id,
        "schema_version": SCHEMA_VERSION,
        "ts_unix_ms": entry["ts_unix_ms"],
        "event_type": entry["event_type"],
        "summary": summary,
        "correlation_id": entry["correlation_id"],
        "source_module": entry["source_module"],
        "axis": entry.get("axis"),
        "tags": sorted(entry.get("tags", [])),
        "body_ref": entry.get("body_ref"),
    }
    path = _INDEX_PATH()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return entry_id


def _load_jsonl(path: Path) -> list[dict]:
    """Parse a JSONL file with mtime+size cache invalidation.

    L1 SLO (D3): p99 query < 50ms @ 5k entries. Re-parsing 5k JSON lines on
    every query() call breaks the SLO on Windows; cache the parsed list keyed
    by (mtime_ns, size) so repeated reads with no append are O(1) instead of
    O(n). Atomic append-only writes guarantee mtime/size change ⇔ content
    change — no torn-line race.

    Delegates to canonical lib.jsonl_cache (shared with L2 l2_facts) using this
    layer's OWN _PARSE_CACHE — cache isolation + semantics preserved verbatim.
    """
    return load_jsonl_cached(path, _PARSE_CACHE)


def _retracted_ids() -> set[str]:
    out: set[str] = set()
    for rec in _load_jsonl(_RETRACTIONS_PATH()):
        rid = rec.get("retracted_id")
        if isinstance(rid, str):
            out.add(rid)
    return out


def query(
    *,
    event_type: str | None = None,
    correlation_id: str | None = None,
    axis: str | None = None,
    tag: str | None = None,
    include_retracted: bool = False,
    limit: int | None = None,
) -> list[dict]:
    """Read entries from insight-index.jsonl, applying filters.

    Filters are AND-combined. Returns list in append order (oldest→newest)
    unless `limit` truncates the tail (most recent `limit` entries).

    Performance: O(n) scan. Tests/run_units.py::test_insight_index_query_p99
    _under_50ms enforces p99 < 50ms at 5000 entries (D3_collision_policy
    footnote — query SLO).
    """
    retracted = set() if include_retracted else _retracted_ids()
    out: list[dict] = []
    for rec in _load_jsonl(_INDEX_PATH()):
        if rec.get("id") in retracted:
            continue
        if event_type is not None and rec.get("event_type") != event_type:
            continue
        if correlation_id is not None and rec.get("correlation_id") != correlation_id:
            continue
        if axis is not None and rec.get("axis") != axis:
            continue
        if tag is not None:
            tags = rec.get("tags") or []
            if tag not in tags:
                continue
        out.append(rec)
    if limit is not None and limit >= 0:
        out = out[-limit:]
    return out


def retract(entry_id: str, *, reason: str) -> bool:
    """Append-only retraction (D7_retraction_mechanism LOCK).

    Writes {retracted_id, reason, ts_unix_ms} to insight-index-retractions.jsonl
    WITHOUT mutating insight-index.jsonl. Subsequent query() calls filter out
    retracted ids unless include_retracted=True.

    Returns True if the retraction record was written (does NOT verify the
    target id existed — append-only semantics deliberately tolerate forward
    retractions for race conditions). False on OSError.
    """
    _assert_caller_allowed("retract")
    if not isinstance(entry_id, str) or not entry_id:
        raise ValueError("entry_id must be non-empty str")
    if not isinstance(reason, str) or not reason:
        raise ValueError("reason must be non-empty str")
    rec = {
        "retracted_id": entry_id,
        "reason": reason,
        "ts_unix_ms": int(time.time() * 1000),
    }
    path = _RETRACTIONS_PATH()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        return False
    return True
