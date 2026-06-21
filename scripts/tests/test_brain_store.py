#!/usr/bin/env python3
"""Unit tests for lib/brain_store.py — core-brain learned-state snapshot/restore.

HARD PREREQUISITE (debate-1781359722-f16550, converged gen-2, ontology
991340aa...). Pins the locked invariants as executable assertions BEFORE impl:
  INV-restore: union-by-id; live-absent seeds; live-present NO-OP; --merge additive;
    retraction sidecars unioned + applied (NO resurrection); graduation re-validated.
  INV-save: operator-invoked; accumulating union (committed ∪ live); staging copy +
    JSONDecodeError-skip torn-line defense.
  D3 branch (b): schema_version-pinned raw-read, hard-fail on mismatch (no lib import,
    no LOCK reader-set amendment).
  INV-layout: SINGLE canonical brain/{l1,l2,graduation}/.

Each test isolates CLAUDE_HOME to a fresh temp dir (set BEFORE imports so
lib.paths/graduation resolve there). Run: python tests/test_brain_store.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_PASS = 0
_FAIL = 0


def _ok(msg: str) -> None:
    global _PASS
    _PASS += 1
    print(f"  [OK]   {msg}")


def _fail(msg: str) -> None:
    global _FAIL
    _FAIL += 1
    print(f"  [FAIL] {msg}")


def _check(cond: bool, msg: str) -> None:
    _ok(msg) if cond else _fail(msg)


def _fresh_home() -> Path:
    """New temp CLAUDE_HOME with memory/ + state/; set env BEFORE brain_store import."""
    home = Path(tempfile.mkdtemp(prefix="brain-test-"))
    (home / "memory").mkdir(parents=True, exist_ok=True)
    (home / "state").mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_HOME"] = str(home)
    return home


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _l1_entry(eid: str, summary: str = "s") -> dict:
    return {"id": eid, "schema_version": "1", "ts_unix_ms": 1, "event_type": "wonder",
            "summary": summary, "correlation_id": "c", "source_module": "m",
            "axis": None, "tags": [], "body_ref": None}


def _import_brain_store():
    """Import fresh under the current CLAUDE_HOME. Purge ALL lib.* modules so
    import-time path constants (lib.paths.STATE_DIR, frozen at first import and
    re-bound by lib.graduation) resolve against THIS test's temp CLAUDE_HOME.
    In real run_units each test is its own subprocess, so this purge is only a
    same-process standalone-run concern."""
    for m in list(sys.modules):
        if m == "lib" or m.startswith("lib."):
            del sys.modules[m]
    import lib.brain_store as bs
    return bs


# ── Scenarios ────────────────────────────────────────────────────────────────

def t_roundtrip() -> None:
    home = _fresh_home()
    bs = _import_brain_store()
    idx = home / "memory" / "insight-index.jsonl"
    _write_jsonl(idx, [_l1_entry("wonder-1-aaa"), _l1_entry("wonder-2-bbb")])
    bs.save()
    brain_idx = home / "brain" / "l1" / "insight-index.jsonl"
    _check(brain_idx.is_file(), "save: brain/l1/insight-index.jsonl created")
    _check(len(_read_jsonl(brain_idx)) == 2, "save: 2 L1 entries snapshotted")
    # wipe live, restore (seed-on-absent)
    idx.unlink()
    bs.restore()
    ids = {e["id"] for e in _read_jsonl(idx)}
    _check(ids == {"wonder-1-aaa", "wonder-2-bbb"}, "restore: seeds live from brain when absent")


def t_accumulate() -> None:
    home = _fresh_home()
    bs = _import_brain_store()
    idx = home / "memory" / "insight-index.jsonl"
    # machine A already committed a1 into brain/
    _write_jsonl(home / "brain" / "l1" / "insight-index.jsonl", [_l1_entry("wonder-A-111", "A")])
    # machine B live has b1
    _write_jsonl(idx, [_l1_entry("wonder-B-222", "B")])
    bs.save()  # accumulate: committed ∪ live
    ids = {e["id"] for e in _read_jsonl(home / "brain" / "l1" / "insight-index.jsonl")}
    _check(ids == {"wonder-A-111", "wonder-B-222"},
           "save: accumulating union (B's live unions into A's committed, no overwrite)")


def t_l1_concat_no_semantic_dedup() -> None:
    home = _fresh_home()
    bs = _import_brain_store()
    # two DISTINCT random ids, same summary content (L1 ids are random, not content-hash)
    _write_jsonl(home / "brain" / "l1" / "insight-index.jsonl", [_l1_entry("wonder-1-aaa", "same")])
    _write_jsonl(home / "memory" / "insight-index.jsonl", [_l1_entry("wonder-1-bbb", "same")])
    bs.save()
    rows = _read_jsonl(home / "brain" / "l1" / "insight-index.jsonl")
    _check(len(rows) == 2, "L1 union-by-id keeps both distinct-id rows (no semantic dedup, INV)")


def t_retraction_no_resurrection() -> None:
    home = _fresh_home()
    bs = _import_brain_store()
    # brain (machine A): index has X + Y, retractions has X
    _write_jsonl(home / "brain" / "l1" / "insight-index.jsonl",
                 [_l1_entry("wonder-X-111"), _l1_entry("wonder-Y-222")])
    _write_jsonl(home / "brain" / "l1" / "insight-index-retractions.jsonl",
                 [{"retracted_id": "wonder-X-111", "reason": "A-retracted", "ts_unix_ms": 9}])
    # live (machine B): index has X live, NO retraction
    _write_jsonl(home / "memory" / "insight-index.jsonl", [_l1_entry("wonder-X-111")])
    bs.restore(merge=True)
    # after restore the live retraction sidecar MUST contain X (A's retraction
    # propagated). We assert brain_store's OUTPUT (the unioned sidecar) — NOT
    # query()'s filtering, which is insight_index's own contract (and importing
    # lib.insight_index here would violate the [^l1-active] importer whitelist;
    # brain_store is deliberately orthogonal to the lib, D3 branch b).
    retr = {r["retracted_id"] for r in _read_jsonl(home / "memory" / "insight-index-retractions.jsonl")}
    idx = {e["id"] for e in _read_jsonl(home / "memory" / "insight-index.jsonl")}
    _check("wonder-X-111" in retr,
           "restore --merge: retraction sidecars unioned -> X retracted everywhere (NO resurrection)")
    _check("wonder-Y-222" in idx and "wonder-Y-222" not in retr,
           "restore --merge: Y present in index and NOT retracted (only X suppressed)")


def t_retraction_union_on_noop_path() -> None:
    # The invariant: retractions union EVEN WHEN the index is NO-OP (merge=False,
    # live present). A retraction on machine A must suppress everywhere without
    # requiring --merge. (Mutation-gap closer: distinct from the merge=True case.)
    home = _fresh_home()
    bs = _import_brain_store()
    _write_jsonl(home / "brain" / "l1" / "insight-index.jsonl", [_l1_entry("wonder-X-111")])
    _write_jsonl(home / "brain" / "l1" / "insight-index-retractions.jsonl",
                 [{"retracted_id": "wonder-X-111", "reason": "A-retracted", "ts_unix_ms": 9}])
    _write_jsonl(home / "memory" / "insight-index.jsonl", [_l1_entry("wonder-X-111")])
    # Live retraction file EXISTS but lacks X (a DIFFERENT retraction) — so this
    # exercises the UNION path, not the seed-on-absent path; the union of X must
    # still land even WITHOUT --merge.
    _write_jsonl(home / "memory" / "insight-index-retractions.jsonl",
                 [{"retracted_id": "wonder-Z-999", "reason": "live-other", "ts_unix_ms": 7}])
    bs.restore(merge=False)
    idx_ids = {e["id"] for e in _read_jsonl(home / "memory" / "insight-index.jsonl")}
    retr = {r["retracted_id"] for r in _read_jsonl(home / "memory" / "insight-index-retractions.jsonl")}
    _check(idx_ids == {"wonder-X-111"}, "restore (no --merge): index NO-OP (live index untouched)")
    _check("wonder-X-111" in retr,
           "restore (no --merge): retraction STILL unioned -> X suppressed without --merge (resurrection guard)")


def t_live_present_noop() -> None:
    home = _fresh_home()
    bs = _import_brain_store()
    idx = home / "memory" / "insight-index.jsonl"
    _write_jsonl(home / "brain" / "l1" / "insight-index.jsonl", [_l1_entry("wonder-brain-1")])
    _write_jsonl(idx, [_l1_entry("wonder-live-1")])
    bs.restore(merge=False)  # live present, not merge -> NO-OP (live wins)
    ids = {e["id"] for e in _read_jsonl(idx)}
    _check(ids == {"wonder-live-1"}, "restore (no --merge): live present -> NO-OP, live untouched")


def t_schema_pin_hardfail() -> None:
    home = _fresh_home()
    bs = _import_brain_store()
    _write_jsonl(home / "memory" / "insight-index.jsonl",
                 [{"id": "wonder-1-aaa", "schema_version": "999", "ts_unix_ms": 1}])
    raised = False
    try:
        bs.save()
    except bs.BrainSchemaError:
        raised = True
    _check(raised, "schema-pin: save hard-fails on schema_version mismatch (D3 branch b, not silent)")


def t_torn_line_skip() -> None:
    home = _fresh_home()
    bs = _import_brain_store()
    idx = home / "memory" / "insight-index.jsonl"
    with idx.open("w", encoding="utf-8") as f:
        f.write(json.dumps(_l1_entry("wonder-good-1")) + "\n")
        f.write('{"id": "wonder-torn-2", "schema_versio')  # torn final line, no newline
    bs.save()  # must not crash; torn line skipped
    ids = {e["id"] for e in _read_jsonl(home / "brain" / "l1" / "insight-index.jsonl")}
    _check(ids == {"wonder-good-1"}, "torn-line: JSONDecodeError-skip keeps good record, drops torn (no crash)")


def t_graduation_restore_streak() -> None:
    home = _fresh_home()
    bs = _import_brain_store()
    # brain graduation: validator V streak 10 (ready); live: V streak 3
    _write_jsonl_json(home / "brain" / "graduation" / "graduation-state.json",
                      {"validators": {"V": {"consecutive_clean": 10, "last_scan_epoch": 5000.0}}})
    _write_jsonl_json(home / "state" / "graduation-state.json",
                      {"validators": {"V": {"consecutive_clean": 3, "last_scan_epoch": 8000.0}}})
    bs.restore(merge=True)
    live = json.loads((home / "state" / "graduation-state.json").read_text(encoding="utf-8"))
    v = live["validators"]["V"]
    _check(v["consecutive_clean"] == 10, "graduation restore: max streak (10) written back to state/")
    _check(float(v["last_scan_epoch"]) == 0.0,
           "graduation restore: raised streak resets last_scan_epoch=0 -> forces re-validate before flip")


def _write_jsonl_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def t_status() -> None:
    home = _fresh_home()
    bs = _import_brain_store()
    _write_jsonl(home / "memory" / "insight-index.jsonl", [_l1_entry("wonder-1-aaa")])
    st = bs.status()
    _check(isinstance(st, dict) and "l1" in st, "status: returns per-layer dict")


def main() -> int:
    print("=== brain_store unit tests ===")
    for fn in (t_roundtrip, t_accumulate, t_l1_concat_no_semantic_dedup,
               t_retraction_no_resurrection, t_retraction_union_on_noop_path,
               t_live_present_noop, t_schema_pin_hardfail,
               t_torn_line_skip, t_graduation_restore_streak, t_status):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            _fail(f"{fn.__name__}: raised {type(e).__name__}: {e}")
    print(f"\n=== {_PASS} passed, {_FAIL} failed ===")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
