#!/usr/bin/env python3
"""Stop hook — session pattern learner (SENSOR only).

Scans ~/.claude/history.jsonl for recurring error phrases within the most
recent window and logs candidates to telemetry. Does NOT auto-write skill
files — that decision is gated behind an explicit user action (Wave 5
`/harness-skill learn`) to avoid silently polluting skills/.

Why SENSOR-only: auto-generating skill files from noise creates skill
bloat and false patterns. Learner here produces actionable signal; the
acting step is user-initiated.

Stop hook schema note: NO additionalContext field. We emit no stdout.
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.io import read_hook_input
from lib.logging import log_telemetry
from lib.paths import CLAUDE_HOME
# S2 W1 wiring (debate-1779267594-edb2a2 LOCK D5_W1_site) — guarded write.
from lib import insight_index


HISTORY_PATH: Path = CLAUDE_HOME / "history.jsonl"
MIN_REPEATS: int = 3             # pattern count threshold to surface as a candidate
LAST_N_EVENTS: int = 300         # scan only the tail — recent session
MAX_CANDIDATES: int = 10


_ERROR_RE = re.compile(
    r"\b(error|failed|denied|not\s*found|permission|timeout|traceback|exception)\b",
    re.I,
)
_NORMALIZE_RE = re.compile(r"\d+|[/\\][\w./\\\-]+")


def _read_tail(path: Path, n: int) -> list[dict]:
    if not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return []
    events: list[dict] = []
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except Exception:
            continue
    return events


def _extract_text(event: dict) -> str:
    parts: list[str] = []
    for key in ("result", "error", "stderr", "stdout", "content", "message"):
        v = event.get(key)
        if isinstance(v, str):
            parts.append(v)
    return " ".join(parts)[:2000]


def find_recurring_errors(events: list[dict]) -> list[tuple[str, int]]:
    """Return (normalized_phrase, count) pairs that recur >= MIN_REPEATS times."""
    phrases: Counter[str] = Counter()
    for ev in events:
        text = _extract_text(ev)
        if not text:
            continue
        for m in _ERROR_RE.finditer(text):
            start = max(0, m.start() - 40)
            end = min(len(text), m.end() + 60)
            snippet = re.sub(r"\s+", " ", text[start:end].strip())
            key = _NORMALIZE_RE.sub("<X>", snippet)[:160]
            phrases[key] += 1
    return [(p, c) for p, c in phrases.most_common() if c >= MIN_REPEATS]


def terminal_convergence_predicate(payload: dict, candidates: list) -> bool:
    """W1 guard (debate-1779267594-edb2a2 D5_W1_site LOCK).

    Returns True iff the Stop hook signals a *convergent* terminal — defined
    as: the learner extracted at least one recurring-error candidate
    (>= MIN_REPEATS occurrences in LAST_N_EVENTS). This filters out
    routine per-turn Stop events that carry no actionable signal, so
    insight-index entries accrue only on genuine convergence moments.

    Architect gen-4 LOCK rationale: "writes only when Stop-hook payload
    signals task completion / convergence, not every turn."
    """
    return bool(candidates)


def main() -> None:
    payload = read_hook_input()
    events = _read_tail(HISTORY_PATH, LAST_N_EVENTS)
    candidates = find_recurring_errors(events)

    log_telemetry("learner-candidates", {
        "scanned_events": len(events),
        "candidates_count": len(candidates),
        "top": [
            {"pattern": p, "count": c}
            for p, c in candidates[:MAX_CANDIDATES]
        ],
    })

    session_id = str(payload.get("session_id") or "unknown")

    if terminal_convergence_predicate(payload, candidates):
        try:
            top_pattern, top_count = candidates[0]
            summary = (
                f"learner Stop convergence: {len(candidates)} recurring pattern(s); "
                f"top={top_pattern[:120]} x{top_count}"
            )[:280]
            insight_index.append({
                "event_type": "learner",
                "summary": summary,
                "ts_unix_ms": int(time.time() * 1000),
                "correlation_id": session_id,
                "source_module": "handlers.stop.learner",
                "axis": "recurring_error",
                "tags": ["stop_hook", "learner"],
                "body_ref": None,
            })
        except Exception:
            # Fail-soft per Stop hook discipline — never break the hook chain.
            pass

    # C2 work_unit digest (debate-1781431026-af5f83, ontology 32808a52c893):
    # a per-session capture that grows L1 from ROUTINE work — not only recurring
    # errors — so the brain auto-save (C1) has fresh insights to persist. Emitted
    # under a DISTINCT correlation_id (session_id + '-wu', NOT session_id) per the
    # C2 lock; handlers/prompt/context_load.py collapses it with the learner row
    # above into ONE surfaced slot. Throttled via the shared work_unit watermark
    # (NOT per-turn). Enumerates the top recurring gotchas so the digest strictly
    # SUBSUMES the learner row it shadows in the surface (no single-pattern loss).
    try:
        from lib import work_unit_store
        if events and work_unit_store.should_emit_digest():
            # Capture WHAT was done this turn (the last assistant message = the work
            # summary), not just THAT something happened — so the permanent L1/brain
            # internalizes work CONTENT, not a generic heartbeat. Whitespace-collapsed
            # + capped; gotchas appended when the learner found recurring errors.
            work = " ".join(str(payload.get("last_assistant_message") or "").split())[:170].rstrip()
            gotcha = ""
            if candidates:
                tops = "; ".join(f"{p[:50]} x{c}" for p, c in candidates[:3])
                gotcha = f" | gotchas: {tops}"
            if work:
                dsumm = f"work_unit: {work}{gotcha}"
            elif candidates:
                dsumm = f"work_unit: {len(candidates)} recurring gotcha(s){gotcha}"
            else:
                dsumm = "work_unit: session activity (no detail available)"
            insight_index.append({
                "event_type": "work_unit_digest",
                "summary": dsumm[:280],
                "ts_unix_ms": int(time.time() * 1000),
                "correlation_id": f"{session_id}-wu",
                "source_module": "handlers.stop.learner",
                "axis": "work_unit",
                "tags": ["stop_hook", "work_unit"],
                "body_ref": None,
            })
            work_unit_store.mark_digest_emitted()
    except Exception:
        # Fail-soft per Stop hook discipline — never break the hook chain.
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
