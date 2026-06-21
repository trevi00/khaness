#!/usr/bin/env python3
"""action_evolver — actuator co-occurrence detector (v15.33).

본 cycle은 self-improving 메타-시스템 차원의 두 번째 building block.

v15.32 sensor_anomaly가 'sensor incompleteness'를 다뤘다면, 본 도구는 'actuator
incompleteness'를 다룬다 — 현재 알려진 5 actions (ralph / Wonder / RF / AC / Rw)
의 *조합 패턴*에서 새 composite action 후보를 신호 추출.

action 어휘 진화는 두 경로로 발생할 수 있다:
1. 새 action 자체를 합성 (e.g., causal reflection, multi-agent collab) — debate 필수
2. 기존 actions를 새 방식으로 조합 (e.g., Wonder→Rw, RF→Rw) — 본 도구가 신호 추출

행동 데이터 source: state/debates/<sid>/events.jsonl 시간순 action-bearing event
시퀀스. 같은 orch_sid 내 bigram (A → B 시퀀스) 카운트 + frequency 분포 + 알려진
"expected" 패턴 외 anomaly 식별.

검출 heuristics (3종):

  1. **unexpected_bigram** — 같은 orch_sid 내 A → B 시퀀스가 expected baseline
     외인데 N회 이상 누적 → 새 composite action 후보. e.g.:
     - wonder.depth_exhausted → rewind.requested = "deep-strike-recovery"
     - reflect.emitted → rewind.requested = "reflection-fallback"
     - rewind.completed → wonder.triggered = "rewind-loop" (warn — 무한 회귀)

  2. **action_skew** — 특정 action이 전체의 80%+ → 다른 actions 미사용 또는 dispatch
     실패 의심 (e.g., 항상 Wonder만 trigger되고 RF는 0번 → RF wiring 결함 가능성)

  3. **silent_action** — 알려진 action이 window 내 0회 emit → 해당 path가 wired
     되지 않았거나 trigger condition이 너무 빡빡 (sensor_anomaly와 상호 보완)

새 action 후보는 advisory only — 실제 액션 어휘 확장은 debate cycle 통과 필수
(CLAUDE.md L0 invariant 준수).

Usage:
    cd ~/.claude/scripts
    python -m cli.action_evolver                  # text summary
    python -m cli.action_evolver --json
    python -m cli.action_evolver --since-hours 168  # default 7d
    python -m cli.action_evolver --min-bigram 3   # bigram count threshold
    python -m cli.action_evolver --self-check     # embedded smoke test

Exit code: 0 (no anomaly) | 2 (anomaly found, CI gate 가능).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


# Action-bearing event_types — exclude ac.leaf_evaluated (too frequent, noise)
_ACTION_EVENTS: frozenset[str] = frozenset({
    "wonder.triggered",
    "wonder.depth_exhausted",
    "reflect.emitted",
    # rewind.* events (currently emitted by lib/rewind.py via emit_fn,
    # taxonomy registration is separate cycle but events show up in raw stream)
    "rewind.requested",
    "rewind.completed",
    "rewind.cap_exhausted",
})

# Baseline EXPECTED bigrams — normal harness flow. Bigrams NOT in this set are
# anomaly candidates. (Each entry: "A→B" as string for set membership.)
_EXPECTED_BIGRAMS: frozenset[str] = frozenset({
    "wonder.triggered→reflect.emitted",        # Wonder → RF (정상)
    "rewind.requested→rewind.completed",       # Rewind lifecycle
    "wonder.triggered→wonder.depth_exhausted", # Wonder depth cap 도달 시 마지막 trigger
})

# Defaults
DEFAULT_WINDOW_HOURS = 168.0
DEFAULT_MIN_BIGRAM = 3
DEFAULT_SKEW_THRESHOLD = 0.80
DEFAULT_TOTAL_MIN = 5


def _claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_HOME") or Path.home() / ".claude")


def _state_dir() -> Path:
    return _claude_home() / "state"


def _epoch_now() -> float:
    return time.time()


def _iso_to_epoch(ts_str: str) -> float | None:
    # Delegates to canonical lib.timefmt (harness-full-review rank 4 dedup):
    # union of the formerly-divergent format lists; this module gains the
    # space-separated shapes it previously lacked (strict superset, no regression).
    from lib.timefmt import iso_to_epoch
    return iso_to_epoch(ts_str)


@dataclass
class ActionAnomaly:
    kind: str       # 'unexpected_bigram' | 'action_skew' | 'silent_action'
    severity: str   # 'advisory' | 'major' | 'warn'
    evidence: dict
    recommendation: str


@dataclass
class ActionReport:
    window_hours: float
    sessions_scanned: int
    total_action_events: int
    action_counts: dict[str, int] = field(default_factory=dict)
    bigram_counts: dict[str, int] = field(default_factory=dict)
    anomalies: list[ActionAnomaly] = field(default_factory=list)


def _load_action_sequences(since_epoch: float | None) -> tuple[dict[str, list[str]], int, int]:
    """Return ({orch_sid: [event_type chronological list]}, sessions_scanned, total_events)."""
    debates_dir = _state_dir() / "debates"
    sequences: dict[str, list[str]] = {}
    sessions = 0
    total = 0
    if not debates_dir.exists():
        return sequences, sessions, total

    for sess_dir in debates_dir.iterdir():
        if not sess_dir.is_dir():
            continue
        events_file = sess_dir / "events.jsonl"
        if not events_file.exists():
            continue
        sessions += 1
        seq: list[tuple[float, str]] = []  # (ts_epoch, event_type)
        try:
            with events_file.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    etype = rec.get("type") or rec.get("event_type")
                    if not isinstance(etype, str) or etype not in _ACTION_EVENTS:
                        continue
                    ts = rec.get("ts")
                    ep = _iso_to_epoch(ts) if isinstance(ts, str) else (
                        float(ts) if isinstance(ts, (int, float)) else None
                    )
                    if since_epoch is not None and ep is not None and ep < since_epoch:
                        continue
                    seq.append((ep if ep is not None else 0.0, etype))
                    total += 1
        except OSError:
            continue
        if seq:
            seq.sort(key=lambda x: x[0])
            sequences[sess_dir.name] = [e for _, e in seq]
    return sequences, sessions, total


def detect_unexpected_bigrams(
    sequences: dict[str, list[str]],
    *,
    min_bigram: int,
) -> tuple[dict[str, int], list[ActionAnomaly]]:
    """Find A→B bigrams not in _EXPECTED_BIGRAMS with count >= min_bigram."""
    bigram_counts: Counter[str] = Counter()
    for seq in sequences.values():
        for i in range(len(seq) - 1):
            bigram_counts[f"{seq[i]}→{seq[i+1]}"] += 1

    anomalies: list[ActionAnomaly] = []
    for bigram, count in bigram_counts.items():
        if bigram in _EXPECTED_BIGRAMS:
            continue
        if count >= min_bigram:
            severity = "warn" if "rewind.completed→wonder.triggered" in bigram else "advisory"
            candidate_name = _suggest_composite_name(bigram)
            anomalies.append(ActionAnomaly(
                kind="unexpected_bigram",
                severity=severity,
                evidence={"bigram": bigram, "count": count, "threshold": min_bigram},
                recommendation=(
                    f"unexpected sequence '{bigram}' occurred {count} times — "
                    f"candidate composite action: '{candidate_name}'. "
                    f"Review via /harness-debate before promoting to action vocabulary."
                ),
            ))
    return dict(bigram_counts), anomalies


def _suggest_composite_name(bigram: str) -> str:
    """Heuristic name suggestion for unexpected bigram → composite action."""
    a, b = bigram.split("→", 1) if "→" in bigram else (bigram, "")
    table = {
        "wonder.depth_exhausted→rewind.requested": "deep-strike-recovery",
        "reflect.emitted→rewind.requested": "reflection-fallback",
        "rewind.completed→wonder.triggered": "rewind-loop-WARN",
        "rewind.completed→reflect.emitted": "post-rewind-reflection",
        "reflect.emitted→reflect.emitted": "reflection-cascade",
        "wonder.triggered→wonder.triggered": "double-strike",
        "rewind.completed→rewind.requested": "chain-rewind",
    }
    return table.get(bigram, f"composite-{a.split('.')[0]}-{b.split('.')[0]}")


def detect_action_skew(
    action_counts: dict[str, int],
    *,
    skew_threshold: float,
    total_min: int,
) -> list[ActionAnomaly]:
    """Single action dominating distribution → other paths underused/broken."""
    total = sum(action_counts.values())
    if total < total_min:
        return []
    anomalies: list[ActionAnomaly] = []
    for action, count in action_counts.items():
        ratio = count / total
        if ratio >= skew_threshold:
            anomalies.append(ActionAnomaly(
                kind="action_skew",
                severity="major",
                evidence={
                    "action": action,
                    "ratio": round(ratio, 3),
                    "count": count,
                    "total": total,
                },
                recommendation=(
                    f"action '{action}' dominates at {ratio:.0%} ({count}/{total}) — "
                    f"other actuator paths underused or dispatch defective. Verify wiring."
                ),
            ))
    return anomalies


def detect_silent_actions(
    action_counts: dict[str, int],
    *,
    total_min: int,
) -> list[ActionAnomaly]:
    """Known actions absent (0 count) when total activity is non-trivial."""
    total = sum(action_counts.values())
    if total < total_min:
        return []
    anomalies: list[ActionAnomaly] = []
    for known_action in _ACTION_EVENTS:
        if action_counts.get(known_action, 0) == 0:
            anomalies.append(ActionAnomaly(
                kind="silent_action",
                severity="advisory",
                evidence={
                    "silent_action": known_action,
                    "total_other_actions": total,
                },
                recommendation=(
                    f"action '{known_action}' never emitted within window (other actions: "
                    f"{total}). Path either unreachable or trigger condition too strict."
                ),
            ))
    return anomalies


def analyze(
    *,
    window_hours: float = DEFAULT_WINDOW_HOURS,
    min_bigram: int = DEFAULT_MIN_BIGRAM,
    skew_threshold: float = DEFAULT_SKEW_THRESHOLD,
    total_min: int = DEFAULT_TOTAL_MIN,
) -> ActionReport:
    since = _epoch_now() - (window_hours * 3600.0)
    sequences, sessions, total = _load_action_sequences(since_epoch=since)
    action_counts: Counter[str] = Counter()
    for seq in sequences.values():
        action_counts.update(seq)

    bigram_counts, bigram_anom = detect_unexpected_bigrams(sequences, min_bigram=min_bigram)
    skew_anom = detect_action_skew(
        dict(action_counts), skew_threshold=skew_threshold, total_min=total_min,
    )
    silent_anom = detect_silent_actions(dict(action_counts), total_min=total_min)

    return ActionReport(
        window_hours=window_hours,
        sessions_scanned=sessions,
        total_action_events=total,
        action_counts=dict(action_counts),
        bigram_counts=bigram_counts,
        anomalies=bigram_anom + skew_anom + silent_anom,
    )


def _render_text(report: ActionReport) -> str:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("Action Evolver Report — v15.33 actuator co-occurrence detector")
    lines.append("=" * 72)
    lines.append(
        f"  window: {report.window_hours:.1f}h | sessions: {report.sessions_scanned} | "
        f"action events: {report.total_action_events}"
    )
    lines.append("")

    if report.action_counts:
        lines.append("[action distribution]")
        for action, count in sorted(report.action_counts.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"  {action:<32s} {count:>5d}")
        lines.append("")

    if report.bigram_counts:
        lines.append("[bigram top 10 (시간순 A→B 시퀀스)]")
        for bigram, count in sorted(report.bigram_counts.items(), key=lambda kv: -kv[1])[:10]:
            tag = "expected" if bigram in _EXPECTED_BIGRAMS else "candidate"
            lines.append(f"  [{tag:<9s}] {bigram:<60s} {count:>5d}")
        lines.append("")

    if not report.anomalies:
        lines.append("  [OK] no action-vocabulary anomalies detected")
    else:
        lines.append(f"  [{len(report.anomalies)} anomaly signals detected]")
        lines.append("")
        for i, a in enumerate(report.anomalies, 1):
            lines.append(f"  #{i} [{a.severity}] {a.kind}")
            for k, v in a.evidence.items():
                lines.append(f"      - {k}: {v}")
            lines.append(f"      recommendation: {a.recommendation}")
            lines.append("")
    lines.append("=" * 72)
    lines.append("Note: action vocabulary evolution is ADVISORY — composite action adoption")
    lines.append("requires a debate cycle (CLAUDE.md L0 invariant). 본 도구는 신호만 제공.")
    return "\n".join(lines)


def _render_json(report: ActionReport) -> str:
    return json.dumps({
        "window_hours": report.window_hours,
        "sessions_scanned": report.sessions_scanned,
        "total_action_events": report.total_action_events,
        "action_counts": report.action_counts,
        "bigram_counts": report.bigram_counts,
        "anomalies": [asdict(a) for a in report.anomalies],
    }, ensure_ascii=False, indent=2)


# ============================================================================
# Embedded self-check (single-file mutation surface invariant — v15.33)
# ============================================================================


def _self_check() -> int:
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

        # Case 1: empty → no anomaly
        r1 = analyze()
        case("empty_no_anomaly", r1.anomalies == [])
        case("empty_zero_events", r1.total_action_events == 0)

        # Case 2: synthesize a session with expected bigrams only
        debates = _state_dir() / "debates" / "orch-test1"
        debates.mkdir(parents=True)
        recent = "2026-05-17T12:00:00+00:00"
        events1 = [
            json.dumps({"type": "wonder.triggered", "ts": "2026-05-17T12:00:00+00:00"}),
            json.dumps({"type": "reflect.emitted",  "ts": "2026-05-17T12:00:01+00:00"}),
            json.dumps({"type": "wonder.triggered", "ts": "2026-05-17T12:00:02+00:00"}),
            json.dumps({"type": "reflect.emitted",  "ts": "2026-05-17T12:00:03+00:00"}),
            json.dumps({"type": "wonder.triggered", "ts": "2026-05-17T12:00:04+00:00"}),
            json.dumps({"type": "reflect.emitted",  "ts": "2026-05-17T12:00:05+00:00"}),
        ]
        (debates / "events.jsonl").write_text("\n".join(events1) + "\n", encoding="utf-8")
        r2 = analyze(window_hours=1000)
        case("expected_bigram_no_unexpected_anomaly",
             not any(a.kind == "unexpected_bigram" for a in r2.anomalies))
        case("bigram_counted", r2.bigram_counts.get("wonder.triggered→reflect.emitted", 0) == 3)

        # Case 3: unexpected bigram — wonder.depth_exhausted → rewind.requested 3회
        debates2 = _state_dir() / "debates" / "orch-test2"
        debates2.mkdir(parents=True)
        unexpected_events = []
        for i in range(3):
            base = i * 10
            unexpected_events.append(json.dumps({
                "type": "wonder.depth_exhausted",
                "ts": f"2026-05-17T12:{base:02d}:00+00:00",
            }))
            unexpected_events.append(json.dumps({
                "type": "rewind.requested",
                "ts": f"2026-05-17T12:{base:02d}:01+00:00",
            }))
            unexpected_events.append(json.dumps({
                "type": "rewind.completed",
                "ts": f"2026-05-17T12:{base:02d}:02+00:00",
            }))
        (debates2 / "events.jsonl").write_text("\n".join(unexpected_events) + "\n", encoding="utf-8")
        r3 = analyze(window_hours=1000, min_bigram=3)
        case("unexpected_bigram_detected",
             any(a.kind == "unexpected_bigram" and "depth_exhausted→rewind.requested" in a.evidence.get("bigram", "")
                 for a in r3.anomalies))

        # Case 4: rewind-loop WARN
        debates3 = _state_dir() / "debates" / "orch-test3"
        debates3.mkdir(parents=True)
        loop_events = []
        for i in range(3):
            base = i * 10
            loop_events.append(json.dumps({
                "type": "rewind.completed",
                "ts": f"2026-05-17T12:{base:02d}:00+00:00",
            }))
            loop_events.append(json.dumps({
                "type": "wonder.triggered",
                "ts": f"2026-05-17T12:{base:02d}:01+00:00",
            }))
        (debates3 / "events.jsonl").write_text("\n".join(loop_events) + "\n", encoding="utf-8")
        r4 = analyze(window_hours=1000, min_bigram=3)
        loop_anom = [a for a in r4.anomalies if a.kind == "unexpected_bigram"
                     and "rewind.completed→wonder.triggered" in a.evidence.get("bigram", "")]
        case("rewind_loop_detected", len(loop_anom) >= 1)
        case("rewind_loop_severity_warn", loop_anom and loop_anom[0].severity == "warn")

    # Case 5/6: silent action + action skew — isolate in fresh tempdir
    with tempfile.TemporaryDirectory() as td2:
        os.environ["CLAUDE_HOME"] = str(Path(td2))
        debates4 = _state_dir() / "debates" / "orch-test4"
        debates4.mkdir(parents=True)
        only_wonder = "\n".join([
            json.dumps({"type": "wonder.triggered", "ts": f"2026-05-17T12:{i:02d}:00+00:00"})
            for i in range(10)
        ])
        (debates4 / "events.jsonl").write_text(only_wonder + "\n", encoding="utf-8")
        r5 = analyze(window_hours=1000)
        silent_kinds = [a.evidence.get("silent_action") for a in r5.anomalies
                        if a.kind == "silent_action"]
        case("silent_reflect_detected", "reflect.emitted" in silent_kinds)
        case("silent_rewind_detected", "rewind.requested" in silent_kinds)

        # Case 6: action skew — same data, single action 100%
        skew_anom = [a for a in r5.anomalies if a.kind == "action_skew"]
        case("action_skew_detected", len(skew_anom) >= 1)
        case("action_skew_evidence", skew_anom and skew_anom[0].evidence.get("ratio") == 1.0)

    with tempfile.TemporaryDirectory() as td3:
        os.environ["CLAUDE_HOME"] = str(Path(td3))

        # Case 7: composite name suggestion
        name = _suggest_composite_name("wonder.depth_exhausted→rewind.requested")
        case("composite_name_deep_strike", name == "deep-strike-recovery")
        name2 = _suggest_composite_name("rewind.completed→wonder.triggered")
        case("composite_name_rewind_loop", "WARN" in name2)
        name3 = _suggest_composite_name("foo.bar→baz.qux")
        case("composite_name_fallback", name3.startswith("composite-"))

    for name, ok, detail in cases:
        marker = "[OK]" if ok else "[FAIL]"
        suffix = f": {detail}" if detail and not ok else ""
        print(f"  {marker} {name}{suffix}")
    if failed:
        print(f"\n[FAIL] {failed}/{len(cases)} self-check assertions failed")
        return 1
    print(f"\n[OK] {len(cases)} self-check assertions passed")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cli.action_evolver",
        description="Action vocabulary evolver — actuator co-occurrence patterns (v15.33)",
    )
    p.add_argument("--json", action="store_true")
    p.add_argument("--since-hours", type=float, default=DEFAULT_WINDOW_HOURS)
    p.add_argument("--min-bigram", type=int, default=DEFAULT_MIN_BIGRAM)
    p.add_argument("--skew-threshold", type=float, default=DEFAULT_SKEW_THRESHOLD)
    p.add_argument("--total-min", type=int, default=DEFAULT_TOTAL_MIN)
    p.add_argument("--self-check", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.self_check:
        return _self_check()
    report = analyze(
        window_hours=args.since_hours,
        min_bigram=args.min_bigram,
        skew_threshold=args.skew_threshold,
        total_min=args.total_min,
    )
    print(_render_json(report) if args.json else _render_text(report))
    return 2 if report.anomalies else 0


if __name__ == "__main__":
    sys.exit(main())
