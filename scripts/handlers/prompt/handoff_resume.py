#!/usr/bin/env python3
"""handoff_resume.py — UserPromptSubmit hook (D5: Cycle 18).

debate-1778987087-311613 D5: HANDOFF Resume Pointer 자동화.

목적:
  cwd에 `HANDOFF.md`가 존재하면, Resume Pointer 블록 (last_completed / next_action)
  유효성을 검증하고 사용자에게 상태를 advisory로 노출. 누락/stale 시 경고 (block 0).

행동 분류:
  1. HANDOFF.md 부재 → no-op (silent exit)
  2. HANDOFF.md 존재 + Resume Pointer 블록 유효 (last_completed + next_action 모두 lock'd) →
     `<handoff-status>` advisory 주입 (현재 cycle marker + 다음 cycle)
  3. HANDOFF.md 존재 + Resume Pointer 블록 부재/불완전 → `<handoff-warn>` advisory (block 0)
  4. HANDOFF.md mtime > 7일 → stale 표기 추가

설계 결정 (debate D5 narrow scope):
  - /clear command 직접 인터셉트 안 함 — UserPromptSubmit이 slash-command와 일반 prompt를 구분하지 않는 한계.
  - 대신 매 prompt마다 informational advisory로 노출 → 사용자가 `이어가자`/`진행하자` 입력 시 즉시 상태 인지.
  - block 0 (exit 0 + advisory only) — 작업 흐름 차단 회피.
"""

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.io import read_hook_input, write_hook_output, additional_context  # noqa: E402
from lib.logging import log_telemetry  # noqa: E402

HANDOFF_FILENAME = "HANDOFF.md"
STALE_DAYS_THRESHOLD = 7

# Resume Pointer 블록 인식 — YAML 코드 펜스 안의 last_completed/next_action 키.
# 정규식은 multiline + 비-greedy + ```yaml 둘 다 허용.
RESUME_BLOCK_RE = re.compile(
    r"```(?:yaml)?\s*\n[\s\S]*?\b(?:last_completed|next_action)\s*:[\s\S]*?\n```",
    re.MULTILINE,
)
LAST_COMPLETED_RE = re.compile(r"^\s*(?:last_completed|cycle)\s*:\s*(.+?)$", re.MULTILINE)
NEXT_ACTION_RE = re.compile(r"^\s*next_action\s*:\s*\n([\s\S]*?)(?=^\S|\Z)", re.MULTILINE)
CYCLE_MARKER_RE = re.compile(r"cycle\s*:\s*([A-Za-z0-9._-]+)")
DECISION_ID_RE = re.compile(r"decision_id\s*:\s*([A-Za-z0-9._-]+)")


def find_handoff(cwd: str) -> Path | None:
    """cwd에서 HANDOFF.md 검색 (상위 5 단계까지). project_paths 패턴과 일관."""
    if not cwd:
        return None
    p = Path(cwd).resolve()
    for _ in range(6):
        candidate = p / HANDOFF_FILENAME
        if candidate.is_file():
            return candidate
        if p.parent == p:
            break
        p = p.parent
    return None


def parse_resume_pointer(text: str) -> dict[str, str | bool]:
    """Resume Pointer 블록 파싱. last_completed/next_action 존재 여부 + 식별자 추출."""
    block_match = RESUME_BLOCK_RE.search(text)
    if not block_match:
        return {"has_block": False}

    block = block_match.group(0)
    last_match = LAST_COMPLETED_RE.search(block)
    next_match = NEXT_ACTION_RE.search(block)
    cycle_match = CYCLE_MARKER_RE.search(block)
    decision_match = DECISION_ID_RE.search(block)

    return {
        "has_block": True,
        "has_last": bool(last_match),
        "has_next": bool(next_match),
        "cycle": cycle_match.group(1) if cycle_match else "",
        "decision": decision_match.group(1) if decision_match else "",
    }


def is_stale(handoff_path: Path) -> tuple[bool, int]:
    """파일 mtime 기준 stale 판정. (is_stale, age_days) 반환."""
    try:
        mtime = handoff_path.stat().st_mtime
    except OSError:
        return False, 0
    age_seconds = datetime.now(timezone.utc).timestamp() - mtime
    # Clamp to non-negative: a freshly-created file's mtime can be a hair AHEAD
    # of now() (clock granularity / stat rounding), making age_seconds a tiny
    # negative whose floor-div yields -1. Age is never negative.
    age_days = max(0, int(age_seconds // 86_400))
    return age_days > STALE_DAYS_THRESHOLD, age_days


def build_status_advisory(info: dict[str, str | bool], age_days: int, path: Path) -> str:
    cycle = info.get("cycle", "") or "(unset)"
    decision = info.get("decision", "") or "(unset)"
    stale_note = f" ⚠️ {age_days}일 미갱신" if age_days > STALE_DAYS_THRESHOLD else ""
    return (
        f"<handoff-status path={str(path)!r}>\n"
        f"  next_cycle: {cycle}\n"
        f"  decision_id: {decision}\n"
        f"  age_days: {age_days}{stale_note}\n"
        f"  hint: Resume Pointer 따라 진행하거나 사용자 입력 우선.\n"
        f"</handoff-status>"
    )


def build_warn_advisory(path: Path, info: dict[str, str | bool]) -> str:
    missing = []
    if not info.get("has_block"):
        missing.append("Resume Pointer YAML 블록")
    else:
        if not info.get("has_last"):
            missing.append("last_completed 필드")
        if not info.get("has_next"):
            missing.append("next_action 필드")
    return (
        f"<handoff-warn path={str(path)!r}>\n"
        f"  missing: {', '.join(missing) or '(파싱 실패)'}\n"
        f"  recommendation: HANDOFF.md에 last_completed + next_action 블록 추가 권고 (debate D5).\n"
        f"</handoff-warn>"
    )


def main() -> None:
    payload = read_hook_input()
    cwd = payload.get("cwd", "")
    handoff_path = find_handoff(cwd)

    if handoff_path is None:
        # Silent — HANDOFF 없는 디렉토리는 본 hook의 대상 아님.
        sys.exit(0)

    try:
        text = handoff_path.read_text(encoding="utf-8")
    except OSError:
        sys.exit(0)

    info = parse_resume_pointer(text)
    stale, age_days = is_stale(handoff_path)

    if info.get("has_block") and info.get("has_last") and info.get("has_next"):
        advisory = build_status_advisory(info, age_days, handoff_path)
    else:
        advisory = build_warn_advisory(handoff_path, info)

    log_telemetry(
        "handoff-resume",
        {
            "cwd": cwd,
            "path": str(handoff_path),
            "has_block": info.get("has_block"),
            "has_last": info.get("has_last"),
            "has_next": info.get("has_next"),
            "cycle": info.get("cycle"),
            "decision": info.get("decision"),
            "age_days": age_days,
            "stale": stale,
        },
    )

    write_hook_output(additional_context(advisory, "UserPromptSubmit"))


if __name__ == "__main__":
    main()
