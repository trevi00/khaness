"""insight_index_pollution_detector — D1 LOCK (debate-1780268884-1di5gw gen 4
sha1 78f09503a8894f02cff45ed53a3ea07d26a5fddf).

Detects sub-second cluster pollution in ~/.claude/memory/insight-index.jsonl
and routes confirmed pollution to lib.insight_index.retract() (D7 LOCK
preserved: append-only retraction record, no hard-delete).

Algorithm
---------
1. Walk insight-index.jsonl entries.
2. Group by bucket = ts_unix_ms // BUCKET_MS (default 250ms).
3. A bucket with >= BUCKET_MIN_COUNT (default 3) entries is a pollution
   candidate.
4. For each candidate, cross-check the entry's correlation_id against the
   filesystem: if NEITHER
     ~/.claude/projects/<correlation_id>/   NOR
     ~/.claude/state/orchestrator/<correlation_id>/
   exists, the entry is confirmed pollution (no live run artifact).
5. Confirmed entries are returned as a retract plan.

Constants exported (D4 single source of truth, S2 fix)
------------------------------------------------------
BUCKET_MS — 250ms default. Widened to 500ms by the measure subcommand if the
            >0.5%-co-fire rule trips on real traffic.
BUCKET_MIN_COUNT — 3 default. Raised to 4 by the measure subcommand if the
            >0.5%-co-fire rule trips.

Ready-flag pattern (atlas debate-1779267594-l1-insight-index.md:58 D17)
----------------------------------------------------------------------
Activation gate: the CLI module (cli/insight_index_pollution_detector.py)
emits state/pollution-threshold-validated.flag via the `measure` subcommand
after analyzing the existing index against the >0.5% rule. D4's --execute
path refuses without the flag via raise SystemExit(3) (distinct from argparse
exit 2 'usage error'). The flag is single-use: D4 deletes it after successful
retract() to force re-measurement on next run. No enable-cron-job token —
invocation is ad-hoc admin, not cron.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Iterable

# D4 single source of truth constants
BUCKET_MS: int = 250
BUCKET_MIN_COUNT: int = 3
COFIRE_RULE_RATIO: float = 0.005  # 0.5%


def _claude_home() -> Path:
    env = os.environ.get("CLAUDE_HOME")
    if env:
        return Path(env)
    up = os.environ.get("USERPROFILE")
    if up:
        return Path(up) / ".claude"
    return Path.home() / ".claude"


def _index_path() -> Path:
    return _claude_home() / "memory" / "insight-index.jsonl"


def _projects_dir() -> Path:
    return _claude_home() / "projects"


def _orchestrator_dir() -> Path:
    return _claude_home() / "state" / "orchestrator"


def _ready_flag_path() -> Path:
    """Fixed-path ready-flag (atlas:58 D17 shape parity; NOT timestamped)."""
    return _claude_home() / "state" / "pollution-threshold-validated.flag"


def _retractions_path(index_path: Path | None = None) -> Path:
    """Sibling of the index file: insight-index-retractions.jsonl."""
    if index_path is not None:
        return index_path.parent / "insight-index-retractions.jsonl"
    return _claude_home() / "memory" / "insight-index-retractions.jsonl"


def _retracted_ids(index_path: Path | None = None) -> set[str]:
    """Already-retracted entry ids (mirrors lib.insight_index._retracted_ids).

    Read-only over the append-only retractions log — NOT a lib.insight_index
    import (the whitelist gates WRITES to the index; reading the sibling
    retractions file is the same read pd already does on the index)."""
    out: set[str] = set()
    p = _retractions_path(index_path)
    if not p.exists():
        return out
    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rid = rec.get("retracted_id")
                if isinstance(rid, str):
                    out.add(rid)
    except OSError:
        return out
    return out


def load_entries(index_path: Path | None = None, *,
                 include_retracted: bool = False) -> list[dict]:
    """Load the ACTIVE insight-index entries (retracted ids excluded by default).

    Retraction-awareness (closes the M29 gap surfaced 2026-06-17): retraction is
    an append-only tombstone in a SIBLING file, so the raw index keeps every
    physical line. Without this filter the burst detector re-confirms
    already-retracted pollution forever — check_pollution never goes QUIET and a
    re-run appends DUPLICATE tombstones (non-idempotent). Excluding retracted ids
    makes detection idempotent and the cron self-quieting. Pass
    include_retracted=True for the raw physical view.
    """
    p = index_path or _index_path()
    if not p.exists():
        return []
    retracted: set[str] = set() if include_retracted else _retracted_ids(index_path)
    out: list[dict] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                if rec.get("id") in retracted:
                    continue
                out.append(rec)
    return out


def cluster_pollution_candidates(
    entries: Iterable[dict],
    *,
    bucket_ms: int = BUCKET_MS,
    bucket_min: int = BUCKET_MIN_COUNT,
) -> list[list[dict]]:
    """Group entries by bucket = ts_unix_ms // bucket_ms; return groups with
    >= bucket_min members. Membership preserves input order within each bucket.
    """
    buckets: dict[int, list[dict]] = defaultdict(list)
    for rec in entries:
        ts = rec.get("ts_unix_ms")
        if not isinstance(ts, int) or ts < 0:
            continue
        buckets[ts // bucket_ms].append(rec)
    return [group for group in buckets.values() if len(group) >= bucket_min]


def confirm_pollution(
    candidates: Iterable[Iterable[dict]],
    *,
    projects_dir: Path | None = None,
    orchestrator_dir: Path | None = None,
) -> list[dict]:
    """For each candidate group, an entry is confirmed pollution iff NEITHER
    projects/<correlation_id>/ NOR state/orchestrator/<correlation_id>/ exists.
    Returns the confirmed entries flattened across groups.
    """
    pdir = projects_dir or _projects_dir()
    odir = orchestrator_dir or _orchestrator_dir()
    confirmed: list[dict] = []
    for group in candidates:
        for rec in group:
            cid = rec.get("correlation_id")
            if not isinstance(cid, str) or not cid:
                continue
            if (pdir / cid).exists() or (odir / cid).exists():
                continue  # live run artifact — keep
            confirmed.append(rec)
    return confirmed


def histogram_inter_event_delta(entries: Iterable[dict]) -> dict[tuple[str, str], list[int]]:
    """Build inter-event Δt distribution grouped by (source_module, event_type).
    Used by the measure subcommand to validate the >0.5%-co-fire rule.
    """
    by_key: dict[tuple[str, str], list[int]] = defaultdict(list)
    sorted_entries = sorted(
        (e for e in entries if isinstance(e.get("ts_unix_ms"), int)),
        key=lambda r: r["ts_unix_ms"],
    )
    last_ts: dict[tuple[str, str], int] = {}
    for rec in sorted_entries:
        sm = rec.get("source_module", "")
        et = rec.get("event_type", "")
        key = (sm if isinstance(sm, str) else "", et if isinstance(et, str) else "")
        ts = rec["ts_unix_ms"]
        prev = last_ts.get(key)
        if prev is not None:
            by_key[key].append(ts - prev)
        last_ts[key] = ts
    return dict(by_key)


def cofire_window_violation_ratio(
    entries: Iterable[dict], *, bucket_ms: int = BUCKET_MS, bucket_min: int = BUCKET_MIN_COUNT
) -> float:
    """Fraction of bucket-sized windows containing >=bucket_min entries from
    the same (source_module, event_type) — used by the measure subcommand.
    """
    by_key: dict[tuple[str, str], list[int]] = defaultdict(list)
    for rec in entries:
        ts = rec.get("ts_unix_ms")
        if not isinstance(ts, int):
            continue
        sm = rec.get("source_module", "")
        et = rec.get("event_type", "")
        if not isinstance(sm, str) or not isinstance(et, str):
            continue
        by_key[(sm, et)].append(ts // bucket_ms)
    total_windows = 0
    violating_windows = 0
    for ts_buckets in by_key.values():
        if not ts_buckets:
            continue
        counts: dict[int, int] = defaultdict(int)
        for b in ts_buckets:
            counts[b] += 1
        total_windows += len(counts)
        violating_windows += sum(1 for n in counts.values() if n >= bucket_min)
    return (violating_windows / total_windows) if total_windows else 0.0


def write_ready_flag(flag_path: Path | None = None) -> None:
    p = flag_path or _ready_flag_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("validated\n", encoding="utf-8")


def delete_ready_flag(flag_path: Path | None = None) -> bool:
    p = flag_path or _ready_flag_path()
    try:
        p.unlink()
        return True
    except FileNotFoundError:
        return False


def ready_flag_exists(flag_path: Path | None = None) -> bool:
    return (flag_path or _ready_flag_path()).exists()
