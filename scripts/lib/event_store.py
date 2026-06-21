"""Append-only JSONL event store for debate sessions.

Mirrors Ouroboros event sourcing — replay events to reconstruct state
without a persistent DB. Used by engine/ for stateless evolve_step resumption.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterator

from .logging import jsonl_append, log_telemetry, now_iso
from .paths import STATE_DIR, ensure_dir


DEBATES_DIR: Path = STATE_DIR / "debates"


def _hash_payload(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(serialized.encode("utf-8")).hexdigest()[:12]


class EventStore:
    """Per-session append-only log at STATE_DIR/debates/<session_id>/events.jsonl."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.dir = ensure_dir(DEBATES_DIR / session_id)
        self.path = self.dir / "events.jsonl"

    def append(
        self,
        event_type: str,
        gen: int,
        actor: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        record = {
            "ts": now_iso(),
            "gen": gen,
            "type": event_type,
            "actor": actor,
            "payload": payload,
            "hash": _hash_payload(payload),
        }
        jsonl_append(self.path, record)
        return record

    def replay(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events: list[dict[str, Any]] = []
        # A torn FINAL line (a concurrent appender caught mid-write) is benign and
        # skipped silently. But an unparseable line FOLLOWED by a good line is
        # MID-LOG CORRUPTION on an append-only log — silently dropping it changes
        # the reconstructed state (last_gen()/convergence read from replay()), so
        # SURFACE it via telemetry instead of dropping it without a trace
        # (deep-audit pass-2 completeness: replay silent-skip-on-corruption).
        # Still fail-soft: replay() never raises.
        pending_bad: list[int] = []
        with self.path.open("r", encoding="utf-8") as f:
            for lineno, raw in enumerate(f, 1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    pending_bad.append(lineno)
                    continue
                if pending_bad:
                    # a good line followed the bad one(s) -> they were mid-log
                    # corruption, not a torn tail.
                    self._signal_corruption(pending_bad)
                    pending_bad = []
                events.append(ev)
        # pending_bad remaining at EOF == a torn FINAL line -> benign, not signaled.
        return events

    def _signal_corruption(self, linenos: list[int]) -> None:
        """Fail-soft telemetry signal that replay() dropped mid-log corrupt line(s).
        Makes append-only-integrity violations observable instead of silent."""
        try:
            log_telemetry("event-store-corruption", {
                "session_id": self.session_id,
                "path": str(self.path),
                "corrupt_linenos": linenos,
                "detail": "mid-log unparseable line(s) dropped during replay",
            })
        except Exception:
            pass

    def last_by_type(self, event_type: str) -> dict[str, Any] | None:
        for ev in reversed(self.replay()):
            if ev.get("type") == event_type:
                return ev
        return None

    def iter_by_type(self, event_type: str) -> Iterator[dict[str, Any]]:
        for ev in self.replay():
            if ev.get("type") == event_type:
                yield ev

    def last_gen(self) -> int:
        events = self.replay()
        if not events:
            return 0
        return max((ev.get("gen", 0) for ev in events), default=0)
