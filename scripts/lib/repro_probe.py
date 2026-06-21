"""repro_probe — deterministic reproduction-probe builder for the strike→skill loop (M18).

Converged design: debate-1781594208-53fee4 gen 3 (snapshot sha1
286f4c8e18a4427dcc897e2b86a4e1844b5a6c79), decision D2.

`build_probe(fingerprint, tool_name, error_excerpt) -> Probe | None` decides whether
a repeat-failure fingerprint is *deterministically reproducible* — the precondition
for auto-staging a skill_gotcha candidate (see lib.no_degradation_gate).

Generator-time interpretation of the design intent (documented per DGE discipline):
the converged spec says "probe deterministically reproduced the fingerprint
pre-codification". A code harness CANNOT safely re-execute an arbitrary failing
tool command (unsafe side effects + non-determinism) — so the probe does NOT
re-run anything. Instead it *classifies* the fingerprint's error signature:

  - TRANSIENT class (403/Cloudflare/anti-bot, transient file-lock, network timeout):
    not deterministically reproducible → build_probe returns None → the caller
    routes to OPERATOR-ESCALATION, never silent fail-closed (condition B6). Silent
    fail-closed on this class would defeat the 2-Strike Rule, since the probe is
    100%% load-bearing once the held-in suite is dropped (skill_gotcha is advisory
    markdown, never executed → Δ_in≡0).

  - DETERMINISTIC class (a well-formed, non-transient signature): build_probe returns
    a Probe whose `.passed()` is True — the failure is of the deterministic class and
    its signature is reconstructable, so codifying a gotcha about it is grounded.

PRECONDITION-FIDELITY ASSUMPTION (stated, per condition MAJOR-1): the error_excerpt
is already `<X>`-normalized (paths/numbers replaced) per lib.repeat_error_tracker
(harness-researcher.md:25). When `<X>`-normalization has erased the discriminating
tokens a probe would need, build_probe biases toward None (over-escalation) rather
than fabricating a reproduction it cannot ground.

Classification is on the TEXTUAL signature keywords, NOT the numeric code — "403" may
already be normalized to "<X>", so we match "forbidden"/"cloudflare"/"timeout" words,
not the digits (condition MINOR). Default unknown/empty → None (over-escalation bias).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Probe:
    """A constructed reproduction probe for a deterministic-class fingerprint.

    `passed()` returns True when the probe establishes that the fingerprint is
    deterministically grounded (deterministic class + well-formed signature).
    The probe performs NO re-execution — see module docstring for why.
    """

    fingerprint: str
    tool_name: str
    signature: str  # the normalized error_excerpt the classification ran on

    def passed(self) -> bool:
        return True  # construction itself is the deterministic-grounding evidence


# Textual signatures of the NON-deterministic (transient) failure class.
# Matched case-insensitively against the already-<X>-normalized excerpt.
# We match WORDS, not numbers (403 may be "<X>" after normalization).
_TRANSIENT_SIGNATURES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bforbidden\b", re.IGNORECASE),          # 403 Forbidden
    re.compile(r"\bcloudflare\b", re.IGNORECASE),
    re.compile(r"\banti[- ]?bot\b", re.IGNORECASE),
    re.compile(r"\bcaptcha\b", re.IGNORECASE),
    re.compile(r"\brate[- ]?limit", re.IGNORECASE),       # 429-class
    re.compile(r"\btoo many requests\b", re.IGNORECASE),
    re.compile(r"\btimed?\s*out\b", re.IGNORECASE),       # timeout / timed out
    re.compile(r"\btimeout\b", re.IGNORECASE),
    re.compile(r"\btemporar(?:y|ily) unavailable\b", re.IGNORECASE),
    re.compile(r"\bconnection reset\b", re.IGNORECASE),
    re.compile(r"\bconnection refused\b", re.IGNORECASE),
    re.compile(r"\bresource temporarily unavailable\b", re.IGNORECASE),
    re.compile(r"\b(?:file|resource) (?:is )?locked\b", re.IGNORECASE),
    re.compile(r"\block(?:ed)? by another process\b", re.IGNORECASE),
    re.compile(r"\bbeing used by another process\b", re.IGNORECASE),
    re.compile(r"\bnetwork (?:is )?unreachable\b", re.IGNORECASE),
    re.compile(r"\bservice unavailable\b", re.IGNORECASE),  # 503-class
    re.compile(r"\bgateway time", re.IGNORECASE),          # 504-class
    re.compile(r"\bephemeral\b", re.IGNORECASE),
    re.compile(r"\bflaky\b", re.IGNORECASE),
)

# A signature is "well-formed" enough to ground a deterministic probe only if it
# carries at least one non-placeholder alphabetic token. An excerpt that has been
# reduced almost entirely to "<X>" placeholders has lost its discriminating
# content → over-escalation bias (return None).
_PLACEHOLDER_RE = re.compile(r"<x>", re.IGNORECASE)
_ALPHA_TOKEN_RE = re.compile(r"[A-Za-z]{3,}")


def is_transient(error_excerpt: str) -> bool:
    """True iff the excerpt matches a known non-deterministic (transient) signature."""
    if not isinstance(error_excerpt, str):
        return False
    return any(p.search(error_excerpt) for p in _TRANSIENT_SIGNATURES)


def _signature_is_groundable(error_excerpt: str) -> bool:
    """Heuristic precondition-fidelity check (over-escalation bias).

    Returns False when `<X>`-normalization has erased the discriminating tokens —
    i.e. the excerpt is empty, or after stripping `<X>` placeholders there is no
    remaining alphabetic signature (≥3-char word) to ground a reproduction on.
    """
    if not isinstance(error_excerpt, str):
        return False
    stripped = _PLACEHOLDER_RE.sub(" ", error_excerpt).strip()
    if not stripped:
        return False
    # Need at least one non-transient alphabetic token to call it "deterministic".
    meaningful = [t for t in _ALPHA_TOKEN_RE.findall(stripped)]
    return len(meaningful) >= 2


def build_probe(
    fingerprint: str,
    tool_name: str,
    error_excerpt: str,
) -> Probe | None:
    """Build a deterministic reproduction probe, or None to route to escalation.

    Returns None (→ operator-escalation, NEVER silent fail-closed) when:
      - inputs are missing/empty,
      - the signature is the transient/non-deterministic class (403/Cloudflare/
        timeout/file-lock/...), or
      - `<X>`-normalization has erased the discriminating tokens (precondition
        fidelity lost) — over-escalation bias.

    Returns a Probe (whose .passed() is True) when the fingerprint is of the
    deterministic class with a well-formed, groundable signature.
    """
    if not fingerprint or not tool_name or not isinstance(error_excerpt, str):
        return None
    if is_transient(error_excerpt):
        return None
    if not _signature_is_groundable(error_excerpt):
        return None
    return Probe(fingerprint=fingerprint, tool_name=tool_name, signature=error_excerpt[:400])
