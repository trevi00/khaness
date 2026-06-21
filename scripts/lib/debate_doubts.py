#!/usr/bin/env python3
"""Aggregate Architect self_doubt notes across debate sessions.

Architect verdicts include a `self_doubt_note` field — the verdict's
honest admission of what was almost-accepted-but-shouldn't-be. These are
high-value insights that often go unaddressed once the debate converges.

This CLI scans state/debates/<session>/events.jsonl and surfaces any
recorded self_doubt entries so they can be reviewed periodically.

Convention (going forward): when logging Architect verdict events to
events.jsonl, include `self_doubt_note` and `implementation_notes` in
the payload (alongside the verdict count). Older sessions logged only
counts — those doubts are unrecoverable but new ones will be tracked.

Usage:
    cd ~/.claude/scripts
    python -m cli.debate_doubts                 # plaintext summary
    python -m cli.debate_doubts --json          # machine-readable
    python -m cli.debate_doubts --since 7d      # last N days only
    python -m cli.debate_doubts --acknowledge <session_id>  # mark seen
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.advisory_ack import REGISTRY  # noqa: E402
from lib.paths import STATE_DIR  # noqa: E402

DEBATES_DIR: Path = STATE_DIR / "debates"

# Wave 19: ack store moved to lib/advisory_ack.py REGISTRY['debate_doubts'].
# These names are kept as backward-compatible aliases bound to the canonical
# AdvisoryAck instance — they share state with REGISTRY automatically.
_ack = REGISTRY["debate_doubts"]
ACK_FILE: Path = _ack.ack_path
load_acknowledged = _ack.load


def parse_since(arg: str | None) -> float | None:
    """Convert '7d' / '24h' / '60m' → seconds-from-now epoch threshold."""
    if not arg:
        return None
    unit = arg[-1].lower()
    try:
        n = int(arg[:-1])
    except ValueError:
        return None
    factor = {"d": 86400, "h": 3600, "m": 60}.get(unit, 0)
    if not factor:
        return None
    return time.time() - n * factor


def acknowledge(session_id: str) -> None:
    """Mark a debate session's doubts as reviewed (no return value, by old contract)."""
    _ack.ack(session_id)


def collect_doubts(since_epoch: float | None = None) -> list[dict[str, Any]]:
    """Walk debate sessions and collect any self_doubt entries.

    Returns list of {session_id, gen, ts, doubt_text, acknowledged}.
    """
    if not DEBATES_DIR.exists():
        return []
    ack = load_acknowledged()
    out: list[dict[str, Any]] = []
    for sess_dir in sorted(DEBATES_DIR.iterdir()):
        if not sess_dir.is_dir():
            continue
        log = sess_dir / "events.jsonl"
        if not log.exists():
            continue
        try:
            with log.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if since_epoch is not None and ev.get("ts", 0) < since_epoch:
                        continue
                    payload = ev.get("payload", {}) or {}
                    if not isinstance(payload, dict):
                        continue
                    doubt = payload.get("self_doubt_note") or payload.get("self_doubt")
                    if not doubt:
                        continue
                    out.append({
                        "session_id": sess_dir.name,
                        "gen": ev.get("gen"),
                        "ts": ev.get("ts"),
                        "actor": ev.get("actor"),
                        "doubt_text": doubt,
                        "acknowledged": sess_dir.name in ack,
                    })
        except Exception:
            continue
    return out


def render_text(doubts: list[dict[str, Any]]) -> str:
    if not doubts:
        return (
            "=== Debate Self-Doubts ===\n"
            "No self_doubt_note entries found in event logs.\n"
            "\n"
            "Going forward, log Architect verdicts with payload including\n"
            "the `self_doubt_note` field so this CLI can surface them.\n"
            "Older sessions logged only verdict counts — historical doubts\n"
            "are unrecoverable."
        )
    pending = [d for d in doubts if not d["acknowledged"]]
    lines = [f"=== Debate Self-Doubts (n={len(doubts)}, pending={len(pending)}) ==="]
    for d in doubts:
        mark = "[seen]" if d["acknowledged"] else "[NEW]"
        text = d["doubt_text"]
        if len(text) > 200:
            text = text[:197] + "..."
        lines.append(f"{mark} {d['session_id']} gen={d['gen']}: {text}")
    return "\n".join(lines)


def count_pending(since_epoch: float | None = None) -> int:
    return sum(1 for d in collect_doubts(since_epoch) if not d["acknowledged"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="debate_doubts")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    parser.add_argument("--since", help="Filter recent: e.g. 7d, 24h, 60m")
    parser.add_argument("--acknowledge", help="Mark session_id doubts as seen")
    args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")

    if args.acknowledge:
        acknowledge(args.acknowledge)
        print(f"acknowledged: {args.acknowledge}")
        return 0

    since_epoch = parse_since(args.since)
    doubts = collect_doubts(since_epoch)

    if args.json:
        print(json.dumps(doubts, ensure_ascii=False, indent=2, default=str))
    else:
        print(render_text(doubts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
