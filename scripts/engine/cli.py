"""Post-hoc inspection CLI for debate sessions.

Not used for orchestration (the slash command drives that).

Usage:
    python -m engine.cli list
    python -m engine.cli show <session_id>
    python -m engine.cli last-verdict <session_id>
"""
from __future__ import annotations

import argparse
import json
import sys

from lib.event_store import DEBATES_DIR, EventStore
from lib.paths import ensure_dir


def _list_sessions() -> int:
    ensure_dir(DEBATES_DIR)
    sessions = sorted(p.name for p in DEBATES_DIR.iterdir() if p.is_dir())
    if not sessions:
        print("(no debate sessions)")
        return 0
    for s in sessions:
        print(s)
    return 0


def _show(session_id: str) -> int:
    store = EventStore(session_id)
    events = store.replay()
    if not events:
        print(f"(no events for session {session_id})", file=sys.stderr)
        return 1
    for ev in events:
        print(json.dumps(ev, ensure_ascii=False))
    return 0


def _last_verdict(session_id: str) -> int:
    store = EventStore(session_id)
    ev = store.last_by_type("verdict")
    if not ev:
        print(f"no verdict recorded for session {session_id}", file=sys.stderr)
        return 1
    print(json.dumps(ev.get("payload", {}), ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="engine.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list all debate session ids")
    sp_show = sub.add_parser("show", help="print every event for a session")
    sp_show.add_argument("session_id")
    sp_lv = sub.add_parser("last-verdict", help="print the last verdict for a session")
    sp_lv.add_argument("session_id")

    args = p.parse_args(argv)
    if args.cmd == "list":
        return _list_sessions()
    if args.cmd == "show":
        return _show(args.session_id)
    if args.cmd == "last-verdict":
        return _last_verdict(args.session_id)
    return 2


if __name__ == "__main__":
    sys.exit(main())
