"""jury_advisory — OPTIONAL cross-vendor jury second-opinion for harness-debate.

ADVISORY ONLY (operator decision 2026-06-18). This seam runs
``engine.external_jury.ask_jury`` as a read-only second opinion AFTER the
harness-architect verdict is appended, and returns a payload the orchestrator
appends as a ``jury_advisory`` event. It NEVER feeds the convergence check —
the deterministic single-architect SHA-LOCK (M24, ``cli.debate_converge_check``)
is untouched. This closes the built-but-unwired ``external_jury`` capability
(0 live callers per M15:122) as an opt-in *augment*, not an Architect
replacement.

Why advisory-only: convergence requires the Architect to reproduce
``ontology_snapshot.fields`` BYTE-IDENTICAL across generations; a non-Claude
panel phrases fields differently, so letting a jury REPLACE the Architect would
break deterministic convergence. Keeping the jury advisory preserves the
load-bearing SHA-LOCK while still surfacing cross-vendor disagreement (the C-2
single-vendor-bias check — e.g. this session a codex evaluator flagged an
``extensibility`` weakness Claude did not).

Opt-in: env ``DEBATE_EXT_JURY=1`` (default off → NO jury call, behavior-
preserving). Fail-soft: disabled / no available non-Claude member / ``ask_jury``
raises → returns a ``skipped`` payload with ``skipped_reason``; this function
NEVER raises into the debate loop.

Public surface:
  - ADVISORY_ONLY (True — a guard constant; the payload carries no
    convergence-affecting keys such as ``ontology_snapshot``)
  - is_enabled(env=None) -> bool
  - default_members() -> list[JuryMember]   (available non-Claude vendors)
  - jury_advisory(architect_prompt, *, architect_verdict=None, ...) -> dict
"""
from __future__ import annotations

import os
import time
from typing import Any, Callable

# A guard constant + contract marker: this module produces ADVISORY payloads only.
# The orchestrator appends the returned dict as a `jury_advisory` event and MUST
# NOT feed it into cli.debate_converge_check. The payload intentionally carries no
# `ontology_snapshot` / `sha` / `converged` keys (asserted by the test suite).
ADVISORY_ONLY: bool = True

# Non-Claude vendors only — Claude/anthropic is the SAME vendor as the generator,
# so it adds no cross-vendor diversity. Registry aliases (lib/providers): codex->openai.
_DEFAULT_CANDIDATES: tuple[str, ...] = ("codex", "ollama")

_VALID_VERDICTS: frozenset[str] = frozenset({"approved", "rejected", "conditional"})


def is_enabled(env: dict[str, str] | None = None) -> bool:
    """True iff the operator opted in via DEBATE_EXT_JURY=1. Default OFF."""
    src = os.environ if env is None else env
    return str(src.get("DEBATE_EXT_JURY", "")).strip() == "1"


def default_members() -> list:
    """Resolve available NON-Claude jury members (codex/ollama).

    Probes the provider registry; keeps only registered + available vendors.
    Returns [] when none are available (→ jury_advisory skips cleanly). Fail-soft
    per candidate (a probe error drops that candidate, never raises)."""
    from engine.external_jury import JuryMember
    from lib.providers import get_provider

    out: list = []
    for name in _DEFAULT_CANDIDATES:
        try:
            provider = get_provider(name)
            if provider.is_available():
                out.append(JuryMember(name))
        except Exception:
            continue
    return out


def jury_advisory(
    architect_prompt: str,
    *,
    architect_verdict: str | None = None,
    members: list | None = None,
    enabled: bool | None = None,
    mode: str = "panel",
    env: dict[str, str] | None = None,
    ask_fn: Callable[..., Any] | None = None,
    members_fn: Callable[[], list] | None = None,
    emit_fn: Callable[[str, dict], None] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    breaker_base_dir=None,
) -> dict:
    """Run an OPTIONAL cross-vendor jury and return an advisory payload.

    NEVER raises into the caller; NEVER affects convergence. The orchestrator
    appends the returned dict as a ``jury_advisory`` event and proceeds with the
    single-architect convergence check unchanged.

    Args:
      architect_prompt: the SAME prompt sent to harness-architect (caller-built).
      architect_verdict: the Claude Architect's verdict (approved|conditional|
        rejected), if known — enables the agreement comparison (the value: does
        the cross-vendor jury disagree with Claude?).
      members: explicit JuryMember list (default = default_members()).
      enabled: explicit override (default = is_enabled(env)).
      mode: 'panel' (independent verdicts, majority) or 'single'.
      ask_fn / members_fn: dependency injection for tests (default = the real
        external_jury.ask_jury / default_members).

    Returns a JSON-safe dict. Shape:
      disabled:  {enabled: False, skipped: True, skipped_reason: 'opt_out'}
      no member: {enabled: True, skipped: True, skipped_reason: 'no_available_non_claude_members'}
      error:     {enabled: True, skipped: True, skipped_reason: 'jury_error:<Type>'}
      ok:        {enabled: True, skipped: False, mode, members, consensus_verdict,
                  votes, agreement, failures, architect_verdict,
                  agrees_with_architect: bool|None, disagreement: bool|None}
    """
    use_enabled = is_enabled(env) if enabled is None else bool(enabled)
    if not use_enabled:
        return {"enabled": False, "skipped": True, "skipped_reason": "opt_out"}

    if not isinstance(architect_prompt, str) or not architect_prompt:
        return {"enabled": True, "skipped": True, "skipped_reason": "empty_prompt"}

    resolve_members = members_fn or default_members
    use_members = members if members is not None else resolve_members()
    if not use_members:
        return {
            "enabled": True, "skipped": True,
            "skipped_reason": "no_available_non_claude_members",
        }

    ask = ask_fn
    if ask is None:
        from engine.external_jury import ask_jury as _ask_jury
        ask = _ask_jury

    try:
        from lib.breakers.composite import _noop_emit
        verdict = ask(
            architect_prompt,
            use_members,
            mode=mode,
            retry_breaker=True,
            emit_fn=emit_fn or _noop_emit,
            sleep_fn=sleep_fn,
            breaker_base_dir=breaker_base_dir,
        )
    except Exception as e:  # ProviderUnavailableError (zero responded) / any error
        return {
            "enabled": True, "skipped": True,
            "skipped_reason": f"jury_error:{type(e).__name__}",
        }

    consensus = getattr(verdict, "consensus_verdict", None)
    agrees: bool | None = None
    if architect_verdict in _VALID_VERDICTS and consensus in _VALID_VERDICTS:
        agrees = (consensus == architect_verdict)

    return {
        "enabled": True,
        "skipped": False,
        "advisory_only": True,  # explicit: this NEVER feeds convergence
        "mode": getattr(verdict, "mode", mode),
        "members": list(getattr(verdict, "members", ()) or ()),
        "consensus_verdict": consensus,
        "votes": dict(getattr(verdict, "votes", {}) or {}),
        "agreement": getattr(verdict, "agreement", 0.0),
        "failures": list(getattr(verdict, "failures", ()) or ()),
        "architect_verdict": architect_verdict,
        "agrees_with_architect": agrees,
        "disagreement": (None if agrees is None else (not agrees)),
    }
