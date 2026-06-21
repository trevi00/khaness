"""calibration.breaker_proposer — composite breaker 임계 자동 제안 (v15.14).

설계 (lib.calibration.proposer R1-R4 패턴 재사용):

  Signal source:
    state/breakers/<project_id>/<agent_type>__<failure_mode>.json (D3 산출)

  Per-(agent_type, failure_mode) 분석:
    - trip_count: 누적 trip 횟수 (re-open 포함)
    - current_state: closed/open/half_open
    - history length: 최근 TRIP_WINDOW(10) entries
    - failures_in_window: 최근 윈도우 내 failure 수

  제안 규칙 (보수적, advisory only — 적용은 코드/config 운영자 영역):

    BR1. sample_size (history 길이) < MIN_HISTORY → 제안 안 함
         (TRIP_WINDOW=10이므로 최소 10번 fire 필요)

    BR2. 빈번한 trip (false positive 의심):
         - trip_count >= FREQUENT_TRIP_COUNT (예: 5)
         - 최근 window의 failure_rate 30% 근처 (3/10 정확히)
         - → TRIP_PER_MODE 상향 권장 (3 → 4)
         - rationale: 임계가 너무 민감하여 정상 failure도 차단

    BR3. trip 없는 누적 (잘못 calibrated 가능):
         - trip_count == 0
         - history length >= MIN_HISTORY * 2 (충분한 sample)
         - failures_in_window > 0 AND < 3 (임계 직전 누적)
         - → 정보성 note만 (action 없음 — 임계 하향은 위험)

    BR4. 빈번한 re-open (backoff 너무 짧음):
         - trip_count >= 3 (여러 번 trip)
         - state == open이면서 cool_off_until - opened_at < 절반 BACKOFF_CAP_SEC
         - → BACKOFF_BASE_SEC 상향 권장
         - rationale: 짧은 backoff로 probe 실패 → re-open 반복

  자동 적용 금지 (CLAUDE.md L0 invariant):
    breaker 임계는 composite.py 의 module-level 상수 — 수정 = 코드 편집
    = invariant 영역. 본 proposer는 제안만, 적용은 운영자 직접.

  Output:
    BreakerProposal dataclass (lib.calibration.proposer.Proposal와 별도 — 다른
    domain). 같은 cli/calibration_review에서 통합 출력.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from ..atomic_json import read_json
from ..breakers.composite import (
    BACKOFF_BASE_SEC,
    BACKOFF_CAP_SEC,
    TRIP_PER_MODE,
    TRIP_WINDOW,
)
from ..paths import STATE_DIR


# --- Tunable thresholds ----------------------------------------------------------

MIN_HISTORY_LEN: int = TRIP_WINDOW   # 최소 한 window 채워야
FREQUENT_TRIP_COUNT: int = 5
REOPEN_HEAVY_TRIP_COUNT: int = 3


@dataclass
class BreakerStats:
    """Per-(agent, failure_mode) breaker 통계."""

    agent_type: str
    failure_mode: str
    current_state: str
    trip_count: int
    history_len: int
    failures_in_window: int
    opened_at: float | None
    cool_off_until: float | None

    @property
    def window_failure_rate(self) -> float:
        if self.history_len == 0:
            return 0.0
        return self.failures_in_window / self.history_len


@dataclass
class BreakerProposal:
    """단일 breaker 임계 변경 제안.

    `target_constant`: composite.py 의 module-level 상수명 (TRIP_PER_MODE 등).
    `current_value`: 현 값 (제안 시점 import).
    `suggested_value`: 제안 값 (None이면 advisory note만).
    """

    agent_type: str
    failure_mode: str
    target_constant: str
    current_value: int | None
    suggested_value: int | None
    evidence: BreakerStats
    rationale: str
    note: str | None = None


def _iter_breaker_files(
    project_root: str | None = None,
    *,
    breakers_root: Path | None = None,
) -> Iterator[Path]:
    """Yield <key>.json under state/breakers/<project_id>/.

    project_root=None → 모든 project_id 스캔. 그 외 → 해당 project만.
    """
    base = breakers_root or (STATE_DIR / "breakers")
    if not base.exists():
        return
    if project_root is not None:
        from ..operator_ledger import project_id_for
        target = base / project_id_for(project_root)
        if not target.exists():
            return
        for p in sorted(target.glob("*.json")):
            yield p
    else:
        for project_dir in sorted(base.iterdir()):
            if not project_dir.is_dir():
                continue
            for p in sorted(project_dir.glob("*.json")):
                yield p


def _parse_key_filename(path: Path) -> tuple[str, str]:
    """<agent_type>__<failure_mode>.json → (agent_type, failure_mode).

    composite.py _key_filename과 inverse (defensive — 분할 실패 시 ('?','?'))."""
    stem = path.stem
    if "__" in stem:
        a, f = stem.split("__", 1)
        return a, f
    return "?", "?"


def analyze_breaker(path: Path) -> BreakerStats | None:
    """Read breaker JSON, compute stats. Missing/malformed → None."""
    if not path.exists():
        return None
    rec = read_json(path, default={})
    if not isinstance(rec, dict):
        return None
    agent_type, failure_mode = _parse_key_filename(path)
    history = rec.get("history", []) or []
    if not isinstance(history, list):
        history = []
    failures = sum(1 for x in history if x is False or x == 0)
    return BreakerStats(
        agent_type=agent_type,
        failure_mode=failure_mode,
        current_state=str(rec.get("state", "closed")),
        trip_count=int(rec.get("trip_count", 0) or 0),
        history_len=len(history),
        failures_in_window=failures,
        opened_at=rec.get("opened_at"),
        cool_off_until=rec.get("cool_off_until"),
    )


def propose_breaker_changes(
    project_root: str | None = None,
    *,
    min_history: int = MIN_HISTORY_LEN,
    breakers_root: Path | None = None,
) -> list[BreakerProposal]:
    """Scan breaker files → BreakerProposal list (BR1-BR4 rules)."""
    proposals: list[BreakerProposal] = []
    for path in _iter_breaker_files(project_root, breakers_root=breakers_root):
        stats = analyze_breaker(path)
        if stats is None:
            continue

        # BR1: insufficient history
        if stats.history_len < min_history:
            continue

        # BR2: frequent trip — false positive suspicion
        if (stats.trip_count >= FREQUENT_TRIP_COUNT
                and stats.failures_in_window >= TRIP_PER_MODE):
            proposals.append(BreakerProposal(
                agent_type=stats.agent_type,
                failure_mode=stats.failure_mode,
                target_constant="trip_per_mode",
                current_value=TRIP_PER_MODE,
                suggested_value=TRIP_PER_MODE + 1,
                evidence=stats,
                rationale=(
                    f"trip_count={stats.trip_count} (>= {FREQUENT_TRIP_COUNT}) + "
                    f"window failure_rate {stats.window_failure_rate:.0%} (>= "
                    f"{TRIP_PER_MODE}/{TRIP_WINDOW}) — 임계 너무 민감, "
                    f"TRIP_PER_MODE {TRIP_PER_MODE} → {TRIP_PER_MODE + 1} 상향 권장. "
                    f"적용은 composite.py 직접 수정 (코드 편집 = 운영자 영역)"
                ),
            ))
            continue

        # BR4: reopen-heavy — backoff too short
        if (stats.trip_count >= REOPEN_HEAVY_TRIP_COUNT
                and stats.current_state == "open"
                and stats.opened_at is not None
                and stats.cool_off_until is not None):
            cool_off_window = stats.cool_off_until - stats.opened_at
            if cool_off_window < BACKOFF_CAP_SEC / 2:
                suggested = min(BACKOFF_BASE_SEC * 2, BACKOFF_CAP_SEC // 2)
                proposals.append(BreakerProposal(
                    agent_type=stats.agent_type,
                    failure_mode=stats.failure_mode,
                    target_constant="backoff_base_sec",
                    current_value=BACKOFF_BASE_SEC,
                    suggested_value=suggested,
                    evidence=stats,
                    rationale=(
                        f"trip_count={stats.trip_count} (>= {REOPEN_HEAVY_TRIP_COUNT}) + "
                        f"현 cool_off window {cool_off_window:.0f}s < "
                        f"{BACKOFF_CAP_SEC // 2}s — probe 실패 반복 의심, "
                        f"BACKOFF_BASE_SEC {BACKOFF_BASE_SEC}s → {suggested}s 상향 권장. "
                        f"적용은 composite.py 직접 수정"
                    ),
                ))
                continue

        # BR3: 잘못 calibrated 가능성 (trip 없음 + 임계 직전 누적) — note only
        if (stats.trip_count == 0
                and stats.history_len >= min_history * 2
                and 0 < stats.failures_in_window < TRIP_PER_MODE):
            proposals.append(BreakerProposal(
                agent_type=stats.agent_type,
                failure_mode=stats.failure_mode,
                target_constant="trip_per_mode",
                current_value=TRIP_PER_MODE,
                suggested_value=None,  # advisory only
                evidence=stats,
                rationale="정보성 — 임계 직전 누적 감지 (자동 하향 안 함, false negative 위험)",
                note=(
                    f"누적 {stats.history_len} fire, trip 0회, window failures "
                    f"{stats.failures_in_window}/{TRIP_PER_MODE}. 임계 직전 안정 또는 "
                    f"운영자 검토 필요 — TRIP_PER_MODE 하향은 false-positive 위험 있어 "
                    f"calibration이 자동 제안하지 않음."
                ),
            ))

    return proposals
