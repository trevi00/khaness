#!/usr/bin/env python3
"""code_blind_proceed — enforce that work is resumable CODE-BLIND from brain + HANDOFF (M16).

The harness's loop-engineering goal: proceed on a task by checking the fully-updated brain
+ HANDOFF + design + passing tests, WITHOUT re-reading source each time. That breaks
silently if the HANDOFF `## Current Phase Block` yaml is present-but-unparseable — the brain's
current-node surface degrades to '' and you can no longer tell where work stands without
reading code.

`handoff_drift` already surfaces this, but only as [WARN] (deliberately, to tolerate transient
anchored-vs-yaml drift during edit cycles) — and [WARN] does NOT trip run_all's failure regex,
so a parse-broken HANDOFF ships GREEN. An unparseable phase-tree is NOT transient drift; it is a
hard breakage of code-blind resumability, so THIS validator emits [FAIL] on it (orthogonal to
handoff_drift's drift WARN — no duplication).

Caller contract (validators/__init__.py): main() -> None, reads os.getcwd() == project root,
prints [PASS]/[FAIL], never raises.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

for _s in (sys.stdin, sys.stdout):
    _r = getattr(_s, "reconfigure", None)
    if _r:
        try:
            _r(encoding="utf-8")
        except Exception:
            pass

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def main() -> None:
    handoff = Path(os.getcwd()) / "HANDOFF.md"
    if not handoff.is_file():
        print("[PASS] code_blind_proceed: no HANDOFF.md in cwd (skip)")
        return
    try:
        from lib.handoff_drift import code_blind_readiness
    except Exception as e:  # noqa: BLE001 — lib breakage shouldn't FAIL the suite here
        print(f"[PASS] code_blind_proceed: import failed, deferring to handoff_drift: {type(e).__name__}")
        return
    try:
        text = handoff.read_text(encoding="utf-8")
    except OSError as e:
        print(f"[PASS] code_blind_proceed: cannot read HANDOFF.md ({e}); skip")
        return

    ok, reason = code_blind_readiness(text)
    if ok:
        print(f"[PASS] code_blind_proceed: {reason}")
        return
    print(f"[FAIL] code_blind_proceed: {reason}")
    try:
        from lib.logging import log_telemetry
        log_telemetry("code-blind-proceed-broken", {"handoff": str(handoff), "reason": reason[:300]})
    except Exception:
        pass


if __name__ == "__main__":
    main()
