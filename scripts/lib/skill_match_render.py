"""skill_match_render — render helpers for the UserPromptSubmit hook output.

Extracted from `handlers/prompt/skill_match.py` (Round 6 W2 P1). Pure
functions that turn the matcher's results into human-readable advisory
strings injected as additionalContext.

Public API:
- `PROMPT_TOOL_ROUTING_HINTS`: list of (signal_keywords, hint_message) used
  by `detect_tool_routing_hints` to nudge users away from Bash for tasks
  that have a dedicated Claude Code tool.
- `build_cross_references(matched_skills, all_skills_meta)`: list of
  (matched_name, recommended_skill_file, summary_keywords) tuples derived
  from the matched skills' `requires:` frontmatter.
- `build_phase_guidance(detected_phases, matched_skills)`: phase-specific
  guidance string. `matched_skills` retained for backward compat (unused).
- `detect_tool_routing_hints(prompt_lower)`: list of hint messages whose
  signals appear in the lowered prompt.
- `build_sensor_reminder(detected_phases)`: list of sensor reminders for
  implement/review phases.

Pure: no module-level state beyond the constant; no I/O.
"""
from __future__ import annotations

from typing import Any

from .frontmatter_norm import split_list_field


# Tool routing rules: (prompt signals, hint message)
PROMPT_TOOL_ROUTING_HINTS: list[tuple[list[str], str]] = [
    (
        ["파일 검색", "파일 찾", "find file", "find files", "파일을 찾", "파일 탐색",
         "파일 목록", "list files", "파일이 어디"],
        "파일 검색에는 Bash(find)가 아닌 Glob 도구를 사용하세요",
    ),
    (
        ["내용 검색", "콘텐츠 검색", "텍스트 검색", "grep", "문자열 찾",
         "코드 검색", "search content", "search for", "찾아줘", "어디에 있"],
        "콘텐츠 검색에는 Bash(grep)가 아닌 Grep 도구를 사용하세요",
    ),
    (
        ["파일 읽", "파일 확인", "내용 확인", "cat ", "read file", "파일 내용",
         "파일을 읽", "파일 보여", "파일을 보"],
        "파일 읽기에는 Bash(cat)가 아닌 Read 도구를 사용하세요",
    ),
    (
        ["파일 수정", "파일 편집", "파일 변경", "sed ", "edit file", "파일을 수정",
         "파일을 편집", "수정해줘", "바꿔줘", "변경해줘"],
        "파일 편집에는 Bash(sed)가 아닌 Edit 도구를 사용하세요",
    ),
]


_PHASE_NAMES: dict[str, str] = {
    "plan": "계획/설계 (Plan)",
    "implement": "구현 (Implement)",
    "review": "검토/리뷰 (Review)",
    "deploy": "배포 (Deploy)",
    "debug": "디버그/수정 (Debug)",
}

_PHASE_GUIDANCE: dict[str, str] = {
    "plan": "설계와 아키텍처 결정에 집중하세요. 체크리스트의 구조 관련 항목을 우선 확인하세요.",
    "implement": "구현 가이드와 코드 패턴을 참고하세요. 체크리스트를 따라 빠짐없이 구현하세요.",
    "review": "체크리스트를 기준으로 검토하세요. 보안, 성능, 에러 처리를 점검하세요.",
    "deploy": "배포 전 체크리스트를 확인하세요. 환경 설정과 시크릿 관리를 점검하세요.",
    "debug": "에러 로그와 스택 트레이스를 분석하세요. 관련 패턴을 참고하여 원인을 찾으세요.",
}


def build_cross_references(
    matched_skills: list[tuple[Any, str, Any, Any]],
    all_skills_meta: dict[str, dict[str, Any]],
) -> list[tuple[str, str, str]]:
    """Derive cross-skill recommendations from each match's `requires:` field.

    Returns (origin_skill_name, recommended_skill_file, top_3_keywords) tuples.
    Skips entries where the recommended file is itself already matched, and
    deduplicates so the same suggestion is not made twice.
    """
    matched_names = {s[1] for s in matched_skills}
    recommendations: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    for _, name, _, _ in matched_skills:
        meta = all_skills_meta.get(name, {})
        requires = split_list_field(meta.get("requires", ""))
        for req in requires:
            req_file = f"{req}.md"
            if req_file in all_skills_meta and req_file not in matched_names:
                if req_file not in seen:
                    seen.add(req_file)
                    req_kws = split_list_field(all_skills_meta[req_file].get("keywords", ""))[:3]
                    recommendations.append((name, req_file, " ".join(req_kws)))
    return recommendations


def build_phase_guidance(
    detected_phases: set[str] | list[str],
    matched_skills: Any = None,  # noqa: ARG001 - kept for backward compat
) -> str:
    """Build phase-specific guidance string for matched skills.

    `matched_skills` parameter is retained for caller compatibility but is
    not consulted; phase guidance is purely a function of `detected_phases`.
    """
    if not detected_phases:
        return ""
    parts: list[str] = []
    for phase in sorted(detected_phases):
        name = _PHASE_NAMES.get(phase, phase)
        guidance = _PHASE_GUIDANCE.get(phase, "")
        parts.append(f"{name}: {guidance}")
    return "\n".join(parts)


def detect_tool_routing_hints(prompt_lower: str) -> list[str]:
    """Return all matching tool-routing hint messages whose signals appear in
    the lowered prompt. One match per rule (rule order = priority).
    """
    hints: list[str] = []
    for signals, message in PROMPT_TOOL_ROUTING_HINTS:
        for signal in signals:
            if signal.lower() in prompt_lower:
                hints.append(message)
                break
    return hints


def build_sensor_reminder(detected_phases: set[str] | list[str]) -> list[str]:
    """Return sensor reminders for implement/review phases."""
    reminders: list[str] = []
    if "implement" in detected_phases:
        reminders.append("구현 후 테스트/린터를 실행하여 피드백 루프를 완성하세요 (Sensor)")
    if "review" in detected_phases:
        reminders.append("정적 분석 도구와 테스트 결과를 확인하세요 (Sensor)")
    return reminders
