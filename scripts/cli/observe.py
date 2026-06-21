#!/usr/bin/env python3
"""observe — harness observability aggregator (v15.27 R).

debate-1778990144-679cb8 D1 (4-gen approved+hard_cap): scripts/cli/observe.py 단일 file +
read-only aggregate over 18 KNOWN_EVENT_TYPES + state stores. operator residual은
inline advisory note (별도 파일 분리 금지 — single mutation surface 유지).

Usage:
    cd ~/.claude/scripts
    python -m cli.observe                       # text summary (default)
    python -m cli.observe --json                # JSON output
    python -m cli.observe --since-hours 24      # filter recent events
    python -m cli.observe --section events      # only event counts
    python -m cli.observe --section seeds       # only seeds + lineage
    python -m cli.observe --section sessions    # only active sessions (wonder/budget/heartbeat)
    python -m cli.observe --section ledger      # only operator-ledger verified_by tally
    python -m cli.observe --section operator-residual  # only pending operator items
    python -m cli.observe --self-check          # embedded smoke test (D5 gate proxy)

Exit code: 0 always (read-only diagnostic — never blocks).

Single-file mutation surface invariant (v15.27 R):
- 본 파일만 추가. lib/event_store.py + state stores 모두 read-only로 소비.
- operator residual은 본 파일 안의 inline advisory note 섹션으로 흡수.
- 신규 lib/ module 추가 금지. 신규 test file 분리 금지 (embedded --self-check 모드).
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_HOME") or Path.home() / ".claude")


def _state_dir() -> Path:
    return _claude_home() / "state"


# ============================================================================
# Section: events (18 KNOWN_EVENT_TYPES counter)
# ============================================================================


def _epoch_now() -> float:
    return time.time()


def _iso_to_epoch(ts_str: str) -> float | None:
    """Best-effort ISO-8601 → epoch float. None on parse failure.

    Delegates to canonical lib.timefmt (harness-full-review rank 4 dedup): the
    union of the formerly-divergent observe/action_evolver/sensor_anomaly lists,
    so the previously-missing %z (timezone-offset) shapes now parse instead of
    silently dropping to None + falling back to mtime.
    """
    from lib.timefmt import iso_to_epoch
    return iso_to_epoch(ts_str)


# debate-protocol-internal event types (engine/debate.py emits these per gen).
# Separate namespace from KNOWN_EVENT_TYPES (which is for runtime taxonomy events
# emitted by handlers/lib). debate events live in state/debates/<sid>/events.jsonl
# but use protocol-internal verbs — observe.py classifies them separately to
# avoid false-positive 'unknown' flagging.
_DEBATE_INTERNAL_TYPES: frozenset[str] = frozenset({
    "proposal",
    "critique",
    "verdict",
    "convergence",
    "session_started",
    "session_start",
    "session_ended",
    "session_resume",
    "similarity_log",
    "architect_decision",
    "fast_path_critic_skip",
    "isolation_leak_observed",
    "ontology_snapshot_final",
    "verdict_invalidated_by_severity",
    "early_hard_cap_recommendation",  # M14: emitted by cli.debate_stagnation_check
    "self_report_mismatch",
    "parse_failure",
    "implementation_complete",
    "contract_strengthening",
    "external_baseline_complete",
    "p0_1_patch",
    "runtime_capture",
    "qa_boundary_pr_merged",
})


@dataclass
class EventCounts:
    """Aggregate event_type → count + 3-way classification (KNOWN / DEBATE / UNKNOWN)."""
    by_type: dict[str, int] = field(default_factory=dict)
    total: int = 0
    debate_internal_types: dict[str, int] = field(default_factory=dict)
    unknown_types: dict[str, int] = field(default_factory=dict)
    sessions_scanned: int = 0
    files_failed: int = 0


def aggregate_events(
    *,
    since_epoch: float | None = None,
    known_types: frozenset[str] | None = None,
) -> EventCounts:
    """Iterate state/debates/<sid>/events.jsonl and count event_type occurrences.

    `known_types`: if provided, types not in this set go to unknown_types.
    Default uses KNOWN_EVENT_TYPES from lib.event_taxonomy when available.
    """
    if known_types is None:
        try:
            from lib.event_taxonomy import KNOWN_EVENT_TYPES
            known_types = KNOWN_EVENT_TYPES
        except Exception:
            known_types = frozenset()

    counts = EventCounts()
    debates_dir = _state_dir() / "debates"
    if not debates_dir.exists():
        return counts

    for sess_dir in sorted(debates_dir.iterdir()):
        if not sess_dir.is_dir():
            continue
        events_file = sess_dir / "events.jsonl"
        if not events_file.exists():
            continue
        counts.sessions_scanned += 1
        try:
            with events_file.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    # Filter by ts (best-effort — record may use "ts" ISO string)
                    if since_epoch is not None:
                        ts = record.get("ts")
                        ep = _iso_to_epoch(ts) if isinstance(ts, str) else (
                            float(ts) if isinstance(ts, (int, float)) else None
                        )
                        if ep is not None and ep < since_epoch:
                            continue
                    # Event type lives in `type` (EventStore.append shape) OR
                    # `event_type` (lib.event_store.append free-form caller shape).
                    etype = record.get("type") or record.get("event_type")
                    if not isinstance(etype, str):
                        continue
                    counts.total += 1
                    counts.by_type[etype] = counts.by_type.get(etype, 0) + 1
                    if etype in _DEBATE_INTERNAL_TYPES:
                        counts.debate_internal_types[etype] = (
                            counts.debate_internal_types.get(etype, 0) + 1
                        )
                    elif known_types and etype not in known_types:
                        counts.unknown_types[etype] = counts.unknown_types.get(etype, 0) + 1
        except OSError:
            counts.files_failed += 1
    return counts


# ============================================================================
# Section: sessions (active orch — wonder/budget/heartbeat per-sid view)
# ============================================================================


@dataclass
class SessionView:
    sid: str
    wonder_depth: int = 0
    wonder_strikes: int = 0  # total across fingerprints
    budget_chars: int = 0
    budget_invocations: int = 0
    heartbeat_age_sec: float | None = None
    heartbeat_count: int = 0
    heartbeat_agent: str | None = None
    reflect_history_len: int = 0


def aggregate_sessions() -> list[SessionView]:
    """Scan state/wonder + state/budgets + state/heartbeats + state/reflect_feedback,
    join by sid (filename stem) into per-session views.
    """
    state = _state_dir()
    by_sid: dict[str, SessionView] = {}

    # Wonder
    wonder_dir = state / "wonder"
    if wonder_dir.exists():
        for f in wonder_dir.glob("*.json"):
            sid = f.stem
            view = by_sid.setdefault(sid, SessionView(sid=sid))
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                view.wonder_depth = int(data.get("total_depth", 0))
                strikes = data.get("strikes_by_fingerprint", {})
                if isinstance(strikes, dict):
                    view.wonder_strikes = sum(
                        int(v) for v in strikes.values() if isinstance(v, (int, float))
                    )
            except (OSError, json.JSONDecodeError, ValueError):
                pass

    # Budgets
    budgets_dir = state / "budgets"
    if budgets_dir.exists():
        for f in budgets_dir.glob("*.json"):
            sid = f.stem
            view = by_sid.setdefault(sid, SessionView(sid=sid))
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                view.budget_chars = int(data.get("total_chars", 0))
                view.budget_invocations = int(data.get("invocation_count", 0))
            except (OSError, json.JSONDecodeError, ValueError):
                pass

    # Heartbeats
    heartbeats_dir = state / "heartbeats"
    if heartbeats_dir.exists():
        now = _epoch_now()
        for f in heartbeats_dir.glob("*.json"):
            sid = f.stem
            view = by_sid.setdefault(sid, SessionView(sid=sid))
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                view.heartbeat_count = int(data.get("count", 0))
                view.heartbeat_agent = data.get("agent_type")
                ts = data.get("last_ts") or data.get("ts")
                last_e: float | None = None
                if isinstance(ts, (int, float)):
                    last_e = float(ts)
                elif isinstance(ts, str):
                    last_e = _iso_to_epoch(ts)
                if last_e is None:
                    # Fallback: file mtime
                    try:
                        last_e = f.stat().st_mtime
                    except OSError:
                        last_e = None
                if last_e is not None:
                    view.heartbeat_age_sec = max(0.0, now - last_e)
            except (OSError, json.JSONDecodeError, ValueError):
                pass

    # Reflect feedback
    rf_dir = state / "reflect_feedback"
    if rf_dir.exists():
        for f in rf_dir.glob("*.json"):
            sid = f.stem
            view = by_sid.setdefault(sid, SessionView(sid=sid))
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                hist = data.get("history", [])
                if isinstance(hist, list):
                    view.reflect_history_len = len(hist)
            except (OSError, json.JSONDecodeError):
                pass

    return sorted(by_sid.values(), key=lambda v: v.sid)


# ============================================================================
# Section: seeds (frozen seeds + addendum lineage depth)
# ============================================================================


@dataclass
class SeedView:
    seed_hash: str
    ts: int
    content_len: int
    addendum_chain_len: int
    is_current: bool


def aggregate_seeds() -> list[SeedView]:
    """Scan state/seeds/<hash>.json + state/seeds/<hash>/addendum_gen*.md."""
    seeds_dir = _state_dir() / "seeds"
    out: list[SeedView] = []
    if not seeds_dir.exists():
        return out
    current_hash: str | None = None
    current_file = seeds_dir / "current.json"
    if current_file.exists():
        try:
            current_hash = json.loads(current_file.read_text(encoding="utf-8")).get("hash")
        except (OSError, json.JSONDecodeError):
            pass
    for f in seeds_dir.glob("*.json"):
        if f.name == "current.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        h = data.get("hash") or f.stem
        addendum_dir = seeds_dir / h
        chain_len = 0
        if addendum_dir.is_dir():
            chain_len = sum(1 for _ in addendum_dir.glob("addendum_gen*.md"))
        out.append(SeedView(
            seed_hash=h,
            ts=int(data.get("ts", 0)),
            content_len=len(data.get("content", "")),
            addendum_chain_len=chain_len,
            is_current=(h == current_hash),
        ))
    return sorted(out, key=lambda v: (not v.is_current, -v.ts))


# ============================================================================
# Section: operator-ledger (verified_by tally — D2 → D2.7 ladder)
# ============================================================================


@dataclass
class LedgerTally:
    total_records: int = 0
    by_verified_by: dict[str, int] = field(default_factory=dict)
    by_agent: dict[str, int] = field(default_factory=dict)
    successes: int = 0
    failures: int = 0


def aggregate_ledger() -> LedgerTally:
    """state/operator-ledger/<pid>/<agent>.jsonl 모든 record 합산."""
    tally = LedgerTally()
    ledger_dir = _state_dir() / "operator-ledger"
    if not ledger_dir.exists():
        return tally
    for pid_dir in ledger_dir.iterdir():
        if not pid_dir.is_dir():
            continue
        for agent_file in pid_dir.glob("*.jsonl"):
            agent = agent_file.stem
            try:
                with agent_file.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        tally.total_records += 1
                        tally.by_agent[agent] = tally.by_agent.get(agent, 0) + 1
                        vb = rec.get("verified_by", "unknown")
                        if isinstance(vb, str):
                            tally.by_verified_by[vb] = tally.by_verified_by.get(vb, 0) + 1
                        if rec.get("success") is True:
                            tally.successes += 1
                        elif rec.get("success") is False:
                            tally.failures += 1
            except OSError:
                continue
    return tally


# ============================================================================
# Section: operator-residual (inline advisory — pending operator mutations)
# ============================================================================


@dataclass
class OperatorResidual:
    """Pending operator-only mutations (CLAUDE.md L0 invariant — NEVER auto)."""
    items: list[dict[str, str]] = field(default_factory=list)


def detect_operator_residual() -> OperatorResidual:
    """Detect pending operator-only items by checking settings.json + cron presence."""
    out = OperatorResidual()

    # 1. agent_depth_guard settings.json hook (v15.20 잔여)
    settings_path = _claude_home() / "settings.json"
    has_depth_guard = False
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            settings_str = json.dumps(settings)
            has_depth_guard = "agent_depth_guard" in settings_str
        except (OSError, json.JSONDecodeError):
            pass
    if not has_depth_guard:
        out.items.append({
            "id": "agent_depth_guard_hook",
            "since": "v15.20",
            "action": "Add PreToolUse:Agent hook in settings.json invoking handlers/pre_tool/agent_depth_guard.py",
            "command": "Edit ~/.claude/settings.json (token-gated: settings.json edits are runtime policy mutations)",
        })

    # 2. heartbeat_check cron (v15.24 잔여)
    # Cron registration is OS-level (Linux crontab / Windows Task Scheduler) — can't auto-detect from harness.
    # Inline as advisory; operator confirms manually.
    out.items.append({
        "id": "heartbeat_check_cron",
        "since": "v15.24",
        "action": "Register cron job: every 5min run `python -m cli.heartbeat_check`",
        "command": "Linux: `*/5 * * * * cd ~/.claude/scripts && python -m cli.heartbeat_check >> ~/.claude/state/heartbeat-check.log`. Windows: Task Scheduler equivalent.",
    })

    return out


# ============================================================================
# Output rendering
# ============================================================================


def _render_text(
    events: EventCounts,
    sessions: list[SessionView],
    seeds: list[SeedView],
    ledger: LedgerTally,
    residual: OperatorResidual,
    *,
    since_epoch: float | None = None,
) -> str:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("Harness Observability — v15.27 R")
    lines.append("=" * 72)
    if since_epoch is not None:
        lines.append(f"Filter: since epoch {since_epoch:.0f} ({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(since_epoch))})")
        lines.append("")

    # Events
    lines.append("[events]")
    lines.append(f"  total: {events.total}")
    lines.append(f"  sessions scanned: {events.sessions_scanned}")
    lines.append(f"  files failed: {events.files_failed}")
    if events.by_type:
        # Split by-type into 3 panels: KNOWN_EVENT_TYPES (runtime taxonomy),
        # debate-internal (protocol verbs), UNKNOWN (typo / unregistered).
        try:
            from lib.event_taxonomy import KNOWN_EVENT_TYPES as _kt
        except Exception:
            _kt = frozenset()
        known_panel = {t: c for t, c in events.by_type.items()
                       if t in _kt and t not in _DEBATE_INTERNAL_TYPES}
        if known_panel:
            lines.append("  by type (taxonomy KNOWN):")
            for t, c in sorted(known_panel.items(), key=lambda kv: (-kv[1], kv[0])):
                lines.append(f"    {t:<40s} {c:>6d}")
    if events.debate_internal_types:
        lines.append("  by type (debate-protocol-internal):")
        for t, c in sorted(events.debate_internal_types.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"    {t:<40s} {c:>6d}")
    if events.unknown_types:
        lines.append("  UNKNOWN event_types (typo / unregistered):")
        for t, c in sorted(events.unknown_types.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"    {t:<40s} {c:>6d}")
    lines.append("")

    # Sessions
    lines.append("[sessions]")
    if not sessions:
        lines.append("  (no active sessions in wonder/budgets/heartbeats/reflect_feedback)")
    else:
        lines.append(f"  active sids: {len(sessions)}")
        lines.append(f"  {'sid':<40s} {'wdepth':>6s} {'wstrikes':>8s} {'bchars':>8s} {'binvk':>5s} {'hbage':>7s} {'rfhist':>6s}")
        for v in sessions[:40]:
            age = f"{v.heartbeat_age_sec:.0f}s" if v.heartbeat_age_sec is not None else "-"
            lines.append(
                f"  {v.sid[:40]:<40s} {v.wonder_depth:>6d} {v.wonder_strikes:>8d} "
                f"{v.budget_chars:>8d} {v.budget_invocations:>5d} {age:>7s} {v.reflect_history_len:>6d}"
            )
        if len(sessions) > 40:
            lines.append(f"  ... ({len(sessions) - 40} more, use --json)")
    lines.append("")

    # Seeds
    lines.append("[seeds]")
    if not seeds:
        lines.append("  (no frozen seeds in state/seeds/)")
    else:
        lines.append(f"  frozen seeds: {len(seeds)}")
        for v in seeds[:20]:
            marker = " (current)" if v.is_current else ""
            lines.append(
                f"  {v.seed_hash}  ts={v.ts}  len={v.content_len}  "
                f"addenda={v.addendum_chain_len}{marker}"
            )
        if len(seeds) > 20:
            lines.append(f"  ... ({len(seeds) - 20} more)")
    lines.append("")

    # Ledger
    lines.append("[operator-ledger]")
    lines.append(f"  total records: {ledger.total_records}")
    lines.append(f"  successes: {ledger.successes}")
    lines.append(f"  failures: {ledger.failures}")
    if ledger.by_verified_by:
        lines.append("  verified_by tally (9-grade ladder):")
        for vb, c in sorted(ledger.by_verified_by.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"    {vb:<48s} {c:>5d}")
    if ledger.by_agent:
        lines.append("  by agent (top 10):")
        for agent, c in sorted(ledger.by_agent.items(), key=lambda kv: -kv[1])[:10]:
            lines.append(f"    {agent:<48s} {c:>5d}")
    lines.append("")

    # Operator residual (inline advisory)
    lines.append("[operator-residual] (NEVER auto — token-gated runtime policy)")
    if not residual.items:
        lines.append("  (no pending operator items detected)")
    else:
        for item in residual.items:
            lines.append(f"  - {item['id']} ({item['since']})")
            lines.append(f"      action:  {item['action']}")
            lines.append(f"      command: {item['command']}")
    lines.append("")
    lines.append("=" * 72)
    return "\n".join(lines)


def _render_json(
    events: EventCounts,
    sessions: list[SessionView],
    seeds: list[SeedView],
    ledger: LedgerTally,
    residual: OperatorResidual,
) -> str:
    return json.dumps({
        "events": asdict(events),
        "sessions": [asdict(v) for v in sessions],
        "seeds": [asdict(v) for v in seeds],
        "ledger": asdict(ledger),
        "operator_residual": asdict(residual),
    }, ensure_ascii=False, indent=2)


# ============================================================================
# CLI
# ============================================================================


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cli.observe",
        description="Harness observability aggregator (read-only, v15.27 R)",
    )
    p.add_argument("--json", action="store_true", help="emit JSON instead of text")
    p.add_argument("--since-hours", type=float, default=None,
                   help="filter events newer than N hours")
    p.add_argument("--section", choices=["all", "events", "sessions", "seeds", "ledger", "operator-residual"],
                   default="all", help="render only one section")
    p.add_argument("--self-check", action="store_true",
                   help="run embedded smoke test (D5 gate proxy — exits 0 on pass)")
    return p


def _self_check() -> int:
    """Embedded smoke test — exercises all aggregator paths.

    Single-file surface invariant: no separate test file. Runs in-process,
    isolated via tempfile CLAUDE_HOME, asserts every aggregate fn returns
    sensible dataclass shapes on empty + populated stores.
    """
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

        # Empty stores
        ec = aggregate_events()
        case("empty_events_total_0", ec.total == 0, f"total={ec.total}")
        case("empty_events_sessions_0", ec.sessions_scanned == 0)

        sv = aggregate_sessions()
        case("empty_sessions_list", sv == [])

        sd = aggregate_seeds()
        case("empty_seeds_list", sd == [])

        lt = aggregate_ledger()
        case("empty_ledger_total_0", lt.total_records == 0)

        # Populated: synthesize a debates event log
        st = _state_dir()
        (st / "debates" / "test-sid").mkdir(parents=True)
        events_file = st / "debates" / "test-sid" / "events.jsonl"
        events_file.write_text(
            json.dumps({"ts": "2026-05-17T12:00:00", "type": "seed.locked", "actor": "test", "gen": 1, "payload": {}, "hash": "x"}) + "\n"
            + json.dumps({"ts": "2026-05-17T12:01:00", "type": "ac.leaf_evaluated", "actor": "test", "gen": 1, "payload": {}, "hash": "y"}) + "\n"
            + json.dumps({"ts": "2026-05-17T12:02:00", "type": "unknown.type", "actor": "test", "gen": 1, "payload": {}, "hash": "z"}) + "\n",
            encoding="utf-8",
        )
        # Add a debate-internal type and a taxonomy type to verify 3-way classification
        with events_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": "2026-05-17T12:03:00", "type": "verdict", "actor": "test", "gen": 1, "payload": {}, "hash": "v"}) + "\n")
            f.write(json.dumps({"ts": "2026-05-17T12:04:00", "type": "proposal", "actor": "test", "gen": 1, "payload": {}, "hash": "p"}) + "\n")

        ec2 = aggregate_events()
        case("populated_events_total_5", ec2.total == 5, f"total={ec2.total}")
        case("populated_seed_locked_counted", ec2.by_type.get("seed.locked") == 1)
        case("populated_unknown_flagged", ec2.unknown_types.get("unknown.type") == 1)
        case("populated_debate_verdict_classified", ec2.debate_internal_types.get("verdict") == 1)
        case("populated_debate_proposal_classified", ec2.debate_internal_types.get("proposal") == 1)
        case("populated_debate_not_in_unknown", "verdict" not in ec2.unknown_types)

        # Populated: synthesize wonder/budget/heartbeat
        (st / "wonder").mkdir(parents=True)
        (st / "wonder" / "orch-x.json").write_text(
            json.dumps({"total_depth": 2, "strikes_by_fingerprint": {"abc": 1, "def": 2}}),
            encoding="utf-8",
        )
        (st / "budgets").mkdir(parents=True)
        (st / "budgets" / "orch-x.json").write_text(
            json.dumps({"total_chars": 12345, "invocation_count": 7}),
            encoding="utf-8",
        )
        sv2 = aggregate_sessions()
        case("populated_sessions_joined", len(sv2) == 1)
        case("populated_wonder_depth", sv2[0].wonder_depth == 2)
        case("populated_wonder_strikes", sv2[0].wonder_strikes == 3)
        case("populated_budget_chars", sv2[0].budget_chars == 12345)

        # Populated: synthesize seeds
        (st / "seeds").mkdir(parents=True)
        (st / "seeds" / "abc1234567890def.json").write_text(
            json.dumps({"hash": "abc1234567890def", "content": "test seed", "ts": 100}),
            encoding="utf-8",
        )
        (st / "seeds" / "current.json").write_text(
            json.dumps({"hash": "abc1234567890def", "ts": 100}),
            encoding="utf-8",
        )
        (st / "seeds" / "abc1234567890def").mkdir(parents=True)
        (st / "seeds" / "abc1234567890def" / "addendum_gen1.md").write_text("---\ngen: 1\n---\nx", encoding="utf-8")
        sd2 = aggregate_seeds()
        case("populated_seeds_one", len(sd2) == 1)
        case("populated_seed_current_flagged", sd2[0].is_current is True)
        case("populated_seed_addendum_chain", sd2[0].addendum_chain_len == 1)

        # Populated: operator-ledger
        (st / "operator-ledger" / "pid-x").mkdir(parents=True)
        (st / "operator-ledger" / "pid-x" / "researcher.jsonl").write_text(
            json.dumps({"verified_by": "evidence_validator", "success": True, "agent_type": "researcher"}) + "\n"
            + json.dumps({"verified_by": "self_only", "success": False, "agent_type": "researcher"}) + "\n",
            encoding="utf-8",
        )
        lt2 = aggregate_ledger()
        case("populated_ledger_2_records", lt2.total_records == 2)
        case("populated_ledger_1_success", lt2.successes == 1)
        case("populated_ledger_1_failure", lt2.failures == 1)
        case("populated_ledger_verified_by_tally", lt2.by_verified_by.get("evidence_validator") == 1)

        # Operator residual — always at least one item (heartbeat_check cron is OS-level)
        res = detect_operator_residual()
        case("residual_at_least_one", len(res.items) >= 1)

        # Time filter
        future_filter = _epoch_now() + 86400  # future cutoff — nothing should pass
        ec3 = aggregate_events(since_epoch=future_filter)
        case("future_filter_excludes_all", ec3.total == 0)

    for name, ok, detail in cases:
        marker = "[OK]" if ok else "[FAIL]"
        suffix = f": {detail}" if detail and not ok else ""
        print(f"  {marker} {name}{suffix}")
    if failed:
        print(f"\n[FAIL] {failed}/{len(cases)} self-check assertions failed")
        return 1
    print(f"\n[OK] {len(cases)} self-check assertions passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.self_check:
        return _self_check()

    since_epoch = None
    if args.since_hours is not None:
        since_epoch = _epoch_now() - (args.since_hours * 3600.0)

    events = aggregate_events(since_epoch=since_epoch)
    sessions = aggregate_sessions()
    seeds = aggregate_seeds()
    ledger = aggregate_ledger()
    residual = detect_operator_residual()

    if args.section != "all":
        empty_events = EventCounts() if args.section != "events" else events
        empty_sessions = [] if args.section != "sessions" else sessions
        empty_seeds = [] if args.section != "seeds" else seeds
        empty_ledger = LedgerTally() if args.section != "ledger" else ledger
        empty_residual = OperatorResidual() if args.section != "operator-residual" else residual
        events, sessions, seeds, ledger, residual = (
            empty_events, empty_sessions, empty_seeds, empty_ledger, empty_residual,
        )

    if args.json:
        print(_render_json(events, sessions, seeds, ledger, residual))
    else:
        print(_render_text(events, sessions, seeds, ledger, residual, since_epoch=since_epoch))

    return 0


if __name__ == "__main__":
    sys.exit(main())
