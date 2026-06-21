#!/usr/bin/env python3
"""
Critic Rationalization Detection Hook (PostToolUse)

DGE(Designer-Generator-Evaluator) 원칙에서 Designer의 Critic 단계를
"개발 편의", "우선 동작만" 등 합리화 문구로 우회하는 패턴을 감지.

감지 시 additionalContext로 경고 주입 (blocking 아님 — 의도적일 수 있음).

Hook event: PostToolUse
Target tools: Edit, MultiEdit, Write
Input: stdin JSON (Claude Code hook protocol)
Output: stdout JSON {additionalContext: ...} or empty (조용히 종료)
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

# Worker-2 H3 (fixplan-meta debate Gen4): use lib.io for PostToolUse contract
# (hookSpecificOutput wrapper) and stdin/stdout/stderr UTF-8 reconfigure.
from lib.io import additional_context, read_hook_input, write_hook_output  # noqa: E402

# 감지 대상 합리화 문구 (한국어)
# 근거: feedback_harness_compliance.md — Critic 단계 우회 재발 방지
RATIONALIZATION_PATTERNS = [
    "개발 편의",
    "우선 동작만",
    "나중에 개선",
    "범위 밖",
    "편의 우선",
    "임시로",
    "일단 돌아가게",
]

# 같은 파일 내 TODO 개수 임계값 (이 값 이상이면 경고)
TODO_THRESHOLD = 3

# 파일 크기 제한: 10 MB 초과 시 TODO 카운트 생략 (성능 보호)
MAX_FILE_SIZE = 10 * 1024 * 1024

# 최대 보고 findings 개수 (컨텍스트 폭증 방지)
MAX_FINDINGS_REPORT = 10


def extract_new_content(tool_input: dict, tool_name: str) -> str:
    """tool_input에서 새로 작성된 내용 추출.

    Write        → content
    Edit         → new_string
    MultiEdit    → edits[].new_string 합산
    """
    if tool_name == "Write":
        return str(tool_input.get("content", "") or "")
    if tool_name == "Edit":
        return str(tool_input.get("new_string", "") or "")
    if tool_name == "MultiEdit":
        edits = tool_input.get("edits", []) or []
        parts = []
        for e in edits:
            if isinstance(e, dict):
                parts.append(str(e.get("new_string", "") or ""))
        return "\n".join(parts)
    return ""


def read_file_safely(file_path: str) -> str | None:
    """파일 전체 읽기 (실패하면 None)."""
    if not file_path:
        return None
    try:
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            return None
        if path.stat().st_size > MAX_FILE_SIZE:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def scan_rationalization(new_content: str) -> list[tuple[int, str, str]]:
    """new_content 라인별로 합리화 패턴 탐색.

    반환: [(line_number, matched_pattern, line_text), ...]
    한 라인에 여러 패턴이 있어도 한 번만 보고 (첫 매치 기준).
    """
    findings: list[tuple[int, str, str]] = []
    for i, line in enumerate(new_content.splitlines(), 1):
        for pattern in RATIONALIZATION_PATTERNS:
            if pattern in line:
                findings.append((i, pattern, line.strip()))
                break
    return findings


def count_todos(file_content: str) -> int:
    """파일 전체에서 TODO 포함 라인 개수 카운트."""
    return sum(1 for line in file_content.splitlines() if "TODO" in line)


def build_warning(file_path: str, findings: list[tuple[int, str, str]], todo_count: int) -> str:
    """additionalContext에 주입할 경고 메시지 작성."""
    lines: list[str] = [
        "[DGE Critic 합리화 패턴 감지]",
        f"파일: {file_path}",
        "",
    ]

    if findings:
        lines.append(f"발견된 합리화 문구 ({len(findings)}건):")
        shown = findings[:MAX_FINDINGS_REPORT]
        for ln, pat, text in shown:
            snippet = text if len(text) <= 80 else text[:77] + "..."
            lines.append(f"  - L{ln}: \"{pat}\" → {snippet}")
        if len(findings) > MAX_FINDINGS_REPORT:
            lines.append(f"  ... (외 {len(findings) - MAX_FINDINGS_REPORT}건 생략)")
        lines.append("")

    if todo_count >= TODO_THRESHOLD:
        lines.append(f"TODO 개수: {todo_count}개 (임계값 {TODO_THRESHOLD}개 이상)")
        lines.append("")

    lines.append(
        "⚠️ Critic 지적을 '개발 편의' 등 합리화로 우회하고 있을 가능성이 있습니다.\n"
        "이 선택이 정당한 의도적 결정인지 근거를 명시하거나,\n"
        "실제로 개선이 필요한 것은 아닌지 재검토하세요.\n"
        "참고: feedback_harness_compliance.md, feedback_avoid_mock.md"
    )
    return "\n".join(lines)


def main() -> int:
    payload = read_hook_input()
    if not payload:
        return 0

    tool_name = payload.get("tool_name", "")
    if tool_name not in ("Edit", "MultiEdit", "Write"):
        return 0

    tool_input = payload.get("tool_input", {}) or {}
    if not isinstance(tool_input, dict):
        return 0

    file_path = str(tool_input.get("file_path", "") or "")
    if not file_path:
        return 0

    new_content = extract_new_content(tool_input, tool_name)
    if not new_content.strip():
        return 0

    findings = scan_rationalization(new_content)
    file_content = read_file_safely(file_path)
    todo_count = count_todos(file_content) if file_content else 0

    if not findings and todo_count < TODO_THRESHOLD:
        return 0

    warning = build_warning(file_path, findings, todo_count)
    write_hook_output(additional_context(warning, "PostToolUse"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
