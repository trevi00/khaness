"""rewind — fork-only generation rollback (v15.30 Rw).

debate-1778990144-679cb8 deferred carryover (Rw → v15.30) + 5-axis analysis
(applied at session entry per same axis-priority as v15.27 R observability cycle):

  Fork-only (selected):
    응집 ↑   — event_store SID-isolation 패턴 그대로 재사용 (new lib/ surface 최소)
    안정 ↑↑  — 원본 parent_sid events.jsonl 절대 미수정 (append-only invariant 보존)
    확장 ↑   — per-SID 격리 fork stream
    결합 ↑   — git worktree 미도입 (Python stdlib + 기존 EventStore만)
    사용 ↓   — fork sid를 사용자가 인지해야 함 (parent_sid_of로 lineage 추적 가능)
    테스트 ↑ — 격리된 stream, side-effect 없음
  Worktree-per-gen (rejected):  scope +200% (git infra), 안정 ↓ (격리 복잡)
  Cursor-only (rejected):       안정 ↓↓ ("rewind 했다고 믿지만 FS는 그대로")

Fork-only semantic: alternative-path 탐색 시 새 SID로 stream을 분기하고
parent_sid의 events.jsonl 일부분만 새 SID로 복사. 원본 SID stream은 그대로
유지되어 사후 비교/감사 가능. 진화형 다이어그램의 'rewind' edge는 conceptually
새 generation으로의 fork (이전 stream + 분기점).

State layout:
- state/debates/<parent_sid>/events.jsonl                — 원본 (NEVER mutated)
- state/debates/<new_sid>/events.jsonl                   — fork된 stream
- state/rewind/<parent_sid>.json                         — fork ledger
    {"forks": [{"new_sid": "...", "up_to_index": N, "ts": ...}], "count": int}

Caps (debate-1778987814-41b475 G2.2):
- per parent_sid total_forks ≤ 3 (재귀적 fork 회피)
- per-fork up_to_index ≤ len(parent events) (안전한 cut)

Public API:
- rewind_session(parent_sid, up_to_event_index, *, emit_fn=None) -> RewindResult
- parent_sid_of(forked_sid) -> str | None
- rewind_count(parent_sid) -> int
- is_rewound(sid) -> bool
- fork_history(parent_sid) -> list[dict]

Events (taxonomy 등록은 single-file gate 유지 위해 별도 cycle — fail-open emit):
- rewind.requested / rewind.completed / rewind.cap_exhausted
  emit_with_validation이 unknown event_type 처리 시 telemetry warn만 발생,
  flow 차단하지 않음. 본 cycle은 lib/rewind.py 단독 mutation surface.

Invariant: NO LLM, NO embedder. Pure stdlib json + path + secrets.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


_SID_SAFE_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
REWIND_CAP_PER_PARENT = 3


def _claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_HOME") or Path.home() / ".claude")


def _state_dir() -> Path:
    return _claude_home() / "state"


def _debates_dir() -> Path:
    p = _state_dir() / "debates"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _rewind_dir() -> Path:
    p = _state_dir() / "rewind"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _validate_sid(sid: str) -> None:
    if not isinstance(sid, str) or not sid:
        raise ValueError(f"sid must be non-empty string, got {sid!r}")
    if not _SID_SAFE_RE.match(sid):
        raise ValueError(f"sid failed safety regex: {sid!r}")


@dataclass
class RewindResult:
    """Outcome of a fork operation."""

    parent_sid: str
    new_sid: str
    up_to_index: int
    events_copied: int
    cap_exhausted: bool  # True iff parent_sid has hit REWIND_CAP_PER_PARENT
    new_events_path: str


def _load_fork_ledger(parent_sid: str) -> dict:
    target = _rewind_dir() / f"{parent_sid}.json"
    if not target.exists():
        return {"forks": [], "count": 0}
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"forks": [], "count": 0}


def _save_fork_ledger(parent_sid: str, ledger: dict) -> None:
    target = _rewind_dir() / f"{parent_sid}.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def _read_parent_events(parent_sid: str) -> list[str]:
    """Read parent events.jsonl as a list of raw lines (preserving order)."""
    parent_file = _debates_dir() / parent_sid / "events.jsonl"
    if not parent_file.exists():
        raise ValueError(f"parent_sid events.jsonl not found: {parent_sid}")
    return [
        line for line in parent_file.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def rewind_count(parent_sid: str) -> int:
    """Total number of forks created from this parent_sid."""
    _validate_sid(parent_sid)
    return int(_load_fork_ledger(parent_sid).get("count", 0))


def is_rewound(sid: str) -> bool:
    """True iff `sid` was created as a fork of some parent (has parent_sid in metadata)."""
    _validate_sid(sid)
    # Scan all rewind ledgers — fork records carry new_sid; absence means original.
    rewind_dir = _rewind_dir()
    if not rewind_dir.exists():
        return False
    for ledger_file in rewind_dir.glob("*.json"):
        try:
            data = json.loads(ledger_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for fork in data.get("forks", []) or []:
            if isinstance(fork, dict) and fork.get("new_sid") == sid:
                return True
    return False


def parent_sid_of(forked_sid: str) -> str | None:
    """Return the parent_sid that created `forked_sid` via rewind, or None if original."""
    _validate_sid(forked_sid)
    rewind_dir = _rewind_dir()
    if not rewind_dir.exists():
        return None
    for ledger_file in rewind_dir.glob("*.json"):
        try:
            data = json.loads(ledger_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for fork in data.get("forks", []) or []:
            if isinstance(fork, dict) and fork.get("new_sid") == forked_sid:
                return ledger_file.stem
    return None


def fork_history(parent_sid: str) -> list[dict]:
    """List of {new_sid, up_to_index, ts, events_copied} for all forks of parent_sid."""
    _validate_sid(parent_sid)
    return list(_load_fork_ledger(parent_sid).get("forks", []) or [])


def _mint_new_sid(parent_sid: str) -> str:
    return f"{parent_sid}-fork-{int(time.time())}-{secrets.token_hex(2)}"


def rewind_session(
    parent_sid: str,
    up_to_event_index: int,
    *,
    emit_fn: Callable[[str, dict], None] | None = None,
) -> RewindResult:
    """Fork parent_sid's events.jsonl into a new SID up to `up_to_event_index`.

    parent events.jsonl is read-only (append-only invariant preserved). The new
    sid receives the first `up_to_event_index` events plus a `rewind.completed`
    event marking the fork point.

    Args:
        parent_sid: source session to fork from. Must exist in state/debates/.
        up_to_event_index: number of events to carry into the fork (0 to len).
            Negative values raise ValueError. Values exceeding event count are
            clamped to the full length.

    Returns:
        RewindResult with new_sid + events_copied + cap_exhausted flag.

    Raises:
        ValueError on bad sid, negative index, missing parent, or cap exceeded
        (REWIND_CAP_PER_PARENT=3 per parent_sid).

    Emits (fail-open via emit_fn — taxonomy registration is separate cycle):
        rewind.requested  on entry
        rewind.completed  on success
        rewind.cap_exhausted  when count would exceed cap (then raises)
    """
    _validate_sid(parent_sid)
    if not isinstance(up_to_event_index, int) or up_to_event_index < 0:
        raise ValueError(f"up_to_event_index must be non-negative int, got {up_to_event_index!r}")

    # Cap check FIRST — emit cap_exhausted before raising
    ledger = _load_fork_ledger(parent_sid)
    current_count = int(ledger.get("count", 0))
    if current_count >= REWIND_CAP_PER_PARENT:
        if emit_fn is not None:
            try:
                emit_fn("rewind.cap_exhausted", {
                    "parent_sid": parent_sid,
                    "count": current_count,
                    "cap": REWIND_CAP_PER_PARENT,
                })
            except Exception:
                pass
        raise ValueError(
            f"rewind cap exhausted for parent_sid={parent_sid}: "
            f"count={current_count} >= cap={REWIND_CAP_PER_PARENT}"
        )

    # Read parent events (raises ValueError if parent missing)
    parent_events = _read_parent_events(parent_sid)
    cut_index = min(up_to_event_index, len(parent_events))

    if emit_fn is not None:
        try:
            emit_fn("rewind.requested", {
                "parent_sid": parent_sid,
                "up_to_index": cut_index,
                "parent_total_events": len(parent_events),
            })
        except Exception:
            pass

    # Mint new sid + create new events.jsonl
    new_sid = _mint_new_sid(parent_sid)
    new_dir = _debates_dir() / new_sid
    new_dir.mkdir(parents=True, exist_ok=True)
    new_events_file = new_dir / "events.jsonl"

    ts = int(time.time())
    fork_marker = json.dumps({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts)),
        "type": "rewind.completed",
        "actor": "lib.rewind",
        "gen": 0,
        "payload": {
            "parent_sid": parent_sid,
            "up_to_index": cut_index,
            "events_copied": cut_index,
        },
    }, ensure_ascii=False)

    # Write copied events + fork marker as the trailing line.
    lines = parent_events[:cut_index] + [fork_marker]
    new_events_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Update parent's fork ledger
    new_count = current_count + 1
    forks_list = ledger.setdefault("forks", [])
    forks_list.append({
        "new_sid": new_sid,
        "up_to_index": cut_index,
        "events_copied": cut_index,
        "ts": ts,
    })
    ledger["count"] = new_count
    _save_fork_ledger(parent_sid, ledger)

    cap_exhausted = new_count >= REWIND_CAP_PER_PARENT

    if emit_fn is not None:
        try:
            emit_fn("rewind.completed", {
                "parent_sid": parent_sid,
                "new_sid": new_sid,
                "up_to_index": cut_index,
                "events_copied": cut_index,
                "fork_count_after": new_count,
            })
        except Exception:
            pass

    return RewindResult(
        parent_sid=parent_sid,
        new_sid=new_sid,
        up_to_index=cut_index,
        events_copied=cut_index,
        cap_exhausted=cap_exhausted,
        new_events_path=str(new_events_file),
    )


# ============================================================================
# Embedded self-check (single-file mutation surface invariant — v15.30 Rw)
# ============================================================================


def _self_check() -> int:
    """Embedded smoke test (D5 gate proxy). Single-file surface invariant — no separate test."""
    import tempfile
    failed = 0
    cases: list[tuple[str, bool, str]] = []

    def case(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failed
        cases.append((name, ok, detail))
        if not ok:
            failed += 1

    with tempfile.TemporaryDirectory() as td:
        os.environ["CLAUDE_HOME"] = str(Path(td))

        # Setup: synthesize a parent session with 5 events
        parent_sid = "orch-test-parent"
        parent_dir = _debates_dir() / parent_sid
        parent_dir.mkdir(parents=True)
        parent_file = parent_dir / "events.jsonl"
        original_events = [
            json.dumps({"type": f"event.{i}", "gen": i, "actor": "test", "payload": {"i": i}, "hash": f"h{i}"})
            for i in range(5)
        ]
        parent_file.write_text("\n".join(original_events) + "\n", encoding="utf-8")
        original_bytes = parent_file.read_bytes()

        # Case 1: empty/invalid sid
        try:
            rewind_session("", 1)
            case("empty_sid_rejected", False, "should have raised")
        except ValueError:
            case("empty_sid_rejected", True)
        try:
            rewind_session("../escape", 1)
            case("path_traversal_rejected", False)
        except ValueError:
            case("path_traversal_rejected", True)

        # Case 2: negative index
        try:
            rewind_session(parent_sid, -1)
            case("negative_index_rejected", False)
        except ValueError:
            case("negative_index_rejected", True)

        # Case 3: missing parent
        try:
            rewind_session("nonexistent-parent", 0)
            case("missing_parent_rejected", False)
        except ValueError:
            case("missing_parent_rejected", True)

        # Case 4: basic fork — 3 events copied
        events: list[tuple[str, dict]] = []
        emit = lambda t, p: events.append((t, p))
        r1 = rewind_session(parent_sid, 3, emit_fn=emit)
        case("fork_returns_new_sid", r1.new_sid.startswith(parent_sid + "-fork-"))
        case("fork_events_copied", r1.events_copied == 3, f"copied={r1.events_copied}")
        case("fork_emits_requested", any(t == "rewind.requested" for t, _ in events))
        case("fork_emits_completed", any(t == "rewind.completed" for t, _ in events))
        case("fork_not_cap_exhausted_yet", r1.cap_exhausted is False)

        # Case 5: parent stream UNCHANGED (append-only invariant)
        case("parent_bytes_unchanged", parent_file.read_bytes() == original_bytes)

        # Case 6: new sid file has correct content (3 events + fork marker)
        new_lines = [l for l in Path(r1.new_events_path).read_text(encoding="utf-8").splitlines() if l.strip()]
        case("new_file_has_4_lines", len(new_lines) == 4, f"got {len(new_lines)}")
        last = json.loads(new_lines[-1])
        case("new_file_last_is_marker", last.get("type") == "rewind.completed")
        case("new_file_marker_has_parent", last.get("payload", {}).get("parent_sid") == parent_sid)

        # Case 7: parent_sid_of works
        case("parent_sid_of_returns_parent", parent_sid_of(r1.new_sid) == parent_sid)
        case("parent_sid_of_returns_none_for_original", parent_sid_of(parent_sid) is None)

        # Case 8: is_rewound
        case("is_rewound_true_for_fork", is_rewound(r1.new_sid))
        case("is_rewound_false_for_original", is_rewound(parent_sid) is False)

        # Case 9: rewind_count
        case("rewind_count_1_after_1_fork", rewind_count(parent_sid) == 1)

        # Case 10: clamp index when > parent length
        r2 = rewind_session(parent_sid, 999)
        case("over_length_index_clamped", r2.events_copied == 5)
        case("rewind_count_2", rewind_count(parent_sid) == 2)

        # Case 11: index=0 → empty fork (only marker)
        r3 = rewind_session(parent_sid, 0)
        case("zero_index_only_marker", r3.events_copied == 0)
        new3_lines = [l for l in Path(r3.new_events_path).read_text(encoding="utf-8").splitlines() if l.strip()]
        case("zero_index_file_one_line", len(new3_lines) == 1)
        case("cap_exhausted_at_3rd_fork", r3.cap_exhausted is True)

        # Case 12: cap rejects 4th fork
        events.clear()
        try:
            rewind_session(parent_sid, 1, emit_fn=emit)
            case("4th_fork_rejected", False)
        except ValueError:
            case("4th_fork_rejected", True)
        case("cap_exhausted_emitted", any(t == "rewind.cap_exhausted" for t, _ in events))

        # Case 13: fork_history returns full ledger
        hist = fork_history(parent_sid)
        case("fork_history_3_entries", len(hist) == 3)

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
    import sys
    if "--self-check" in sys.argv:
        sys.exit(_self_check())
    print("lib.rewind — use --self-check to run embedded smoke test")
    sys.exit(0)
