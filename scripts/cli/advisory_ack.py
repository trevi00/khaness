#!/usr/bin/env python3
"""argv-rewrite alias dispatching to per-advisory CLIs (Wave 19).

This module is a thin REDIRECTOR. It deliberately does NOT define an
argparse surface — that would duplicate the per-command parsers and
re-introduce the generic-CLI shape rejected by the gen-1 Architect
verdict. Instead, it inspects argv positionally (length + first two
slots only) and re-invokes the existing per-advisory CLI's main() with
rewritten arguments.

Usage:
    python -m cli.advisory_ack <advisory> <key>

Examples:
    python -m cli.advisory_ack debate_doubts debate-1777968334-6b381e
        → equivalent to: python -m cli.debate_doubts --acknowledge <sid>
    python -m cli.advisory_ack strict_design 2026-05-05T11:22:00Z
        → equivalent to: python -m engine.trigger_summary --ack-ts <ts>

This is a CONVENIENCE alias for users who don't want to remember which
underlying CLI handles which advisory. The per-command CLIs remain the
canonical surface — listing, --json modes, and all other flags exist
only there (use `python -m cli.debate_doubts` etc.).
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


_USAGE = "usage: python -m cli.advisory_ack <advisory> <key>\n"


def _redirect(advisory: str, key: str) -> int:
    """Dispatch to the per-command CLI's main() with rewritten args."""
    if advisory == "debate_doubts":
        from cli.debate_doubts import main as dd_main
        return dd_main(["--acknowledge", key])
    if advisory == "strict_design":
        from engine.trigger_summary import main as ts_main
        return ts_main(["--ack-ts", key])
    sys.stderr.write(f"unknown advisory: {advisory!r}\n")
    sys.stderr.write(_USAGE)
    return 2


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if len(args) != 2:
        sys.stderr.write(_USAGE)
        return 2
    return _redirect(args[0], args[1])


if __name__ == "__main__":
    sys.exit(main())
