#!/usr/bin/env python3
"""threshold_registry_locked — compile-time guard that no LOCKED invariant is tunable (M22 D1).

The compile-time half of D1 enforcement (the runtime half is the ValueError raised inside
threshold_proposer.propose_threshold_changes via assert_locked_disjoint). Per gen-1 Critic
B4, an import-time `assert` is the WRONG enforcement (stripped under -O; an ImportError at
module load is uncatchable by a hook's try/except → silently empty <activated-skills>). This
validator runs in the run_all walk and FAILS the boolean validator gate if any
threshold_registry.REGISTRY entry's qualified name is in LOCKED_DENY.

Caller contract (validators/__init__.py): main() -> None, prints [PASS]/[FAIL] to stdout,
never raises (failures surfaced via stdout marker + telemetry).
"""
from __future__ import annotations

import sys
from pathlib import Path

for _stream in (sys.stdout,):
    _reconf = getattr(_stream, "reconfigure", None)
    if _reconf:
        try:
            _reconf(encoding="utf-8")
        except Exception:
            pass

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def main() -> None:
    try:
        from lib.calibration import threshold_registry as reg
    except Exception as exc:  # noqa: BLE001 — import failure is itself a FAIL signal
        print(f"[FAIL] threshold_registry_locked — cannot import registry: {exc!r}")
        return

    registered = {e.qualified() for e in reg.REGISTRY.values()}
    overlap = sorted(registered & reg.LOCKED_DENY)
    if overlap:
        for q in overlap:
            print(f"[FAIL] threshold_registry_locked — LOCKED invariant is registered as tunable: {q}")
        try:
            from lib.logging import log_telemetry
            log_telemetry("threshold-registry-locked-violations",
                          {"event": "locked_tunable", "overlap": overlap})
        except Exception:
            pass
        return

    print(
        f"[PASS] threshold_registry_locked — {len(registered)} tunables disjoint from "
        f"{len(reg.LOCKED_DENY)} LOCKED invariants"
    )


if __name__ == "__main__":
    main()
