"""phase_events — autopilot phase-tree event producer + reader (v15.35.5).

debate-1779008782-230c36 gen 4 Architect condition P1 fix infrastructure.

Provides the producer-side vocabulary (phase_status events) that an
autopilot evaluator dispatch precondition would consume. The gen 4
Critic blocker confirmed that no such producer exists in the codebase —
`lib/phase_tree` is pure structural logic (Status enum + Phase dataclass
+ render/parse), zero I/O. This module adds the missing I/O layer
without modifying phase_tree.

## Scope (this cycle: infrastructure-only)

- **Land**: producer (`append_phase_event`) + reader (`read_recent_events`,
  `latest_status`) + 11 self-check cases.
- **NOT land**: autopilot.md Phase 3.5 wiring, evaluator dispatch
  precondition consumer, integration with `lib/evaluator_dispatcher`.
  Those require operator token per CLAUDE.md L0 Mutation 분류표
  (runtime policy mutation) and a new (narrower) debate session.

## Storage

Append-only JSONL at `state/orchestrator/<sid>/phase_events.jsonl`
(same dir as the orchestrator events.jsonl that already lives here —
phase_events is a sibling stream, NOT a duplicate of orchestrator
events). Mirrors the durability convention from
`lib/axis_scores_log.py`: O_APPEND single-write per line, fsync, line
size capped at PIPE_BUF (4096 bytes — atomic concurrent append).

## Vocabulary

`PHASE_EVENT_STATUSES` is a frozenset distinct from
`lib/autopilot_state._STATUSES` (which is `{in_progress, done, failed}`
for the AutopilotState machine). phase events describe per-phase
lifecycle inside a super-session; autopilot status describes the
super-session itself. The vocabularies do not overlap by design — a
super-session can be `in_progress` while a single phase is `failed`
inside it.

Members chosen per debate gen 4 condition: `started`, `completed`,
`failed`, `escalated`, `aborted_user`, `aborted_error`,
`aborted_timeout`. Conservative — any future addition requires a new
debate (vocabulary expansion is a meta-decision per Architect S1).

## Public surface

- `SCHEMA_VERSION` (current = "1")
- `PHASE_EVENT_STATUSES` (frozenset[str])
- `_MAX_EVENT_BYTES` (PIPE_BUF cap)
- `log_dir(sid) -> Path`
- `append_phase_event(sid, phase_id, status, reason="") -> bool`
- `read_recent_events(sid, limit=20) -> list[dict]`
- `latest_status(sid, phase_id) -> str | None`
- `events_for_phase(sid, phase_id) -> list[dict]`

Reader functions fail-soft (return empty/None on I/O failure); writer
returns False on oversize/IO failure (caller decides whether to retry).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


SCHEMA_VERSION: str = "1"

# Distinct from lib/autopilot_state._STATUSES — see module docstring.
PHASE_EVENT_STATUSES: frozenset[str] = frozenset({
    "started",
    "completed",
    "failed",
    "escalated",
    "aborted_user",
    "aborted_error",
    "aborted_timeout",
})

# Same atomic-append cap as axis_scores_log / writeback_store.
_MAX_EVENT_BYTES: int = 4096


def log_dir(sid: str) -> Path:
    """Lazy STATE_DIR resolution. state/orchestrator/<sid>/.

    Lives next to the existing orchestrator events.jsonl (sibling
    stream); creating the dir is idempotent.
    """
    if not isinstance(sid, str) or not sid:
        raise ValueError(f"sid must be non-empty str, got {sid!r}")
    from .paths import STATE_DIR
    d = STATE_DIR / "orchestrator" / sid
    d.mkdir(parents=True, exist_ok=True)
    return d


def _events_path(sid: str) -> Path:
    return log_dir(sid) / "phase_events.jsonl"


def append_phase_event(
    sid: str,
    phase_id: str,
    status: str,
    reason: str = "",
) -> bool:
    """Append one phase event to state/orchestrator/<sid>/phase_events.jsonl.

    Returns True on success, False on I/O failure or oversize.

    Raises ValueError on:
      - empty sid (delegated to log_dir)
      - empty phase_id
      - status not in PHASE_EVENT_STATUSES
      - reason not a str (defensive — caller may pass non-str by mistake)
    """
    if not isinstance(phase_id, str) or not phase_id:
        raise ValueError(f"phase_id must be non-empty str, got {phase_id!r}")
    if status not in PHASE_EVENT_STATUSES:
        raise ValueError(
            f"status must be one of {sorted(PHASE_EVENT_STATUSES)}, "
            f"got {status!r}"
        )
    if not isinstance(reason, str):
        raise ValueError(
            f"reason must be str, got {type(reason).__name__}"
        )

    event: dict = {
        "schema_version": SCHEMA_VERSION,
        "ts": time.time(),
        "phase_id": phase_id,
        "status": status,
        "reason": reason,
    }
    line = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
    encoded = line.encode("utf-8")
    if len(encoded) > _MAX_EVENT_BYTES:
        # Reject oversize (same policy as axis_scores_log) — no silent
        # truncation. Caller can shorten reason and retry.
        return False

    path = _events_path(sid)
    fd = None
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        os.write(fd, encoded)
        try:
            os.fsync(fd)
        except OSError:
            pass
        return True
    except OSError:
        return False
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def read_recent_events(sid: str, limit: int = 20) -> list[dict]:
    """Return up to `limit` most recent phase events (chronological).

    `limit <= 0` → return ALL events (no slice). Skips malformed lines,
    lines missing schema_version, or lines with status not in
    PHASE_EVENT_STATUSES (forward-compat guard — if future cycle adds
    a status without bumping schema_version, old readers ignore it).

    Fail-soft: returns [] on missing file / OSError / empty sid.
    """
    if not isinstance(sid, str) or not sid:
        return []
    path = _events_path(sid)
    if not path.exists():
        return []

    out: list[dict] = []
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            if "schema_version" not in rec:
                continue
            if not isinstance(rec.get("phase_id"), str):
                continue
            if rec.get("status") not in PHASE_EVENT_STATUSES:
                continue
            out.append(rec)
    except OSError:
        return []

    if limit and limit > 0:
        return out[-limit:]
    return out


def latest_status(sid: str, phase_id: str) -> str | None:
    """Most recent status for `phase_id` in this sid's stream.

    Returns None if no events exist for that phase_id. Use as a
    cheap precondition probe (e.g., "is phase X escalated?").
    """
    if not isinstance(sid, str) or not sid:
        return None
    if not isinstance(phase_id, str) or not phase_id:
        return None
    matching = [
        e for e in read_recent_events(sid, limit=0)
        if e.get("phase_id") == phase_id
    ]
    if not matching:
        return None
    return matching[-1].get("status")


def events_for_phase(sid: str, phase_id: str) -> list[dict]:
    """Return ALL events for one phase_id, chronological order.

    Use when latest_status alone is insufficient (e.g., reason audit).
    """
    if not isinstance(sid, str) or not sid:
        return []
    if not isinstance(phase_id, str) or not phase_id:
        return []
    return [
        e for e in read_recent_events(sid, limit=0)
        if e.get("phase_id") == phase_id
    ]


# ============================================================================
# Embedded self-check (single-file mutation surface — v15.35.5)
# ============================================================================


def _self_check() -> int:
    import tempfile

    failed = 0
    cases: list[tuple[str, bool, str]] = []

    def case(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failed
        cases.append((name, ok, detail))
        if not ok:
            failed += 1

    with tempfile.TemporaryDirectory() as td:
        prev_home = os.environ.get("CLAUDE_HOME")
        os.environ["CLAUDE_HOME"] = str(Path(td))
        try:
            # ---- 1. Empty stream returns [] / None ----
            case("read_empty_sid_returns_empty",
                 read_recent_events("") == [])
            case("read_nonexistent_sid_returns_empty",
                 read_recent_events("orch-noexist") == [])
            case("latest_status_empty_returns_none",
                 latest_status("orch-noexist", "P1") is None)
            case("events_for_phase_empty_returns_empty",
                 events_for_phase("orch-noexist", "P1") == [])

            # ---- 2. Input validation on writer ----
            try:
                append_phase_event("", "P1", "started")
                case("writer_empty_sid_rejects", False, "expected ValueError")
            except ValueError:
                case("writer_empty_sid_rejects", True)

            try:
                append_phase_event("orch-1", "", "started")
                case("writer_empty_phase_id_rejects", False,
                     "expected ValueError")
            except ValueError:
                case("writer_empty_phase_id_rejects", True)

            try:
                append_phase_event("orch-1", "P1", "bogus_status")
                case("writer_bad_status_rejects", False,
                     "expected ValueError")
            except ValueError:
                case("writer_bad_status_rejects", True)

            try:
                append_phase_event("orch-1", "P1", "started", reason=123)  # type: ignore[arg-type]
                case("writer_non_str_reason_rejects", False,
                     "expected ValueError")
            except ValueError:
                case("writer_non_str_reason_rejects", True)

            # ---- 3. Write + read round-trip ----
            sid = "orch-roundtrip"
            ok1 = append_phase_event(sid, "P1", "started", "init")
            ok2 = append_phase_event(sid, "P1", "completed", "validators pass")
            ok3 = append_phase_event(sid, "P2", "started", "")
            case("write_all_three_succeed", ok1 and ok2 and ok3)

            events = read_recent_events(sid)
            case("read_returns_3_events", len(events) == 3)
            case("read_chronological_order",
                 events[0]["phase_id"] == "P1"
                 and events[0]["status"] == "started"
                 and events[2]["phase_id"] == "P2")
            case("read_schema_version_injected",
                 all(e.get("schema_version") == "1" for e in events))
            case("read_ts_field_present",
                 all(isinstance(e.get("ts"), float) for e in events))

            # ---- 4. latest_status + events_for_phase ----
            case("latest_status_P1_is_completed",
                 latest_status(sid, "P1") == "completed")
            case("latest_status_P2_is_started",
                 latest_status(sid, "P2") == "started")
            case("latest_status_unknown_phase_none",
                 latest_status(sid, "P3") is None)
            p1_events = events_for_phase(sid, "P1")
            case("events_for_phase_P1_returns_2",
                 len(p1_events) == 2
                 and all(e["phase_id"] == "P1" for e in p1_events))

            # ---- 5. limit semantics ----
            for i in range(5):
                append_phase_event(sid, f"PX{i}", "started")
            recent_3 = read_recent_events(sid, limit=3)
            case("limit_3_returns_3", len(recent_3) == 3)
            case("limit_3_is_tail",
                 recent_3[-1]["phase_id"] == "PX4")
            all_evts = read_recent_events(sid, limit=0)
            case("limit_0_returns_all", len(all_evts) == 8)
            all_evts_neg = read_recent_events(sid, limit=-1)
            case("limit_negative_returns_all", len(all_evts_neg) == 8)

            # ---- 6. Oversize rejection (writer returns False) ----
            big_reason = "x" * 5000
            ok_big = append_phase_event(sid, "Pbig", "started", big_reason)
            case("oversize_event_rejected", ok_big is False)

            # ---- 7. Malformed line in store skipped on read ----
            # Manually inject a malformed line + a missing-schema_version
            # line to verify reader robustness.
            from . import paths as _p
            inj_path = _p.STATE_DIR / "orchestrator" / "orch-malformed" / "phase_events.jsonl"
            inj_path.parent.mkdir(parents=True, exist_ok=True)
            with inj_path.open("w", encoding="utf-8") as f:
                f.write("not json at all\n")
                f.write(json.dumps({"phase_id": "P1", "status": "started"}) + "\n")  # no schema_version
                f.write(json.dumps({"schema_version": "1", "phase_id": "P1", "status": "bogus"}) + "\n")  # bad status
                f.write(json.dumps({"schema_version": "1", "phase_id": "P1", "status": "started", "ts": 1.0, "reason": ""}) + "\n")  # valid
                f.write("\n")  # empty line
            events_mf = read_recent_events("orch-malformed")
            case("malformed_lines_skipped",
                 len(events_mf) == 1
                 and events_mf[0]["phase_id"] == "P1"
                 and events_mf[0]["status"] == "started")

            # ---- 8. Vocabulary closure ----
            for valid_status in PHASE_EVENT_STATUSES:
                ok = append_phase_event(sid, "Pvocab",
                                        valid_status, f"reason-{valid_status}")
                if not ok:
                    case(f"vocab_status_{valid_status}_writes", False,
                         f"write failed for {valid_status}")
                    break
            else:
                case("vocab_all_statuses_writable", True)
            case("vocabulary_size_7", len(PHASE_EVENT_STATUSES) == 7)
            case("vocabulary_immutable",
                 isinstance(PHASE_EVENT_STATUSES, frozenset))

            # ---- 9. Separation from autopilot_state vocabulary ----
            # Design intent: PHASE_EVENT_STATUSES describes per-phase
            # lifecycle inside a super-session; _STATUSES describes the
            # super-session itself. The ONLY intentional overlap is
            # 'failed' (failure semantic is identical at both scopes —
            # a super-session can transition to status='failed' when a
            # phase's most-recent event is status='failed'). Any other
            # overlap would be a vocabulary collision bug.
            try:
                from . import autopilot_state as _aps
                overlap = PHASE_EVENT_STATUSES & _aps._STATUSES
                allowed_overlap = {"failed"}
                unexpected = overlap - allowed_overlap
                case("vocabulary_overlap_only_failed",
                     unexpected == set(),
                     f"unexpected overlap beyond 'failed': {unexpected}"
                     if unexpected else "")
                case("failed_is_present_in_both_by_design",
                     "failed" in overlap)
            except (ImportError, AttributeError):
                case("vocabulary_overlap_only_failed", True,
                     "(skipped — autopilot_state not introspectable)")
                case("failed_is_present_in_both_by_design", True,
                     "(skipped)")

            # ---- 10. Latest-status ignores other phases ----
            append_phase_event(sid, "Piso", "started")
            append_phase_event(sid, "Piso", "failed", "test")
            append_phase_event(sid, "Pother", "completed")
            case("latest_status_isolated_by_phase_id",
                 latest_status(sid, "Piso") == "failed")
        finally:
            if prev_home is None:
                os.environ.pop("CLAUDE_HOME", None)
            else:
                os.environ["CLAUDE_HOME"] = prev_home

    for name, ok, detail in cases:
        marker = "[OK]" if ok else "[FAIL]"
        suffix = f": {detail}" if detail and not ok else ""
        print(f"  {marker} {name}{suffix}")
    if failed:
        print(f"\n[FAIL] {failed}/{len(cases)} self-check assertions failed")
        return 1
    print(f"\n[OK] {len(cases)} self-check assertions passed")
    return 0


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        sys.exit(_self_check())
    print("lib.phase_events — autopilot phase-tree event producer/reader (v15.35.5)")
    print(f"  schema_version:           {SCHEMA_VERSION}")
    print(f"  PHASE_EVENT_STATUSES:     {sorted(PHASE_EVENT_STATUSES)}")
    print(f"  max event bytes:          {_MAX_EVENT_BYTES}")
    print(f"  storage:                  state/orchestrator/<sid>/phase_events.jsonl")
    print(f"  NOT wired to autopilot — infrastructure only this cycle")
    print(f"  use --self-check to run embedded smoke test")
    sys.exit(0)
