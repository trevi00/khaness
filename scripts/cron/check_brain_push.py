#!/usr/bin/env python3
"""check_brain_push — brain-durability safety-net trigger (M29 + M-brain-handoff D1,
auto-OK).

Emits state/brain-push-ready.flag when brain learning is not yet DURABLE on the
remote — fired on EITHER gap:
  ① live→file: live L1/L2 records not yet in the brain/ snapshot (a missed Stop tick).
  ②③ file→remote: brain/ not yet auto-pushed to origin/brain-snapshots
     (lib.brain_git_status.at_risk) — the gap that survives the Stop-hook auto-save,
     which zeroes ① by writing the file but leaves it only on the local disk.
Read-only (brain_store.status() + git read), no token, fail-soft exit 0. The
token-gated run_brain_push then force-saves (①) AND auto-pushes to brain-snapshots (②③).

Why this is NOT redundant with the Stop-hook auto-save (the honest scope, per the
M29 grounding workflow R4 + lib/brain_store.py:32-43):
  brain_store.save() is already invoked by the THROTTLED Stop-hook (<=once/900s,
  gated on divergence). This checker is the SAFETY NET for when that Stop tick was
  MISSED — a crash / kill / abnormal exit that skipped the Stop hook leaves live
  learning un-snapshotted. A scheduled read-only divergence check catches that case
  and surfaces it. It deliberately does NOT call save() (that is the Stop-hook's job,
  fired after appenders quiesce; a cron save() would race the live appenders that
  INV-save forbids — lib/brain_store.py C4/INV-save-race).

State files written:
  ~/.claude/state/brain-push-ready.flag   (when divergence > 0)
  ~/.claude/state/brain-push-check.json     (per-run telemetry)

Run manually:  python -m cron.check_brain_push
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

from lib.paths import STATE_DIR  # noqa: E402

FLAG_PATH: Path = STATE_DIR / "brain-push-ready.flag"
CHECK_STATE_PATH: Path = STATE_DIR / "brain-push-check.json"


def _total_divergence(status: dict) -> int:
    """Sum live_not_in_brain across all L1+L2 JSONL layers (records that would be lost)."""
    total = 0
    for layer in ("l1", "l2"):
        layer_stat = status.get(layer) or {}
        if not isinstance(layer_stat, dict):
            continue
        for entry in layer_stat.values():
            if isinstance(entry, dict):
                v = entry.get("live_not_in_brain")
                if isinstance(v, int) and v > 0:
                    total += v
    return total


def evaluate() -> dict:
    """One evaluation. Writes check.json; writes the flag iff divergence > 0."""
    from lib import brain_store
    try:
        status = brain_store.status()
    except Exception as e:  # noqa: BLE001 — fail-soft (schema drift etc. → QUIET, never crash cron)
        status = {"error": f"{type(e).__name__}: {e}"}

    divergence = _total_divergence(status) if "error" not in status else 0
    # Also fire on the FILE→REMOTE gap (②③), not just live→file (①): the Stop-hook
    # auto-save zeroes ① by writing brain/ files, but those files are not durable until
    # auto-pushed to brain-snapshots. brain_git_status.at_risk is True iff a live brain
    # record id is not yet on origin/brain-snapshots (or, pre-branch, brain/ is
    # uncommitted/unpushed). Without this, run_brain_push's autopush would almost never
    # fire (M-brain-handoff D1 wiring). Fail-soft → False.
    try:
        from lib.brain_git_status import at_risk as _push_at_risk
        push_gap = bool(_push_at_risk())
    except Exception:  # noqa: BLE001
        push_gap = False
    now_ms = int(time.time() * 1000)
    fired = divergence > 0 or push_gap
    state = {
        "ts_ms": now_ms,
        "live_not_in_brain_total": divergence,
        "push_gap": push_gap,
        "status": status,
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
        why = []
        if state["live_not_in_brain_total"] > 0:
            why.append(f"{state['live_not_in_brain_total']} live record(s) not in brain/ (unsaved)")
        if state.get("push_gap"):
            why.append("brain/ not yet on origin/brain-snapshots (unpushed)")
        print(f"[FIRE] brain-push: {'; '.join(why)} — token-gated run_brain_push will save + auto-push.")
    else:
        print("[QUIET] brain-push: live learned-state saved AND on origin/brain-snapshots (durable).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
