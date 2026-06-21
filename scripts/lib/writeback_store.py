"""writeback_store — stdlib-only atomic JSONL log + index for writeback proposals.

Per debate-1778230575-aebdd3 D2 (locked: store=jsonl_oappend_oreplace_fsync).

Layout (under STATE_DIR/writeback/):
  proposals.jsonl  — append-only event log (1 line per proposal, fsync per line)
  index.json       — current state of pending/acked/rejected proposals
                     (atomic write via tmp + os.replace)

Stdlib-only constraint (per Architect gen 2 condition #1):
  FORBIDDEN: portalocker, fcntl, msvcrt.locking, filelock
  ALLOWED:   os.O_APPEND, os.O_CREAT, os.O_WRONLY, os.fsync, os.replace,
             tempfile.NamedTemporaryFile

PIPE_BUF cap (per Architect gen 3 addendum 1):
  Per-line JSONL write capped at 4096 bytes. Lines exceeding cap are
  split-rejected with the `writeback_split_rejected_total` telemetry counter.
  NOT silent truncation.

Single-writer model: one Python process per session id (sid). Concurrent
multi-process write across sessions is hypothetical (autopilot uses one
session at a time); O_APPEND atomicity for sub-PIPE_BUF writes covers it.

Public surface:
  - append_proposal(p: ProposalRecord) -> bool
  - read_index() -> dict[str, dict]
  - update_index(mutator: Callable[[dict], dict]) -> bool
  - mark_status(proposal_id: str, status: Literal['acked','rejected']) -> bool
  - SPLIT_REJECTED_COUNTER constant (env override)
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Literal


# Per-line JSONL cap (Architect gen 3 addendum 1)
PIPE_BUF_CAP_BYTES: int = 4096


@dataclass(frozen=True)
class ProposalRecord:
    """One writeback proposal entry."""
    id: str               # unique id (e.g., fingerprint + ts)
    fingerprint: str      # source strike fingerprint
    target_skill_path: str
    sha1_of_diff: str
    status: Literal["pending", "acked", "rejected"] = "pending"
    created_ts: float = field(default_factory=time.time)


def _writeback_dir() -> Path:
    """Lazy STATE_DIR resolution (honors test fixture redirection per
    lib/strike_dispatcher + lib/team_mailbox + lib/autopilot_state pattern)."""
    from .paths import STATE_DIR
    d = STATE_DIR / "writeback"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _proposals_path() -> Path:
    return _writeback_dir() / "proposals.jsonl"


def _index_path() -> Path:
    return _writeback_dir() / "index.json"


def _telemetry_path() -> Path:
    return _writeback_dir() / "telemetry.json"


def _bump_telemetry(counter: str, by: int = 1) -> None:
    """Increment a telemetry counter atomically."""
    p = _telemetry_path()
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8") or "{}")
            if not isinstance(data, dict):
                data = {}
        else:
            data = {}
    except (OSError, json.JSONDecodeError):
        data = {}
    data[counter] = int(data.get(counter, 0)) + by
    _atomic_write_json(p, data)


def _atomic_write_json(path: Path, data: dict) -> bool:
    """tmp file + os.replace atomic write. fsync on tmp before rename."""
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd = None
    tmp_name: str | None = None
    try:
        # Use NamedTemporaryFile for unique name in the same directory
        tmp = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False,
            dir=str(parent), prefix=path.stem + ".", suffix=".tmp",
        )
        tmp_name = tmp.name
        try:
            json.dump(data, tmp, ensure_ascii=False, sort_keys=True)
            tmp.flush()
            try:
                os.fsync(tmp.fileno())
            except OSError:
                pass  # fsync may fail on some filesystems; non-fatal
        finally:
            tmp.close()
        os.replace(tmp_name, str(path))
        tmp_name = None  # consumed by replace
        return True
    except OSError:
        return False
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def append_proposal(record: ProposalRecord) -> bool:
    """Append a proposal as one JSONL line. Returns True on success.

    On line-size > PIPE_BUF_CAP_BYTES: increments
    `writeback_split_rejected_total` counter and returns False (split-reject).
    NEVER silently truncates.
    """
    if not isinstance(record, ProposalRecord):
        return False
    payload = asdict(record)
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    encoded = line.encode("utf-8")

    if len(encoded) > PIPE_BUF_CAP_BYTES:
        _bump_telemetry("writeback_split_rejected_total")
        return False

    path = _proposals_path()
    fd = None
    try:
        fd = os.open(
            str(path),
            os.O_WRONLY | os.O_APPEND | os.O_CREAT,
            0o600,
        )
        # Single write() call for sub-PIPE_BUF atomicity
        os.write(fd, encoded)
        try:
            os.fsync(fd)
        except OSError:
            pass  # non-fatal on some fs
        return True
    except OSError:
        return False
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def read_index() -> dict[str, dict]:
    """Read the current index. Returns {} on missing/corrupt."""
    path = _index_path()
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text) if text.strip() else {}
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def update_index(mutator: Callable[[dict], dict]) -> bool:
    """Apply `mutator` to the current index and atomically rewrite.

    Read-modify-write race: concurrent processes can both read pre-state and
    both write. Single-writer model (one autopilot session per cwd) makes this
    acceptable; under contention the last-writer wins. For multi-session
    contention, callers must coordinate at a higher layer.
    """
    current = read_index()
    try:
        new = mutator(dict(current))
    except Exception:
        return False
    if not isinstance(new, dict):
        return False
    return _atomic_write_json(_index_path(), new)


def mark_status(proposal_id: str, status: Literal["acked", "rejected"]) -> bool:
    """Update the index entry for `proposal_id` to the given terminal status."""
    if not proposal_id or status not in ("acked", "rejected"):
        return False

    def _mutate(idx: dict) -> dict:
        entry = idx.get(proposal_id)
        if isinstance(entry, dict):
            entry["status"] = status
            entry["resolved_ts"] = time.time()
            idx[proposal_id] = entry
        return idx

    return update_index(_mutate)


def register_proposal(record: ProposalRecord) -> bool:
    """High-level: append to jsonl AND insert pending entry into index.

    Both writes succeed → True. If append succeeds but index update fails,
    log surface remains consistent (jsonl is canonical), return False so
    caller can retry index alone if desired.
    """
    if not append_proposal(record):
        return False

    def _mutate(idx: dict) -> dict:
        idx[record.id] = {
            "fingerprint": record.fingerprint,
            "target_skill_path": record.target_skill_path,
            "sha1_of_diff": record.sha1_of_diff,
            "status": record.status,
            "created_ts": record.created_ts,
        }
        return idx

    return update_index(_mutate)


def mark_applied(proposal_id: str, apply_record: dict) -> bool:
    """Record a successful apply against `proposal_id`.

    Per debate-1778236168-53dedd D3: this is a SEPARATE function from
    mark_status — it does NOT extend the Literal['acked','rejected'] type
    (Liskov-preserving for callers that introspect the status state machine).

    `apply_record` must include at minimum: apply_id, target_path,
    pre_image_sha1, post_image_sha1, applied_ts. The function:
      1. Appends a JSONL line to state/writeback/applied.jsonl (atomic
         O_APPEND single-write under PIPE_BUF_CAP_BYTES; if the line
         exceeds cap, drops `hunk_headers` field then retries; if still
         too long, increments writeback_apply_oversize_total telemetry
         and returns False without writing — caller sees clear failure,
         NOT silent truncation).
      2. Updates the index: sets `index[proposal_id].status = 'applied'`
         along with apply_id + applied_ts. The 'applied' status is a NEW
         index value (not part of mark_status's Literal); callers that
         only know 'pending'|'acked'|'rejected' will treat it as unknown.
    """
    if not isinstance(proposal_id, str) or not proposal_id:
        return False
    if not isinstance(apply_record, dict):
        return False
    required = ("apply_id", "target_path", "pre_image_sha1",
                "post_image_sha1", "applied_ts")
    for k in required:
        if k not in apply_record:
            return False

    payload = dict(apply_record)
    payload["proposal_id"] = proposal_id
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    encoded = line.encode("utf-8")

    if len(encoded) > PIPE_BUF_CAP_BYTES:
        slimmer = dict(payload)
        slimmer.pop("hunk_headers", None)
        slimmer["hunk_headers_dropped_for_size"] = True
        line = json.dumps(slimmer, ensure_ascii=False, sort_keys=True) + "\n"
        encoded = line.encode("utf-8")
        if len(encoded) > PIPE_BUF_CAP_BYTES:
            _bump_telemetry("writeback_apply_oversize_total")
            return False

    path = _writeback_dir() / "applied.jsonl"
    fd = None
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        os.write(fd, encoded)
        try:
            os.fsync(fd)
        except OSError:
            pass
    except OSError:
        return False
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    apply_id = apply_record.get("apply_id")
    applied_ts = apply_record.get("applied_ts")

    def _mutate(idx: dict) -> dict:
        entry = idx.get(proposal_id)
        if isinstance(entry, dict):
            entry["status"] = "applied"
            entry["apply_id"] = apply_id
            entry["applied_ts"] = applied_ts
            idx[proposal_id] = entry
        return idx

    return update_index(_mutate)


def gc_old_sidecars(now: float | None = None,
                    retention_days: int = 30) -> int:
    """Delete preimage sidecar files older than `retention_days` (by mtime).

    Returns count of files removed. Sidecars under
    state/writeback/preimages/<apply_id>.bin support rollback after apply;
    once retention has elapsed, the rollback option is forfeit and the
    file is reclaimable. Operator can still manually restore from git
    history if a regression appears past the retention window.

    Fail-soft: per-file unlink errors are skipped silently.
    """
    cur = time.time() if now is None else now
    if retention_days <= 0:
        return 0
    cutoff = cur - retention_days * 86400

    d = _writeback_dir() / "preimages"
    if not d.exists():
        return 0

    removed = 0
    for p in d.glob("*.bin"):
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if mtime > cutoff:
            continue
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def list_applied() -> list[dict]:
    """Return all applied.jsonl records as parsed dicts (oldest first).

    Skips any malformed line silently. For audit display + rollback lookup.
    """
    path = _writeback_dir() / "applied.jsonl"
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
            if isinstance(rec, dict):
                out.append(rec)
    except OSError:
        return []
    return out


def list_pending() -> list[dict]:
    """Return all proposals with status=='pending', oldest first."""
    idx = read_index()
    out: list[dict] = []
    for pid, entry in idx.items():
        if isinstance(entry, dict) and entry.get("status") == "pending":
            out.append({"id": pid, **entry})
    out.sort(key=lambda x: x.get("created_ts", 0))
    return out


def telemetry_snapshot() -> dict:
    """Read telemetry counters without mutation."""
    p = _telemetry_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8") or "{}")
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
