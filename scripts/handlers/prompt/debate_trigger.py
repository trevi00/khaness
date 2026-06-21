#!/usr/bin/env python3
"""UserPromptSubmit hook — debate trigger detection (ACTIVE-SUGGEST + skill graph, P5c).

Detects when a user prompt looks like a strict-design decision (the kind
that should go through harness-debate), logs it to telemetry, AND when
strict intent is matched emits a NON-BLOCKING suggestion to consider
`/harness-debate <주제>` enriched with:
  - Top 3 relevant skills (from state/skill-graph.json keyword overlap)
  - Count of recent debate sessions in the last 14 days

Never forces the engine — user can ignore.

Modes this file went through:
  - P5a (shadow-only):   log every prompt, emit no stdout.
  - P5b (active-suggest): log every prompt; emit hint when strict intent matches.
  - P5c (graph-enriched, current): hint includes top-N skills + recent debate count.

Why soft suggest (Critic C-1 mitigation):
  phase_detector.PHASE_SIGNALS includes "how"/"어떻게", which matches
  almost every developer question. is_strict_design_intent() gates on
  STRICT_DESIGN_KEYWORDS (architecture/설계/구조/리팩토링/refactor/재구성)
  so we only suggest the debate engine when the prompt genuinely looks
  architectural — never for casual how-to's.

Output files:
  - $CLAUDE_HOME/telemetry/debate-triggers.jsonl (one line per prompt, always)
  - stdout additionalContext JSON (only when strict-design intent matched)
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.io import read_hook_input
from lib.logging import log_telemetry
from lib.phase_detector import detect_phase, is_strict_design_intent

# System re-invocations (background task completions, etc.) arrive on the
# UserPromptSubmit channel but are NOT user design intent. A <task-notification>
# whose task summary happens to contain a design keyword (설계/구조/리팩토링)
# must not be counted as strict-design intent nor fire the debate advisory.
# Telemetry FP observed 2026-06-02 (trigger-summary surfaced a task-notification
# among the strict-design samples). The classifier now lives in lib.prompt_origin
# (single source of truth, shared with mode_detector + skill_match — STEP 3);
# re-exported here under the original private names so the call site below and
# the existing tests are unchanged. Caller-side guard ONLY: is_strict_design_intent
# itself stays untouched (the debate fast-path relies on it).
from lib.prompt_origin import (
    SYSTEM_REINVOCATION_PREFIXES as _SYSTEM_REINVOCATION_PREFIXES,  # noqa: F401
    is_system_reinvocation as _is_system_reinvocation,
)


# Skill graph + debate state cached per-process (cheap on the hook hot path)
_SKILL_GRAPH_CACHE: dict | None = None


def _load_skill_graph() -> dict | None:
    """Lazy-load state/skill-graph.json. Returns None if missing or malformed."""
    global _SKILL_GRAPH_CACHE
    if _SKILL_GRAPH_CACHE is not None:
        return _SKILL_GRAPH_CACHE if _SKILL_GRAPH_CACHE else None
    try:
        from lib.paths import STATE_DIR
        path = STATE_DIR / "skill-graph.json"
        if not path.is_file():
            _SKILL_GRAPH_CACHE = {}
            return None
        _SKILL_GRAPH_CACHE = json.loads(path.read_text(encoding="utf-8"))
        return _SKILL_GRAPH_CACHE
    except Exception:
        _SKILL_GRAPH_CACHE = {}
        return None


def _top_relevant_skills(prompt: str, n: int = 3) -> list[tuple[str, str]]:
    """Rank skills by keyword overlap with the prompt. Returns [(name, description), ...]."""
    graph = _load_skill_graph()
    if not graph or "nodes" not in graph:
        return []

    prompt_lower = prompt.lower()
    scored: list[tuple[int, str, str]] = []
    for node in graph.get("nodes", []):
        keywords = node.get("keywords") or []
        if not keywords:
            continue
        score = sum(1 for k in keywords if k.lower() in prompt_lower and len(k) > 1)
        if score > 0:
            scored.append((score, node.get("name", ""), node.get("description", "")))

    scored.sort(reverse=True)
    return [(name, desc) for _, name, desc in scored[:n]]


def _recent_debate_count(window_days: int = 14) -> int:
    """Count debate sessions modified within the rolling window."""
    try:
        from lib.paths import STATE_DIR
        debates = STATE_DIR / "debates"
        if not debates.is_dir():
            return 0
        cutoff = time.time() - (window_days * 86400)
        return sum(
            1 for d in debates.iterdir()
            if d.is_dir() and d.stat().st_mtime >= cutoff
        )
    except Exception:
        return 0


def _build_advisory(prompt: str) -> str:
    parts = [
        "<harness-debate-suggestion>",
        # The static rule (strict-design 키워드 목록 + 복잡하면 /harness-debate) is
        # already permanently loaded in CLAUDE.md 핵심3원칙 (L0). Collapse the
        # recitation to a one-line pointer (token-efficiency, wave effort-2);
        # keyword list still lives in STRICT_DESIGN_KEYWORDS + CLAUDE.md.
        "strict-design intent 감지 — 복잡한 설계 결정이면 `/harness-debate <주제>` 고려 "
        "(상세 기준: CLAUDE.md 핵심3원칙).",
    ]

    relevant = _top_relevant_skills(prompt, n=3)
    if relevant:
        parts.append("")
        parts.append("**관련 스킬 후보 (skill-graph 기반)**:")
        for name, desc in relevant:
            desc_one = (desc or "").split("\n")[0][:120]
            parts.append(f"- `{name}` — {desc_one}")

    recent = _recent_debate_count()
    if recent > 0:
        parts.append("")
        parts.append(f"_최근 14일 내 debate 세션: **{recent}회**_ "
                     "(`state/debates/` 참조)")

    parts.append("</harness-debate-suggestion>")
    return "\n".join(parts)


# ---- Round-robin advisory channel (debate-1778230575-aebdd3 D3) ----
# Two FIFO slots: 'debate' (strict-design suggestion) and 'writeback'
# (observe-only writeback proposals). Alternates each turn; ack token
# suppresses a slot for 3 turns. State persists in
# state/writeback/advisory_state.json for cross-turn continuity.

_ADVISORY_ACK_TTL_TURNS: int = 3
_ACK_TOKEN_DEBATE_RE = "/ack-debate"
_ACK_TOKEN_WRITEBACK_RE = "/ack-writeback"


def _advisory_state_path():
    from lib.paths import STATE_DIR
    d = STATE_DIR / "writeback"
    d.mkdir(parents=True, exist_ok=True)
    return d / "advisory_state.json"


def _load_advisory_state() -> dict:
    """Load persisted advisory state. Returns defaults on missing/corrupt."""
    try:
        from lib.atomic_json import read_json
        data = read_json(_advisory_state_path(), default={})
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    return {
        "turn_ordinal": int(data.get("turn_ordinal", 0)),
        "last_emitted_slot": str(data.get("last_emitted_slot", "")),
        "ack_remaining_debate": int(data.get("ack_remaining_debate", 0)),
        "ack_remaining_writeback": int(data.get("ack_remaining_writeback", 0)),
    }


def _save_advisory_state(state: dict) -> None:
    """Atomic write per debate D2 store contract semantics."""
    try:
        from lib.atomic_json import write_json_atomic
        write_json_atomic(str(_advisory_state_path()), state)
    except Exception:
        pass  # fail-open: hook discipline never crashes on state write


def _detect_ack_tokens(prompt: str) -> tuple[bool, bool]:
    """Return (ack_debate_seen, ack_writeback_seen). Tokens may appear anywhere."""
    return (
        _ACK_TOKEN_DEBATE_RE in prompt,
        _ACK_TOKEN_WRITEBACK_RE in prompt,
    )


def _list_pending_writeback() -> list[dict]:
    """Read pending writeback proposals from store. Returns [] on any error."""
    try:
        from lib.writeback_store import list_pending
        return list_pending()
    except Exception:
        return []


def _build_writeback_advisory(pending: list[dict]) -> str:
    """Render <harness-writeback-advisory> block listing up to 2 pending proposals."""
    shown = pending[:2]
    parts = [
        "<harness-writeback-advisory>",
        "harness-researcher가 영구 코드화 제안한 변경사항 (observe-only, "
        "사용자 ack 전 자동 적용 안 함):",
    ]
    for entry in shown:
        target = entry.get("target_skill_path", "?")
        fp = entry.get("fingerprint", "?")[:8]
        pid = entry.get("id", "?")
        parts.append(f"- `{target}` (fp {fp}, id {pid})")
    parts.append(
        f"검토 후 ack: prompt에 `/ack-writeback` 포함 시 다음 "
        f"{_ADVISORY_ACK_TTL_TURNS} turn 동안 advisory 억제."
    )
    parts.append(
        "전체 검토: `python -m cli.writeback_inspect` "
        "(--show <id> / --dismiss <id>)"
    )
    parts.append("</harness-writeback-advisory>")
    return "\n".join(parts)


def _select_advisory_slot(
    *,
    want_debate: bool,
    want_writeback: bool,
    last_slot: str,
) -> str:
    """Round-robin slot selection. Returns 'debate', 'writeback', or '' (none)."""
    if want_debate and want_writeback:
        # Alternate: if last was debate, this turn writeback; vice versa.
        return "writeback" if last_slot == "debate" else "debate"
    if want_debate:
        return "debate"
    if want_writeback:
        return "writeback"
    return ""


def main() -> None:
    payload = read_hook_input()
    prompt = payload.get("prompt", "")
    if not prompt:
        sys.exit(0)

    # ---- D3 ordinal-1 ack gate: read state, decrement TTLs, detect ack tokens ----
    state = _load_advisory_state()
    state["turn_ordinal"] = state["turn_ordinal"] + 1
    if state["ack_remaining_debate"] > 0:
        state["ack_remaining_debate"] -= 1
    if state["ack_remaining_writeback"] > 0:
        state["ack_remaining_writeback"] -= 1

    ack_debate_seen, ack_writeback_seen = _detect_ack_tokens(prompt)
    if ack_debate_seen:
        state["ack_remaining_debate"] = _ADVISORY_ACK_TTL_TURNS
    if ack_writeback_seen:
        state["ack_remaining_writeback"] = _ADVISORY_ACK_TTL_TURNS

    # ---- Phase + strict-design detection (existing) ----
    phases = detect_phase(prompt)
    system_origin = _is_system_reinvocation(prompt)
    # Gate strict-design on user-origin: a system re-invocation never counts
    # (prevents <task-notification> design-keyword FP from polluting telemetry
    # or firing a spurious debate advisory).
    strict = is_strict_design_intent(prompt) and not system_origin

    log_telemetry(
        "debate-triggers",
        {
            "prompt_preview": prompt[:200],
            "prompt_len": len(prompt),
            "phases": sorted(phases),
            "strict_design": strict,
            "system_origin": system_origin,
            "cwd": payload.get("cwd", ""),
            "mode": "active-suggest-graph-rr",
            "turn_ordinal": state["turn_ordinal"],
        },
    )

    # ---- Round-robin slot selection ----
    pending = _list_pending_writeback()
    want_debate = strict and state["ack_remaining_debate"] == 0
    want_writeback = bool(pending) and state["ack_remaining_writeback"] == 0
    selected = _select_advisory_slot(
        want_debate=want_debate,
        want_writeback=want_writeback,
        last_slot=state.get("last_emitted_slot", ""),
    )

    # ---- Emit at most ONE advisory block per turn ----
    if selected == "debate":
        from lib.io import additional_context, write_hook_output
        write_hook_output(additional_context(_build_advisory(prompt), "UserPromptSubmit"))
        state["last_emitted_slot"] = "debate"
    elif selected == "writeback":
        from lib.io import additional_context, write_hook_output
        write_hook_output(additional_context(_build_writeback_advisory(pending), "UserPromptSubmit"))
        state["last_emitted_slot"] = "writeback"
    # else: no slot wants emission this turn

    # ---- Persist state for next turn ----
    _save_advisory_state(state)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Advisory hook MUST fail-OPEN (exit 0) on any error — never crash to
        # exit 1 on a malformed/hostile prompt (deep-audit pass-2 rank 3).
        sys.exit(0)
