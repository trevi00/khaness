"""response_guard_core.py — pure analysis functions extracted from response_guard.py.

Per debate-1778224899-c24de4 D3'' (single-hook merge): the analyzer is
extracted into this module so handlers/stop/autopilot_continue.py can
import it without triggering the CLI's module-level side effects
(`sys.stdin/stdout.reconfigure` at response_guard.py:36-37, COOLDOWN_FILE
env-read at response_guard.py:39-42).

This module is import-safe:
  - NO `sys.stdin/stdout.reconfigure` at module level
  - NO `os.environ.get` at module level (no env-coupled constants)
  - NO file I/O at module level
  - RESPONSE_PATTERNS regex compilation IS at module level (acceptable —
    Python regex cache is shared, fresh-process Stop hook re-pays cost
    once regardless of structure)

Public API:
  - RESPONSE_PATTERNS: list[dict] — quality-pattern rules
  - MIN_MESSAGE_LENGTH: int = 30
  - strip_quoted_content(message: str) -> str
  - analyze_response(message: str) -> tuple[list[tuple[str, str, str]], bool]
"""
from __future__ import annotations

import re


# Minimum message length to bother checking (very short = likely not a real response)
MIN_MESSAGE_LENGTH: int = 30


# Conversational lazy patterns — detect laziness in RESPONSE TEXT, not in code
RESPONSE_PATTERNS: list[dict] = [
    # Premature stop / seeking permission to stop
    {
        "patterns": [
            re.compile(
                r"(?:good|natural|logical)\s+(?:stopping|breaking|pausing)\s+point",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?:should|shall|want me to)\s+(?:I\s+)?(?:continue|keep going|proceed)",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?:이쯤|여기서|이 정도)\s*(?:에서|면)?\s*(?:멈추|중단|그만|마무리)",
            ),
            re.compile(
                r"계속\s*(?:할까요|진행할까요|해도 될까요)",
            ),
        ],
        "category": "조기 중단",
        "message": "작업을 자의적으로 중단하지 마세요. 지시받은 범위를 완료하세요.",
        "severity": "block",
    },
    # Blame-shifting / deflecting responsibility
    {
        "patterns": [
            re.compile(
                r"(?:not\s+(?:caused|related)\s+(?:by|to)\s+(?:my|this|these)\s+change|"
                r"existing\s+(?:issue|bug|problem)|pre-existing|was\s+already\s+broken)",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?:기존|이전|원래)\s*(?:부터|의)?\s*(?:문제|버그|이슈|결함)",
            ),
        ],
        "category": "책임 회피",
        "message": "원인을 조사하고 수정하세요. 기존 문제라 해도 범위 내라면 해결해야 합니다.",
        "severity": "warn",
    },
    # Deferring work / future promises
    {
        "patterns": [
            re.compile(
                r"(?:in\s+(?:a\s+)?future|Phase\s*[2-9]|later\s+(?:we|you|I)\s+(?:can|could|should|will)|"
                r"out\s+of\s+scope\s+(?:for\s+)?(?:now|this|today)|"
                r"beyond\s+(?:the\s+)?(?:scope|current))",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?:나중에|향후|추후|다음에)\s*(?:구현|처리|해결|추가|작업)",
            ),
            re.compile(
                r"(?:범위\s*밖|스코프\s*밖|현재\s*범위\s*외)",
            ),
        ],
        "category": "작업 지연",
        "message": "현재 범위에서 완료하세요. 작업을 미루지 마세요.",
        "severity": "warn",
    },
    # Unsupported claims without verification
    {
        "patterns": [
            re.compile(
                r"(?:I\s+(?:think|believe|assume)\s+(?:this|that|it)\s+(?:should|would|might)\s+(?:work|be\s+fine|be\s+ok)|"
                r"this\s+should\s+(?:work|be\s+enough|suffice)\s+(?:for\s+now|as\s+is))",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?:아마|대충|대략|일단)\s*(?:될\s*(?:거|것)|괜찮|충분)",
            ),
        ],
        "category": "미검증 추측",
        "message": "추측하지 말고 실제로 테스트/확인하세요.",
        "severity": "warn",
    },
    # Simplest fix / minimal effort
    {
        "patterns": [
            re.compile(
                r"(?:simplest|quickest|easiest|minimal)\s+(?:fix|solution|approach|workaround|way)",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?:간단하게|최소한으로|일단|대충)\s*(?:처리|수정|해결|고쳤|했)",
            ),
        ],
        "category": "최소 노력",
        "message": "'simplest fix' 대신 근본 원인을 해결하세요.",
        "severity": "warn",
    },
]


def strip_quoted_content(message: str) -> str:
    """Remove content inside quotes, code blocks, and markdown tables
    to prevent false positives when the assistant discusses patterns.

    Strips:
    - Fenced code blocks (```...```)
    - Inline code (`...`)
    - Double-quoted strings ("...")
    - Markdown table cells (|...|)
    """
    result = re.sub(r"```[\s\S]*?```", "", message)
    result = re.sub(r"`[^`]+`", "", result)
    result = re.sub(r'"[^"\n]{3,}"', "", result)
    result = re.sub(r"^\|.*\|$", "", result, flags=re.MULTILINE)
    return result


def analyze_response(message: str) -> tuple[list[tuple[str, str, str]], bool]:
    """Analyze assistant response for quality issues.

    Returns (findings, has_blocking) where findings is a list of
    (category, message, severity) tuples.
    """
    if not message or len(message) < MIN_MESSAGE_LENGTH:
        return [], False

    cleaned = strip_quoted_content(message)
    if len(cleaned.strip()) < MIN_MESSAGE_LENGTH:
        return [], False

    findings: list[tuple[str, str, str]] = []
    has_blocking = False

    for rule in RESPONSE_PATTERNS:
        for pattern in rule["patterns"]:
            if pattern.search(cleaned):
                findings.append((
                    rule["category"],
                    rule["message"],
                    rule["severity"],
                ))
                if rule["severity"] == "block":
                    has_blocking = True
                break  # One match per rule is enough

    return findings, has_blocking


def format_finding_lines(findings: list[tuple[str, str, str]], max_count: int = 5) -> str:
    """Render findings as bullet lines with severity icons.

    Extracted so callers (response_guard CLI + autopilot_continue merger) share
    the exact same finding presentation contract.
    """
    lines: list[str] = []
    for category, msg, severity in findings[:max_count]:
        icon = "🚫" if severity == "block" else "⚠️"
        lines.append(f"  {icon} [{category}] {msg}")
    return "\n".join(lines)
