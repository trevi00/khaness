#!/usr/bin/env python3
"""CLI for human override → operator ledger (v15.10 D5).

Usage:
    cd ~/.claude/scripts
    python -m cli.operator_override \\
        --agent <agent_type> \\
        --action {force_close|force_open|skip_critic_once} \\
        --reason "<free text>" \\
        --token configure-critic-policy \\
        [--project-root <path>]    # defaults to cwd

Exit codes:
    0  success — record appended
    2  argparse error / validation error
    3  PermissionError — wrong/missing token

The token argument is the Mutation tier name from CLAUDE.md L0 row 14
(`configure-critic-policy`). The CLI does NOT default the token — it must
be supplied explicitly so an operator typing the command consciously
asserts the tier.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.operator_ledger import (  # noqa: E402
    VALID_OVERRIDE_ACTIONS,
    apply_override,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="operator-override",
        description=(
            "Append a human override record to the project operator-ledger. "
            "Requires Mutation token 'configure-critic-policy' (CLAUDE.md L0 row 14)."
        ),
    )
    p.add_argument("--agent", required=True, help="agent_type to override")
    p.add_argument(
        "--action",
        required=True,
        choices=VALID_OVERRIDE_ACTIONS,
        help="override action",
    )
    p.add_argument(
        "--reason",
        required=True,
        help="human-readable rationale (recorded in ledger)",
    )
    p.add_argument(
        "--token",
        required=True,
        help="Mutation token (must be 'configure-critic-policy')",
    )
    p.add_argument(
        "--project-root",
        default=None,
        help="project root path (default: current working directory)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 2

    project_root = args.project_root or os.getcwd()
    try:
        path = apply_override(
            project_root,
            args.agent,
            args.action,
            reason=args.reason,
            token=args.token,
        )
    except PermissionError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 3
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 2

    print(f"[OK] appended override to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
