"""ultrawork_plan — slice/wave plan persistence + resume for /harness-ultrawork.

Closes the ultrawork stub's biggest gap: "resume command: not first-class … re-running
produces a different graph each time, idempotent NO". ultrawork decomposes a task into
dependency waves of parallel slices, but the decomposition is LLM-generated and lost
after the run — so a re-attempt re-decomposes (non-deterministic) instead of resuming
where it stopped. This persists the plan + per-slice status so a re-run reads the SAME
plan and skips already-done slices.

Pure filesystem (the LLM still authors the plan; this just stores/queries it),
fail-soft (a bad record never blocks the run).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

_SLICE_STATUSES = ("pending", "done", "failed", "skipped")


def _dir(sid: str):
    from .paths import STATE_DIR
    safe = "".join(c for c in str(sid) if c.isalnum() or c in "._-") or "run"
    return Path(STATE_DIR) / "ultrawork" / safe


def _plan_path(sid: str) -> Path:
    return _dir(sid) / "plan.json"


def save_plan(sid: str, waves: list[list[str]], *, ts_ms: int | None = None) -> bool:
    """Persist the decomposition: waves = ordered list of waves, each a list of slice ids.
    Initializes every slice at status 'pending'. Returns True on write. Fail-soft.
    Idempotent-friendly: re-saving an EXISTING plan preserves prior slice statuses."""
    if not sid or not isinstance(waves, list):
        return False
    try:
        prior = load_plan(sid)
        prior_status = {s["id"]: s["status"] for w in (prior.get("waves") or []) for s in w} if prior else {}
        plan = {
            "sid": str(sid),
            "ts_ms": int(ts_ms if ts_ms is not None else time.time() * 1000),
            "waves": [
                [{"id": str(sl), "status": prior_status.get(str(sl), "pending")} for sl in wave]
                for wave in waves
            ],
        }
        p = _plan_path(sid)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:  # noqa: BLE001
        return False


def load_plan(sid: str) -> dict | None:
    p = _plan_path(sid)
    if not p.is_file():
        return None
    try:
        v = json.loads(p.read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else None
    except Exception:  # noqa: BLE001
        return None


def mark_slice(sid: str, slice_id: str, status: str) -> bool:
    """Record a slice's outcome (done|failed|skipped|pending). Returns True if the slice
    was found + updated. Fail-soft."""
    if status not in _SLICE_STATUSES:
        return False
    plan = load_plan(sid)
    if not plan:
        return False
    found = False
    for wave in plan.get("waves", []):
        for sl in wave:
            if sl.get("id") == str(slice_id):
                sl["status"] = status
                found = True
    if not found:
        return False
    try:
        _plan_path(sid).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:  # noqa: BLE001
        return False


def pending_slices(sid: str) -> list[str]:
    """Slice ids NOT yet done (status pending|failed) — what a resume must (re)run, in
    wave order. 'done'/'skipped' are excluded so a re-run picks up where it stopped."""
    plan = load_plan(sid)
    if not plan:
        return []
    out: list[str] = []
    for wave in plan.get("waves", []):
        for sl in wave:
            if sl.get("status") in ("pending", "failed"):
                out.append(sl.get("id"))
    return out


def progress(sid: str) -> dict:
    """{total, done, failed, pending, skipped, complete}. Pure read."""
    plan = load_plan(sid)
    counts = {"pending": 0, "done": 0, "failed": 0, "skipped": 0}
    if plan:
        for wave in plan.get("waves", []):
            for sl in wave:
                st = sl.get("status")
                if st in counts:
                    counts[st] += 1
    total = sum(counts.values())
    return {"total": total, **counts, "complete": total > 0 and counts["done"] + counts["skipped"] == total}


def render_progress(sid: str) -> str:
    p = progress(sid)
    if p["total"] == 0:
        return f"[ultrawork {sid}] no persisted plan"
    return (f"[ultrawork {sid}] {p['done']}/{p['total']} done "
            f"(failed={p['failed']}, pending={p['pending']}, skipped={p['skipped']}, "
            f"complete={p['complete']})")
