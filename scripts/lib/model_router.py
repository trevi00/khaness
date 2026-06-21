"""Complexity-based model tier router.

Classifies a prompt into haiku|sonnet|opus based on heuristic signals.
Pure function — no I/O, no state, deterministic. Caller opt-in.

## Integration pattern (recommended)

Concrete providers should NOT call this implicitly when `request.model == ""`,
because callers currently rely on each provider's `default_model` constant
(documented behavior). Instead, callers who want auto-routing pass the result
explicitly:

    from lib.model_router import classify_complexity, resolve_model_id
    tier = classify_complexity(prompt).tier
    model = resolve_model_id("anthropic", tier) or AnthropicProvider.default_model
    resp = anthropic.ask(AskRequest(prompt=prompt, model=model))

The `external_jury` panel and `harness-autopilot` orchestration are the
intended consumers; explicit call site keeps model selection auditable
(consensus debate logs the picked tier per juror) and avoids surprising
existing callers that depend on the per-provider default.

Extend by editing `_RULES`. Add new provider → new entry in DEFAULT_MODEL_IDS.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


Tier = Literal["haiku", "sonnet", "opus"]


@dataclass(frozen=True)
class Classification:
    tier: Tier
    score: int
    reasons: tuple[str, ...]


# Each rule: (regex, delta, reason). Positive delta escalates the tier.
_RULES: tuple[tuple[re.Pattern[str], int, str], ...] = (
    # Escalators
    (re.compile(r"\b(architecture|아키텍처|설계|refactor|리팩토링|재구성)\b", re.I),
     3, "design-class"),
    (re.compile(r"\b(security|보안|vulnerability|취약점|threat|위협)\b", re.I),
     3, "security-sensitive"),
    (re.compile(r"\b(debug|디버그|traceback|stacktrace|fix\s*bug|버그\s*수정)\b", re.I),
     2, "debug"),
    (re.compile(r"\b(implement|구현|create|작성|build|개발)\b", re.I),
     1, "implement"),
    # De-escalators
    (re.compile(r"\b(typo|rename|오타|이름\s*변경|list\s*files|show\s*me)\b", re.I),
     -2, "trivial"),
    (re.compile(r"^\s*(hi|hello|thanks|ok|yes|no|네|아니오)\s*[!?.]*\s*$", re.I),
     -5, "greeting"),
)

_OPUS_FLOOR: int = 4
_SONNET_FLOOR: int = 1


def classify_complexity(prompt: str) -> Classification:
    """Return (tier, score, reasons). Side-effect free."""
    if not prompt or not prompt.strip():
        return Classification(tier="haiku", score=-5, reasons=("empty",))

    score = 0
    reasons: list[str] = []

    for pattern, delta, reason in _RULES:
        if pattern.search(prompt):
            score += delta
            reasons.append(reason)

    length = len(prompt)
    if length > 2000:
        score += 2
        reasons.append(f"long-prompt-{length}")
    elif length > 500:
        score += 1
        reasons.append(f"medium-prompt-{length}")

    if score >= _OPUS_FLOOR:
        tier: Tier = "opus"
    elif score >= _SONNET_FLOOR:
        tier = "sonnet"
    else:
        tier = "haiku"

    return Classification(tier=tier, score=score, reasons=tuple(reasons))


# (provider, tier) -> concrete model id
DEFAULT_MODEL_IDS: dict[str, dict[Tier, str]] = {
    "anthropic": {
        "haiku":  "claude-haiku-4-5-20251001",
        "sonnet": "claude-sonnet-4-6",
        "opus":   "claude-opus-4-7",
    },
    "openai": {
        # Codex CLI accepts via `-c model="<id>"`. Empty → CLI's own default.
        "haiku":  "gpt-4o-mini",
        "sonnet": "gpt-5-codex",
        "opus":   "o3",
    },
    # Future: "google": {...}
}


def resolve_model_id(provider: str, tier: Tier) -> str | None:
    """Map (provider, tier) to a concrete model id, or None if unmapped.

    Worker-3 R2 MED (W23 fix): canonicalize provider via lib.providers alias
    map so JuryMember(provider="claude", model="auto") routes to anthropic
    tiers (previously: silent no-op because "claude" key was absent).
    """
    canonical = provider
    try:
        from .providers import _REGISTRY as _PROVIDER_REGISTRY
        canonical = _PROVIDER_REGISTRY.get(provider.lower(), provider)
    except Exception:
        pass
    return DEFAULT_MODEL_IDS.get(canonical, {}).get(tier)
