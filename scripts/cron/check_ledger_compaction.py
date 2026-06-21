#!/usr/bin/env python3
"""check_ledger_compaction — operator-ledger compaction trigger (M29, auto-OK).

Emits state/ledger-compaction-ready.flag when ANY operator-ledger JSONL has grown
enough AND carries enough superseded (re-run) duplicates that compaction would
reclaim meaningful space. Mirrors cron/check_l2_promotion.py: read-only flag
emission, no token, fail-soft exit 0.

Closes the follow-up deferred in lib/operator_ledger.py:54-56. The actual rewrite
(latest-per-task_hash kept, superseded archived) is performed by the token-gated
cron/run_ledger_compaction.py — flag *emission* is auto-OK; flag *consumption* is
`enable-cron-job` gated (CLAUDE.md §Mutation table).

Fire rule (conservative, non-tautological — current ledgers are tiny so this stays
QUIET until a heavily-used project actually accumulates redundant records):
  record_count >= MIN_RECORDS  AND  redundancy_ratio >= MIN_REDUNDANCY

State files written:
  ~/.claude/state/ledger-compaction-ready.flag   (when any ledger qualifies)
  ~/.claude/state/ledger-compaction-check.json   (per-run telemetry)

Run manually:  python -m cron.check_ledger_compaction
Exit code: 0 (always — cron is fail-soft).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.ledger_compaction import redundancy_ratio  # noqa: E402
from lib.paths import STATE_DIR  # noqa: E402


MIN_RECORDS: int = 50          # below this, compaction reclaims too little to bother
MIN_REDUNDANCY: float = 0.25   # >=25% superseded duplicates → worth compacting

LEDGER_ROOT: Path = STATE_DIR / "operator-ledger"
FLAG_PATH: Path = STATE_DIR / "ledger-compaction-ready.flag"
CHECK_STATE_PATH: Path = STATE_DIR / "ledger-compaction-check.json"


def _read_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except OSError:
        return out
    return out


def _iter_ledger_files(root: Path):
    """Active <agent_type>.jsonl ledgers (skip _HEADER.txt + .compacted.* archives)."""
    if not root.is_dir():
        return
    for proj_dir in sorted(root.iterdir()):
        if not proj_dir.is_dir():
            continue
        for f in sorted(proj_dir.glob("*.jsonl")):
            if ".compacted." in f.name:
                continue
            yield f


def evaluate() -> dict:
    """One evaluation. Writes check.json; writes the flag iff any ledger qualifies."""
    candidates: list[dict] = []
    scanned = 0
    for ledger in _iter_ledger_files(LEDGER_ROOT):
        records = _read_jsonl(ledger)
        scanned += 1
        count = len(records)
        if count < MIN_RECORDS:
            continue
        ratio = redundancy_ratio(records)
        if ratio >= MIN_REDUNDANCY:
            candidates.append({
                "path": str(ledger),
                "record_count": count,
                "redundancy_ratio": round(ratio, 4),
                "reclaimable": int(round(ratio * count)),
            })

    now_ms = int(time.time() * 1000)
    fired = bool(candidates)
    state = {
        "ts_ms": now_ms,
        "ledgers_scanned": scanned,
        "min_records": MIN_RECORDS,
        "min_redundancy": MIN_REDUNDANCY,
        "candidates": candidates,
        "fired": fired,
    }
    try:
        CHECK_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CHECK_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    if fired:
        try:
            FLAG_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
    return state


def main() -> int:
    state = evaluate()
    if state["fired"]:
        n = len(state["candidates"])
        total = sum(c["reclaimable"] for c in state["candidates"])
        print(f"[FIRE] ledger-compaction: {n} ledger(s) compactable, ~{total} records reclaimable "
              f"(scanned {state['ledgers_scanned']})")
    else:
        print(f"[QUIET] ledger-compaction: nothing to compact (scanned {state['ledgers_scanned']}, "
              f"threshold {MIN_RECORDS} records & {MIN_REDUNDANCY:.0%} redundancy)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
