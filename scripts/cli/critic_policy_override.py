#!/usr/bin/env python3
"""CLI for critic_policy override → ~/.claude/config/critic-policy.yaml (v15.17 H closure).

cli/breaker_override.py와 1:1 mirror — critic_policy 도메인을 동일 패턴
(asymmetric token gate + yaml runtime override)으로 노출. v15.16에서 breaker
도메인의 closure가 완성된 것을 critic_policy 도메인도 동등하게 도달.

Usage:
    cd ~/.claude/scripts
    python -m cli.critic_policy_override \\
        --agent <agent_type> \\
        --decision {invoke|skip} \\
        --token <required_token>

Token gate (lib/critic_policy.py 정의, asymmetric per D4):
    invoke → skip : configure-critic-policy (강한 — Critic 비활성화 = E1 disable)
    skip → invoke : apply-user-preference (안전 — Critic 활성화)
    unknown agent default = invoke (보수적 conservative)

Exit codes:
    0  success — persisted (또는 no-op)
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

from lib.critic_policy import (  # noqa: E402
    apply_override,
    resolve as resolve_decision,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="critic-policy-override",
        description=(
            "v15.17 H closure — critic_policy invoke/skip 결정의 yaml runtime "
            "override. asymmetric token gate (invoke→skip=강한 / skip→invoke=안전). "
            "yaml: ~/.claude/config/critic-policy.yaml"
        ),
    )
    parser.add_argument(
        "--agent", required=True,
        help="대상 agent_type (예: harness-planner, Explore, custom-agent)",
    )
    parser.add_argument(
        "--decision", required=True, choices=["invoke", "skip"],
        help="목표 결정: invoke (critic 활성) 또는 skip (critic 비활성)",
    )
    parser.add_argument(
        "--token", required=True,
        help="Mutation token (방향에 따라 configure-critic-policy 또는 apply-user-preference)",
    )
    args = parser.parse_args(argv)

    try:
        changed = apply_override(args.agent, args.decision, token=args.token)
    except PermissionError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 3
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 2

    current = resolve_decision(args.agent)
    if changed:
        print(f"[OK] {args.agent} = {current} (persisted)")
    else:
        print(f"[NOOP] {args.agent} already at {current}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
