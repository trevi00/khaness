"""Phase detection — classify a user prompt into plan/implement/review/deploy/debug.

Ported from scripts/skill-matcher.py. Used by UserPromptSubmit hook to
activate relevant skills and (future) trigger the debate engine.
"""
from __future__ import annotations

import re


PHASE_SIGNALS: dict[str, tuple[str, ...]] = {
    "plan": (
        "설계", "계획", "구조", "아키텍처", "어떻게", "방법", "전략", "구상", "분석",
        "plan", "design", "architecture", "strategy", "approach", "how",
    ),
    "implement": (
        "만들", "구현", "추가", "생성", "코딩", "작성", "개발",
        "implement", "create", "add", "build", "develop", "write", "code",
    ),
    "review": (
        "검토", "리뷰", "확인", "체크", "점검",
        "review", "check", "inspect", "audit",
    ),
    "deploy": (
        "배포", "릴리즈", "출시", "운영",
        "deploy", "release", "ship", "launch", "production",
    ),
    "debug": (
        "디버그", "에러", "버그", "오류", "안돼", "안됨", "실패", "고쳐",
        "debug", "error", "bug", "fix", "broken", "fail", "issue",
    ),
}

# Strict design signals — subset used by the debate-engine trigger.
# Rationale: "how"/"어떻게" alone matches every casual question and would
# fire the Planner-Critic-Architect loop unnecessarily (Critic C-1).
# These keywords reliably indicate a real architectural decision.
STRICT_DESIGN_KEYWORDS: frozenset[str] = frozenset({
    "architecture", "아키텍처", "설계", "구조",
    "refactor", "리팩토링", "재구성",
})


def _is_ascii(text: str) -> bool:
    return all(ord(c) < 128 for c in text)


def _signal_matches(signal: str, prompt_lower: str) -> bool:
    """Match a signal against a lowercased prompt.

    ASCII signals use word boundaries; Korean falls back to substring match.
    """
    sig = signal.lower()
    if _is_ascii(sig):
        return bool(re.search(
            r"(?<![a-zA-Z0-9])" + re.escape(sig) + r"(?![a-zA-Z0-9])",
            prompt_lower,
        ))
    return sig in prompt_lower


def detect_phase(prompt: str) -> set[str]:
    """Return the set of matched phase names from PHASE_SIGNALS."""
    if not prompt:
        return set()
    prompt_lower = prompt.lower()
    phases: set[str] = set()
    for phase, signals in PHASE_SIGNALS.items():
        for signal in signals:
            if _signal_matches(signal, prompt_lower):
                phases.add(phase)
                break
    return phases


def is_strict_design_intent(prompt: str) -> bool:
    """Return True only when the prompt contains a strict-design keyword.

    Used by the debate-engine trigger to avoid 'how do I rename X' firing
    the suggestion. Gate is the keyword set alone — NOT phase=plan — because
    STRICT_DESIGN_KEYWORDS such as 'refactor'/'리팩토링'/'재구성' are not
    in PHASE_SIGNALS['plan'], yet genuinely indicate architectural intent.
    Phase detection and strict-design detection are independent axes.
    """
    if not prompt:
        return False
    prompt_lower = prompt.lower()
    return any(_signal_matches(kw, prompt_lower) for kw in STRICT_DESIGN_KEYWORDS)
