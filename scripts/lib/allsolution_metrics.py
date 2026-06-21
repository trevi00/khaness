"""allsolution_metrics — composition break-frequency instrumentation.

Closes the harness-allsolution self-doubt: "break 빈도 측정은 별도 metric 필요
(현재 미구현)" (commands/harness-allsolution.md). allsolution composes
interview → research → autopilot; its biggest stated risk is a SINGLE break point
(if interview dies the whole chain dies). Until now there was no way to see WHICH
phase breaks or how often.

This is the deterministic consumer the markdown orchestrator calls at each phase
boundary: `record_phase(sid, phase, status)` appends one line per phase outcome, and
`break_summary()` aggregates across all runs into per-phase break rates + the most
fragile phase. Pure filesystem (no LLM), fail-soft (a bad record never raises into the
orchestrator). Mirrors the debate-engine deterministic-seam pattern (advisory signal →
deterministic recorder + reader).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

# The composition phases (commands/harness-allsolution.md Protocol A–D).
PHASES = ("A_interview", "B_research", "C_autopilot", "D_synthesis")
# ok = phase completed; broke = phase failed/aborted; escalated = handed to user
# (hard_cap etc.); skipped = intentionally not run (e.g. research no-op).
STATUSES = ("ok", "broke", "escalated", "skipped")


def _runs_dir():
    from .paths import STATE_DIR
    return Path(STATE_DIR) / "allsolution" / "runs"


def _run_path(sid: str) -> Path:
    safe = "".join(c for c in str(sid) if c.isalnum() or c in "._-") or "run"
    return _runs_dir() / f"{safe}.jsonl"


def record_phase(sid: str, phase: str, status: str, *, detail: str | None = None,
                 ts_ms: int | None = None) -> bool:
    """Append one phase outcome for an allsolution run. Returns True on write.
    Fail-soft: an unknown phase/status or a write error returns False, never raises —
    the orchestrator must never break because instrumentation failed."""
    if phase not in PHASES or status not in STATUSES or not sid:
        return False
    try:
        p = _run_path(sid)
        p.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts_ms": int(ts_ms if ts_ms is not None else time.time() * 1000),
               "phase": phase, "status": status}
        if detail:
            rec["detail"] = str(detail)[:300]
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception:  # noqa: BLE001 — fail-soft
        return False


def run_phases(sid: str) -> list[dict]:
    """The phase records for one run, in order. Fail-soft → []."""
    p = _run_path(sid)
    if not p.is_file():
        return []
    out: list[dict] = []
    try:
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        return []
    return out


def break_summary() -> dict:
    """Aggregate break frequency across ALL allsolution runs.

    Returns {runs, by_phase: {phase: {ok, broke, escalated, skipped, reached,
    break_rate}}, most_fragile_phase, total_breaks}. break_rate = (broke+escalated) /
    reached, where reached = how many runs got to that phase at all. Pure read."""
    by_phase: dict[str, dict[str, int]] = {
        ph: {"ok": 0, "broke": 0, "escalated": 0, "skipped": 0, "reached": 0} for ph in PHASES}
    runs = 0
    d = _runs_dir()
    if d.is_dir():
        for fp in sorted(d.glob("*.jsonl")):
            recs = run_phases(fp.stem)
            if not recs:
                continue
            runs += 1
            for r in recs:
                ph, st = r.get("phase"), r.get("status")
                if ph in by_phase and st in STATUSES:
                    by_phase[ph][st] += 1
                    by_phase[ph]["reached"] += 1

    total_breaks = 0
    for ph, c in by_phase.items():
        breaks = c["broke"] + c["escalated"]
        total_breaks += breaks
        c["break_rate"] = round(breaks / c["reached"], 3) if c["reached"] else 0.0
    # most fragile = highest break_rate among phases actually reached
    reached = [(ph, c) for ph, c in by_phase.items() if c["reached"]]
    most_fragile = max(reached, key=lambda kc: kc[1]["break_rate"])[0] if reached else None
    return {"runs": runs, "by_phase": by_phase,
            "most_fragile_phase": most_fragile, "total_breaks": total_breaks}


def render_break_summary() -> str:
    s = break_summary()
    if s["runs"] == 0:
        return "[allsolution] no instrumented runs yet (break-metric forward-looking)"
    lines = [f"[allsolution] {s['runs']} run(s), {s['total_breaks']} break(s); "
             f"most fragile phase: {s['most_fragile_phase']}"]
    for ph in PHASES:
        c = s["by_phase"][ph]
        if c["reached"]:
            lines.append(f"  {ph}: reached={c['reached']} ok={c['ok']} broke={c['broke']} "
                         f"escalated={c['escalated']} break_rate={c['break_rate']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    print(render_break_summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
