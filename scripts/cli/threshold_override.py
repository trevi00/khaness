#!/usr/bin/env python3
"""threshold_override — operator CLI to apply a staged threshold change (M22 D4).

Token-gated writer around lib.threshold_policy.apply_threshold_override. The agent NEVER
calls this — it is the operator's apply step after reviewing a staged proposal
(cli.calibration_review). The risky/unsafe direction requires the graduate-validator token
AND a gate-accepted ready-flag; the safe direction needs apply-user-preference.

Usage:
    python -m cli.threshold_override --name skill_match.FULL_BODY_MIN_SCORE --value 4 \
        --token graduate-validator

Exit: 0 applied/no-op; 1 refused (bad token / no ready-flag / locked / unregistered); 2 argparse.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.threshold_policy import apply_threshold_override  # noqa: E402


def _coerce(raw: str):
    try:
        return int(raw) if ("." not in raw and "e" not in raw.lower()) else float(raw)
    except ValueError:
        return float(raw)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cli.threshold_override",
                                description="Apply a staged threshold override (M22, operator + token).")
    p.add_argument("--name", required=True)
    p.add_argument("--value", required=True)
    p.add_argument("--token", required=True)
    args = p.parse_args(argv)
    try:
        value = _coerce(args.value)
    except ValueError:
        sys.stderr.write(f"[refused] --value not numeric: {args.value!r}\n")
        return 1
    try:
        changed = apply_threshold_override(args.name, value, token=args.token)
    except (ValueError, PermissionError) as e:
        sys.stderr.write(f"[refused] {e}\n")
        return 1
    print(f"{'applied' if changed else 'no-op'}: {args.name} = {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
