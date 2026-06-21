"""graduation_audit — read-only reader for the validator graduation audit trail (M13).

`lib/graduation.py` APPENDS every flip to `state/graduation-history.jsonl` via
`_append_history()` — actions `graduate` / `demote` / `circuit_breaker_demote`,
each with `{ts, action, validator, token_used, ...}`. Nothing READ that append-only
trail: `graduation.status_report()` reports the CURRENT streak state, and the
per-validator `history_tail` in graduation-state.json keeps only the last 12
entries. The full forensic trail (who flipped what, with which token, when, and
how often the circuit-breaker auto-demoted) had no consumer.

This module is the reader half (signal collect → signal spend): pure functions
that parse the jsonl and aggregate it into a per-validator / per-action summary,
plus a tail view. Read-only — it NEVER writes state, mutates nothing, and is
fail-soft (missing/garbled file → empty result). The graduation flip itself stays
token-gated in `cli/graduate_validator.py`; this only SURFACES what already happened.

Currently the live trail is empty (no validator has graduated yet — the two
tracked validators sit at READY), so the reader is forward-looking: it returns an
empty summary today and aggregates real events the moment the operator graduates
or a circuit-breaker fires. Path resolution defers to `graduation._history_path()`
so the STATE_DIR junction isolation used by run_units (and any future relocation)
is honored — tests redirect by patching `graduation.STATE_DIR`.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from . import graduation as _g

# The append-only audit actions graduation.py emits (for stable summary keys /
# zero-fill so a consumer always sees every action bucket, even at count 0).
KNOWN_ACTIONS: tuple[str, ...] = ("graduate", "demote", "circuit_breaker_demote")


def _history_path() -> Path:
    """Single source of truth = graduation's lazy path (STATE_DIR at call time)."""
    return _g._history_path()


def read_history(limit: int | None = None) -> list[dict[str, Any]]:
    """Parse `graduation-history.jsonl` into a list of records (oldest→newest).

    Fail-soft: missing file → []; a garbled line is skipped, never fatal; a
    non-object JSON line is ignored. `limit` (>=0) returns only the last N
    records (the audit tail); None / negative returns all.
    """
    path = _history_path()
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    if limit is not None and limit >= 0:
        return out[-limit:] if limit else []   # limit==0 → []; out[-0:] is the whole list
    return out


def history_for_validator(name: str, limit: int | None = None) -> list[dict[str, Any]]:
    """The audit records for one validator (oldest→newest). `limit` tails as above."""
    recs = [r for r in read_history() if r.get("validator") == name]
    if limit is not None and limit >= 0:
        return recs[-limit:] if limit else []   # limit==0 → []; recs[-0:] is the whole list
    return recs


def summary_report() -> dict[str, Any]:
    """Aggregate the whole trail into a forensic summary. Pure, no I/O beyond read.

    Returns:
      {
        total_records: int,
        by_action: {action: count}      # zero-filled over KNOWN_ACTIONS + any extra
        validators: {name: {total, actions: {action: count},
                            last_action, last_ts, last_token}},
      }
    Records are append-ordered, so the LAST occurrence per validator is the most
    recent flip.
    """
    records = read_history()
    by_action: Counter[str] = Counter()
    validators: dict[str, dict[str, Any]] = {}

    for r in records:
        action = r.get("action")
        name = r.get("validator")
        if isinstance(action, str):
            by_action[action] += 1
        if not isinstance(name, str):
            continue
        v = validators.setdefault(name, {"total": 0, "actions": Counter(), "last": None})
        v["total"] += 1
        if isinstance(action, str):
            v["actions"][action] += 1
        v["last"] = r

    # Zero-fill the known buckets so a reader always sees every action category.
    action_dist = {a: by_action.get(a, 0) for a in KNOWN_ACTIONS}
    for a, c in by_action.items():
        if a not in action_dist:
            action_dist[a] = c

    return {
        "total_records": len(records),
        "by_action": action_dist,
        "validators": {
            name: {
                "total": v["total"],
                "actions": dict(v["actions"]),
                "last_action": (v["last"] or {}).get("action"),
                "last_ts": (v["last"] or {}).get("ts"),
                "last_token": (v["last"] or {}).get("token_used"),
            }
            for name, v in sorted(validators.items())
        },
    }
