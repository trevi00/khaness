#!/usr/bin/env python3
"""sensor_anomaly — adaptive sensor framework 첫 단계 (v15.32).

본 cycle은 self-improving 메타-시스템 차원의 첫 building block:
operator-ledger를 windowed-aggregate해서 *새 sensor 후보 신호*를 추출.
실제 sensor (validator) 추가는 debate 게이트를 통과해야만 land — CLAUDE.md L0
invariant (runtime_policy_mutated_by_command=false) 준수. 본 도구는 신호만 emit,
적용은 사용자/debate 책임.

면역계 비유 (사용자 vision 답변): 항체를 미리 가질 수 없음. 새 병원체 등장 시
B-cell이 anomaly를 감지 → 항체 학습. 본 도구가 B-cell 역할. 항체(validator) 합성은
별도 cycle.

검출 heuristics (4종):

  1. **verified_by 분포 skew** — 시간창 내 distribution skew 검출
     - `evidence_validator` (default, 9-grade 중 마지막) 비율 ≥ 80% → lower tier
       fabrication class가 우회 중 의심 (semantic/cross_ref/boilerplate 추가 후보)
     - `self_only` (D2 fail) 비율 ≥ 30% → schema 또는 evidence file 결함 누적

  2. **failure_modes 반복** — 같은 failure_mode가 windowed count ≥ N → 영구
     패턴화 후보 (2-Strike Rule 차원과는 별개, fabrication class 차원)

  3. **task_hash 비결정성** — 같은 task_hash + 다른 verified_by 출현 → 평가 불일치

  4. **agent-specific skew** — 특정 agent가 대부분 self_only인데 다른 agent는 정상 →
     해당 agent의 output_schema 또는 prompt 결함 의심

Output: 각 anomaly에 대해 *후보 신호* (signal type + evidence + 추천 액션). 실제 action은
사용자가 debate로 진입해 결정.

Usage:
    cd ~/.claude/scripts
    python -m cli.sensor_anomaly                       # text summary (default)
    python -m cli.sensor_anomaly --json                # JSON output
    python -m cli.sensor_anomaly --since-hours 24      # window 조정 (default 168=7d)
    python -m cli.sensor_anomaly --min-count 5         # minimum 누적 카운트
    python -m cli.sensor_anomaly --self-check          # embedded smoke test

Exit code:
    0 — no anomaly detected (또는 정상 작동)
    2 — anomaly found (CI 게이트로 사용 가능)
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


# Thresholds (advisory; tunable per env)
DEFAULT_WINDOW_HOURS = 168.0  # 7 days
DEFAULT_MIN_COUNT = 5         # ignore noise below this count
DEFAULT_SKEW_THRESHOLD = 0.80  # 80% in single bucket
DEFAULT_SELF_ONLY_THRESHOLD = 0.30
DEFAULT_REPEAT_FAILURE_MIN = 3


def _claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_HOME") or Path.home() / ".claude")


def _state_dir() -> Path:
    return _claude_home() / "state"


def _epoch_now() -> float:
    return time.time()


def _iso_to_epoch(ts_str: str) -> float | None:
    # Delegates to canonical lib.timefmt (harness-full-review rank 4 dedup):
    # union of the formerly-divergent format lists; gains the space-separated
    # shapes it previously lacked (strict superset, no regression).
    from lib.timefmt import iso_to_epoch
    return iso_to_epoch(ts_str)


@dataclass
class Anomaly:
    """A single candidate signal for sensor adaptation."""

    kind: str       # 'verified_by_skew' | 'self_only_excess' | 'repeat_failure_mode' | 'task_hash_inconsistency' | 'agent_self_only_skew'
    severity: str   # 'advisory' | 'major'
    evidence: dict
    recommendation: str


@dataclass
class AnomalyReport:
    window_hours: float
    records_scanned: int
    pid_count: int
    anomalies: list[Anomaly] = field(default_factory=list)


def _load_ledger_records(since_epoch: float | None) -> list[dict]:
    """Read all operator-ledger jsonl records (optionally filtered by ts >= since_epoch)."""
    ledger_root = _state_dir() / "operator-ledger"
    out: list[dict] = []
    if not ledger_root.exists():
        return out
    for pid_dir in ledger_root.iterdir():
        if not pid_dir.is_dir():
            continue
        for agent_file in pid_dir.glob("*.jsonl"):
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
                        if not isinstance(rec, dict):
                            continue
                        rec["_pid"] = pid_dir.name
                        if since_epoch is not None:
                            ts = rec.get("ts")
                            ep = _iso_to_epoch(ts) if isinstance(ts, str) else None
                            if ep is not None and ep < since_epoch:
                                continue
                        out.append(rec)
            except OSError:
                continue
    return out


def detect_verified_by_skew(
    records: list[dict],
    *,
    min_count: int,
    skew_threshold: float,
    self_only_threshold: float,
) -> list[Anomaly]:
    """Detect distribution skew in verified_by field."""
    out: list[Anomaly] = []
    counts: Counter[str] = Counter()
    for rec in records:
        vb = rec.get("verified_by")
        if isinstance(vb, str):
            counts[vb] += 1
    total = sum(counts.values())
    if total < min_count:
        return out

    # Default-tier (evidence_validator) excess → lower tiers bypassed
    default_count = counts.get("evidence_validator", 0)
    default_ratio = default_count / total
    if default_ratio >= skew_threshold:
        out.append(Anomaly(
            kind="verified_by_skew",
            severity="advisory",
            evidence={
                "default_tier_ratio": round(default_ratio, 3),
                "default_count": default_count,
                "total": total,
                "distribution": dict(counts),
            },
            recommendation=(
                f"{default_ratio:.0%} of records hit 'evidence_validator' default tier — "
                "lower tiers (lexical/cross_ref/boilerplate) bypassed. Consider new D2.x "
                "fabrication class detector cycle via /harness-debate."
            ),
        ))

    # self_only (D2 fail) excess → schema or evidence file defects
    self_only_count = counts.get("self_only", 0)
    self_only_ratio = self_only_count / total
    if self_only_ratio >= self_only_threshold:
        out.append(Anomaly(
            kind="self_only_excess",
            severity="major",
            evidence={
                "self_only_ratio": round(self_only_ratio, 3),
                "self_only_count": self_only_count,
                "total": total,
            },
            recommendation=(
                f"{self_only_ratio:.0%} of records D2-fail (self_only) — agent output_schema "
                "or evidence file existence defects accumulating. Review agent prompts or "
                "structural validator thresholds."
            ),
        ))
    return out


def detect_repeat_failure_modes(
    records: list[dict],
    *,
    repeat_min: int,
) -> list[Anomaly]:
    """Detect same failure_mode repeating >= repeat_min times."""
    out: list[Anomaly] = []
    mode_counts: Counter[str] = Counter()
    for rec in records:
        modes = rec.get("failure_modes")
        if isinstance(modes, list):
            for m in modes:
                if isinstance(m, str):
                    mode_counts[m] += 1
    for mode, count in mode_counts.items():
        if count >= repeat_min:
            out.append(Anomaly(
                kind="repeat_failure_mode",
                severity="major" if count >= repeat_min * 2 else "advisory",
                evidence={"failure_mode": mode, "count": count, "threshold": repeat_min},
                recommendation=(
                    f"failure_mode '{mode}' repeated {count} times — "
                    "candidate for permanent skill Gotcha or hook rule (2-Strike Rule promote)."
                ),
            ))
    return out


def detect_task_hash_inconsistency(
    records: list[dict],
    *,
    min_count: int,
) -> list[Anomaly]:
    """Same task_hash + different verified_by → non-determinism."""
    out: list[Anomaly] = []
    by_task: dict[str, set[str]] = defaultdict(set)
    for rec in records:
        th = rec.get("task_hash")
        vb = rec.get("verified_by")
        if isinstance(th, str) and isinstance(vb, str):
            by_task[th].add(vb)
    inconsistent = {th: list(vbs) for th, vbs in by_task.items() if len(vbs) > 1}
    if inconsistent:  # any inconsistency is advisory-worthy
        out.append(Anomaly(
            kind="task_hash_inconsistency",
            severity="major",
            evidence={
                "inconsistent_task_count": len(inconsistent),
                "sample": dict(list(inconsistent.items())[:3]),
            },
            recommendation=(
                f"{len(inconsistent)} task_hashes evaluated with different verified_by tiers — "
                "non-deterministic verdict signal. Investigate evaluator paradox guard or "
                "validator ordering."
            ),
        ))
    return out


def detect_agent_self_only_skew(
    records: list[dict],
    *,
    min_count: int,
    self_only_threshold: float,
) -> list[Anomaly]:
    """Per-agent self_only ratio anomaly."""
    out: list[Anomaly] = []
    by_agent: dict[str, Counter[str]] = defaultdict(Counter)
    for rec in records:
        agent = rec.get("agent_type")
        vb = rec.get("verified_by")
        if isinstance(agent, str) and isinstance(vb, str):
            by_agent[agent][vb] += 1
    for agent, counts in by_agent.items():
        total = sum(counts.values())
        if total < min_count:
            continue
        self_only_count = counts.get("self_only", 0)
        ratio = self_only_count / total
        if ratio >= self_only_threshold:
            out.append(Anomaly(
                kind="agent_self_only_skew",
                severity="major",
                evidence={
                    "agent_type": agent,
                    "self_only_ratio": round(ratio, 3),
                    "self_only_count": self_only_count,
                    "total": total,
                },
                recommendation=(
                    f"agent '{agent}' shows {ratio:.0%} self_only rate ({self_only_count}/{total}) — "
                    "agent-specific output_schema or prompt defect suspected. Review agent "
                    f"definition file (agents/{agent}.md)."
                ),
            ))
    return out


def analyze(
    *,
    window_hours: float = DEFAULT_WINDOW_HOURS,
    min_count: int = DEFAULT_MIN_COUNT,
    skew_threshold: float = DEFAULT_SKEW_THRESHOLD,
    self_only_threshold: float = DEFAULT_SELF_ONLY_THRESHOLD,
    repeat_min: int = DEFAULT_REPEAT_FAILURE_MIN,
) -> AnomalyReport:
    since = _epoch_now() - (window_hours * 3600.0)
    records = _load_ledger_records(since_epoch=since)
    pids = {rec.get("_pid") for rec in records if rec.get("_pid")}
    report = AnomalyReport(
        window_hours=window_hours,
        records_scanned=len(records),
        pid_count=len(pids),
    )
    report.anomalies.extend(detect_verified_by_skew(
        records, min_count=min_count,
        skew_threshold=skew_threshold,
        self_only_threshold=self_only_threshold,
    ))
    report.anomalies.extend(detect_repeat_failure_modes(records, repeat_min=repeat_min))
    report.anomalies.extend(detect_task_hash_inconsistency(records, min_count=min_count))
    report.anomalies.extend(detect_agent_self_only_skew(
        records, min_count=min_count, self_only_threshold=self_only_threshold,
    ))
    return report


def _render_text(report: AnomalyReport) -> str:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("Sensor Anomaly Report — v15.32 R adaptive-framework first signal")
    lines.append("=" * 72)
    lines.append(f"  window: {report.window_hours:.1f}h | records: {report.records_scanned} | pids: {report.pid_count}")
    lines.append("")
    if not report.anomalies:
        lines.append("  [OK] no anomalies detected within window/thresholds")
        lines.append("")
        lines.append("=" * 72)
        return "\n".join(lines)
    lines.append(f"  [{len(report.anomalies)} anomaly signals detected]")
    lines.append("")
    for i, a in enumerate(report.anomalies, 1):
        lines.append(f"  #{i} [{a.severity}] {a.kind}")
        lines.append(f"      evidence:")
        for k, v in a.evidence.items():
            lines.append(f"        - {k}: {v}")
        lines.append(f"      recommendation: {a.recommendation}")
        lines.append("")
    lines.append("=" * 72)
    lines.append("Note: anomaly signals are ADVISORY — actual sensor/validator adoption requires")
    lines.append("a debate cycle (CLAUDE.md L0 runtime_policy_mutated_by_command=false invariant).")
    return "\n".join(lines)


def _render_json(report: AnomalyReport) -> str:
    return json.dumps({
        "window_hours": report.window_hours,
        "records_scanned": report.records_scanned,
        "pid_count": report.pid_count,
        "anomalies": [asdict(a) for a in report.anomalies],
    }, ensure_ascii=False, indent=2)


# ============================================================================
# Embedded self-check (single-file mutation surface invariant — v15.32)
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

        # Case 1: empty state → no anomalies
        r1 = analyze()
        case("empty_state_no_anomaly", r1.anomalies == [])
        case("empty_state_zero_records", r1.records_scanned == 0)

        # Case 2: synthesize ledger with skewed verified_by
        ledger_dir = _state_dir() / "operator-ledger" / "pid-test"
        ledger_dir.mkdir(parents=True)
        recent_ts = "2026-05-17T12:00:00+00:00"

        records = []
        # 10 records all 'evidence_validator' → 100% default-tier skew
        for i in range(10):
            records.append(json.dumps({
                "agent_type": "researcher", "verified_by": "evidence_validator",
                "task_hash": f"th{i}", "success": True, "ts": recent_ts,
                "failure_modes": [],
            }))
        (ledger_dir / "researcher.jsonl").write_text("\n".join(records) + "\n", encoding="utf-8")

        r2 = analyze(window_hours=1000, min_count=5)
        case("skew_detected", any(a.kind == "verified_by_skew" for a in r2.anomalies))
        skew = next((a for a in r2.anomalies if a.kind == "verified_by_skew"), None)
        case("skew_evidence_correct", skew is not None and skew.evidence["default_tier_ratio"] == 1.0)

        # Case 3: self_only excess
        (ledger_dir / "researcher.jsonl").write_text("\n".join([
            json.dumps({"agent_type": "researcher", "verified_by": "self_only",
                       "task_hash": f"so{i}", "success": False, "ts": recent_ts,
                       "failure_modes": ["schema_violation"]})
            for i in range(10)
        ]) + "\n", encoding="utf-8")
        r3 = analyze(window_hours=1000, min_count=5)
        case("self_only_excess_detected", any(a.kind == "self_only_excess" for a in r3.anomalies))
        case("repeat_failure_mode_detected", any(a.kind == "repeat_failure_mode" for a in r3.anomalies))
        case("agent_self_only_skew_detected", any(a.kind == "agent_self_only_skew" for a in r3.anomalies))

        # Case 4: task_hash inconsistency
        (ledger_dir / "researcher.jsonl").write_text("\n".join([
            json.dumps({"agent_type": "researcher", "verified_by": "evidence_validator",
                       "task_hash": "same_th", "success": True, "ts": recent_ts,
                       "failure_modes": []}),
            json.dumps({"agent_type": "researcher", "verified_by": "self_only",
                       "task_hash": "same_th", "success": False, "ts": recent_ts,
                       "failure_modes": ["schema_violation"]}),
        ] * 3) + "\n", encoding="utf-8")
        r4 = analyze(window_hours=1000, min_count=5)
        case("task_hash_inconsistency_detected",
             any(a.kind == "task_hash_inconsistency" for a in r4.anomalies))

        # Case 5: window filter excludes old records
        old_ts = "2020-01-01T00:00:00+00:00"
        (ledger_dir / "researcher.jsonl").write_text("\n".join([
            json.dumps({"agent_type": "researcher", "verified_by": "self_only",
                       "task_hash": f"old{i}", "success": False, "ts": old_ts,
                       "failure_modes": []})
            for i in range(20)
        ]) + "\n", encoding="utf-8")
        r5 = analyze(window_hours=24, min_count=5)
        case("window_excludes_old", r5.records_scanned == 0)
        case("window_excludes_old_no_anomaly", r5.anomalies == [])

        # Case 6: min_count threshold
        (ledger_dir / "researcher.jsonl").write_text("\n".join([
            json.dumps({"agent_type": "researcher", "verified_by": "self_only",
                       "task_hash": f"low{i}", "success": False, "ts": recent_ts,
                       "failure_modes": []})
            for i in range(3)  # below min_count=5
        ]) + "\n", encoding="utf-8")
        r6 = analyze(window_hours=1000, min_count=5)
        case("below_min_count_no_skew_anomaly",
             not any(a.kind in ("verified_by_skew", "self_only_excess") for a in r6.anomalies))

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
        prog="cli.sensor_anomaly",
        description="Adaptive sensor anomaly detector — operator-ledger pattern signals (v15.32)",
    )
    p.add_argument("--json", action="store_true")
    p.add_argument("--since-hours", type=float, default=DEFAULT_WINDOW_HOURS)
    p.add_argument("--min-count", type=int, default=DEFAULT_MIN_COUNT)
    p.add_argument("--skew-threshold", type=float, default=DEFAULT_SKEW_THRESHOLD)
    p.add_argument("--self-only-threshold", type=float, default=DEFAULT_SELF_ONLY_THRESHOLD)
    p.add_argument("--repeat-min", type=int, default=DEFAULT_REPEAT_FAILURE_MIN)
    p.add_argument("--self-check", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.self_check:
        return _self_check()
    report = analyze(
        window_hours=args.since_hours,
        min_count=args.min_count,
        skew_threshold=args.skew_threshold,
        self_only_threshold=args.self_only_threshold,
        repeat_min=args.repeat_min,
    )
    if args.json:
        print(_render_json(report))
    else:
        print(_render_text(report))
    return 2 if report.anomalies else 0


if __name__ == "__main__":
    sys.exit(main())
