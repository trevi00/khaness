"""calibration — operator-ledger 누적 분석 → 정책 변경 *제안* (v15.12).

자가개선 메타루프의 첫 자기-인스턴스화. ledger 데이터 패턴에서 critic_policy
변경을 *제안*하지만 **자동 적용은 절대 금지** — 적용은 CLAUDE.md L0
"NEVER 자동" 영역인 정책 변경 (apply-user-preference / configure-critic-policy
토큰 게이트 통과 필수).

본 패키지의 역할:
1. ledger 데이터 통계 분석 (per-agent_type)
2. 정책 변경 후보 생성 + evidence 첨부
3. 운영자 검토용 reporting

NOT in scope (v15.12):
- 자동 적용 (운영자 수동 단계 영구 유지 — MANUAL-ENFORCEMENT-AUDIT.md 결론)
- ledger 데이터 mutation (read-only)
- breaker 또는 다른 lib 정책 calibration (다음 cycle)

Public surface:
- analyze_ledger(project_root, agent_type) -> AgentStats
- propose_critic_policy_changes(project_root, *, min_sample) -> list[Proposal]
- Proposal (dataclass): agent_type, current, suggested, evidence, rationale
"""
from __future__ import annotations

from .proposer import (
    AgentStats,
    Proposal,
    analyze_ledger,
    propose_critic_policy_changes,
)
from .breaker_proposer import (
    BreakerProposal,
    BreakerStats,
    analyze_breaker,
    propose_breaker_changes,
)

__all__ = [
    "AgentStats",
    "BreakerProposal",
    "BreakerStats",
    "Proposal",
    "analyze_breaker",
    "analyze_ledger",
    "propose_breaker_changes",
    "propose_critic_policy_changes",
]
