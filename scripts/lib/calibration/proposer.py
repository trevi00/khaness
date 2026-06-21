"""calibration.proposer — ledger 분석 + critic_policy 변경 제안 (v15.12).

설계 결정 (inline, debate 없음 — 기존 D4 패턴의 직접 응용):

  Signal source:
    state/operator-ledger/<project_id>/<agent_type>.jsonl (D5 산출)

  Per-agent_type 분석:
    - sample_size: 누적 record 수
    - success_count: failure_modes==[] AND success==True
    - failure_count: failure_modes non-empty
    - failure_mode 분포: {schema_violation: N, evidence_fabrication: N, ...}

  제안 규칙 (보수적 — 잘못된 제안이 적용되면 invariant 약화 위험):

    R1. sample_size < MIN_SAMPLE_SIZE → 제안 안 함 (insufficient evidence)

    R2. invoke → skip 제안 (자원 절약 방향, 약한 토큰 게이트 통과):
        - current decision = invoke
        - failure_rate < SKIP_THRESHOLD_FAILURE_RATE (예: 0.05)
        - sample_size >= MIN_SAMPLE_SIZE
        - agent_type NOT in DEFAULT_INVOKE (judgment-class agent는 자동 제안 안 함
          — 그 결정은 사용자 직접만 가능)
        - rationale: "최근 N개 dispatch 중 failure 0건 — critic 비활성화로 자원 절약"

    R3. skip → invoke 제안 (검출 강화 방향, 가장 안전):
        - current decision = skip
        - failure_rate >= INVOKE_THRESHOLD_FAILURE_RATE (예: 0.20)
        - sample_size >= MIN_SAMPLE_SIZE
        - rationale: "최근 N개 dispatch 중 failure N건 (rate >= 20%) — critic 활성 권장"

    R4. fabrication-heavy: evidence_fabrication >= 50% of failures
        → current==skip이면 invoke 제안 (R3 임계 미만에서도 격상).
          이유: D2 structural validator는 schema-conforming hallucination을
          못 잡지만 critic LLM-graded는 semantic으로 검출 가능. fabrication
          비율이 높으면 failure_rate가 R3 임계(20%) 아래여도 critic 격상 정당.
        → current==invoke면 D2 semantic layer trigger note (별도 cycle 작업)
        → Proposal evidence에 fabrication_fraction 명시

  자가개선 closure:
    제안 → 운영자 검토 (cli/calibration_review) → 운영자가 D4 토큰 들고
    critic_policy.apply_override() 호출. agent는 적용 안 함 (invariant 의도).

  Determinism:
    같은 ledger 입력 → 같은 제안 출력. 시간/랜덤 의존 없음.
    제안 ordering: agent_type 알파벳 순.

  Failure tolerance:
    ledger 디렉토리 부재 / 빈 파일 / malformed line → 빈 결과 반환 (raise 없음).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Literal

from ..critic_policy import resolve as resolve_critic_policy, DEFAULT_INVOKE
from ..operator_ledger import LEDGER_ROOT, read_records


# --- Tunable thresholds (calibrated conservatively) ------------------------------

MIN_SAMPLE_SIZE: int = 10
SKIP_THRESHOLD_FAILURE_RATE: float = 0.05
INVOKE_THRESHOLD_FAILURE_RATE: float = 0.20
FABRICATION_NOTE_FRACTION: float = 0.50


Decision = Literal["invoke", "skip"]


@dataclass
class AgentStats:
    """Per-agent ledger 통계 — 모든 제안의 source of truth."""

    agent_type: str
    sample_size: int
    success_count: int
    failure_count: int
    failure_mode_counts: dict[str, int] = field(default_factory=dict)

    @property
    def failure_rate(self) -> float:
        if self.sample_size == 0:
            return 0.0
        return self.failure_count / self.sample_size

    @property
    def success_rate(self) -> float:
        return 1.0 - self.failure_rate


@dataclass
class Proposal:
    """단일 정책 변경 제안.

    `current` = 현 시점 critic_policy.resolve 결과.
    `suggested` = 제안된 새 decision (None이면 action 없는 advisory note).
    `evidence` = AgentStats (정량 근거).
    `rationale` = 한국어 한 줄 사유.
    `note` = action 없는 advisory (예: fabrication-heavy 경고).
    """

    agent_type: str
    current: Decision
    suggested: Decision | None
    evidence: AgentStats
    rationale: str
    note: str | None = None


def _iter_project_dirs(ledger_root: Path | None = None) -> Iterator[Path]:
    base = ledger_root or LEDGER_ROOT
    if not base.exists():
        return
    for p in sorted(base.iterdir()):
        if p.is_dir() and not p.name.startswith("_"):
            yield p


def _iter_agent_jsonl(project_dir: Path) -> Iterator[Path]:
    for p in sorted(project_dir.glob("*.jsonl")):
        if not p.name.startswith("_"):
            yield p


def analyze_ledger(
    project_root: str,
    agent_type: str,
    *,
    ledger_root: Path | None = None,
) -> AgentStats:
    """Per-(project_root, agent_type) 통계 — 빈 ledger는 sample_size=0."""
    stats = AgentStats(
        agent_type=agent_type,
        sample_size=0,
        success_count=0,
        failure_count=0,
        failure_mode_counts={},
    )
    # ledger_root override: monkey-patch operator_ledger.LEDGER_ROOT 대신,
    # 우리가 직접 경로를 구성하고 read_records를 우회한다 (테스트 격리).
    if ledger_root is not None:
        from ..operator_ledger import project_id_for
        path = ledger_root / project_id_for(project_root) / f"{agent_type}.jsonl"
        records = _read_jsonl_safe(path)
    else:
        records = list(read_records(project_root, agent_type))
    for rec in records:
        stats.sample_size += 1
        modes = rec.get("failure_modes") or []
        if not isinstance(modes, list):
            modes = []
        if modes:
            stats.failure_count += 1
            for m in modes:
                if isinstance(m, str):
                    stats.failure_mode_counts[m] = (
                        stats.failure_mode_counts.get(m, 0) + 1
                    )
        else:
            if rec.get("success") is True:
                stats.success_count += 1
            # success=False AND failure_modes=[] → 카운트 안 함 (애매한 케이스)
    return stats


def _read_jsonl_safe(path: Path):
    if not path.exists():
        return
    import json
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def propose_critic_policy_changes(
    project_root: str,
    *,
    min_sample: int = MIN_SAMPLE_SIZE,
    ledger_root: Path | None = None,
    agent_types: list[str] | None = None,
) -> list[Proposal]:
    """Project 내 모든 agent_type을 스캔 → 제안 목록 반환.

    `agent_types`가 None이면 ledger 디렉토리에서 자동 검출.
    제안은 agent_type 알파벳 순 정렬.
    """
    proposals: list[Proposal] = []

    # ledger_root resolution
    base = ledger_root or LEDGER_ROOT
    from ..operator_ledger import project_id_for
    project_dir = base / project_id_for(project_root)

    # agent_type 검출
    if agent_types is None:
        if not project_dir.exists():
            return []
        agent_types = sorted(
            p.stem for p in project_dir.glob("*.jsonl")
            if not p.name.startswith("_")
        )

    for at in agent_types:
        stats = analyze_ledger(project_root, at, ledger_root=ledger_root)
        if stats.sample_size < min_sample:
            continue

        current = resolve_critic_policy(at)
        fr = stats.failure_rate

        # R2: invoke → skip (자원 절약, 강한 토큰 — judgment-class agent 자동 보호)
        if (current == "invoke"
                and fr < SKIP_THRESHOLD_FAILURE_RATE
                and at not in DEFAULT_INVOKE):
            proposals.append(Proposal(
                agent_type=at,
                current="invoke",
                suggested="skip",
                evidence=stats,
                rationale=(
                    f"최근 {stats.sample_size}개 dispatch 중 failure "
                    f"{stats.failure_count}건 (rate {fr:.1%} < "
                    f"{SKIP_THRESHOLD_FAILURE_RATE:.0%}) — critic 비활성화로 자원 절약 권장. "
                    f"적용 시 configure-critic-policy 토큰 필수 (invoke→skip 강한 방향)"
                ),
            ))
            continue

        # R3: skip → invoke (검출 강화, 안전 방향)
        if current == "skip" and fr >= INVOKE_THRESHOLD_FAILURE_RATE:
            proposals.append(Proposal(
                agent_type=at,
                current="skip",
                suggested="invoke",
                evidence=stats,
                rationale=(
                    f"최근 {stats.sample_size}개 dispatch 중 failure "
                    f"{stats.failure_count}건 (rate {fr:.1%} >= "
                    f"{INVOKE_THRESHOLD_FAILURE_RATE:.0%}) — critic 활성 권장. "
                    f"적용 시 apply-user-preference 토큰 (skip→invoke 안전 방향)"
                ),
            ))
            continue

        # R4: fabrication-heavy — R3 임계 미만에서도 격상 OR semantic-layer 호출
        fab_count = stats.failure_mode_counts.get("evidence_fabrication", 0)
        if (stats.failure_count > 0
                and fab_count / stats.failure_count >= FABRICATION_NOTE_FRACTION):
            fab_frac = fab_count / stats.failure_count
            if current == "skip":
                # critic LLM-graded는 schema-conforming hallucination 검출 가능
                proposals.append(Proposal(
                    agent_type=at,
                    current="skip",
                    suggested="invoke",
                    evidence=stats,
                    rationale=(
                        f"evidence_fabrication {fab_count}/{stats.failure_count} "
                        f"({fab_frac:.0%}, >= {FABRICATION_NOTE_FRACTION:.0%}) — "
                        f"D2 structural은 schema-conforming hallucination 못 잡음, "
                        f"critic LLM-graded 필요. failure_rate {fr:.1%}가 R3 임계 "
                        f"{INVOKE_THRESHOLD_FAILURE_RATE:.0%} 아래여도 fabrication 비율로 격상. "
                        f"적용 시 apply-user-preference 토큰 (skip→invoke 안전 방향)"
                    ),
                ))
            else:
                # current=invoke: critic 활성인데도 fabrication 누락 → semantic layer trigger
                proposals.append(Proposal(
                    agent_type=at,
                    current="invoke",
                    suggested=None,
                    evidence=stats,
                    rationale=(
                        "critic 활성에도 fabrication 발생 — Architect self_doubt 시나리오 실현. "
                        "D2 semantic layer 별도 cycle 필요 (calibration 범위 외이지만 surface는 필수)."
                    ),
                    note=(
                        f"evidence_fabrication {fab_count}/{stats.failure_count} "
                        f"({fab_frac:.0%}). critic invoke 중에도 누락된 케이스 — "
                        f"D2 structural layer만으로는 차단 불가, semantic 계층 필요."
                    ),
                ))

    return proposals
