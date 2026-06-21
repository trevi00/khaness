#!/usr/bin/env python3
"""brain_store — core-brain learned-state snapshot/restore (L0-L4 durability).

Persists the harness's LEARNED runtime state (currently gitignored, local-only,
lost on machine death) into a tracked `brain/` snapshot folder so it survives
push and rehydrates on a fresh machine. Design locked by
debate-1781359722-f16550 (converged gen-2, ontology 991340aa...).

Scope (INV-scope): L1 insight-index + L2 global-facts + graduation streak ONLY.
NOT L4 projects/ (639MB transcripts), NOT skill-candidates (inert until activated).

Layout (INV-layout) — SINGLE canonical tree, no per-machine namespace:
  brain/l1/insight-index.jsonl, insight-index-retractions.jsonl
  brain/l2/global-facts.jsonl, global-facts-retractions.jsonl, global-facts-evidence.jsonl
  brain/graduation/graduation-state.json

Reading contract (D3 branch b — schema_version-pinned raw read): this module
reads the live JSONL files DIRECTLY (it does NOT import lib.insight_index /
lib.l2_facts, so it is neither in their LOCK reader/writer sets nor the
[^l1-active] forbidden importer set). The format coupling is GUARDED, not silent:
every record carrying a `schema_version` is asserted == SCHEMA_VERSION; a mismatch
raises BrainSchemaError (hard-fail, NOT silent) so a future format bump is caught
loudly. Torn final lines (a concurrent live appender mid-write) are skipped via
the same per-line JSONDecodeError tolerance the lib readers use.

Reconcile contract (INV-restore): union-by-id; live-absent seeds; live-present
NO-OP unless merge=True; retraction sidecars unioned so a retraction on ANY
machine suppresses the insight everywhere (no resurrection). L1 ids are NOT
content-addressed (event_type-ts-6hex random) so L1 union is concat-by-distinct-id
(append-only by design; growth bounded by the existing insight-index compaction).

Save contract (INV-save, amended debate-1781431026-af5f83 / ontology 32808a52c893):
invoked by the operator CLI (cli/brain_snapshot) AND by a THROTTLED Stop-hook
auto-save (≤ once / 900s, gated on brain divergence; lib.work_unit_store). Still
NO SessionStart auto-tick — that was the specific path INV-save forbade for racing
the 3 unlocked live appenders, and it stays forbidden; the Stop tick fires after
the turn's appenders quiesce. The save/append race is KEPT and only TOLERATED (C4),
NEVER claimed structurally prevented. Accumulates committed ∪ live; NO auto-commit
(the operator commits brain/ in their normal push flow, C5). Cross-machine
accumulation happens HERE: machine B's save unions B's live into the brain/ that
already holds machine A's committed insights. The .gitattributes `brain/**
merge=binary` guard makes git REFUSE to text-merge brain/ on pull, forcing
reconcile back through save.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

SCHEMA_VERSION = "1"  # L1/L2 record schema this module is pinned to (D3 branch b).


class BrainSchemaError(RuntimeError):
    """A live/snapshot record's schema_version != SCHEMA_VERSION — the JSONL format
    drifted from what brain_store is pinned to. Hard-fail (never silent) so the
    operator updates brain_store rather than persisting mis-parsed state."""


# ── paths (resolve CLAUDE_HOME at CALL time, matching insight_index._claude_home
#    so run_units CLAUDE_HOME isolation + per-machine env overrides both work) ──

def _claude_home() -> Path:
    env = os.environ.get("CLAUDE_HOME")
    if env:
        return Path(env)
    up = os.environ.get("USERPROFILE")
    if up:
        return Path(up) / ".claude"
    return Path.home() / ".claude"


def _memory_dir() -> Path:
    return _claude_home() / "memory"


def _state_dir() -> Path:
    return _claude_home() / "state"


def _brain_dir() -> Path:
    return _claude_home() / "brain"


# ── layer manifest: (live_path, brain_path, union_key | None for json blobs) ──
# union_key=None marks a non-JSONL file handled specially (graduation json).

def _l1_layer() -> list[tuple[Path, Path, str]]:
    m, b = _memory_dir(), _brain_dir() / "l1"
    return [
        (m / "insight-index.jsonl", b / "insight-index.jsonl", "id"),
        (m / "insight-index-retractions.jsonl", b / "insight-index-retractions.jsonl", "retracted_id"),
    ]


def _l2_layer() -> list[tuple[Path, Path, str]]:
    m, b = _memory_dir(), _brain_dir() / "l2"
    return [
        (m / "global-facts.jsonl", b / "global-facts.jsonl", "id"),
        (m / "global-facts-retractions.jsonl", b / "global-facts-retractions.jsonl", "retracted_id"),
        (m / "global-facts-evidence.jsonl", b / "global-facts-evidence.jsonl", "__line__"),
    ]


def _jsonl_layers() -> list[tuple[Path, Path, str]]:
    return _l1_layer() + _l2_layer()


def _graduation_paths() -> tuple[Path, Path]:
    return (_state_dir() / "graduation-state.json", _brain_dir() / "graduation" / "graduation-state.json")


# ── schema-pinned raw JSONL read (torn-line skip + hard-fail on version drift) ──

def _read_jsonl_pinned(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            # Torn final line from a concurrent appender — skip (the next save
            # re-unions the dropped record). Same tolerance the lib readers use.
            continue
        if not isinstance(rec, dict):
            continue
        sv = rec.get("schema_version")
        if sv is not None and str(sv) != SCHEMA_VERSION:
            raise BrainSchemaError(
                f"{path.name}: schema_version={sv!r} != pinned {SCHEMA_VERSION!r} "
                f"— update lib/brain_store.py (D3 branch b hard-fail)."
            )
        out.append(rec)
    return out


def _write_jsonl_sorted(path: Path, records: list[dict], union_key: str) -> int:
    """Write records as deterministic JSONL (sorted) for stable, minimal diffs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if union_key == "__line__":
        # whole-line dedup (no stable id field, e.g. L2 evidence edges)
        seen: set[str] = set()
        uniq: list[str] = []
        for r in records:
            s = json.dumps(r, ensure_ascii=False, sort_keys=True)
            if s not in seen:
                seen.add(s)
                uniq.append(s)
        uniq.sort()
        body = "\n".join(uniq)
    else:
        body = "\n".join(
            json.dumps(r, ensure_ascii=False, sort_keys=True)
            for r in sorted(records, key=lambda r: (str(r.get("ts_unix_ms") or 0), str(r.get(union_key) or "")))
        )
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(body + ("\n" if body else ""), encoding="utf-8")
    tmp.replace(path)
    return len(records) if union_key == "__line__" else len({r.get(union_key) for r in records})


def _union_by_key(base: list[dict], overlay: list[dict], union_key: str) -> list[dict]:
    """Union two record lists. union_key=='__line__' → set-union of whole lines;
    else dedup by key with overlay winning on collision (content-hash ids ⇒ same
    key == same content for L2; for L1 random ids, collision is effectively never,
    so this is concat-of-distinct-ids — INV: no semantic dedup for L1)."""
    if union_key == "__line__":
        seen: set[str] = set()
        out: list[dict] = []
        for r in base + overlay:
            s = json.dumps(r, ensure_ascii=False, sort_keys=True)
            if s not in seen:
                seen.add(s)
                out.append(r)
        return out
    merged: dict[str, dict] = {}
    for r in base:
        k = r.get(union_key)
        if k is not None:
            merged[str(k)] = r
    for r in overlay:  # overlay (live) wins on collision
        k = r.get(union_key)
        if k is not None:
            merged[str(k)] = r
    return list(merged.values())


# ── public API ────────────────────────────────────────────────────────────────

def save() -> dict[str, Any]:
    """Snapshot live learned-state into brain/, ACCUMULATING with the existing
    committed snapshot (committed ∪ live). No git commit (C5). Invoked by the
    operator CLI (cli/brain_snapshot) AND, since debate-1781431026-af5f83, by the
    throttled Stop-hook auto-save (lib.work_unit_store.maybe_autosave/force_autosave).

    Reads live via a tmp staging copy (shutil.copy2) which REDUCES but does NOT
    eliminate overlap with a concurrent live appender — copy2 is non-atomic, so the
    race is TOLERATED, not structurally prevented (C4/INV-save-race). A line torn
    mid-append is skipped by _read_jsonl_pinned and re-unioned on the next save. No
    lock is taken.
    """
    summary: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="brain-save-") as td:
        stage = Path(td)
        for live, brain, key in _jsonl_layers():
            staged = stage / brain.name
            if live.is_file():
                try:
                    shutil.copy2(live, staged)
                except OSError:
                    staged = live  # fall back to direct read; pin-read still skips torn lines
            live_recs = _read_jsonl_pinned(staged if staged.exists() else live)
            committed = _read_jsonl_pinned(brain)
            unioned = _union_by_key(committed, live_recs, key)
            _write_jsonl_sorted(brain, unioned, key)
            summary[brain.parent.name + "/" + brain.name] = len(unioned)
    # graduation: snapshot the live state json into brain/ (accumulate max-streak)
    live_g, brain_g = _graduation_paths()
    summary["graduation"] = _save_graduation(live_g, brain_g)
    return summary


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {"validators": {}}
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {"validators": {}}
    except (OSError, json.JSONDecodeError):
        return {"validators": {}}


def _save_graduation(live_g: Path, brain_g: Path) -> dict[str, Any]:
    """brain graduation = per-validator max(committed, live) streak + max epoch."""
    live = _load_json(live_g).get("validators") or {}
    committed = _load_json(brain_g).get("validators") or {}
    names = set(live) | set(committed)
    merged: dict[str, Any] = {}
    for n in names:
        le = live.get(n) if isinstance(live.get(n), dict) else {}
        ce = committed.get(n) if isinstance(committed.get(n), dict) else {}
        merged[n] = {
            "consecutive_clean": max(int(le.get("consecutive_clean") or 0), int(ce.get("consecutive_clean") or 0)),
            "last_scan_epoch": max(float(le.get("last_scan_epoch") or 0.0), float(ce.get("last_scan_epoch") or 0.0)),
        }
    brain_g.parent.mkdir(parents=True, exist_ok=True)
    tmp = brain_g.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"validators": merged}, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(brain_g)
    return {"validators": len(merged)}


def restore(merge: bool = False) -> dict[str, Any]:
    """Rehydrate live learned-state from brain/.

    Per JSONL layer: if live ABSENT → seed (write brain verbatim, deduped).
    If live PRESENT and not merge → NO-OP (live wins, never clobbered).
    If merge → additive union-by-id (committed ∪ live). RETRACTION SIDECARS are
    ALWAYS unioned (even when index is NO-OP), so a retraction on any machine
    propagates and query() suppresses the insight everywhere — no resurrection.
    Graduation goes through graduation.restore_streak (write-back to state/ +
    forced re-validation on raised streaks).
    """
    summary: dict[str, Any] = {}
    retraction_keys = {"retracted_id"}
    for live, brain, key in _jsonl_layers():
        committed = _read_jsonl_pinned(brain)
        if not committed:
            summary[brain.name] = "no-snapshot"
            continue
        is_retraction = key in retraction_keys
        if not live.is_file():
            _write_jsonl_sorted(live, committed, key)  # seed
            summary[brain.name] = f"seeded:{len(committed)}"
        elif merge or is_retraction:
            # retractions ALWAYS union (suppress-everywhere); index unions only on --merge
            live_recs = _read_jsonl_pinned(live)
            unioned = _union_by_key(committed, live_recs, key)
            _write_jsonl_sorted(live, unioned, key)
            summary[brain.name] = f"{'merged' if merge else 'retraction-union'}:{len(unioned)}"
        else:
            summary[brain.name] = "noop-live-present"
    # graduation write-back (the ONLY path into state/graduation-state.json)
    _, brain_g = _graduation_paths()
    if brain_g.is_file():
        from . import graduation
        summary["graduation"] = graduation.restore_streak(_load_json(brain_g))
    return summary


def status() -> dict[str, Any]:
    """Per-layer live-vs-snapshot counts + divergence (live ids absent from brain).
    Also surfaces the graduation restore-target git-invisibility (D6/INV-scope)."""
    out: dict[str, Any] = {}
    for layer_name, layers in (("l1", _l1_layer()), ("l2", _l2_layer())):
        layer_stat: dict[str, Any] = {}
        for live, brain, key in layers:
            live_recs = _read_jsonl_pinned(live) if live.is_file() else []
            brain_recs = _read_jsonl_pinned(brain) if brain.is_file() else []
            if key == "__line__":
                diverged = 0
            else:
                brain_ids = {str(r.get(key)) for r in brain_recs}
                diverged = sum(1 for r in live_recs if str(r.get(key)) not in brain_ids)
            layer_stat[brain.name] = {"live": len(live_recs), "brain": len(brain_recs), "live_not_in_brain": diverged}
        out[layer_name] = layer_stat
    live_g, brain_g = _graduation_paths()
    out["graduation"] = {
        "live_validators": len(_load_json(live_g).get("validators") or {}),
        "brain_validators": len(_load_json(brain_g).get("validators") or {}),
        "note": "restore-target state/graduation-state.json is gitignored (git-invisible); "
                "restored streak is re-validated against a live scan at flip, never authoritative alone.",
    }
    out["note"] = ("brain/l1 is append-only/concat-by-id (L1 ids are not content-addressed) "
                   "and grows monotonically — rely on the existing insight-index compaction. "
                   "save/restore are operator-invoked; recovery on a fresh machine is manual "
                   "(`brain_snapshot restore`).")
    return out
