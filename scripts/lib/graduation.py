"""Validator advisory→blocking graduation state machine (Track 1).

Design: harness-debate `debate-1780722434-e5h19n` gen-2 converged (approved,
ontology_snapshot sha1 98f0fa4eca228fc36828c610544f765e287aa4cf). Decisions
D1-D5 + binding conditions C8 (three-part-graduation-atomicity), C9
(mtime-watermark stat-gate + static-clean-via-circuit-breaker), C10
(STATE_DIR-lazy + exception-leaves-counter-unchanged).

What this module owns
---------------------
- The consecutive-clean STREAK tracker for the TRACKED advisory validators
  (doc_code_drift, self_model_drift). `claim_verifier` is advisory-only and
  NOT graduation-eligible this generation (D3).
- `graduated_names()` — the GRADUATED_NAMES the validator registry concatenates
  onto `_BUILTIN` (D2/C3: concat, never in-place splice).
- `is_graduated(name)` — a PURE state read used by the validators to decide
  whether to emit [FAIL]+exit-nonzero on drift (graduated-mode) vs stay
  advisory (C8 part-2). This function and the module are import-safe and
  fail-soft so a graduated validator never crashes on a missing/garbled state.
- `run_tracked_scans_and_tick()` — the SINGLE shared tick helper (D1a/D1b),
  imported by handlers/session/init.py (SessionStart-amortized) AND
  cli/graduate_validator.py (`status`). NO cron, NO scheduler (the harness has
  none — init.py:245). The COUNTED EVENT is a fresh in-process scan() RESULT,
  not the SessionStart firing.
- `graduate()` / `demote()` — the token-gated flip and the safe un-flip.

Tick semantics (resolves the gen-1 self-doubt)
----------------------------------------------
Each tracked validator ticks at most once per rolling DEDUP_WINDOW (12h),
keyed to its own `last_scan_epoch` — so N=10 means 10 DISTINCT zero-drift live
scans over >=10 windows (~>=5 days), NOT 10 sessions. Within a window the tick
is skipped and the streak is left UNTOUCHED (never incremented on a skip — that
would re-introduce session-counting). When the window elapses:
  - C9 mtime-watermark stat-gate: if no tracked path's mtime exceeds the stored
    watermark, the content is provably identical to the last scan, so we reuse
    the last drift result WITHOUT the expensive rglob (latency win) and still
    advance the streak (static-clean accrual, justified by the circuit-breaker).
  - else run the validator's scan() in-process for a fresh drift count.
Then: total_drift==0 -> increment consecutive_clean (ready when >=N); else
hard-reset to 0. Every accounting branch is wrapped so an exception leaves the
counter at its PRIOR value (C10) — a flaky disk must never silently block
graduation NOR silently inflate the streak.

State file (lazy CLAUDE_HOME via lib.paths.STATE_DIR — C10):
  state/graduation-state.json   { "validators": { <name>: {entry} } }
  state/graduation-history.jsonl  append-only audit {ts, action, validator, ...}
  state/graduation-ready.flag    ready signal (emission auto; consumption gated)
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from .logging import jsonl_append, now_iso
from .paths import AGENTS_DIR, ATLAS_DIR, CLAUDE_HOME, STATE_DIR, ensure_dir

# ── policy constants ──
TRACKED: tuple[str, ...] = ("doc_code_drift", "self_model_drift")
GRADUATION_THRESHOLD: int = 10            # N consecutive clean runs (D1; > L2's 3)
DEDUP_WINDOW_SECONDS: int = 43_200        # 12h run-event dedup (D1a)
CIRCUIT_BREAKER_K: int = 5                # first FAIL within K post-grad runs → auto-demote (D5)
TOKEN_GRADUATE: str = "graduate-validator"   # advisory→blocking (risky dir) — §Mutation
TOKEN_DEMOTE: str = "apply-user-preference"  # blocking→advisory (safe dir) — D5 asymmetry

# Cheap mtime-watermark roots (C9). Stat'd, never walked, for the change-gate.
_WATERMARK_ROOTS: tuple[Path, ...] = (
    ATLAS_DIR,
    CLAUDE_HOME / "commands",
    CLAUDE_HOME / "skills",
    AGENTS_DIR,
    CLAUDE_HOME / "scripts" / "validators",
)


def _state_path() -> Path:
    # Lazy: read STATE_DIR at call time so run_units CLAUDE_HOME junction
    # isolation (and any future relocation) is honored — never a module-level
    # absolute path captured at import (C10).
    return STATE_DIR / "graduation-state.json"


def _history_path() -> Path:
    return STATE_DIR / "graduation-history.jsonl"


def _ready_flag_path() -> Path:
    return STATE_DIR / "graduation-ready.flag"


def _default_entry() -> dict[str, Any]:
    return {
        "consecutive_clean": 0,
        "graduated": False,
        "ready": False,
        "last_scan_epoch": 0.0,
        "last_watermark": 0.0,
        "last_total_drift": None,     # None = never scanned
        "runs_since_graduation": 0,
        "history_tail": [],           # <=12 recent {ts, total_drift, action}
    }


def load_state() -> dict[str, Any]:
    """Read the whole state. Fail-soft: missing/garbled → empty validators map."""
    path = _state_path()
    if not path.exists():
        return {"validators": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "validators" not in data:
            return {"validators": {}}
        if not isinstance(data["validators"], dict):
            data["validators"] = {}
        return data
    except (OSError, json.JSONDecodeError):
        return {"validators": {}}


def save_state(state: dict[str, Any]) -> bool:
    """Atomic-ish write. Fail-soft (returns False on IO error)."""
    try:
        ensure_dir(STATE_DIR)
        tmp = _state_path().with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(_state_path())
        return True
    except OSError:
        return False


def _entry(state: dict[str, Any], name: str) -> dict[str, Any]:
    vals = state.setdefault("validators", {})
    e = vals.get(name)
    if not isinstance(e, dict):
        e = _default_entry()
        vals[name] = e
    else:
        # Backfill any missing keys from default (forward-compatible).
        for k, v in _default_entry().items():
            e.setdefault(k, v)
    return e


def restore_streak(snapshot_state: dict[str, Any]) -> dict[str, Any]:
    """Merge a brain-snapshot graduation state into the LIVE state (state/).

    Called by lib.brain_store.restore — the brain/graduation/ snapshot is a
    parallel tree nothing else reads, so this is the ONLY write-back path into
    STATE_DIR/graduation-state.json (debate-1781359722-f16550 INV-restore).

    Per-validator: consecutive_clean = max(live, snapshot). A snapshot can only
    RAISE a streak (accumulate), never lower it. CRITICAL (re-validate-at-flip):
    any validator whose streak the snapshot RAISED has its last_scan_epoch reset
    to 0.0, which forces tick_validator to run a fresh live scan before the next
    flip (last_scan_epoch==0 bypasses the 12h dedup) — so a stale cross-machine
    streak can never graduate a locally-dirty validator without revalidation.
    Validators where live >= snapshot keep their (fresher) live epoch untouched.

    Returns a summary {restored: [names raised], unchanged: [names]}.
    """
    if not isinstance(snapshot_state, dict):
        return {"restored": [], "unchanged": []}
    snap_vals = snapshot_state.get("validators") or {}
    if not isinstance(snap_vals, dict) or not snap_vals:
        return {"restored": [], "unchanged": []}

    state = load_state()
    restored: list[str] = []
    unchanged: list[str] = []
    for name, snap_e in snap_vals.items():
        if not isinstance(snap_e, dict):
            continue
        live_e = _entry(state, name)
        live_streak = int(live_e.get("consecutive_clean") or 0)
        snap_streak = int(snap_e.get("consecutive_clean") or 0)
        if snap_streak > live_streak:
            live_e["consecutive_clean"] = snap_streak
            # Force re-validation: 0 epoch makes tick_validator scan immediately,
            # so the raised streak is confirmed against THIS machine before flip.
            live_e["last_scan_epoch"] = 0.0
            # Deliberately do NOT set e["ready"]=True: a raised-but-unconfirmed
            # streak must not be flip-eligible. graduate() checks e["ready"], and
            # only the forced tick_validator scan (epoch=0) sets ready after a real
            # zero-drift scan on THIS machine. So restore can never graduate a
            # locally-dirty validator off a stale cross-machine streak.
            restored.append(name)
        else:
            unchanged.append(name)
    save_state(state)
    return {"restored": sorted(restored), "unchanged": sorted(unchanged)}


# ── pure reads (used by validators — import-safe, fail-soft) ──
def graduated_names() -> tuple[str, ...]:
    """Validators currently graduated to blocking. The validator registry does
    `VALIDATOR_NAMES = _BUILTIN + graduated_names()` (D2/C3). Only TRACKED names
    can graduate, returned in alpha order for a deterministic registry."""
    try:
        state = load_state()
        out = [
            n for n in TRACKED
            if isinstance(state["validators"].get(n), dict)
            and state["validators"][n].get("graduated") is True
        ]
        return tuple(sorted(out))
    except Exception:
        return ()


def is_graduated(name: str) -> bool:
    """True iff `name` is currently graduated to blocking. PURE, fail-soft —
    the validators call this to decide [FAIL]-on-drift vs advisory (C8 p2)."""
    try:
        return name in graduated_names()
    except Exception:
        return False


# ── history / flag ──
def _append_history(record: dict[str, Any]) -> None:
    try:
        rec = {"ts": now_iso(), **record}
        jsonl_append(_history_path(), rec)
    except Exception:
        pass


def _push_tail(entry: dict[str, Any], total_drift: Any, action: str) -> None:
    tail = entry.setdefault("history_tail", [])
    tail.append({"ts": now_iso(), "total_drift": total_drift, "action": action})
    del tail[:-12]  # keep last 12


def _refresh_ready_flag(state: dict[str, Any]) -> None:
    """Emit (or clear) the ready-flag. Emission is auto-OK (D4); the flip that
    CONSUMES it is token-gated (cli/graduate_validator.py)."""
    ready = sorted(
        n for n in TRACKED
        if isinstance(state["validators"].get(n), dict)
        and state["validators"][n].get("ready") is True
        and state["validators"][n].get("graduated") is not True
    )
    try:
        if ready:
            ensure_dir(STATE_DIR)
            _ready_flag_path().write_text(
                json.dumps(
                    {"ts": now_iso(), "ready": ready, "threshold": GRADUATION_THRESHOLD},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        elif _ready_flag_path().exists():
            _ready_flag_path().unlink()
    except OSError:
        pass


def ready_validators() -> list[str]:
    """Names with streak>=N and not yet graduated (drives the SessionStart line)."""
    state = load_state()
    return sorted(
        n for n in TRACKED
        if isinstance(state["validators"].get(n), dict)
        and state["validators"][n].get("ready") is True
        and state["validators"][n].get("graduated") is not True
    )


# ── scan + tick ──
def _max_watermark() -> float:
    """Cheap stat-only max mtime over tracked roots (C9). Never walks files —
    a directory mtime changes when its entries change, which is a sufficient
    coarse change-signal for the latency gate. Fail-soft → 0.0."""
    best = 0.0
    for root in _WATERMARK_ROOTS:
        try:
            best = max(best, root.stat().st_mtime)
        except OSError:
            continue
    return best


def tick_validator(
    state: dict[str, Any],
    name: str,
    *,
    now: float,
    scan_fn: Callable[[str], int],
    watermark_fn: Callable[[], float] | None = None,
) -> str:
    """Tick ONE tracked validator against `state` (mutated in place). Returns the
    action taken: 'skip-dedup' | 'increment' | 'reset' | 'circuit-breaker-demote'
    | 'error-untouched'. Pure accounting — the caller persists state.

    `scan_fn(name)->int` is INJECTED by the caller (handlers/cli supply the real
    validators dispatcher `validators.graduation_scan_drift`; tests supply a
    stub). lib/ must not import validators (layering), so there is no default.

    C10: any exception leaves the entry's counters at their PRIOR value.
    """
    watermark_fn = watermark_fn or _max_watermark
    e = _entry(state, name)

    # D1a dedup: at most one counted run per 12h window. Streak UNTOUCHED on
    # skip. last_scan_epoch==0 means never scanned → always run the first scan
    # (a fresh install must be able to start its streak immediately).
    last_epoch = float(e.get("last_scan_epoch") or 0.0)
    if last_epoch > 0.0 and now - last_epoch < DEDUP_WINDOW_SECONDS:
        return "skip-dedup"

    # Snapshot prior counters so an exception can't half-mutate (C10).
    prior_clean = int(e.get("consecutive_clean") or 0)
    prior_drift = e.get("last_total_drift")
    prior_epoch = float(e.get("last_scan_epoch") or 0.0)
    prior_wm = float(e.get("last_watermark") or 0.0)
    try:
        wm = watermark_fn()
        if prior_drift is not None and wm <= prior_wm:
            # C9: content provably unchanged since last scan → reuse last result,
            # skip the expensive rglob, but still advance (static-clean accrual).
            total_drift = int(prior_drift)
        else:
            total_drift = int(scan_fn(name))
    except Exception:
        # Restore everything we may have touched and report untouched (C10).
        e["consecutive_clean"] = prior_clean
        e["last_total_drift"] = prior_drift
        e["last_scan_epoch"] = prior_epoch
        e["last_watermark"] = prior_wm
        return "error-untouched"

    e["last_scan_epoch"] = now
    e["last_watermark"] = wm
    e["last_total_drift"] = total_drift

    if e.get("graduated"):
        e["runs_since_graduation"] = int(e.get("runs_since_graduation") or 0) + 1

    if total_drift == 0:
        e["consecutive_clean"] = prior_clean + 1
        if e["consecutive_clean"] >= GRADUATION_THRESHOLD:
            e["ready"] = True
        _push_tail(e, total_drift, "increment")
        return "increment"

    # drift > 0 → hard reset
    e["consecutive_clean"] = 0
    e["ready"] = False
    # D5 circuit-breaker: a freshly-graduated validator that drifts within K runs
    # auto-demotes loudly (back to advisory) so it cannot wedge run_all.
    if e.get("graduated") and int(e.get("runs_since_graduation") or 0) <= CIRCUIT_BREAKER_K:
        e["graduated"] = False
        _push_tail(e, total_drift, "circuit-breaker-demote")
        _append_history({
            "action": "circuit_breaker_demote", "validator": name,
            "total_drift": total_drift,
            "runs_since_graduation": int(e.get("runs_since_graduation") or 0),
            "token_used": None,
        })
        return "circuit-breaker-demote"
    _push_tail(e, total_drift, "reset")
    return "reset"


def run_tracked_scans_and_tick(
    *, scan_fn: Callable[[str], int],
    now: float | None = None,
    watermark_fn: Callable[[], float] | None = None,
) -> dict[str, str]:
    """Tick all TRACKED validators once (the shared D1a/D1b helper). Loads state,
    ticks each, refreshes the ready-flag, persists. Fully fail-soft — returns a
    {name: action} map (empty on catastrophic failure). Safe to call from the
    interactive SessionStart path (per-validator dedup + mtime-watermark bound
    the cost; a slow/raising scan leaves that validator's counter untouched).

    `scan_fn(name)->int` is injected by the caller — see tick_validator (lib/
    must not import validators)."""
    if now is None:
        now = time.time()
    actions: dict[str, str] = {}
    try:
        state = load_state()
        for name in TRACKED:
            try:
                actions[name] = tick_validator(
                    state, name, now=now, scan_fn=scan_fn, watermark_fn=watermark_fn
                )
            except Exception:
                actions[name] = "error-untouched"
        _refresh_ready_flag(state)
        save_state(state)
    except Exception:
        return actions
    return actions


# ── flip / un-flip (token-gated; consumed by cli/graduate_validator.py) ──
class TokenError(PermissionError):
    """Raised when a graduation/demotion is attempted without the required token."""


def graduate(name: str, *, token: str) -> dict[str, Any]:
    """Advisory→blocking FLIP (D2). Requires TOKEN_GRADUATE *and* the ready-flag
    (streak>=N). Refuses early on a bad token or an un-ready validator. Mutates
    and persists state; appends history. Returns the post-flip entry."""
    if name not in TRACKED:
        raise ValueError(f"{name!r} is not graduation-eligible (TRACKED={TRACKED})")
    if (token or "").strip() != TOKEN_GRADUATE:
        raise TokenError(
            f"graduate requires HARNESS_MUTATION_TOKEN={TOKEN_GRADUATE!r} "
            f"(advisory→blocking is the risky direction; §Mutation gate)"
        )
    state = load_state()
    e = _entry(state, name)
    if e.get("graduated"):
        return e
    if not e.get("ready"):
        raise TokenError(
            f"{name!r} not ready: consecutive_clean="
            f"{e.get('consecutive_clean')}/{GRADUATION_THRESHOLD} — ready-flag absent"
        )
    e["graduated"] = True
    e["runs_since_graduation"] = 0
    _push_tail(e, e.get("last_total_drift"), "graduate")
    _refresh_ready_flag(state)
    save_state(state)
    _append_history({
        "action": "graduate", "validator": name,
        "prev_in_registry": False, "token_used": TOKEN_GRADUATE,
        "consecutive_clean": e.get("consecutive_clean"),
    })
    return e


def demote(name: str, *, token: str) -> dict[str, Any]:
    """Blocking→advisory un-flip (D5 safe direction). Needs only TOKEN_DEMOTE
    (apply-user-preference) — no ready-flag, for fast incident response. Resets
    the streak to 0 (anti-flap). Mutates and persists; appends history."""
    if name not in TRACKED:
        raise ValueError(f"{name!r} is not a tracked validator")
    tok = (token or "").strip()
    if tok not in (TOKEN_DEMOTE, TOKEN_GRADUATE):
        # graduate token is also accepted (a superset privilege); demote is safe.
        raise TokenError(
            f"demote requires HARNESS_MUTATION_TOKEN={TOKEN_DEMOTE!r}"
        )
    state = load_state()
    e = _entry(state, name)
    was = bool(e.get("graduated"))
    e["graduated"] = False
    e["consecutive_clean"] = 0
    e["ready"] = False
    e["runs_since_graduation"] = 0
    _push_tail(e, e.get("last_total_drift"), "demote")
    _refresh_ready_flag(state)
    save_state(state)
    _append_history({
        "action": "demote", "validator": name,
        "prev_in_registry": was, "token_used": tok,
    })
    return e


def status_report() -> list[dict[str, Any]]:
    """Per-tracked-validator status for the CLI `status` subcommand."""
    state = load_state()
    out: list[dict[str, Any]] = []
    for name in TRACKED:
        e = _entry(state, name)
        out.append({
            "validator": name,
            "graduated": bool(e.get("graduated")),
            "ready": bool(e.get("ready")),
            "consecutive_clean": int(e.get("consecutive_clean") or 0),
            "threshold": GRADUATION_THRESHOLD,
            "remaining": max(0, GRADUATION_THRESHOLD - int(e.get("consecutive_clean") or 0)),
            "last_total_drift": e.get("last_total_drift"),
            "last_scan_epoch": e.get("last_scan_epoch"),
        })
    return out
