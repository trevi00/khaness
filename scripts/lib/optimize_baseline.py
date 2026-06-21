"""optimize_baseline — cost/cache-driver baseline tracking for /harness-optimize.

Closes the harness-optimize gap: it is "read-only; no baseline tracking" — every run
recommends in a vacuum with no memory of how the harness's cost profile changed since
last time. This persists a timestamped snapshot of the deterministic cost/cache drivers
each run and computes the DELTA vs the last snapshot, so optimize can say "CLAUDE.md
grew 2.1KB since last run → cache-invalidation risk" instead of a static impression.

Drivers tracked (all affect prompt-cache hit-rate or per-turn token cost):
  claude_md_bytes   — the live L0 CLAUDE.md size (a cache-invalidating non-cached section)
  settings_bytes    — settings.json size
  mcp_server_count  — MCP servers (recomputed EVERY turn → per-turn cost)
  hook_event_count  — registered hook events
  commands_count / skills_count — surface that feeds skill-match + tool schema

Pure read + append-only snapshot log. Fail-soft (missing artifact → 0, never raises).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

_METRICS = ("claude_md_bytes", "settings_bytes", "mcp_server_count",
            "hook_event_count", "commands_count", "skills_count")


def _home(home) -> Path:
    if home is None:
        from .paths import CLAUDE_HOME
        return Path(CLAUDE_HOME)
    return Path(home)


def _bytes(p: Path) -> int:
    try:
        return p.stat().st_size if p.is_file() else 0
    except Exception:  # noqa: BLE001
        return 0


def _count(d: Path, pattern: str) -> int:
    try:
        return sum(1 for _ in d.glob(pattern)) if d.is_dir() else 0
    except Exception:  # noqa: BLE001
        return 0


def _json(p: Path) -> dict:
    try:
        v = json.loads(p.read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def current_metrics(home=None) -> dict:
    """Measure the cost/cache drivers right now. Pure read, fail-soft."""
    h = _home(home)
    settings = _json(h / "settings.json")
    hooks = settings.get("hooks") if isinstance(settings.get("hooks"), dict) else {}
    # MCP servers live in .claude.json (user/project) under "mcpServers"
    mcp = {}
    for cand in (h / ".claude.json", h.parent / ".claude.json"):
        m = _json(cand).get("mcpServers")
        if isinstance(m, dict) and m:
            mcp = m
            break
    return {
        # the LIVE L0 CLAUDE.md is at the home PARENT (~/CLAUDE.md), not ~/.claude/
        "claude_md_bytes": _bytes(h.parent / "CLAUDE.md") or _bytes(h / "CLAUDE.md"),
        "settings_bytes": _bytes(h / "settings.json"),
        "mcp_server_count": len(mcp),
        "hook_event_count": len([k for k in hooks if hooks.get(k)]),
        "commands_count": _count(h / "commands", "*.md"),
        "skills_count": _count(h / "skills", "**/*.md"),
    }


def _snapshots_path(home=None) -> Path:
    from .paths import STATE_DIR
    return Path(STATE_DIR) / "optimize" / "snapshots.jsonl"


def record_snapshot(home=None, ts_ms: int | None = None) -> dict:
    """Measure current drivers and append a timestamped snapshot. Returns the record.
    Fail-soft (a write error still returns the measured metrics)."""
    metrics = current_metrics(home)
    rec = {"ts_ms": int(ts_ms if ts_ms is not None else time.time() * 1000), **metrics}
    try:
        p = _snapshots_path(home)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass
    return rec


def last_snapshot(home=None) -> dict | None:
    """The most recent recorded snapshot, or None. Fail-soft."""
    p = _snapshots_path(home)
    if not p.is_file():
        return None
    last = None
    try:
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                last = json.loads(ln)
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        return None
    return last


def delta_from_last(home=None) -> dict:
    """Current drivers vs the last recorded snapshot. {current, previous_ts, deltas:
    {metric: cur-prev}, grew: [metrics that increased]}. previous_ts None on first run."""
    cur = current_metrics(home)
    prev = last_snapshot(home)
    if not prev:
        return {"current": cur, "previous_ts": None, "deltas": {}, "grew": []}
    deltas = {m: cur[m] - int(prev.get(m, 0)) for m in _METRICS}
    return {"current": cur, "previous_ts": prev.get("ts_ms"), "deltas": deltas,
            "grew": [m for m, d in deltas.items() if d > 0]}


def render_delta(home=None) -> str:
    d = delta_from_last(home)
    if d["previous_ts"] is None:
        return "[optimize baseline] first snapshot — no prior baseline to diff (run again later to see deltas)"
    lines = ["[optimize baseline] drivers vs last snapshot:"]
    for m in _METRICS:
        delta = d["deltas"][m]
        sign = f"{delta:+}" if delta else "0"
        flag = "  ↑ growth" if delta > 0 else ""
        lines.append(f"  {m}: {d['current'][m]} ({sign}){flag}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="optimize_baseline")
    ap.add_argument("--record", action="store_true", help="record a snapshot (else just show delta)")
    args = ap.parse_args(argv)
    if args.record:
        rec = record_snapshot()
        print(f"[optimize baseline] recorded snapshot ts={rec['ts_ms']}")
    print(render_delta())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
