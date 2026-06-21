r"""operator_ledger — project-scoped JSONL outcome ledger (v15.10 D5).

Per debate-1778946602-jj7vxk D5:

  Storage layout
    state/operator-ledger/<project_id>/<agent_type>.jsonl
    state/operator-ledger/<project_id>/_HEADER.txt    (collision-bound doc)

  project_id = sha256(project_root_abs_path).hexdigest()[:12]   # 48-bit
    Collision bound (implementation note 3): with N project_roots the
    birthday-paradox collision probability is ≈ N² / 2^49. For N=1000
    that's ~10⁻⁹ — accepted as small-enough for operator-visible tag.
    Documented in the per-project _HEADER.txt on first write.

  task_hash = sha256(
      project_root_abs_path + b'\x00'
      + normalized_prompt + b'\x00'
      + json.dumps(sorted(tool_allowlist))
  ).hexdigest()[:16]
    normalized_prompt = re.sub(r'\s+', ' ', prompt).strip().lower()

  Record shape (per-line JSON, append-only):
    {
      "ts", "parent_sid", "agent_type", "task_hash",
      "failure_modes", "success", "evidence_paths",
      "breaker_state_before", "breaker_state_after",
      "critic_invoked", "critic_verdict", "replay_hash",
      "verified_by", "downstream_used",
      "human_override", "retry_count"
    }

  Side-channel: any record with verified_by="self_only" AND
  downstream_used=true emits a `ledger.verification_gap` event via the
  caller-supplied emit_fn (default no-op) for operator visibility.

  Human override:
    apply_override(project_root, agent_type, action, *, reason, token)
    Requires token == "configure-critic-policy" (enable-skill tier, see
    CLAUDE.md L0 row 14). Persists as the next ledger record with
    `human_override` populated; never mutates existing records.
    Actions: force_close, force_open, skip_critic_once.

    ⚠️ AUDIT-NOTE-ONLY — NOT a breaker control (deep-audit pass-2 rank 1):
    these override records have ZERO consumer. lib.breakers.composite
    (snapshot/try_acquire/record_failure) never reads operator_ledger /
    human_override, so force_close does NOT re-close a tripped breaker and
    force_open does NOT trip one. Running force_close in the belief the muted
    backend is now live is a correctness landmine. The REAL, wired operator
    control over breaker behavior is lib.breakers.config.apply_override (mutates
    threshold yaml that resolve_thresholds() reads) via cli/breaker_override.py.
    Do NOT wire a breaker.force_close() consumer to "fix" this — an in-process
    force_open re-closing a tripped breaker would CREATE a real safety-bypass.
    The token here is a self-supplied arg = accident/cron barrier, not an agent
    boundary (see ~/CLAUDE.md §Mutation honest threat-model).

Public surface (lock):
  - LedgerRecord (TypedDict-ish dict — schema documented, not enforced)
  - project_id_for(project_root) -> str
  - task_hash_for(project_root, prompt, tool_allowlist) -> str
  - ledger_path(project_root, agent_type) -> Path
  - header_path(project_root) -> Path
  - append_record(project_root, agent_type, record, *, emit_fn) -> Path
  - read_records(project_root, agent_type) -> Iterator[dict]
  - apply_override(project_root, agent_type, action, *, reason, token,
                   emit_fn) -> Path

Not in this module: cron-based weekly compaction. That belongs under the
`enable-cron-job` Mutation gate and lives wherever the other cron entries
live (engine/cron_*.py); reference implementation deferred to a follow-up.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Iterator, Literal

from .paths import STATE_DIR


# --- Constants -------------------------------------------------------------------

LEDGER_ROOT: Path = STATE_DIR / "operator-ledger"

PROJECT_ID_BITS: int = 48
PROJECT_ID_HEX_LEN: int = PROJECT_ID_BITS // 4   # 12 hex chars
TASK_HASH_HEX_LEN: int = 16

VALID_OVERRIDE_ACTIONS: tuple[str, ...] = (
    "force_close",
    "force_open",
    "skip_critic_once",
)

TOKEN_OVERRIDE: str = "configure-critic-policy"

OverrideAction = Literal["force_close", "force_open", "skip_critic_once"]


# --- ID + hash helpers ------------------------------------------------------------

def _normalize_path(project_root: str | os.PathLike) -> str:
    """Absolute, normalized, case-preserved on disk, lowercase only on Windows.

    On case-insensitive filesystems (Windows / default macOS) two roots
    differing only in case ARE the same project — normalize to lower for
    the hash so the project_id is stable.
    """
    p = os.path.abspath(os.fspath(project_root))
    if os.name == "nt":
        p = p.lower()
    return p


def project_id_for(project_root: str | os.PathLike) -> str:
    """sha256(abs_root_path).hexdigest()[:12]   — 48-bit project id."""
    raw = _normalize_path(project_root).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:PROJECT_ID_HEX_LEN]


def task_hash_for(
    project_root: str | os.PathLike,
    prompt: str,
    tool_allowlist: list[str] | tuple[str, ...] | set[str] | None,
) -> str:
    """16-hex task hash per D5 recipe (verbatim)."""
    normalized_prompt = re.sub(r"\s+", " ", prompt or "").strip().lower()
    tools = sorted(tool_allowlist or [])
    payload = (
        _normalize_path(project_root).encode("utf-8")
        + b"\x00"
        + normalized_prompt.encode("utf-8")
        + b"\x00"
        + json.dumps(tools, sort_keys=True).encode("utf-8")
    )
    return hashlib.sha256(payload).hexdigest()[:TASK_HASH_HEX_LEN]


# --- Path helpers -----------------------------------------------------------------

def _safe_segment(name: str) -> str:
    """Forbid path separators in agent_type to prevent traversal."""
    return name.replace("/", "_").replace("\\", "_")


def project_dir(project_root: str | os.PathLike) -> Path:
    return LEDGER_ROOT / project_id_for(project_root)


def ledger_path(project_root: str | os.PathLike, agent_type: str) -> Path:
    if not agent_type:
        raise ValueError("agent_type must be non-empty")
    return project_dir(project_root) / f"{_safe_segment(agent_type)}.jsonl"


def header_path(project_root: str | os.PathLike) -> Path:
    return project_dir(project_root) / "_HEADER.txt"


_HEADER_TEMPLATE = (
    "# Operator ledger — project_id = {project_id} (sha256[:12] of project_root)\n"
    "# project_root_absolute = {project_root}\n"
    "# Generated by lib.operator_ledger.append_record on first write.\n"
    "#\n"
    "# Collision bound (v15.10 implementation note 3):\n"
    "#   With N project_roots the birthday-paradox collision probability is\n"
    "#   ≈ N^2 / 2^{bits}. For N=1000 that's ~10^-9 — accepted.\n"
    "#\n"
    "# This file is documentation only; readers MUST NOT depend on its\n"
    "# format. Per-record JSONL lives in <agent_type>.jsonl alongside.\n"
).format


def _ensure_header(project_root: str | os.PathLike) -> None:
    proj_dir = project_dir(project_root)
    proj_dir.mkdir(parents=True, exist_ok=True)
    hp = header_path(project_root)
    if hp.exists():
        return
    hp.write_text(
        _HEADER_TEMPLATE(
            project_id=project_id_for(project_root),
            project_root=_normalize_path(project_root),
            bits=PROJECT_ID_BITS + 1,   # birthday bound uses ½, hence +1 bit
        ),
        encoding="utf-8",
    )


# --- Record schema ---------------------------------------------------------------

def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _coerce_record(record: dict[str, Any]) -> dict[str, Any]:
    """Apply lock-shape defaults so writers don't have to fill every field.

    Caller-supplied keys win; missing keys get the type-safe default.
    """
    out: dict[str, Any] = {
        "ts": _now_iso(),
        "parent_sid": None,
        "agent_type": None,
        "task_hash": None,
        "failure_modes": [],
        "success": False,
        "evidence_paths": [],
        "breaker_state_before": None,
        "breaker_state_after": None,
        "critic_invoked": False,
        "critic_verdict": None,
        "replay_hash": None,
        "verified_by": "self_only",
        "downstream_used": False,
        "human_override": None,
        "retry_count": 0,
    }
    for k, v in (record or {}).items():
        out[k] = v
    return out


# --- Public writer ---------------------------------------------------------------

def _noop_emit(event_type: str, payload: dict) -> None:
    return None


def append_record(
    project_root: str | os.PathLike,
    agent_type: str,
    record: dict[str, Any],
    *,
    emit_fn: Callable[[str, dict], None] = _noop_emit,
) -> Path:
    """Append a JSON record to <project_id>/<agent_type>.jsonl.

    Creates the project directory + _HEADER.txt on first write per project.
    Emits `ledger.verification_gap` when record.verified_by == "self_only"
    AND record.downstream_used is True (Architect self_doubt mitigation).
    Returns the path written to.
    """
    if not agent_type:
        raise ValueError("agent_type must be non-empty")

    rec = _coerce_record(record)
    if rec.get("agent_type") is None:
        rec["agent_type"] = agent_type
    if rec["agent_type"] != agent_type:
        raise ValueError(
            f"record.agent_type={rec['agent_type']!r} contradicts arg={agent_type!r}"
        )

    _ensure_header(project_root)
    path = ledger_path(project_root, agent_type)
    line = json.dumps(rec, ensure_ascii=False, sort_keys=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

    if rec["verified_by"] == "self_only" and rec["downstream_used"]:
        emit_fn(
            "ledger.verification_gap",
            {
                "project_id": project_id_for(project_root),
                "agent_type": agent_type,
                "task_hash": rec.get("task_hash"),
                "ts": rec["ts"],
            },
        )

    return path


def read_records(
    project_root: str | os.PathLike,
    agent_type: str,
) -> Iterator[dict[str, Any]]:
    """Yield records from the per-agent JSONL. Missing file → empty iterator.

    Malformed lines are silently skipped (with a stderr-style log to keep
    consistent with the other tolerant readers in lib/).
    """
    path = ledger_path(project_root, agent_type)
    if not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


# --- Human override ---------------------------------------------------------------

def apply_override(
    project_root: str | os.PathLike,
    agent_type: str,
    action: str,
    *,
    reason: str,
    token: str | None,
    emit_fn: Callable[[str, dict], None] = _noop_emit,
) -> Path:
    """Persist a human override as the next ledger record. Gated on token.

    Raises:
      ValueError      : empty agent_type / reason, or invalid action.
      PermissionError : token does not match TOKEN_OVERRIDE.
    """
    if not agent_type:
        raise ValueError("agent_type must be non-empty")
    if not reason or not reason.strip():
        raise ValueError("reason must be non-empty")
    if action not in VALID_OVERRIDE_ACTIONS:
        raise ValueError(
            f"action must be one of {VALID_OVERRIDE_ACTIONS}, got {action!r}"
        )
    if token != TOKEN_OVERRIDE:
        raise PermissionError(
            f"operator override requires Mutation token {TOKEN_OVERRIDE!r}, "
            f"got {token!r}"
        )

    rec: dict[str, Any] = {
        "agent_type": agent_type,
        "human_override": {
            "token": token,
            "action": action,
            "reason": reason.strip(),
            "ts": _now_iso(),
        },
    }
    path = append_record(project_root, agent_type, rec, emit_fn=emit_fn)
    emit_fn(
        "ledger.human_override",
        {
            "project_id": project_id_for(project_root),
            "agent_type": agent_type,
            "action": action,
            "reason": reason.strip(),
        },
    )
    return path


__all__ = [
    "LEDGER_ROOT",
    "OverrideAction",
    "TOKEN_OVERRIDE",
    "VALID_OVERRIDE_ACTIONS",
    "append_record",
    "apply_override",
    "header_path",
    "ledger_path",
    "project_dir",
    "project_id_for",
    "read_records",
    "task_hash_for",
]
