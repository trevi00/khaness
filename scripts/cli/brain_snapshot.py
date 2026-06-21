#!/usr/bin/env python3
"""brain_snapshot — operator CLI for core-brain learned-state persistence.

Thin wrapper over lib.brain_store (debate-1781359722-f16550). Operator-invoked
ONLY (INV-save: no SessionStart auto-tick). Does NOT git commit — the operator
commits brain/ in their normal push flow.

Usage:
    python -m cli.brain_snapshot save       # snapshot live L1/L2/graduation -> brain/ (accumulating)
    python -m cli.brain_snapshot restore     # rehydrate live from brain/ (seed-on-absent; retractions always unioned)
    python -m cli.brain_snapshot restore --merge   # additive union committed ∪ live (also unions indexes)
    python -m cli.brain_snapshot status      # live-vs-snapshot counts + divergence

After `save`, commit brain/ and push. On a fresh machine after pull, run
`restore` to rehydrate (recovery is intentionally manual — INV-save forbids an
auto-tick that would race the live appenders).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import brain_store  # noqa: E402


def _emit(text: str, *, err: bool = False) -> None:
    """Write UTF-8 regardless of console codec (Windows cp949 can't encode em-dashes
    in the status note). Use the binary buffer rather than reconfigure() — the
    latter can break pytest stdin capture."""
    stream = sys.stderr if err else sys.stdout
    data = text.encode("utf-8", "replace")
    buf = getattr(stream, "buffer", None)
    if buf is not None:
        buf.write(data)
        buf.flush()
    else:
        stream.write(text)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in {"save", "restore", "status"}:
        _emit("Usage: python -m cli.brain_snapshot {save|restore [--merge]|status}\n", err=True)
        return 2
    cmd = argv[0]
    try:
        if cmd == "save":
            result = brain_store.save()
        elif cmd == "restore":
            result = brain_store.restore(merge="--merge" in argv[1:])
        else:
            result = brain_store.status()
    except brain_store.BrainSchemaError as e:
        _emit(f"brain_snapshot: SCHEMA MISMATCH - {e}\n", err=True)
        return 1
    _emit(json.dumps({"command": cmd, "result": result}, ensure_ascii=False, indent=2) + "\n")
    if cmd == "save":
        _emit("\n# snapshot written to brain/ (uncommitted). Commit + push to persist.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
