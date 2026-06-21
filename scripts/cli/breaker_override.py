#!/usr/bin/env python3
"""CLI for breaker threshold override → yaml runtime config (v15.16 F closure).

Usage:
    cd ~/.claude/scripts
    python -m cli.breaker_override \\
        --key {trip_per_mode|trip_window|trip_any_mode|trip_any_window|backoff_base_sec|backoff_cap_sec} \\
        --value <int> \\
        --token <required_token>

Token gate (asymmetric):
    임계 상향 (더 관대): configure-critic-policy
    임계 하향 (검출 강화): apply-user-preference
    window/any 키: apply-user-preference (양방향 안전)

Exit codes:
    0  success
    2  argparse / validation error
    3  PermissionError (wrong token)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.breakers.config import apply_override, resolve_thresholds  # noqa: E402


_VALID_KEYS = [
    "trip_per_mode", "trip_window", "trip_any_mode",
    "trip_any_window", "backoff_base_sec", "backoff_cap_sec",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="breaker-override",
        description=(
            "v15.16 F closure — breaker 임계 runtime override. "
            "asymmetric token gate (상향=강한, 하향=안전). "
            "yaml: ~/.claude/config/breaker-thresholds.yaml"
        ),
    )
    parser.add_argument("--key", required=True, choices=_VALID_KEYS)
    parser.add_argument("--value", required=True, type=int)
    parser.add_argument("--token", required=True)
    args = parser.parse_args(argv)

    try:
        changed = apply_override(args.key, args.value, token=args.token)
    except PermissionError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 3
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 2

    th = resolve_thresholds()
    current = getattr(th, args.key)
    if changed:
        print(f"[OK] {args.key} = {current} (persisted)")
    else:
        print(f"[NOOP] {args.key} already at {current}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
