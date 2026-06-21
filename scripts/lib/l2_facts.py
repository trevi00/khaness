"""l2_facts — L2 Global Facts store (S2, debate-1779328283-9076f2 LOCK sha1 59cc1bab06a1af2019763d414cf345a2db7626df).

L0-L4 Memory Architecture (per CLAUDE.md §8):
  L1 Insight Index  — `lib/insight_index.py` (raw observations, append-only)
  L2 Global Facts   — THIS MODULE (compressed/deduplicated facts derived from L1)

Public surface (D16 LOCK):
  append(record: dict) -> str                    — write fact, return content-hash id (writers only)
  query(**filters) -> list[dict]                 — read facts, optionally filtered
  retract(fact_id: str, *, reason: str) -> bool  — append-only retraction record
  latest_for(subject, predicate) -> dict | None  — most recent non-retracted fact for (subject, predicate)
  promote() -> dict                              — invoke L1→L2 projection (alias for lib.l2_promoter.promote_all)
  add_evidence(fact_id, l1_correlation_id, l1_entry_id) -> bool — append D14 evidence edge
  evidence_for(fact_id: str) -> list[dict]       — read provenance edges for a fact

Inner shape (D2 LOCK, 11 fields):
  id              — sha1(canonical_json({subject, predicate, object_canonical}))[:16] (D9 LOCK)
  schema_version  — string "1" (D10 LOCK)
  ts_unix_ms      — int (caller supplies)
  subject         — str (SPO subject)
  predicate       — str (SPO predicate)
  object          — str (canonical_json of original value)
  object_datatype — enum: 'int'|'float'|'bool'|'none'|'str'|'list'|'dict' (D2 type tag)
  confidence      — float (deterministic = 1 - 1/(support_count+1))
  event_type      — str (one of {wonder, debate, evaluator} per D3)
  correlation_id  — str (representative L1 correlation_id)
  source_module   — str (writer's fully-qualified module — runtime-verified)

Canonical serialization (D15 LOCK):
  object_canonical = json.dumps(value, sort_keys=True, separators=(',', ':'),
                                ensure_ascii=False).encode('utf-8') for ALL value
  types (scalar, list, dict, None) — eliminates repr/json split incoherence
  flagged by Critic gen-2 S2. .encode('utf-8') per Critic gen-3 SC2.

Writers + Readers (D5 + D6 LOCK):
  WRITERS (runtime-only ModuleSpec assert, D5 — AST validator deferred):
    cron.run_l2_promotion (D17 — production caller)
    lib.l2_promoter        (D5 — projection module, internal helper)
  READERS (D6 sanctioned set):
    handlers.session.init
    handlers.prompt.context_load
    cli.l2_facts_cli
  FORBIDDEN (judge-generator isolation, inherited from L1):
    engine.debate.*
    lib.evaluator_dispatcher

Storage layout (D1 + D7 + D14 LOCK):
  ~/.claude/memory/global-facts.jsonl              — fact records (D1)
  ~/.claude/memory/global-facts-retractions.jsonl  — retraction records (D7)
  ~/.claude/memory/global-facts-evidence.jsonl     — L1→L2 provenance edges (D14)

Out-of-scope (D13 LOCK):
  - refute-patterns side-stream (separate ontology, future debate)
  - cross-fact inference (orthogonal subsystem)
  - multi-source merge resolution (trust scoring, future design)
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from lib.jsonl_cache import load_jsonl_cached


SCHEMA_VERSION = "1"

_ALLOWED_OBJECT_DATATYPES: frozenset[str] = frozenset({
    "int", "float", "bool", "none", "str", "list", "dict",
})

_REQUIRED_FIELDS: tuple[str, ...] = (
    "subject", "predicate", "object", "object_datatype",
    "ts_unix_ms", "support_count", "event_type",
    "correlation_id", "source_module",
)

# D5 + D6 LOCK — runtime-only ModuleSpec assert (AST validator deferred per gen-1 cond #6).
_ALLOWED_WRITER_MODULES: frozenset[str] = frozenset({
    "lib.l2_facts",              # self (internal use within module)
    "lib.l2_promoter",           # D5 LOCK — projection writes facts
    "cron.run_l2_promotion",     # D17 LOCK — production caller of promoter
    # housekeeping — tests must be able to write fixtures
    "tests.test_l2_facts",
    "tests.test_l2_promoter",
})

_ALLOWED_READER_MODULES: frozenset[str] = frozenset({
    "lib.l2_facts",                        # self
    "lib.l2_promoter",                     # projection reads existing facts for dedup
    "handlers.session.init",               # D6 R1
    "handlers.prompt.context_load",        # D6 R2
    "cli.l2_facts_cli",                    # D6 R3
    "cron.run_l2_promotion",               # promoter caller may read for forensics
    # housekeeping
    "tests.test_l2_facts",
    "tests.test_l2_promoter",
})

# Forbidden set inherits L1's (debate-1778248254-0b7092 judge-generator isolation).
_FORBIDDEN_MODULE_PREFIXES: tuple[str, ...] = (
    "engine.debate.",
    "engine.debate",
    "lib.evaluator_dispatcher",
)


class L2WriterNotAllowedError(RuntimeError):
    """Raised when a non-whitelisted module attempts to write L2 facts."""


class L2ReaderNotAllowedError(RuntimeError):
    """Raised when a forbidden module attempts to read L2 facts."""


class L2ValidationError(ValueError):
    """Raised on malformed record / missing required field / bad datatype."""


def _claude_home() -> Path:
    env = os.environ.get("CLAUDE_HOME")
    if env:
        return Path(env)
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        return Path(user_profile) / ".claude"
    return Path.home() / ".claude"


def _memory_dir() -> Path:
    p = _claude_home() / "memory"
    p.mkdir(parents=True, exist_ok=True)
    return p


# D1 + D7 + D14 LOCK — module-internal underscore path constants (D16: no path exports).
def _FACTS_PATH() -> Path:
    return _memory_dir() / "global-facts.jsonl"


def _RETRACTIONS_PATH() -> Path:
    return _memory_dir() / "global-facts-retractions.jsonl"


def _EVIDENCE_PATH() -> Path:
    return _memory_dir() / "global-facts-evidence.jsonl"


# Parsed-entries cache (mtime+size keyed, per L1 _load_jsonl pattern).
_PARSE_CACHE: dict[Path, tuple[tuple[int, int], list[dict]]] = {}


def _caller_module_name(skip: int = 2) -> str | None:
    """Return caller's ModuleSpec.name; None when unresolvable (REPL, frozen, etc.)."""
    try:
        frame = sys._getframe(skip)
    except ValueError:
        return None
    mod = inspect.getmodule(frame)
    if mod is None:
        return None
    spec = getattr(mod, "__spec__", None)
    if spec is None:
        return None
    name = getattr(spec, "name", None)
    return name if isinstance(name, str) else None


def _assert_writer_allowed(public_fn_name: str) -> None:
    """D5 LOCK — runtime gate: caller MUST be in _ALLOWED_WRITER_MODULES.

    Stricter than L1 (which fails open on unresolvable callers) because L2
    writes are projections — wrong-writer = breaks D4 determinism + D9
    idempotency. Fail closed.

    Forbidden set blocks engine.debate.*, lib.evaluator_dispatcher even if
    they somehow get listed (defense in depth — judge-generator isolation).
    """
    name = _caller_module_name(skip=3)
    if name is None:
        # Unresolvable caller (REPL / frozen). Fail closed for writes.
        raise L2WriterNotAllowedError(
            f"l2_facts.{public_fn_name}() blocked: caller module unresolvable. "
            f"Allowed writers: {sorted(_ALLOWED_WRITER_MODULES)}."
        )
    for prefix in _FORBIDDEN_MODULE_PREFIXES:
        if name == prefix or name.startswith(prefix + "."):
            raise L2WriterNotAllowedError(
                f"l2_facts.{public_fn_name}() blocked: caller {name!r} in forbidden set "
                f"(judge-generator isolation, debate-1778248254-0b7092)."
            )
    if name not in _ALLOWED_WRITER_MODULES:
        raise L2WriterNotAllowedError(
            f"l2_facts.{public_fn_name}() blocked: caller {name!r} not in writer whitelist. "
            f"Allowed: {sorted(_ALLOWED_WRITER_MODULES)}."
        )


def _assert_reader_allowed(public_fn_name: str) -> None:
    """D6 LOCK — runtime gate for reads. Forbidden set blocked even with whitelist match.

    Read gate is softer than write: unresolvable callers (REPL, tests) fail
    OPEN to keep ergonomics — operator inspection should not be blocked by
    sandbox quirks. Forbidden set still rejects.
    """
    name = _caller_module_name(skip=3)
    if name is None:
        return  # fail-open for reads
    for prefix in _FORBIDDEN_MODULE_PREFIXES:
        if name == prefix or name.startswith(prefix + "."):
            raise L2ReaderNotAllowedError(
                f"l2_facts.{public_fn_name}() blocked: caller {name!r} in forbidden set "
                f"(judge-generator isolation)."
            )
    if name not in _ALLOWED_READER_MODULES:
        raise L2ReaderNotAllowedError(
            f"l2_facts.{public_fn_name}() blocked: caller {name!r} not in reader whitelist. "
            f"Allowed: {sorted(_ALLOWED_READER_MODULES)}."
        )


def _detect_object_datatype(value: Any) -> str:
    """Return the D2 object_datatype enum tag for a Python value."""
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "bool"  # bool before int — Python bool isinstance int is True
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    raise L2ValidationError(
        f"unsupported object type {type(value).__name__}; "
        f"allowed: {sorted(_ALLOWED_OBJECT_DATATYPES)}"
    )


def canonicalize(value: Any) -> str:
    """D15 LOCK — uniform canonical serialization for ALL value types.

    json.dumps(sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    handles scalar (int/float/bool/None/str) + container (list/dict)
    uniformly. Eliminates repr() / json split incoherence (Critic gen-2 S2:
    repr(None)='None' vs json.dumps(None)='null').

    Returns str (caller can .encode('utf-8') for hashing per SC2).
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _compute_fact_id(subject: str, predicate: str, object_canonical: str) -> str:
    """D9 LOCK — content-hash id over (subject, predicate, object_canonical).

    supporting_l1_ids EXCLUDED from hash (gen-1 cond #2): stable identity
    across new corroborating evidence; supporting_l1_ids stored separately
    in D14 evidence file. Identity changes only when (subject, predicate,
    object) changes.

    SC2: explicit .encode('utf-8') before sha1 — required for ensure_ascii=False
    output that may contain non-ASCII chars.
    """
    payload = canonicalize({
        "subject": subject,
        "predicate": predicate,
        "object_canonical": object_canonical,
    })
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _validate_record(rec: dict) -> None:
    if not isinstance(rec, dict):
        raise L2ValidationError(f"record must be dict, got {type(rec).__name__}")
    missing = [k for k in _REQUIRED_FIELDS if k not in rec]
    if missing:
        raise L2ValidationError(f"record missing required fields: {missing}")
    if not isinstance(rec["subject"], str) or not rec["subject"]:
        raise L2ValidationError("subject must be non-empty str")
    if not isinstance(rec["predicate"], str) or not rec["predicate"]:
        raise L2ValidationError("predicate must be non-empty str")
    if not isinstance(rec["ts_unix_ms"], int) or rec["ts_unix_ms"] < 0:
        raise L2ValidationError("ts_unix_ms must be non-negative int")
    if rec["object_datatype"] not in _ALLOWED_OBJECT_DATATYPES:
        raise L2ValidationError(
            f"object_datatype {rec['object_datatype']!r} not in "
            f"{sorted(_ALLOWED_OBJECT_DATATYPES)}"
        )
    if not isinstance(rec["support_count"], int) or rec["support_count"] < 1:
        raise L2ValidationError("support_count must be int >= 1")
    if not isinstance(rec["event_type"], str) or not rec["event_type"]:
        raise L2ValidationError("event_type must be non-empty str")
    if not isinstance(rec["correlation_id"], str) or not rec["correlation_id"]:
        raise L2ValidationError("correlation_id must be non-empty str")
    if not isinstance(rec["source_module"], str) or not rec["source_module"]:
        raise L2ValidationError("source_module must be non-empty str")


def _compute_confidence(support_count: int) -> float:
    """Deterministic confidence formula = 1 - 1/(support_count + 1).

    Closed-form, monotonic non-decreasing in support_count, asymptotic to 1.
    """
    return 1.0 - 1.0 / (support_count + 1)


def append(record: dict) -> str:
    """Write one L2 fact. Returns the content-hash id (D9 LOCK).

    Caller MUST supply: subject, predicate, object (raw Python value),
    object_datatype, ts_unix_ms, support_count, event_type, correlation_id,
    source_module. `object` is canonicalized via D15 internally; the stored
    `object` field is the canonical string. id, schema_version, confidence
    are computed by this function.

    Idempotency (D9): re-appending a record with same (subject, predicate,
    object_canonical) produces the SAME id. The file will then contain two
    physical lines with the same id — readers de-dup via query()'s latest
    wins semantic.

    Raises L2WriterNotAllowedError on non-whitelisted caller.
    Raises L2ValidationError on missing/bad field.
    """
    _assert_writer_allowed("append")
    _validate_record(record)
    obj_canonical = canonicalize(record["object"])
    fact_id = _compute_fact_id(record["subject"], record["predicate"], obj_canonical)
    full: dict[str, Any] = {
        "id": fact_id,
        "schema_version": SCHEMA_VERSION,
        "ts_unix_ms": record["ts_unix_ms"],
        "subject": record["subject"],
        "predicate": record["predicate"],
        "object": obj_canonical,
        "object_datatype": record["object_datatype"],
        "confidence": _compute_confidence(record["support_count"]),
        "event_type": record["event_type"],
        "correlation_id": record["correlation_id"],
        "source_module": record["source_module"],
    }
    path = _FACTS_PATH()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(full, ensure_ascii=False, sort_keys=True) + "\n")
    return fact_id


def _load_jsonl(path: Path) -> list[dict]:
    """Mirror of L1 _load_jsonl: mtime+size cache invalidation (D12 SLO target).

    Delegates to canonical lib.jsonl_cache (shared with L1 insight_index) using
    this layer's OWN _PARSE_CACHE — cache isolation + semantics preserved.
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
    subject: str | None = None,
    predicate: str | None = None,
    fact_type: str | None = None,
    event_type: str | None = None,
    include_retracted: bool = False,
    limit: int | None = None,
) -> list[dict]:
    """Read L2 facts, applying AND-combined filters.

    fact_type kept as alias parameter for forward compat (D2 record currently
    has no fact_type field; if added in v2 schema migration the filter is
    pre-wired). event_type filters the D2 event_type field directly.

    Performance (D12 LOCK): p99 < 75ms @ 2k facts.

    De-dup semantic: when the file contains multiple physical lines with
    the same id (D9 idempotent append-of-same-content), the LAST one wins.
    """
    _assert_reader_allowed("query")
    retracted = set() if include_retracted else _retracted_ids()
    # Latest-wins de-dup by id.
    by_id: dict[str, dict] = {}
    for rec in _load_jsonl(_FACTS_PATH()):
        fid = rec.get("id")
        if not isinstance(fid, str):
            continue
        if fid in retracted:
            by_id.pop(fid, None)
            continue
        by_id[fid] = rec
    out: list[dict] = []
    for rec in by_id.values():
        if subject is not None and rec.get("subject") != subject:
            continue
        if predicate is not None and rec.get("predicate") != predicate:
            continue
        if event_type is not None and rec.get("event_type") != event_type:
            continue
        if fact_type is not None and rec.get("fact_type") != fact_type:
            continue
        out.append(rec)
    out.sort(key=lambda r: r.get("ts_unix_ms", 0))
    if limit is not None and limit >= 0:
        out = out[-limit:]
    return out


def latest_for(subject: str, predicate: str) -> dict | None:
    """D9 LOCK reader API — most recent non-retracted fact for (subject, predicate).

    Returns None when no fact matches. When multiple physical lines exist
    for the same id (idempotent append), the latest non-retracted one is
    returned via query()'s latest-wins de-dup.
    """
    _assert_reader_allowed("latest_for")
    if not isinstance(subject, str) or not subject:
        raise L2ValidationError("subject must be non-empty str")
    if not isinstance(predicate, str) or not predicate:
        raise L2ValidationError("predicate must be non-empty str")
    matches = query(subject=subject, predicate=predicate)
    return matches[-1] if matches else None


def retract(fact_id: str, *, reason: str) -> bool:
    """D7 LOCK — append-only retraction record.

    Writes {retracted_id, reason, ts_unix_ms} to retractions sibling file
    WITHOUT mutating the facts file. Subsequent query() calls suppress
    retracted ids unless include_retracted=True.

    Returns True on successful write, False on OSError.
    """
    _assert_writer_allowed("retract")
    if not isinstance(fact_id, str) or not fact_id:
        raise L2ValidationError("fact_id must be non-empty str")
    if not isinstance(reason, str) or not reason:
        raise L2ValidationError("reason must be non-empty str")
    rec = {
        "retracted_id": fact_id,
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


def add_evidence(fact_id: str, l1_correlation_id: str, l1_entry_id: str) -> bool:
    """D14 LOCK — append one L1→L2 provenance edge to evidence sidecar.

    Edge shape: {fact_id, l1_correlation_id, l1_entry_id, added_ts_ms}.
    Multiple edges per fact_id are normal (D9: support_count >= 1 means
    >=1 L1 entry; D4 threshold means typically >=3 edges per fact).
    """
    _assert_writer_allowed("add_evidence")
    if not isinstance(fact_id, str) or not fact_id:
        raise L2ValidationError("fact_id must be non-empty str")
    if not isinstance(l1_correlation_id, str) or not l1_correlation_id:
        raise L2ValidationError("l1_correlation_id must be non-empty str")
    if not isinstance(l1_entry_id, str) or not l1_entry_id:
        raise L2ValidationError("l1_entry_id must be non-empty str")
    rec = {
        "fact_id": fact_id,
        "l1_correlation_id": l1_correlation_id,
        "l1_entry_id": l1_entry_id,
        "added_ts_ms": int(time.time() * 1000),
    }
    path = _EVIDENCE_PATH()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        return False
    return True


def evidence_for(fact_id: str) -> list[dict]:
    """Read all provenance edges for one fact_id (chronological order)."""
    _assert_reader_allowed("evidence_for")
    if not isinstance(fact_id, str) or not fact_id:
        return []
    return [
        e for e in _load_jsonl(_EVIDENCE_PATH())
        if e.get("fact_id") == fact_id
    ]


# M25 D7 read-side insight floor (debate-1781649830-m25a01 LOCK
# d42ac5e34ecf9dc7a5da558ca9880cfae1c9fa19).
_INSIGHT_FLOOR_SUPPORT: int = 3
_INSIGHT_FLOOR_DISTINCT_SESSIONS: int = 2


def is_insight_floor(fact: dict) -> bool:
    """M25 read-side floor: True iff a fact recurs with enough support across enough
    DISTINCT sessions to be worth surfacing — support_count >= 3 AND distinct_sessions
    >= 2, both derived OFF-HASH from the fact's evidence edges (one edge per source L1
    id, each carrying its own l1_correlation_id, which IS the session id for the
    eligible classes). No record-schema change: the floor reads the D14 evidence file,
    mirroring the write-side gate in lib.l2_promoter.

    Any FUTURE L2 session-injection reader MUST filter by this floor so the M25
    re-activation's first low-insight self-observation facts (e.g. 'orchestrator
    verdict=complete') cannot silently pollute a read path. (No live L2 session-
    injecting reader exists today — context_load reads L1, session.init is forensic-
    grep only — so this is a forward-looking guard.) Returns False on a fact with no
    id or no evidence.
    """
    fid = fact.get("id") if isinstance(fact, dict) else None
    if not isinstance(fid, str) or not fid:
        return False
    edges = evidence_for(fid)
    support = len(edges)
    distinct_sessions = len({
        e.get("l1_correlation_id") for e in edges
        if isinstance(e.get("l1_correlation_id"), str) and e.get("l1_correlation_id")
    })
    return support >= _INSIGHT_FLOOR_SUPPORT and distinct_sessions >= _INSIGHT_FLOOR_DISTINCT_SESSIONS


def evidence_l1_to_fact(l1_entry_id: str) -> list[str]:
    """Reverse lookup: which facts cite this L1 entry?

    O(N) scan over evidence file (SC6 acknowledged minor concern from gen-2;
    a future optimization may build a lazy reverse index but the current
    expected entry volume keeps this acceptable).
    """
    _assert_reader_allowed("evidence_l1_to_fact")
    out: list[str] = []
    for rec in _load_jsonl(_EVIDENCE_PATH()):
        if rec.get("l1_entry_id") == l1_entry_id:
            fid = rec.get("fact_id")
            if isinstance(fid, str):
                out.append(fid)
    return out


def promote() -> dict:
    """D16 LOCK public surface — alias for lib.l2_promoter.promote_all().

    Re-exported here so callers can use the unified `lib.l2_facts` surface
    without importing the promoter module directly. The actual projection
    algorithm lives in lib/l2_promoter.py per D4 (separation of pure-function
    projector from store).
    """
    _assert_writer_allowed("promote")
    from . import l2_promoter
    return l2_promoter.promote_all()
