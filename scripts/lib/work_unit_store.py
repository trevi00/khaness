#!/usr/bin/env python3
"""lib/work_unit_store.py — auto-brain-update + session-continuity substrate.

Locked by debate-1781431026-af5f83 (converged gen-3, ontology SHA-1
32808a52c893). Implements:
  C1  throttled-autosave watermark — decides WHEN brain_store.save() runs, for
      BOTH autopilot AND non-autopilot Stop turns (≤ once per bounded interval),
      reusing the graduation-tick mtime-watermark family. NOT per-turn.
  C3  resume breadcrumb — state/work_unit/<sid>.json records what was being
      worked on so a new session resumes; 30-day GC wired into init.py.

PURE module (C6): does NOT import lib.insight_index — that keeps it out of the
L1 writer set entirely (no 4th-writer trap). The C2 work_unit digest that grows
L1 is emitted by handlers.stop.learner (an already-whitelisted writer/importer),
NOT here. This module only persists brain/ snapshots (via brain_store) and the
resume breadcrumb.

C4 (INV-save race KEPT, NOT prevented): brain_store.save() copies live JSONL with
shutil.copy2 (non-atomic) before parsing; a live appender in ANOTHER concurrent
session can still tear a line. That race is TOLERATED — torn lines are skipped and
the next save re-unions the dropped record. This module adds NO lock and makes NO
"structurally prevented" claim. The Stop-hook placement merely reduces (does not
eliminate) overlap: within one Stop sequence the appenders have already quiesced.

C5: this module NEVER git-commits. Auto-save touches working-tree/state only; the
operator commits brain/ in their normal push flow.

INV-save (debate-1781359722-f16550) preserved literally: there is still NO
SessionStart auto-tick (the path that raced live appenders). The auto-save tick
lives in the Stop lifecycle (handlers.stop.autopilot_continue), after the turn's
appenders are done.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

# Throttle intervals (seconds). 900s == 15min, the graduation-tick watermark
# family cadence. BOUNDS frequency only — a burst of work within one interval
# collapses to a single capture (accepted fidelity loss, C1).
SAVE_INTERVAL_SECONDS: int = 900
DIGEST_INTERVAL_SECONDS: int = 900
WORK_UNIT_RETENTION_DAYS: int = 30

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


def _claude_home() -> Path:
    env = os.environ.get("CLAUDE_HOME")
    if env:
        return Path(env)
    up = os.environ.get("USERPROFILE")
    if up:
        return Path(up) / ".claude"
    return Path.home() / ".claude"


def _work_unit_dir() -> Path:
    return _claude_home() / "state" / "work_unit"


def _safe_name(sid: str) -> str:
    """Collapse a session id to a path-safe filename stem (defends <sid>.json
    against traversal / illegal chars). Separators → '_', dot-runs collapsed and
    leading dots stripped so no '..' traversal token survives. Empty → 'unknown'."""
    s = _SAFE_RE.sub("_", str(sid or "").strip())
    s = re.sub(r"\.{2,}", "_", s).lstrip(".")
    return s[:128] or "unknown"


def _now(now: float | None) -> float:
    return time.time() if now is None else float(now)


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


# ── throttle watermark (C1) ─────────────────────────────────────────────────

def _watermark_path(name: str) -> Path:
    return _work_unit_dir() / f"{_safe_name(name)}_watermark.json"


def throttle_ok(name: str, now: float | None = None, interval: float = SAVE_INTERVAL_SECONDS) -> bool:
    """True iff at least `interval` seconds elapsed since the last mark(name) (or
    no watermark exists yet). Pure read — does NOT mark. A torn/garbage watermark
    is treated as 'elapsed' (fail-open toward saving)."""
    now = _now(now)
    wm = _read_json(_watermark_path(name))
    if not wm:
        return True
    try:
        last = float(wm.get("last_ts") or 0.0)
    except (TypeError, ValueError):
        return True
    return (now - last) >= float(interval)


def mark(name: str, now: float | None = None) -> None:
    """Stamp the watermark for `name` at `now`. Fail-soft (best-effort)."""
    try:
        _write_json_atomic(_watermark_path(name), {"last_ts": _now(now)})
    except OSError:
        pass


# ── forward-plan capture (handoff-replacement: "what's NEXT", not just "what was done") ──

# Lines that announce remaining/next work. The breadcrumb captures the PAST (summary);
# this captures the FUTURE so a resumed session sees the plan, closing the last gap vs
# HANDOFF.md's next_action. Markers are matched case-insensitively, KO + EN.
_NEXT_MARKER_RE = re.compile(
    r"(남은|다음(?!\s*과)|이어서|후속|할\s*일|TODO|FIXME|"
    r"\bnext\b|\bremaining\b|\bpending\b|follow[- ]?up|\bthen\b)",
    re.IGNORECASE,
)
# strip leading markdown list/quote/heading noise so the surfaced line reads cleanly
_LINE_LEAD_RE = re.compile(r"^[\s>#*\-•\d.)\]]+")


def extract_next_steps(text: str, max_chars: int = 200) -> str:
    """Heuristically pull the forward-looking 'next steps' from an assistant message
    (the lines that announce remaining/next work). Returns '' when none found.
    Advisory/over-inclusive by design — a resume HINT, not a contract."""
    if not text:
        return ""
    picked: list[str] = []
    seen: set[str] = set()
    for raw in str(text).splitlines():
        line = _LINE_LEAD_RE.sub("", raw).strip()
        if not line or not _NEXT_MARKER_RE.search(line):
            continue
        line = re.sub(r"\s+", " ", line)
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        picked.append(line)
        if sum(len(p) for p in picked) >= max_chars:
            break
    return " / ".join(picked)[:max_chars].rstrip()


# ── resume breadcrumb (C3) ──────────────────────────────────────────────────

def record_work_unit(
    sid: str,
    cwd: str,
    summary: str,
    now: float | None = None,
    *,
    status: str = "active",
    next_steps: str = "",
    extra: dict | None = None,
) -> Path | None:
    """Write/update state/work_unit/<sid>.json — the resume breadcrumb of what
    was being worked on (summary = PAST) PLUS next_steps (FUTURE, handoff-style).
    Overwrites in place (one row per session, REPLACES not ADDS). Fail-soft."""
    try:
        rec: dict[str, Any] = {
            "sid": str(sid),
            "cwd": str(cwd or ""),
            "summary": str(summary or "")[:500],
            "next_steps": str(next_steps or "")[:300],
            "status": str(status),
            "last_activity_ts": _now(now),
        }
        if extra:
            rec["extra"] = extra
        path = _work_unit_dir() / f"{_safe_name(sid)}.json"
        _write_json_atomic(path, rec)
        return path
    except OSError:
        return None


def read_work_unit(sid: str) -> dict | None:
    return _read_json(_work_unit_dir() / f"{_safe_name(sid)}.json")


# ── kha SDLC one-way state mirror (READ side) ───────────────────────────────
# debate-1781871696-sdoggn (converged gen-3, 24-field LOCK). PURE read-only
# derive of a gsd/kha `.planning/STATE.md` into a tiny breadcrumb dict. The
# WRITE side rides the existing every-Stop record_work_unit `extra=` (in
# handlers/stop/autopilot_continue.py — the sole breadcrumb writer; the LOCK
# named the learner but Generator-phase reading found autopilot_continue owns
# the breadcrumb, so the site was corrected with operator sign-off). NEVER
# writes back into .planning/ (one-way). Stays out of the insight_index writer
# whitelist — this module imports lib.frontmatter only, NOT lib.insight_index,
# so the documented C6 purity holds.

_KHA_MAX_PARENT_LEVELS = 3  # self + up to 3 parents (matches gsd init.py:69)


def read_planning_state(cwd: str | None) -> dict | None:
    """Resolve <cwd>/.planning/STATE.md (ascending <=3 parents) and extract the
    gsd state-sync frontmatter into {project,current_phase,current_plan,status}.

    Returns None — a counted no-op for the caller's telemetry — when no STATE.md
    is reachable, it has no valid `---` frontmatter, or no usable field is present
    (e.g. a non-gsd STATE.md like a hand-maintained one with no synced frontmatter).
    gsd `state-sync` emits snake_case keys (current_phase/current_plan/status/
    milestone_name) per get-shit-done/bin/lib/state.cjs buildStateFrontmatter; the
    parser is lib.frontmatter.parse_frontmatter (the minimal no-PyYAML reader).
    PURE + fail-soft: reads only, never raises into the Stop hook chain."""
    try:
        from lib.frontmatter import parse_frontmatter

        node = Path(cwd) if cwd else Path.cwd()
        state_path: Path | None = None
        for _ in range(_KHA_MAX_PARENT_LEVELS + 1):
            candidate = node / ".planning" / "STATE.md"
            if candidate.is_file():
                state_path = candidate
                break
            if node.parent == node:  # filesystem / drive root
                break
            node = node.parent
        if state_path is None:
            return None

        parsed = parse_frontmatter(state_path)
        if not parsed:
            return None
        meta, _body = parsed
        kha = {
            "project": meta.get("milestone_name") or meta.get("milestone") or "",
            "current_phase": meta.get("current_phase") or meta.get("current_phase_name") or "",
            "current_plan": meta.get("current_plan") or "",
            "status": meta.get("status") or "",
        }
        # Require at least one meaningful field — else a STATE.md with frontmatter
        # but no gsd keys (or all-empty) is a no-op, not a row of empty strings.
        if not any(v for v in kha.values()):
            return None
        return kha
    except Exception:
        return None


def _norm_cwd(p: str) -> str:
    s = str(p or "").replace("\\", "/").rstrip("/")
    return s.casefold() if os.name == "nt" else s


def _cwd_match(query: str, stored: str) -> bool:
    """True iff `stored` breadcrumb cwd is the SAME project tree as `query` —
    normalized (separator + Windows case) and segment-aware ancestor/descendant
    tolerant, so a session launched at <proj> still resumes a breadcrumb recorded
    at <proj>/scripts (and vice-versa). Brittle exact-string match was hiding the
    work-resume line + the folded work-tree node (debate-1781493074 live demo)."""
    if not stored:
        return False
    q, s = _norm_cwd(query), _norm_cwd(stored)
    return q == s or s.startswith(q + "/") or q.startswith(s + "/")


def latest_work_unit(
    cwd: str | None = None,
    now: float | None = None,
    max_age_seconds: float = WORK_UNIT_RETENTION_DAYS * 86400,
) -> dict | None:
    """Most-recent non-stale breadcrumb (optionally cwd-filtered, same-tree
    tolerant), by last_activity_ts. Skips watermark sidecars and stale/expired
    rows. Used by the SessionStart resume surface."""
    d = _work_unit_dir()
    if not d.is_dir():
        return None
    now = _now(now)
    best: dict | None = None
    best_ts = -1.0
    try:
        names = sorted(d.glob("*.json"))
    except OSError:
        return None
    for p in names:
        if p.name.endswith("_watermark.json"):
            continue
        rec = _read_json(p)
        if not rec or "last_activity_ts" not in rec:
            continue
        try:
            ts = float(rec.get("last_activity_ts") or 0.0)
        except (TypeError, ValueError):
            continue
        if (now - ts) > max_age_seconds:
            continue
        if cwd is not None and not _cwd_match(cwd, rec.get("cwd", "")):
            continue
        if ts > best_ts:
            best_ts, best = ts, rec
    return best


def gc_old_work_units(now: float | None = None, max_age_days: int = WORK_UNIT_RETENTION_DAYS) -> int:
    """Prune state/work_unit/*.json (incl. watermark sidecars) whose mtime is
    older than max_age_days. Returns count removed. Fail-soft. Mirrors the
    30-day SessionStart-amortized GC family (writeback/evaluator/subagent)."""
    d = _work_unit_dir()
    if not d.is_dir():
        return 0
    now = _now(now)
    cutoff = now - (max_age_days * 86400)
    removed = 0
    try:
        candidates = list(d.glob("*.json"))
    except OSError:
        return 0
    for p in candidates:
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except OSError:
            continue
    return removed


# ── brain divergence + autosave (C1) ────────────────────────────────────────

def brain_has_unsaved_work() -> bool:
    """True iff the live L1/L2 brain state has records absent from the committed
    brain/ snapshot (work-unit-happened gate). Cheap-ish: brain_store.status()
    reads the compacted JSONL. Fail-soft → False (don't save on a status error)."""
    try:
        from lib import brain_store
        st = brain_store.status()
    except Exception:
        return False
    for layer in ("l1", "l2"):
        layer_stat = st.get(layer) or {}
        for file_stat in layer_stat.values():
            if isinstance(file_stat, dict) and int(file_stat.get("live_not_in_brain") or 0) > 0:
                return True
    return False


def maybe_autosave(now: float | None = None) -> dict | None:
    """C1 throttled auto-save. Gate order (cheapest first):
      1. throttle: ≥ SAVE_INTERVAL_SECONDS since last save (one small file read)
      2. work-unit-happened: live brain diverged from snapshot
    Only then brain_store.save() + mark. Returns the save summary, or None when
    skipped/failed. Fail-soft: never raises (Stop-hook side-effect discipline).

    Deliberately does NOT mark on the no-divergence path — so a change that lands
    just after the interval elapses is captured on the NEXT Stop rather than
    waiting a full interval. status() re-runs each post-interval idle turn; that
    is the accepted cost of not delaying a real save."""
    now = _now(now)
    try:
        if not throttle_ok("save", now, SAVE_INTERVAL_SECONDS):
            return None
        if not brain_has_unsaved_work():
            return None
        from lib import brain_store
        summary = brain_store.save()
        mark("save", now)
        return summary
    except Exception:
        return None


def force_autosave(now: float | None = None) -> dict | None:
    """Unconditional definitive save for an authoritative autopilot terminal
    transition (write_state done/failed, C1). Bypasses the throttle + divergence
    gates but still marks the watermark. Fail-soft → None on error."""
    now = _now(now)
    try:
        from lib import brain_store
        summary = brain_store.save()
        mark("save", now)
        return summary
    except Exception:
        return None


# ── digest throttle (C2 — consulted by handlers.stop.learner) ───────────────

def should_emit_digest(now: float | None = None) -> bool:
    """True iff the work_unit digest may be emitted this Stop (≥
    DIGEST_INTERVAL_SECONDS since the last digest). learner.py owns the emit;
    this only throttles it so L1 does not grow per-turn (C1 'NOT per-turn')."""
    return throttle_ok("digest", now, DIGEST_INTERVAL_SECONDS)


def mark_digest_emitted(now: float | None = None) -> None:
    mark("digest", now)
