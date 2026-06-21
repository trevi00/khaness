#!/usr/bin/env python3
"""mirror — operator CLI for the per-project mirror context brain.

debate-1781435805-qb14p7 (ontology c4ad11f4d9a2). On-demand REGENERATE (M4: heavy
extraction allowed here, never on the SessionStart hot path) + status/scan surfaces.
Writes ONLY under <project>/atlas/mirror/ (M7). Run from the PROJECT root (cwd).

Usage (from the project root):
    python -m cli.mirror regenerate     # (re)build atlas/mirror/{manifest.json,STRUCTURE.md}
    python -m cli.mirror status         # show drift scan for cwd
    python -m cli.mirror scan           # alias of status (machine JSON)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import mirror_drift  # noqa: E402


def _emit(text: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    buf = getattr(stream, "buffer", None)
    if buf is not None:
        buf.write(text.encode("utf-8", "replace"))
        buf.flush()
    else:
        stream.write(text)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in {"regenerate", "status", "scan"}:
        _emit("Usage: python -m cli.mirror {regenerate|status|scan}\n", err=True)
        return 2
    cmd = argv[0]
    cwd = os.getcwd()
    if cmd == "regenerate":
        res = mirror_drift.regenerate(cwd)
        _emit(json.dumps({"command": "regenerate", "cwd": cwd, "result": res}, ensure_ascii=False, indent=2) + "\n")
        if not res.get("ok"):
            return 1
        _emit(f"\n# mirror written to {cwd}/atlas/mirror/ (uncommitted). Commit + push to persist.\n")
        return 0
    # status / scan
    res = mirror_drift.scan(cwd)
    _emit(json.dumps({"command": cmd, "cwd": cwd, "result": res}, ensure_ascii=False, indent=2) + "\n")
    if res.get("marker") and not res.get("unverifiable") and not res.get("fingerprint_match"):
        _emit(f"\n# STALE scopes: {', '.join(res.get('stale_scopes') or [])} — run `python -m cli.mirror regenerate`\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
