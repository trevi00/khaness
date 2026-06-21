"""External jury — cross-vendor Architect option for harness-debate.

Critic C-2 mitigation: the original debate engine runs Planner/Critic/Architect
all on the same Claude model, so their reasoning biases correlate. This
module replaces (SINGLE) or augments (PANEL) the Architect with jurors from
multiple vendors, eliminating single-vendor bias.

Modes:
  SINGLE — the first available non-Claude vendor acts as Architect.
  PANEL  — N vendors produce independent verdicts; majority rule; tie-break
           order "rejected > conditional > approved" (conservative).

Design (DIP):
  Depends only on lib.providers. The architect prompt is built by the
  caller (typically engine.prompts.architect_prompt). This module asks,
  parses, and tallies — it never fabricates verdict content.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Literal

from lib.providers import AskRequest, ProviderUnavailableError, get_provider
from lib.providers.base import AskResponse
from lib.breakers.composite import CompositeBreaker, _noop_emit  # M15
from lib.breakers.config import BreakerThresholds  # M15
from .dispatch_retry import call_with_retry  # M15


Mode = Literal["single", "panel"]

# M15 (debate-1781607404-695af5): retry + circuit-breaker for jury dispatch.
# Global sentinel project_id — a vendor outage is not project-scoped, so all debates
# share one breaker state file per provider under state/breakers/_external_jury/.
EXT_JURY_PROJECT_ID = "_external_jury"
# Jury breaker uses a SHORT cap (300s) instead of the 3600s global hook default, so a
# flaky juror recovers in minutes and cross-vendor diversity is restored (D2, gen-1 B2).
JURY_THRESHOLDS = BreakerThresholds(backoff_cap_sec=300)

# Permanent (non-retryable, breaker-exempt) exceptions: code/config bugs where retry is
# futile and a trip would be wrong. EVERYTHING ELSE (incl. ProviderUnavailableError,
# timeouts, and UNKNOWN exception types) is transient — fail-TOWARD the breaker (D3,
# Architect self-doubt: an unclassified novel error must not be silently treated as a
# bug that masks a real availability problem).
_PERMANENT_EXC: tuple[type[BaseException], ...] = (
    TypeError, KeyError, ValueError, AttributeError, NameError, ImportError, IndexError,
)


def _classify_jury(exc: BaseException) -> Literal["transient", "permanent"]:
    return "permanent" if isinstance(exc, _PERMANENT_EXC) else "transient"


@dataclass(frozen=True)
class JuryMember:
    provider: str                       # canonical name or alias (e.g. 'claude', 'codex')
    model: str | None = None            # None → provider default


@dataclass(frozen=True)
class JuryVerdict:
    mode: Mode
    members: tuple[str, ...]            # "provider/model" per successful member
    responses: tuple[AskResponse, ...]
    parsed: tuple[dict | None, ...]     # parsed Architect JSON per member
    consensus_verdict: str | None       # approved | rejected | conditional | None
    votes: dict[str, int]
    agreement: float                    # fraction agreeing with consensus, 0.0~1.0
    raw_text_per_member: tuple[str, ...]
    failures: tuple[str, ...]           # providers skipped + reason


# Conservative tie-break: reject > conditional > approve
_TIEBREAK: tuple[str, ...] = ("rejected", "conditional", "approved")


def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.splitlines()
    if len(lines) >= 3 and lines[-1].strip().startswith("```"):
        return "\n".join(lines[1:-1])
    return t


def _try_parse_json(text: str) -> dict | None:
    stripped = _strip_code_fence(text)
    try:
        obj = json.loads(stripped)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _tally(parsed: list[dict | None]) -> tuple[str | None, dict[str, int]]:
    votes = {"approved": 0, "rejected": 0, "conditional": 0}
    for p in parsed:
        if not p:
            continue
        v = p.get("verdict")
        if v in votes:
            votes[v] += 1
    if all(c == 0 for c in votes.values()):
        return None, votes
    max_count = max(votes.values())
    winners = [v for v in _TIEBREAK if votes[v] == max_count]
    return winners[0], votes


def _resolve_model(m: JuryMember, architect_prompt: str, failures: list[str]) -> str | None:
    """Resolve the model id for member `m` (opt-in 'auto' routing). Behavior-identical to
    the inline block the legacy path used — extracted so both dispatch paths share it
    verbatim (D4 behavior-preservation). Routing exceptions degrade to provider default."""
    resolved_model = m.model
    if m.model == "auto":
        try:
            from lib.model_router import classify_complexity, resolve_model_id
            tier = classify_complexity(architect_prompt).tier
            resolved_model = resolve_model_id(m.provider, tier) or ""
        except Exception as e:  # noqa: BLE001 — routing must not kill panel
            failures.append(
                f"{m.provider}: model_router routing failed ({type(e).__name__}: {e}); "
                f"falling back to provider default"
            )
            resolved_model = ""
    return resolved_model


def _dispatch_legacy(m, provider, architect_prompt, system, failures) -> AskResponse | None:
    """Legacy (retry_breaker=False) per-member dispatch — preserves the original 3-arm
    is_available + ask cascade byte-for-behavior."""
    if not provider.is_available():
        failures.append(f"{m.provider}: unavailable")
        return None
    resolved_model = _resolve_model(m, architect_prompt, failures)
    try:
        return provider.ask(AskRequest(prompt=architect_prompt, model=resolved_model, system=system))
    except ProviderUnavailableError as e:
        failures.append(f"{m.provider}: ask failed ({e})")
        return None
    except Exception as e:  # noqa: BLE001 — panel resilience (worker-3 H7)
        failures.append(f"{m.provider}: ask raised {type(e).__name__}({e})")
        return None


def _dispatch_with_breaker(
    m, provider, architect_prompt, system, failures, *, emit_fn, sleep_fn, max_attempts, base_dir,
) -> AskResponse | None:
    """retry_breaker path (M15 D3): try_acquire gate → call_with_retry probe → exactly one
    record_success/record_failure (finally-safe, no half-open probe leak). NO pre-is_available
    gate (an unavailable provider's ask raises ProviderUnavailableError = transient, handled
    here). A PERMANENT fault after acquire → record_success (the provider was REACHED, so it is
    available; the fault is a code bug, not unavailability — gen-1 B1)."""
    breaker = CompositeBreaker(
        agent_type=m.provider, failure_mode="jury_dispatch", project_id=EXT_JURY_PROJECT_ID,
        base_dir=base_dir, emit_fn=emit_fn, thresholds=JURY_THRESHOLDS,
        # any_mode_keys=None: secondary cross-mode trip intentionally dormant (single mode).
    )
    if not breaker.try_acquire():
        failures.append(f"{m.provider}: circuit_open (backing off)")
        return None
    resolved_model = _resolve_model(m, architect_prompt, failures)
    resp: AskResponse | None = None
    outcome = "failure"  # one of: success | reached(permanent, available) | failure(transient)
    try:
        resp = call_with_retry(
            lambda: provider.ask(AskRequest(prompt=architect_prompt, model=resolved_model, system=system)),
            classify=_classify_jury, max_attempts=max_attempts, sleep_fn=sleep_fn,
        )
        outcome = "success"
    except Exception as e:  # noqa: BLE001
        if _classify_jury(e) == "permanent":
            outcome = "reached"  # provider reached → available; do not trip the breaker
            failures.append(f"{m.provider}: ask raised {type(e).__name__}({e})")
        else:
            failures.append(f"{m.provider}: retry_exhausted ({type(e).__name__}: {e})")
    finally:
        # Exactly ONE record per acquired dispatch — releases the half-open probe.
        if outcome in ("success", "reached"):
            breaker.record_success()
        else:
            breaker.record_failure()
    return resp


def ask_jury(
    architect_prompt: str,
    members: list[JuryMember],
    *,
    mode: Mode = "panel",
    system: str | None = None,
    retry_breaker: bool = False,
    emit_fn=_noop_emit,
    sleep_fn=time.sleep,
    max_attempts: int = 3,
    call_budget_sec: float = 20.0,
    breaker_base_dir=None,
) -> JuryVerdict:
    """Send `architect_prompt` to each jury member and tally verdicts.

    Rules (unchanged contract):
      - Unknown providers and unavailable backends are SKIPPED (recorded in `failures`).
      - Non-JSON responses are kept in raw_text, but their parsed slot = None.
      - Raises ProviderUnavailableError only if ZERO members respond.
      - 'single' mode: keeps the FIRST successful member and skips the rest.

    M15: `retry_breaker=True` adds bounded full-jitter retry (transient failures) + a
    per-provider circuit breaker (skip-fast on persistent failure, short-cap backoff). New
    `failures` strings 'circuit_open (backing off)' / 'retry_exhausted (<Exc>)' distinguish a
    tripped breaker from a genuinely failing provider. `retry_breaker=False` (default) is the
    BEHAVIOR-PRESERVING legacy path. `sleep_fn`/`emit_fn`/`breaker_base_dir` are injected for
    determinism + observability. `call_budget_sec` is reserved (D1 dropped the explicit
    deadline; max_attempts bounds wall-time to seconds, so the budget never binds at defaults).
    """
    if not members:
        raise ValueError("empty jury")

    responses: list[AskResponse] = []
    parsed: list[dict | None] = []
    raw_texts: list[str] = []
    member_names: list[str] = []
    failures: list[str] = []

    for m in members:
        try:
            provider = get_provider(m.provider)
        except KeyError as e:
            failures.append(f"{m.provider}: unknown ({e})")
            continue

        if retry_breaker:
            resp = _dispatch_with_breaker(
                m, provider, architect_prompt, system, failures,
                emit_fn=emit_fn, sleep_fn=sleep_fn, max_attempts=max_attempts,
                base_dir=breaker_base_dir,
            )
        else:
            resp = _dispatch_legacy(m, provider, architect_prompt, system, failures)
        if resp is None:
            continue

        responses.append(resp)
        raw_texts.append(resp.text)
        member_names.append(f"{resp.provider}/{resp.model}")
        parsed.append(_try_parse_json(resp.text))

        if mode == "single":
            break

    if not responses:
        raise ProviderUnavailableError(
            f"all jury members failed: {'; '.join(failures) or '(none registered)'}"
        )

    consensus, votes = _tally(parsed)
    total = sum(votes.values())
    agreement = (votes[consensus] / total) if consensus and total else 0.0

    return JuryVerdict(
        mode=mode,
        members=tuple(member_names),
        responses=tuple(responses),
        parsed=tuple(parsed),
        consensus_verdict=consensus,
        votes=votes,
        agreement=agreement,
        raw_text_per_member=tuple(raw_texts),
        failures=tuple(failures),
    )


__all__ = [
    "JuryMember",
    "JuryVerdict",
    "Mode",
    "ask_jury",
]
