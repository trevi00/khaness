#!/usr/bin/env python3
"""HANDOFF.md phase-tree drift validator — autonomous closure 4th surveillance.

Surveillance surfaces (for HANDOFF.md drift):
  1. PostToolUse — Edit/Write hook (handlers/post_tool/reviewer.py)
  2. SessionStart — `<harness-status>` block (handlers/session/init.py)
  3. harness_health — `[Phase-tree]` dashboard (cli/harness_health.py)
  4. validators registry — this module (run on every regression)

This validator emits [WARN], NOT [FAIL], when drift is detected. Drift is
expected during edit cycles (yaml block changes before --in-place rerun);
failing run_all on transient drift would block the development loop.
[WARN] doesn't trigger run_all's silent-failure regex (matches only
[FAIL]/[ERROR]/Traceback), so the suite still reports rc=0.

Caller contract (per validators/__init__.py):
  - main() -> None, no args
  - reads os.getcwd() == project root
  - prints [PASS]/[WARN] lines; never raises

Decision lattice:
  no HANDOFF.md           -> [PASS] handoff_drift: no HANDOFF.md (skip)
  HANDOFF without yaml    -> [PASS] handoff_drift: no '## Current Phase Block' (skip)
  yaml parse error        -> [WARN] handoff_drift: yaml parse error: ...
  yaml ok, no anchor      -> [PASS] handoff_drift: anchor block absent (opt-out)
  yaml ok, anchor in_sync -> [PASS] handoff_drift: anchored block matches yaml
  yaml ok, anchor drift   -> [WARN] handoff_drift: drift detected — fix: ...
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def main() -> None:
    cwd = Path(os.getcwd())
    handoff = cwd / "HANDOFF.md"
    if not handoff.is_file():
        print("[PASS] handoff_drift: no HANDOFF.md in cwd (skip)")
        return

    try:
        from lib.handoff_drift import (
            check_drift,
            is_anchor_present,
            render_from_handoff,
        )
    except Exception as e:
        # Fail-soft: if lib import fails, validator emits WARN and exits cleanly.
        # We do NOT want to FAIL run_all on a missing dependency — that would
        # mask the real issue (lib breakage).
        print(f"[WARN] handoff_drift: import failed: {type(e).__name__}: {e}")
        return

    try:
        text = handoff.read_text(encoding="utf-8")
    except OSError as e:
        print(f"[WARN] handoff_drift: cannot read HANDOFF.md: {e}")
        return

    try:
        tree = render_from_handoff(text)
    except Exception as e:
        # Distinguish "no yaml block" (PASS — not our format) from real parse
        # errors (WARN — surface to operator). render_from_handoff raises
        # ValueError on missing fence and yaml.YAMLError on parse failure;
        # one Exception catch covers both.
        msg = str(e)
        if isinstance(e, ValueError) and "Current Phase Block" in msg:
            print("[PASS] handoff_drift: HANDOFF.md has no '## Current Phase Block' yaml block (skip)")
            return
        print(f"[WARN] handoff_drift: yaml parse error: {type(e).__name__}: {msg}")
        return

    # Drift check (anchored block vs yaml)
    if not is_anchor_present(text):
        print("[PASS] handoff_drift: anchor block absent (opt-out — populate via `python -m cli.handoff_render <handoff> --in-place`)")
    elif check_drift(text, tree):
        print("[WARN] handoff_drift: anchored block != yaml-rendered tree")
        print(f"  fix: `python -m cli.handoff_render {handoff} --in-place`")
    else:
        print("[PASS] handoff_drift: anchored block matches yaml-rendered tree")

    # Promotion candidate check (orthogonal to drift; same yaml source)
    try:
        from lib.handoff_drift import detect_promotable_sub_phases
        candidates = detect_promotable_sub_phases(text)
    except Exception:
        candidates = []
    if candidates:
        for cid in candidates:
            print(f"[WARN] handoff_drift: sub_phase {cid!r} satisfies promotion rule (>=5 steps + nested marker)")
        print(f"  apply: yaml block에서 해당 sub_phase의 flat step_* 키들을 자식 phase block으로 재구성 (CLAUDE.md Phase Tree Convention)")


if __name__ == "__main__":
    main()
