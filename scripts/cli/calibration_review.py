#!/usr/bin/env python3
"""calibration_review — 운영자 검토 CLI (v15.12).

operator-ledger 누적 데이터를 분석하여 critic_policy 변경 제안을 출력.
**적용은 절대 안 함** (CLAUDE.md L0 invariant — agent가 정책 직접 변경 금지).
운영자가 제안을 검토 후 별도 명령(critic_policy.apply_override CLI 등)으로
직접 적용.

Usage:
    cd ~/.claude/scripts
    python -m cli.calibration_review                       # 현재 cwd 기준 ledger
    python -m cli.calibration_review --project-root <path> # 특정 프로젝트
    python -m cli.calibration_review --json                # 기계 가독 출력
    python -m cli.calibration_review --min-sample 20       # 임계 조정

Exit codes:
    0  제안 있음 또는 없음 (정상 종료, dry-run only)
    1  argparse error
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.calibration import (  # noqa: E402
    BreakerProposal,
    Proposal,
    propose_breaker_changes,
    propose_critic_policy_changes,
)
from lib.calibration.proposer import MIN_SAMPLE_SIZE  # noqa: E402
from lib.calibration.threshold_proposer import (  # noqa: E402  M22
    ThresholdProposal,
    propose_threshold_changes,
)
from lib.threshold_policy import TOKEN_RISKY, TOKEN_SAFE as THRESHOLD_TOKEN_SAFE, _is_risky  # noqa: E402
from lib.calibration.threshold_registry import REGISTRY as THRESHOLD_REGISTRY  # noqa: E402
from lib.critic_policy import (  # noqa: E402
    TOKEN_GATE_INVOKE_TO_SKIP,
    TOKEN_GATE_SKIP_TO_INVOKE,
)
from lib.breakers.config import TOKEN_SAFE, TOKEN_STRONG  # noqa: E402


def _threshold_apply_command(p: ThresholdProposal) -> str | None:
    """Copy-pasteable apply CLI for a gate-accepted threshold proposal. None when the
    gate did not accept (note-only — no apply offered)."""
    if p.suggested is None:
        return None
    entry = THRESHOLD_REGISTRY.get(p.name)
    token = TOKEN_RISKY if (entry is None or _is_risky(entry, p.suggested)) else THRESHOLD_TOKEN_SAFE
    return (
        f"python -m cli.threshold_override --name {p.name} "
        f"--value {p.suggested} --token {token}"
    )


def _format_threshold_proposal(p: ThresholdProposal) -> str:
    gate = p.gate_result
    lines = [
        f"  name           : {p.name}",
        f"  current        : {p.current}",
        f"  suggested      : {p.suggested if p.suggested is not None else '(no action — advisory)'}",
        f"  sample_size    : {p.evidence.get('sample_size')}",
        f"  gate accept    : {gate.accept if gate else 'n/a'}",
        f"  gate reason    : {gate.reason if gate else 'n/a'}",
        f"  rationale      : {p.rationale}",
    ]
    if p.note:
        lines.append(f"  note           : {p.note}")
    cmd = _threshold_apply_command(p)
    if cmd:
        lines.append(f"  >>> apply      : {cmd}")
    return "\n".join(lines)


def _threshold_proposal_to_dict(p: ThresholdProposal) -> dict:
    return {
        "kind": "threshold",
        "name": p.name,
        "current": p.current,
        "suggested": p.suggested,
        "rationale": p.rationale,
        "note": p.note,
        "holdout_boundary": p.holdout_boundary,
        "gate": (None if p.gate_result is None else {
            "accept": p.gate_result.accept,
            "target_delta_holdout": p.gate_result.target_delta_holdout,
            "guard_delta": p.gate_result.guard_delta,
            "reason": p.gate_result.reason,
        }),
        "apply_command": _threshold_apply_command(p),
        "evidence": p.evidence,
    }


def _critic_apply_command(p: Proposal) -> str | None:
    """Render a copy-pasteable CLI command for applying a critic_policy proposal.

    Returns None when the proposal has no actionable suggestion (note-only).
    Token selection mirrors lib.critic_policy.apply_override's asymmetric gate:
      invoke→skip : configure-critic-policy
      skip→invoke : apply-user-preference
    """
    if p.suggested is None:
        return None
    if p.current == "invoke" and p.suggested == "skip":
        token = TOKEN_GATE_INVOKE_TO_SKIP
    else:
        token = TOKEN_GATE_SKIP_TO_INVOKE
    return (
        f"python -m cli.critic_policy_override "
        f"--agent {p.agent_type} --decision {p.suggested} --token {token}"
    )


def _breaker_apply_command(p: BreakerProposal) -> str | None:
    """Copy-pasteable CLI for breaker proposal. None on advisory-only."""
    if p.suggested_value is None or p.current_value is None:
        return None
    # asymmetric gate (lib.breakers.config 정책과 일치)
    if p.target_constant in ("trip_window", "trip_any_window"):
        token = TOKEN_SAFE  # ambiguous
    elif p.suggested_value > p.current_value:
        token = TOKEN_STRONG  # increase = lenient
    else:
        token = TOKEN_SAFE   # decrease = safer
    return (
        f"python -m cli.breaker_override "
        f"--key {p.target_constant} --value {p.suggested_value} --token {token}"
    )


def _format_proposal(p: Proposal) -> str:
    lines = [
        f"  agent_type     : {p.agent_type}",
        f"  current        : {p.current}",
        f"  suggested      : {p.suggested if p.suggested else '(no action — advisory)'}",
        f"  sample_size    : {p.evidence.sample_size}",
        f"  success_count  : {p.evidence.success_count}",
        f"  failure_count  : {p.evidence.failure_count}",
        f"  failure_rate   : {p.evidence.failure_rate:.1%}",
    ]
    if p.evidence.failure_mode_counts:
        modes = ", ".join(
            f"{k}={v}" for k, v in sorted(p.evidence.failure_mode_counts.items())
        )
        lines.append(f"  failure_modes  : {modes}")
    lines.append(f"  rationale      : {p.rationale}")
    if p.note:
        lines.append(f"  note           : {p.note}")
    cmd = _critic_apply_command(p)
    if cmd:
        lines.append(f"  >>> apply      : {cmd}")
    return "\n".join(lines)


def _proposal_to_dict(p: Proposal) -> dict:
    return {
        "kind": "critic_policy",
        "agent_type": p.agent_type,
        "current": p.current,
        "suggested": p.suggested,
        "rationale": p.rationale,
        "note": p.note,
        "apply_command": _critic_apply_command(p),
        "evidence": {
            "sample_size": p.evidence.sample_size,
            "success_count": p.evidence.success_count,
            "failure_count": p.evidence.failure_count,
            "failure_rate": p.evidence.failure_rate,
            "failure_mode_counts": p.evidence.failure_mode_counts,
        },
    }


def _format_breaker_proposal(p: BreakerProposal) -> str:
    lines = [
        f"  agent_type     : {p.agent_type}",
        f"  failure_mode   : {p.failure_mode}",
        f"  target         : {p.target_constant}",
        f"  current_value  : {p.current_value}",
        f"  suggested      : {p.suggested_value if p.suggested_value is not None else '(no action — advisory)'}",
        f"  current_state  : {p.evidence.current_state}",
        f"  trip_count     : {p.evidence.trip_count}",
        f"  history_len    : {p.evidence.history_len}",
        f"  failures/window: {p.evidence.failures_in_window}/{p.evidence.history_len}",
        f"  rationale      : {p.rationale}",
    ]
    if p.note:
        lines.append(f"  note           : {p.note}")
    cmd = _breaker_apply_command(p)
    if cmd:
        lines.append(f"  >>> apply      : {cmd}")
    return "\n".join(lines)


def _breaker_proposal_to_dict(p: BreakerProposal) -> dict:
    return {
        "kind": "breaker",
        "agent_type": p.agent_type,
        "failure_mode": p.failure_mode,
        "target_constant": p.target_constant,
        "current_value": p.current_value,
        "suggested_value": p.suggested_value,
        "rationale": p.rationale,
        "note": p.note,
        "apply_command": _breaker_apply_command(p),
        "evidence": {
            "current_state": p.evidence.current_state,
            "trip_count": p.evidence.trip_count,
            "history_len": p.evidence.history_len,
            "failures_in_window": p.evidence.failures_in_window,
            "window_failure_rate": p.evidence.window_failure_rate,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="calibration-review",
        description=(
            "v15.12 — ledger 누적 분석 → critic_policy 변경 제안 (dry-run only). "
            "적용은 별도 명령으로 운영자가 직접 (CLAUDE.md L0 invariant 유지)."
        ),
    )
    parser.add_argument(
        "--project-root", default=None,
        help="대상 프로젝트 루트 (기본: cwd)",
    )
    parser.add_argument(
        "--min-sample", type=int, default=MIN_SAMPLE_SIZE,
        help=f"제안 생성을 위한 최소 누적 record 수 (기본 {MIN_SAMPLE_SIZE})",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="기계 가독 JSON 출력",
    )
    args = parser.parse_args(argv)

    project_root = args.project_root or os.getcwd()
    critic_proposals = propose_critic_policy_changes(
        project_root, min_sample=args.min_sample,
    )
    breaker_proposals = propose_breaker_changes(project_root)
    try:  # M22: threshold proposals read live telemetry; fail-soft (review must not crash)
        threshold_proposals = propose_threshold_changes(min_sample=args.min_sample)
    except Exception:  # noqa: BLE001
        threshold_proposals = []
    total = len(critic_proposals) + len(breaker_proposals) + len(threshold_proposals)

    if args.json:
        out = {
            "project_root": project_root,
            "min_sample": args.min_sample,
            "proposal_count": total,
            "critic_policy_count": len(critic_proposals),
            "breaker_count": len(breaker_proposals),
            "threshold_count": len(threshold_proposals),
            "proposals": (
                [_proposal_to_dict(p) for p in critic_proposals]
                + [_breaker_proposal_to_dict(p) for p in breaker_proposals]
                + [_threshold_proposal_to_dict(p) for p in threshold_proposals]
            ),
        }
        print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    print(f"=== calibration review — project_root={project_root} ===")
    print(f"min_sample={args.min_sample}  critic_policy={len(critic_proposals)}  breaker={len(breaker_proposals)}")
    print()
    if total == 0:
        print("[INFO] 변경 제안 없음")
        print("  - ledger / breaker 데이터가 비어있거나 (다음 Agent dispatch 후 누적)")
        print("  - 모든 agent_type이 임계 미만 sample_size (--min-sample 낮춰서 재시도 가능)")
        print("  - 모든 항목이 안정 상태 (action 불필요)")
        return 0

    if critic_proposals:
        print("--- Critic Policy 제안 ---")
        for i, p in enumerate(critic_proposals, 1):
            print(f"[{i}/{len(critic_proposals)}] critic_policy Proposal")
            print(_format_proposal(p))
            print()

    if breaker_proposals:
        print("--- Breaker 임계 제안 ---")
        for i, p in enumerate(breaker_proposals, 1):
            print(f"[{i}/{len(breaker_proposals)}] breaker Proposal")
            print(_format_breaker_proposal(p))
            print()

    if threshold_proposals:
        print("--- Threshold 튜닝 제안 (M22) ---")
        for i, p in enumerate(threshold_proposals, 1):
            print(f"[{i}/{len(threshold_proposals)}] threshold Proposal")
            print(_format_threshold_proposal(p))
            print()

    print("=== 적용 안내 ===")
    print("본 CLI는 dry-run only. 적용 시 운영자가 직접:")
    print("  python -m cli.<future_apply_critic_policy_cli> \\")
    print("    --agent <agent_type> --decision <invoke|skip> --token <required_token>")
    print()
    print("토큰 매핑 (critic_policy.py 게이트):")
    print("  invoke → skip : configure-critic-policy  (강한 방향)")
    print("  skip → invoke : apply-user-preference    (안전 방향)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
