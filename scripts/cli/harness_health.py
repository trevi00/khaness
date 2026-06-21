#!/usr/bin/env python3
"""Harness ecosystem health snapshot — single-pane view.

Aggregates state across the 16-step skill_lint pipeline + debate engine
+ telemetry into one operator-facing dashboard. Read-only.

Sections:
  1. Skills inventory (tree × shape distribution + size stats)
  2. Lint status (active R002 + R003 trigger)
  3. Debate state (sessions count + pending doubts + recent activity)
  4. Telemetry summary (record counts + last writes)
  5. Tests presence (unit + regression test counts)

Usage:
    cd ~/.claude/scripts
    python -m cli.harness_health           # text dashboard
    python -m cli.harness_health --json    # machine-readable

Origin: 17th closing wave (2026-05-05) — replaces ad-hoc inspection of
multiple individual CLIs (skill_lint_report / debate_doubts /
skill_trigger_eval) with a single periodic-check entry point.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.paths import SKILLS_DIR, STATE_DIR, TELEMETRY_DIR  # noqa: E402


def section_skills_inventory() -> dict[str, Any]:
    """Tree × shape distribution + total + size stats."""
    from lib.frontmatter import parse_frontmatter
    from lib.skill_lint import classify_shape

    by_tree_shape: dict[str, dict[str, int]] = {}
    total = 0
    sizes: list[int] = []
    if SKILLS_DIR.exists():
        for md in SKILLS_DIR.rglob("*.md"):
            name = md.name.lower()
            if name in ("readme.md", "changelog.md", "todo.md"):
                continue
            if md.name.startswith("_template"):
                continue
            res = parse_frontmatter(md)
            meta = res[0] if res else {}
            shape = classify_shape(meta)
            tree = md.relative_to(SKILLS_DIR).as_posix().split("/")[0]
            by_tree_shape.setdefault(tree, {})[shape] = (
                by_tree_shape.setdefault(tree, {}).get(shape, 0) + 1
            )
            total += 1
            try:
                sizes.append(md.stat().st_size)
            except OSError:
                pass

    sizes.sort()
    size_stats = {
        "n": len(sizes),
        "median": sizes[len(sizes) // 2] if sizes else 0,
        "p90": sizes[int(len(sizes) * 0.9)] if sizes else 0,
        "max": sizes[-1] if sizes else 0,
    }
    return {
        "total_skills": total,
        "trees_count": len(by_tree_shape),
        "size_bytes": size_stats,
        "by_tree": {t: dict(d) for t, d in sorted(by_tree_shape.items())},
    }


def section_lint_status() -> dict[str, Any]:
    """Active R002 violations + R003 trigger state."""
    try:
        from cli.skill_lint_report import (  # type: ignore[import]
            load_records, latest_per_path, lint, evaluate_r003_trigger,
            file_size_stats, R002_DEFAULT_BYTES,
        )
        records = load_records()
        if not records:
            return {"telemetry_present": False}
        latest = latest_per_path(records)
        violations = lint(latest, threshold_bytes=R002_DEFAULT_BYTES)
        trigger = evaluate_r003_trigger(
            {"file_size_stats": file_size_stats(latest),
             "r002_violations_count": len(violations)},
            latest=latest,
        )
        return {
            "telemetry_present": True,
            "telemetry_records": len(records),
            "skills_observed": len(latest),
            "active_r002_violations": len(violations),
            "r002_threshold_bytes": R002_DEFAULT_BYTES,
            "r003_trigger_fired": trigger["fired"],
            "r003_clauses": trigger["clauses"],
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def section_debate_state() -> dict[str, Any]:
    """Debate sessions + pending self_doubts + last activity."""
    try:
        from cli.debate_doubts import collect_doubts, count_pending  # type: ignore[import]
        all_doubts = collect_doubts(since_epoch=None)
        pending = count_pending()
        debates_dir = STATE_DIR / "debates"
        sessions: list[str] = []
        if debates_dir.exists():
            sessions = sorted(d.name for d in debates_dir.iterdir() if d.is_dir())
        return {
            "total_sessions": len(sessions),
            "doubts_logged": len(all_doubts),
            "doubts_pending": pending,
            "doubts_acknowledged": len(all_doubts) - pending,
            "recent_sessions": sessions[-5:] if sessions else [],
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def section_strict_design() -> dict[str, Any]:
    """Strict-design intent triggers — total / pending / acknowledged."""
    try:
        from lib.advisory_ack import REGISTRY
        from lib.telemetry_read import iter_events
        ack = REGISTRY["strict_design"].load()
        total = 0
        pending = 0
        for r in iter_events("debate-triggers"):
            if r.get("strict_design") is True:
                total += 1
                if r.get("ts") not in ack:
                    pending += 1
        return {
            "total": total,
            "pending": pending,
            "acknowledged": total - pending,
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def section_telemetry_summary() -> dict[str, Any]:
    """Telemetry file presence + sizes."""
    out: dict[str, Any] = {"dir": str(TELEMETRY_DIR)}
    if not TELEMETRY_DIR.exists():
        return {**out, "present": False}
    files: list[dict] = []
    for f in sorted(TELEMETRY_DIR.glob("*.jsonl")):
        try:
            size = f.stat().st_size
            with f.open("r", encoding="utf-8") as h:
                lines = sum(1 for _ in h)
            files.append({"name": f.name, "size_bytes": size, "lines": lines})
        except Exception:
            files.append({"name": f.name, "error": "stat-failed"})
    return {**out, "present": True, "files": files}


def section_tests_presence() -> dict[str, Any]:
    """Test files count (suggestive — does not run)."""
    tests_dir = _SCRIPTS / "tests"
    if not tests_dir.exists():
        return {"present": False}
    test_files = sorted(p.name for p in tests_dir.glob("test_*.py"))
    return {
        "present": True,
        "test_files": len(test_files),
        "files": test_files,
    }


def section_phase_tree(handoff_path: Path | None = None) -> dict[str, Any]:
    """HANDOFF.md phase-tree drift status — autonomous closure 3rd surface.

    Default path: ~/.claude/HANDOFF.md (canonical operational HANDOFF).
    Tests inject a tmpfile path via the argument. Layout:
      {present: bool, drift: bool | None, path: str, error: str | None}
    Fail-soft: any error returns {present: True, error: "...", drift: None}.
    """
    if handoff_path is None:
        handoff_path = Path.home() / ".claude" / "HANDOFF.md"
    out: dict[str, Any] = {"path": str(handoff_path)}
    if not handoff_path.is_file():
        return {**out, "present": False}
    try:
        from lib.handoff_drift import check_drift, render_from_handoff
        text = handoff_path.read_text(encoding="utf-8")
        tree = render_from_handoff(text)
        return {**out, "present": True, "drift": check_drift(text, tree)}
    except Exception as e:
        return {**out, "present": True, "drift": None,
                "error": f"{type(e).__name__}: {e}"}


def section_writeback() -> dict[str, Any]:
    """Writeback queue health — surface harness-researcher proposals that
    haven't been reviewed yet + accumulated telemetry counters.

    Layout:
      {pending_count: int, total_count: int, by_status: {pending,acked,
       rejected: int}, telemetry: {<counter>: int}, error: str | None}
    Fail-soft per dashboard discipline.
    """
    try:
        from lib.writeback_store import read_index, telemetry_snapshot
        idx = read_index()
        by_status: dict[str, int] = {}
        for entry in idx.values():
            if isinstance(entry, dict):
                st = entry.get("status", "?")
                by_status[st] = by_status.get(st, 0) + 1
        return {
            "pending_count": int(by_status.get("pending", 0)),
            "total_count": len(idx),
            "by_status": by_status,
            "telemetry": telemetry_snapshot(),
        }
    except Exception as e:
        return {"pending_count": 0, "total_count": 0, "by_status": {},
                "telemetry": {}, "error": f"{type(e).__name__}: {e}"}


def section_audit_log() -> dict[str, Any]:
    """Subagent invocation audit log — total sessions + per-agent counts.

    Closes the operator-surface gap for A2 wiring + post-tool hook (commit
    7aff8b7 + agent_invocation_audit hook). Reads
    ``state/subagent_invocations/*.jsonl`` and aggregates:

    - ``total_sessions``: number of distinct session JSONL files.
    - ``total_invocations``: sum of records across all sessions.
    - ``by_agent``: per-agent invocation count (top 10).
    - ``by_origin``: breakdown by ``extra.origin`` field (E2 closure
      2026-05-10) — split hook vs directive vs manual vs untagged
      (legacy records pre-D4 land in ``"_untagged"``).
    - ``recent_invocations``: last 5 records (newest first by ts) with
      sid + agent + role for quick scan.
    - ``hook_failed_count``: total entries in
      ``telemetry/audit-log-hook-failed.jsonl`` (E3 closure 2026-05-10)
      — surfaces silent hook regression that the fail-soft path would
      otherwise hide.

    Layout ensures fail-soft: any I/O exception → keys present with zeros
    + ``error`` field, never raises.
    """
    out: dict[str, Any] = {
        "total_sessions": 0,
        "total_invocations": 0,
        "by_agent": {},
        "by_origin": {},
        "recent_invocations": [],
        "hook_failed_count": 0,
    }
    try:
        invocations_dir = STATE_DIR / "subagent_invocations"
        if not invocations_dir.exists():
            # Even with no invocations, surface hook_failed_count from telemetry
            try:
                hook_failed_path = TELEMETRY_DIR / "audit-log-hook-failed.jsonl"
                if hook_failed_path.exists():
                    with hook_failed_path.open("r", encoding="utf-8") as f:
                        out["hook_failed_count"] = sum(
                            1 for line in f if line.strip()
                        )
            except Exception:
                pass
            return out
        sessions = sorted(invocations_dir.glob("*.jsonl"))
        out["total_sessions"] = len(sessions)
        all_records: list[dict[str, Any]] = []
        for jsonl in sessions:
            try:
                text = jsonl.read_text(encoding="utf-8")
            except OSError:
                continue
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    all_records.append(rec)
        out["total_invocations"] = len(all_records)
        # Per-origin counts (E2)
        by_origin: dict[str, int] = {}
        for rec in all_records:
            extra = rec.get("extra") or {}
            origin = extra.get("origin", "_untagged") if isinstance(extra, dict) else "_untagged"
            by_origin[origin] = by_origin.get(origin, 0) + 1
        out["by_origin"] = dict(sorted(by_origin.items(), key=lambda kv: -kv[1]))
        # Per-agent counts (top 10)
        by_agent: dict[str, int] = {}
        for rec in all_records:
            name = rec.get("agent", "?")
            by_agent[name] = by_agent.get(name, 0) + 1
        out["by_agent"] = dict(
            sorted(by_agent.items(), key=lambda kv: -kv[1])[:10]
        )
        # Recent invocations (newest first by ts; lexicographic on Z-format)
        sorted_recent = sorted(
            all_records,
            key=lambda r: r.get("ts", ""),
            reverse=True,
        )[:5]
        out["recent_invocations"] = [
            {
                "ts": r.get("ts", ""),
                "sid": r.get("sid", ""),
                "agent": r.get("agent", ""),
                "role": r.get("role", ""),
            }
            for r in sorted_recent
        ]
        # Hook failure surface (E3)
        try:
            hook_failed_path = TELEMETRY_DIR / "audit-log-hook-failed.jsonl"
            if hook_failed_path.exists():
                with hook_failed_path.open("r", encoding="utf-8") as f:
                    out["hook_failed_count"] = sum(1 for line in f if line.strip())
        except Exception:
            # Never fail dashboard render because of telemetry read trouble
            pass
        return out
    except Exception as e:
        return {**out, "error": f"{type(e).__name__}: {e}"}


def section_operational_metrics() -> dict[str, Any]:
    """Operational-validation N-target progress (post-vision-close phase).

    Reads lib.operational_metrics for every sub_phase metric and surfaces
    current/target/met flag per row. Operators see at a glance how close
    the harness is to its N-of-N empirical-backing target.

    Fail-soft: any exception → keys present with empty metrics + error.
    """
    try:
        from lib.operational_metrics import all_metrics
        metrics = all_metrics()
        met_count = sum(1 for m in metrics.values() if m.get("met"))
        return {
            "metrics": metrics,
            "met_count": met_count,
            "total_count": len(metrics),
        }
    except Exception as e:
        return {
            "metrics": {},
            "met_count": 0,
            "total_count": 0,
            "error": f"{type(e).__name__}: {e}",
        }


def build_dashboard() -> dict[str, Any]:
    return {
        "skills": section_skills_inventory(),
        "lint": section_lint_status(),
        "debate": section_debate_state(),
        "strict_design": section_strict_design(),
        "telemetry": section_telemetry_summary(),
        "tests": section_tests_presence(),
        "phase_tree": section_phase_tree(),
        "writeback": section_writeback(),
        "audit_log": section_audit_log(),
        "operational_metrics": section_operational_metrics(),
    }


def render_text(d: dict[str, Any]) -> str:
    lines = ["=== Harness Ecosystem Health ==="]

    s = d["skills"]
    lines.append("")
    lines.append(f"[Skills] total={s['total_skills']} across {s['trees_count']} trees")
    sz = s["size_bytes"]
    lines.append(f"  size: median={sz['median']:,}b · p90={sz['p90']:,}b · max={sz['max']:,}b")
    # Top 5 trees by skill count
    by_tree = s["by_tree"]
    sorted_trees = sorted(by_tree.items(), key=lambda x: -sum(x[1].values()))
    for tree, shapes in sorted_trees[:5]:
        n = sum(shapes.values())
        parts = ", ".join(f"{shape}={c}" for shape, c in sorted(shapes.items(), key=lambda x: -x[1]))
        lines.append(f"  {tree}: n={n} ({parts})")
    if len(sorted_trees) > 5:
        lines.append(f"  ... +{len(sorted_trees)-5} more trees")

    lin = d["lint"]
    lines.append("")
    lines.append("[Lint] " + ("clean" if lin.get("active_r002_violations") == 0
                              and not lin.get("r003_trigger_fired")
                              else "ATTENTION"))
    if lin.get("telemetry_present"):
        fired = [c for c, hit in (lin.get("r003_clauses") or {}).items() if hit]
        lines.append(f"  observed_skills={lin['skills_observed']} · "
                     f"R002_violations={lin['active_r002_violations']} · "
                     f"R003_fired={lin['r003_trigger_fired']}"
                     + (f" ({', '.join(fired)})" if fired else ""))
    elif "error" in lin:
        lines.append(f"  error: {lin['error']}")
    else:
        lines.append("  (no telemetry data yet)")

    deb = d["debate"]
    lines.append("")
    if "error" in deb:
        lines.append(f"[Debate] error: {deb['error']}")
    else:
        lines.append(f"[Debate] sessions={deb['total_sessions']} · "
                     f"doubts={deb['doubts_logged']} (pending={deb['doubts_pending']}, "
                     f"ack={deb['doubts_acknowledged']})")
        if deb.get("recent_sessions"):
            lines.append(f"  recent: {', '.join(deb['recent_sessions'])}")

    sd = d.get("strict_design", {})
    lines.append("")
    if "error" in sd:
        lines.append(f"[StrictDesign] error: {sd['error']}")
    else:
        lines.append(f"[StrictDesign] triggers={sd.get('total', 0)} "
                     f"(pending={sd.get('pending', 0)}, ack={sd.get('acknowledged', 0)})")

    tel = d["telemetry"]
    lines.append("")
    if not tel.get("present"):
        lines.append("[Telemetry] (dir absent)")
    else:
        files = tel.get("files", [])
        lines.append(f"[Telemetry] {len(files)} files")
        for f in files[:5]:
            sz = f.get("size_bytes", 0)
            lns = f.get("lines", "?")
            lines.append(f"  {f['name']:35s} {sz:>9,}b  {lns} lines")

    t = d["tests"]
    lines.append("")
    if t.get("present"):
        lines.append(f"[Tests] {t['test_files']} test files in scripts/tests/")

    pt = d.get("phase_tree", {})
    lines.append("")
    if not pt.get("present"):
        lines.append(f"[Phase-tree] (HANDOFF.md absent at {pt.get('path', '?')})")
    elif pt.get("error"):
        lines.append(f"[Phase-tree] error: {pt['error']}")
    elif pt.get("drift") is True:
        lines.append("[Phase-tree] DRIFT — anchored block != yaml-rendered tree")
        lines.append(f"  fix: `python -m cli.handoff_render {pt['path']} --in-place`")
    elif pt.get("drift") is False:
        lines.append("[Phase-tree] in_sync (anchored block == yaml-rendered tree)")
    else:
        lines.append(f"[Phase-tree] indeterminate (drift={pt.get('drift')!r})")

    wb = d.get("writeback", {})
    lines.append("")
    if "error" in wb:
        lines.append(f"[Writeback] error: {wb['error']}")
    elif wb.get("total_count", 0) == 0:
        lines.append("[Writeback] queue empty (no harness-researcher proposals yet)")
    else:
        by = wb.get("by_status", {})
        parts = ", ".join(f"{k}={v}" for k, v in sorted(by.items()))
        lines.append(
            f"[Writeback] pending={wb.get('pending_count', 0)} · "
            f"total={wb.get('total_count', 0)} ({parts})"
        )
        tel = wb.get("telemetry") or {}
        if tel:
            tel_parts = ", ".join(f"{k}={v}" for k, v in sorted(tel.items()))
            lines.append(f"  telemetry: {tel_parts}")
        if wb.get("pending_count", 0) > 0:
            lines.append(
                "  inspect: `python -m cli.writeback_inspect` "
                "(--show / --preview / --dismiss <id>)"
            )

    al = d.get("audit_log", {})
    lines.append("")
    if "error" in al:
        lines.append(f"[Audit-log] error: {al['error']}")
    elif al.get("total_sessions", 0) == 0:
        msg = "[Audit-log] (no subagent invocations recorded yet)"
        hf = al.get("hook_failed_count", 0)
        if hf:
            msg += f" — hook_failed={hf} (E3 surface: hook is failing despite no records)"
        lines.append(msg)
    else:
        lines.append(
            f"[Audit-log] sessions={al.get('total_sessions', 0)} · "
            f"invocations={al.get('total_invocations', 0)}"
        )
        bo = al.get("by_origin", {}) or {}
        if bo:
            origin_parts = ", ".join(f"{k}={v}" for k, v in bo.items())
            lines.append(f"  by_origin: {origin_parts}")
        by = al.get("by_agent", {}) or {}
        if by:
            top_parts = ", ".join(f"{k}={v}" for k, v in by.items())
            lines.append(f"  by_agent (top 10): {top_parts}")
        hf = al.get("hook_failed_count", 0)
        if hf:
            lines.append(
                f"  ATTENTION: hook_failed={hf} "
                f"(see telemetry/audit-log-hook-failed.jsonl)"
            )
        recents = al.get("recent_invocations", []) or []
        if recents:
            lines.append("  recent (newest first):")
            for r in recents:
                ts = (r.get("ts") or "")[:19]  # trim sub-second + Z
                lines.append(
                    f"    {ts} {r.get('agent', '?'):24s} "
                    f"role={r.get('role', '?'):16s} sid={r.get('sid', '?')}"
                )

    om = d.get("operational_metrics", {})
    lines.append("")
    if "error" in om:
        lines.append(f"[Operational] error: {om['error']}")
    else:
        lines.append(
            f"[Operational] {om.get('met_count', 0)}/{om.get('total_count', 0)} targets met"
        )
        for name, m in (om.get("metrics") or {}).items():
            badge = "x" if m.get("met") else " "
            lines.append(
                f"  [{badge}] {name:32s} {m.get('current', 0):>3}/{m.get('target', 0):<3}"
            )

    lines.append("")
    lines.append("Run individual CLIs for details:")
    lines.append("  python -m cli.skill_lint_report --lint")
    lines.append("  python -m cli.skill_trigger_eval <skill.md> --queries <queries.json>")
    lines.append("  python -m cli.debate_doubts")
    lines.append("  python -m engine.trigger_summary  [--acknowledge-all]")
    lines.append("  python -m cli.handoff_render <path> [--check | --in-place]")
    lines.append("  python -m cli.writeback_inspect [--list | --preview <id> | --dismiss <id>]")
    lines.append("  python -c \"from lib.subagent_invocation_log import search_by_agent; "
                 "print(search_by_agent('harness-critic', since_ts='2026-01-01T00:00:00Z'))\"")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness_health")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")
    d = build_dashboard()
    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=2, default=str))
    else:
        print(render_text(d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
