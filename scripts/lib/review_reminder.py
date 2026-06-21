"""review_reminder — post-tool 코드 리뷰 리마인더 메시지 빌더 (Round 6 W2 P1).

Extracted from handlers/post_tool/reviewer.py. Pure function: takes tool name
+ file path + optional recent changes string, returns formatted review prompt
to inject into the post-tool hook output.

Language-aware: appends `.py` 타입힌트, `.rs` borrow checker, `.cpp` memory
관리 등 확장자별 체크포인트.
"""
from __future__ import annotations

import os


# Common checklist items applied to any code file.
BASE_CHECKS = (
    "에러 처리: 예외 상황이 적절히 처리되는가?",
    "보안: 입력 검증, 인젝션 등 보안 취약점은 없는가?",
    "빠진 부분: 엣지 케이스나 누락된 로직이 있는가?",
    "영향 범위: 이 변경이 다른 코드에 미치는 영향은?",
)

# Extension → additional check appended after base.
LANG_CHECKS = {
    ".js":  "비동기: async/await, Promise 처리가 올바른가?",
    ".ts":  "비동기: async/await, Promise 처리가 올바른가?",
    ".tsx": "비동기: async/await, Promise 처리가 올바른가?",
    ".jsx": "비동기: async/await, Promise 처리가 올바른가?",
    ".py":  "타입 힌트: 주요 함수에 타입 힌트가 있는가?",
    ".gd":  "시그널/노드: 시그널 연결과 노드 참조가 유효한가?",
    ".c":   "메모리: 할당/해제 균형이 맞는가?",
    ".cpp": "메모리: 할당/해제 균형이 맞는가?",
    ".h":   "메모리: 할당/해제 균형이 맞는가?",
    ".rs":  "소유권/수명: borrow checker 관련 이슈는 없는가?",
}


def get_review_context(tool_name: str, file_path: str, recent_changes: str = "") -> str:
    """Generate <post-tool-review> wrapped reminder message.

    Args:
        tool_name: 'Write' / 'Edit' / 'MultiEdit' / 'Bash' / etc.
        file_path: file under review (used for ext detection + display).
        recent_changes: optional pre-rendered string of recent change log lines.

    Returns:
        Formatted review prompt with checklist, change history, and quality guidance.
    """
    ext = os.path.splitext(file_path)[1].lower() if file_path else ""

    checks = list(BASE_CHECKS)
    if ext in LANG_CHECKS:
        checks.append(LANG_CHECKS[ext])
    if tool_name == "Write":
        checks.append("새 파일: 기존 코드와의 일관성을 확인했는가?")

    checklist = "\n".join(f"- {c}" for c in checks)

    parts = [
        "<post-tool-review>",
        f"[코드 리뷰 리마인더] ({os.path.basename(file_path)})",
        "",
        "체크리스트:",
        checklist,
    ]

    if recent_changes:
        parts.extend(["", "최근 수정 기록:", recent_changes])

    parts.extend([
        "",
        "품질 검사 지침:",
        "- 위 체크리스트에서 문제를 발견한 경우:",
        "  - 사소한 오류(1-2개): 즉시 수정하고 수정 내용을 알려주세요",
        "  - 심각하거나 다수의 오류: 문제 목록을 정리하고 전문적 리뷰를 추천하세요",
        "- 문제가 없으면 별도 언급 없이 계속 진행하세요",
        "</post-tool-review>",
    ])
    return "\n".join(parts)


def get_error_recovery_hint() -> str:
    """Static error-recovery hint string."""
    return (
        "<error-recovery>\n"
        "[에러 복구 가이드] 실패 원인을 파악하고 다른 접근법을 시도하세요. "
        "같은 명령어 재시도보다 대안을 찾는 것이 효과적입니다.\n"
        "</error-recovery>"
    )
