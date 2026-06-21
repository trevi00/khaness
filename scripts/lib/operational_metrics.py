"""operational_metrics — N-target progress tracking for harness operational validation.

Closes the "harness self-improvement is done; runtime statistics are sparse"
gap. After all vision items + actionable residuals close, the next harness
phase is operational-validation: accumulate real-run statistics so happy-path
claims gain N-of-N empirical backing.

Each helper returns (current_n: int, target_n: int) for one operational
sub_phase. Operators read the dashboard once and immediately know how
close the harness is to its operational target. No mocking — every count
reads filesystem state set by real runs.

Sub-phase metrics (current target):
- autopilot real runs (10): state/orchestrator/<sid>/events.jsonl files
- autopilot parallel real enable (1): telemetry/autopilot-parallel-runs.jsonl entries
- DGE E2 cross-target invocations (5): state/evaluator/<sid>/axis_scores.jsonl
  records with cross_target_first_invocation=True OR similar marker
- team runtime real sessions (3): state/team/<sid>/ directories
- allsolution real runs (1): state/allsolution/*.md synthesis artifacts

All helpers are fail-soft: missing dirs / unreadable files / corrupt JSONL
return current_n=0; the dashboard surfaces the zero rather than crashing.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from lib.paths import STATE_DIR, TELEMETRY_DIR

# Targets are policy — bump when the harness is ready for a tighter goal.
AUTOPILOT_RUN_TARGET = 10
AUTOPILOT_PARALLEL_TARGET = 1
DGE_E2_CROSS_TARGET_TARGET = 5
TEAM_RUNTIME_TARGET = 3
ALLSOLUTION_RUN_TARGET = 1


def _safe_glob(parent: Path, pattern: str) -> list[Path]:
    if not parent.exists():
        return []
    try:
        return list(parent.glob(pattern))
    except OSError:
        return []


def _count_jsonl_records_with_marker(
    path: Path, *, marker_keys: Iterable[str], marker_values: Iterable[bool] = (True,),
) -> int:
    """Return the number of valid JSONL records whose payload sets any of
    ``marker_keys`` to a value in ``marker_values``. Fail-soft on every
    failure mode (missing file / unreadable / malformed line).
    """
    if not path.exists():
        return 0
    keys = tuple(marker_keys)
    values = tuple(marker_values)
    count = 0
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        for key in keys:
            if rec.get(key) in values:
                count += 1
                break
    return count


def get_autopilot_run_count() -> tuple[int, int]:
    """Distinct super-session sids under state/orchestrator/<sid>/.

    Each successful or partial autopilot invocation produces one sid dir,
    so the directory count is a faithful run count (terminal status is
    tracked separately by autopilot_state).
    """
    root = STATE_DIR / "orchestrator"
    if not root.exists():
        return (0, AUTOPILOT_RUN_TARGET)
    try:
        sids = [p for p in root.iterdir() if p.is_dir()]
    except OSError:
        sids = []
    return (len(sids), AUTOPILOT_RUN_TARGET)


def get_autopilot_parallel_count() -> tuple[int, int]:
    """AUTOPILOT_PARALLEL=1 enable count from parallel-run telemetry.

    The autopilot Phase 5 D5 telemetry hook writes one record per real
    parallel run via ``lib.autopilot_flip_policy.log_parallel_run_outcome``
    (category ``autopilot-parallel-runs``) → ``telemetry/autopilot-parallel-runs.jsonl``
    (status + sid + merge_conflicts + pane_failures). Counts every entry —
    distinct or not — because each line is one real enable.

    Canonical-file fix (debate-1781756389-x73qz8, canonical_telemetry_file):
    this reader previously read ``parallel-run.jsonl`` — a file NO writer ever
    targets — so the metric was permanently 0 regardless of real runs. Repointed
    to the writer's actual file (``log_telemetry`` writes ``<category>.jsonl``)
    so reader and writer agree.
    """
    path = TELEMETRY_DIR / "autopilot-parallel-runs.jsonl"
    if not path.exists():
        return (0, AUTOPILOT_PARALLEL_TARGET)
    try:
        with path.open("r", encoding="utf-8") as f:
            n = sum(1 for line in f if line.strip())
    except OSError:
        n = 0
    return (n, AUTOPILOT_PARALLEL_TARGET)


def get_dge_e2_cross_target_count() -> tuple[int, int]:
    """DGE E2 cross-target invocation count from axis_scores.jsonl files.

    Per debate-1778248254-0b7092: cross_target_first_invocation=True is
    the marker on records where evaluator was applied to a non-evaluator
    artifact (the load-bearing self-validation paradox avoidance). We
    walk every state/evaluator/<sid>/axis_scores.jsonl and count.
    """
    root = STATE_DIR / "evaluator"
    if not root.exists():
        return (0, DGE_E2_CROSS_TARGET_TARGET)
    total = 0
    for axis_file in _safe_glob(root, "*/axis_scores.jsonl"):
        total += _count_jsonl_records_with_marker(
            axis_file, marker_keys=("cross_target_first_invocation",),
        )
    return (total, DGE_E2_CROSS_TARGET_TARGET)


def get_team_runtime_count() -> tuple[int, int]:
    """Team runtime session count from ``state/team/<sid>/`` directories.

    Each /harness-team invocation creates one team session dir under
    ``~/.omc/team/team-<unix_ts>/`` for legacy or
    ``state/team/<orch_sid>/`` for autopilot-driven runs. We count both
    paths; a team session is the unit, not individual workers.
    """
    count = 0
    state_team = STATE_DIR / "team"
    if state_team.exists():
        try:
            count += sum(1 for p in state_team.iterdir() if p.is_dir())
        except OSError:
            pass
    return (count, TEAM_RUNTIME_TARGET)


def get_allsolution_run_count() -> tuple[int, int]:
    """Allsolution synthesis artifact count from state/allsolution/*.md.

    Each /harness-allsolution invocation writes one
    ``state/allsolution/<unix_ts>.md`` synthesis. Successful runs and
    escalated runs both produce the file (escalate path documents the
    block point), so the count tracks dispatches not just completions.
    """
    root = STATE_DIR / "allsolution"
    files = _safe_glob(root, "*.md")
    return (len(files), ALLSOLUTION_RUN_TARGET)


def all_metrics() -> dict[str, dict[str, int | bool]]:
    """Aggregate every operational metric into one dashboard-ready dict.

    Layout per metric: ``{current, target, met}`` — ``met`` is True when
    ``current >= target`` (the operator can collapse the row when met).
    """
    out: dict[str, dict[str, int | bool]] = {}
    for name, fn in (
        ("autopilot_runs", get_autopilot_run_count),
        ("autopilot_parallel_enables", get_autopilot_parallel_count),
        ("dge_e2_cross_target", get_dge_e2_cross_target_count),
        ("team_runtime_sessions", get_team_runtime_count),
        ("allsolution_runs", get_allsolution_run_count),
    ):
        cur, tgt = fn()
        out[name] = {"current": cur, "target": tgt, "met": cur >= tgt}
    return out
