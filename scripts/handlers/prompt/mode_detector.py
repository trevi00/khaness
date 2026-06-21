#!/usr/bin/env python3
"""UserPromptSubmit hook — mode trigger detection (OMC-style keywords).

Detects prefix/body keywords that map to our /harness-* slash commands,
logs every match to telemetry, and emits a soft suggestion to consider
the mapped command. Never forces; user can ignore.

Keywords recognized:
  autopilot: / autopilot <x>      -> /harness-autopilot
  ralph:     / don't stop until   -> /harness-ralph
  ultrawork: / ulw:               -> /harness-ultrawork
  ultrathink                      -> hint: Opus tier
  deepsearch                      -> hint: Explore agent (very thorough)
  deep interview / ouroboros      -> /harness-interview

Output:
  - telemetry/mode-triggers.jsonl (one record per match)
  - UserPromptSubmit additionalContext wrapped in <mode-trigger-suggestion>

Design: SENSOR only. Never invokes engines. Caller (main agent) decides
whether to follow the hint.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.io import additional_context, read_hook_input, write_hook_output
from lib.logging import log_telemetry
from lib.prompt_origin import is_system_reinvocation


# (regex, mode_name, suggested_command_or_None, message)
# Prefix keywords require explicit punctuation (`:` or `-`) to avoid false
# positives on natural-language mentions like "explain autopilot feature"
# or "ultrawork tomorrow".
_MODE_RULES: tuple[tuple[re.Pattern[str], str, str | None, str], ...] = (
    (
        re.compile(r"^\s*autopilot\s*[:\-]", re.I),
        "autopilot", "/harness-autopilot",
        "자율 실행 모드. Planner→Executor→Verifier 파이프라인 자동 실행.",
    ),
    (
        re.compile(r"^\s*ralph\s*[:\-]|don[’']t\s*stop\s*until", re.I),
        "ralph", "/harness-ralph",
        "지속성 루프. validators 전수 PASS 또는 hard_cap(iteration 10)까지 verify/fix 반복.",
    ),
    (
        re.compile(r"^\s*(?:ultrawork|ulw)\s*[:\-]", re.I),
        "ultrawork", "/harness-ultrawork",
        "최대 병렬. 독립 작업을 서브에이전트로 동시 스폰.",
    ),
    (
        re.compile(r"\bultrathink\b", re.I),
        "ultrathink", None,
        "깊은 추론 요청. Opus 티어 사용 검토 권장.",
    ),
    (
        re.compile(r"\bdeepsearch\b", re.I),
        "deepsearch", None,
        "코드베이스 심층 검색. Agent(Explore, thoroughness='very thorough') 권장.",
    ),
    (
        re.compile(r"\bdeep\s*interview\b|\bouroboros\b", re.I),
        "deep-interview", "/harness-interview",
        "소크라테스식 요구사항 명확화. 온톨로지 수렴까지 질문 반복.",
    ),
)


def detect_modes(prompt: str) -> list[tuple[str, str | None, str]]:
    """Return (mode_name, suggested_command, message) tuples for each hit."""
    if not prompt:
        return []
    hits: list[tuple[str, str | None, str]] = []
    for pattern, mode, cmd, msg in _MODE_RULES:
        if pattern.search(prompt):
            hits.append((mode, cmd, msg))
    return hits


def build_suggestion(hits: list[tuple[str, str | None, str]]) -> str:
    lines = ["<mode-trigger-suggestion>"]
    for mode, cmd, msg in hits:
        prefix = f"[{mode}]" if not cmd else f"[{mode} -> {cmd}]"
        lines.append(f"{prefix} {msg}")
    lines.append("")
    lines.append("위 모드는 힌트입니다. 사용자가 명시적으로 원하는 경우에만 해당 슬래시 커맨드로 진행하세요.")
    lines.append("</mode-trigger-suggestion>")
    return "\n".join(lines)


def main() -> None:
    payload = read_hook_input()
    prompt = payload.get("prompt", "")
    if not prompt:
        sys.exit(0)

    # System re-invocations (e.g. <task-notification>) are harness turns, not
    # user intent — never surface a mode suggestion for them. Shared gate
    # (lib.prompt_origin, STEP 3); telemetry still records the prompt with the
    # system_origin flag so the FP class stays auditable.
    system_origin = is_system_reinvocation(prompt)
    hits = [] if system_origin else detect_modes(prompt)
    log_telemetry("mode-triggers", {
        "prompt_preview": prompt[:200],
        "modes": [h[0] for h in hits],
        "system_origin": system_origin,
        "cwd": payload.get("cwd", ""),
    })

    if not hits:
        sys.exit(0)

    write_hook_output(additional_context(
        build_suggestion(hits),
        "UserPromptSubmit",
    ))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Advisory SENSOR hook MUST fail-OPEN (exit 0) on any error — a malformed
        # /hostile payload must never crash to exit 1 and surface as a hook failure
        # (deep-audit pass-2 rank 3, LIVE-confirmed on a non-string prompt).
        sys.exit(0)
