"""Stop-phrase / lazy-pattern detector for code review.

Extracted from `handlers/post_tool/reviewer.py` in W15 (fixplan-meta debate Gen4
follow-through). Pure data table + pure function — no I/O, no global state.
Originally merged from a standalone `stop-phrase-guard.py` hook; now lives in
lib so other handlers (e.g., a future PreToolUse code-quality gate) can reuse
the same patterns without duplicating the regex table.

Caller contract:
- `check_stop_phrases(tool_name, tool_input)` returns a list of finding strings.
- Empty list = no lazy patterns detected (or unsupported tool / file in suppress dir).
- Pattern-definition files (hook scripts containing `re.compile`) are skipped to
  avoid false positives — see HOOK_SCRIPT_DIRS suppression below.
"""
from __future__ import annotations

import re
from typing import Any


# Directories where hook/config scripts live (false-positive suppression).
# Any file under these dirs is assumed to contain pattern definitions.
HOOK_SCRIPT_DIRS: frozenset[str] = frozenset({".claude/scripts", ".claude\\scripts"})


CODE_LAZY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Incomplete work markers
    # Note: [2-9](?!\d) excludes multi-digit phases like "Phase 21" to avoid
    # false positives on markdown section headers (### Phase 21.)
    (
        re.compile(
            r"(?://|#|/\*)\s*TODO:?\s*(?:later|phase\s*[2-9](?!\d)|will be|implement later)",
            re.IGNORECASE,
        ),
        "미완성 TODO: 지금 구현하세요",
    ),
    (
        re.compile(
            r"(?://|#|/\*)\s*(?:Phase\s*[2-9](?!\d)|future work|known limitation|will be completed)",
            re.IGNORECASE,
        ),
        "작업 미루기 주석: 현재 범위에서 완료하세요",
    ),
    # Lazy fix indicators
    (
        re.compile(
            r"(?:simplest|simple|quick(?:est)?)\s+(?:fix|workaround|hack|solution|approach)",
            re.IGNORECASE,
        ),
        "근본 원인을 해결하세요",
    ),
    (
        re.compile(
            r"(?:temporary|temp)\s+(?:hack|workaround|fix|solution)",
            re.IGNORECASE,
        ),
        "임시 해결책: 영구적 수정을 구현하세요",
    ),
    # Blame-shifting in comments
    (
        re.compile(
            r"(?://|#|/\*)\s*(?:not (?:caused by|related to) (?:my|this) change|"
            r"existing (?:issue|bug|problem)|pre-existing|was already broken)",
            re.IGNORECASE,
        ),
        "책임 회피 주석: 원인을 조사하고 수정하세요",
    ),
    # Removed code markers
    (
        re.compile(
            r"(?://|#|/\*)\s*(?:removed|deleted|was here|old code)",
            re.IGNORECASE,
        ),
        "삭제 코드 주석: 불필요한 주석을 남기지 마세요",
    ),
)


_PATTERN_DEF_RE = re.compile(r"re\.compile\(|regex[=:]|pattern[=:]")


def check_stop_phrases(tool_name: str, tool_input: dict[str, Any]) -> list[str]:
    """Return list of finding messages for lazy-code patterns in Edit/Write content.

    Filters out false positives:
      - Tool not in {Edit, MultiEdit, Write} → []
      - File in HOOK_SCRIPT_DIRS (hook/script directories with pattern definitions) → []
      - Content shorter than 10 chars → []
      - Content that looks like a pattern/regex definition file → []
    """
    if tool_name not in {"Edit", "MultiEdit", "Write"}:
        return []

    file_path = (tool_input.get("file_path") or "").replace("\\", "/")
    if file_path:
        for hook_dir in HOOK_SCRIPT_DIRS:
            if hook_dir.replace("\\", "/") in file_path:
                return []

    if tool_name == "Write":
        content = tool_input.get("content", "") or ""
    else:
        content = tool_input.get("new_string", "") or ""

    if not content or len(content) < 10:
        return []

    if _PATTERN_DEF_RE.search(content):
        return []

    findings: list[str] = []
    for pattern, message in CODE_LAZY_PATTERNS:
        if pattern.search(content):
            findings.append(message)
    return findings
