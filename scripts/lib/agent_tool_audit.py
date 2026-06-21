"""agent_tool_audit — cross-check subagent self-reported tool inventory vs frontmatter.

Closes the residual surfaced at debate-1778302432-1ce6ea citation drift audit
(commit 30ceb91): a Critic agent whose frontmatter declares ``WebFetch`` may
nonetheless self-report 'WebFetch unavailable' in its critique payload —
this LLM self-report inaccuracy can let citation-integrity verification be
silently skipped.

The orchestrator (harness-debate skill body) calls
``verify_self_report_consistency()`` after parsing a Critic critique JSON.
If the Critic claimed a tool was unavailable that the agent's frontmatter
actually declares, we surface a mismatch advisory — the orchestrator can
then either re-spawn the Critic or proceed with reduced confidence in the
verification verdict.

Severity escalation (added 2026-05-10): when research_citations were claimed
verified by the same Critic AND a self-report mismatch exists, the cite-
verification path itself may have been silently skipped. ``classify_severity``
returns ``"invalidate"`` for that case — caller MUST treat the architect's
verdict as ``rejected`` regardless of its declared status. Mismatch without
citations stays ``"advisory"`` (informational, no verdict change).
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from lib.frontmatter import parse_frontmatter

VerdictSeverity = Literal["clean", "advisory", "invalidate"]


_AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "agents"


def _agent_file(agent_name: str) -> Path:
    """Resolve agent_name (e.g. 'harness-critic') to its markdown file path."""
    if not agent_name:
        raise ValueError("agent_name must be non-empty")
    if "/" in agent_name or "\\" in agent_name or ".." in agent_name:
        raise ValueError(f"invalid agent_name: {agent_name!r}")
    return _AGENTS_DIR / f"{agent_name}.md"


def expected_tools(agent_name: str) -> set[str]:
    """Parse the agent's frontmatter ``tools`` field; return as a set.

    Returns an empty set if the agent file is missing, has no frontmatter,
    or has no ``tools`` field. Comma-separated tokens are stripped.
    """
    path = _agent_file(agent_name)
    parsed = parse_frontmatter(path)
    if parsed is None:
        return set()
    meta, _body = parsed
    raw = meta.get("tools", "")
    if not raw:
        return set()
    return {tok.strip() for tok in raw.split(",") if tok.strip()}


def verify_self_report_consistency(
    agent_name: str,
    *,
    self_reported_missing: list[str] | set[str] | tuple[str, ...],
) -> list[str]:
    """Return tools the agent claimed missing that frontmatter actually declares.

    A non-empty result indicates the agent's self-report is inconsistent
    with its declared toolset — caller surfaces this as an advisory.
    """
    expected = expected_tools(agent_name)
    if not expected:
        return []
    claimed = {t.strip() for t in self_reported_missing if t.strip()}
    return sorted(expected & claimed)


def check_overclaim(
    agent_name: str,
    *,
    self_reported_used: list[str] | set[str] | tuple[str, ...],
) -> list[str]:
    """Return tools the agent claimed *using* that frontmatter does NOT declare.

    The complement to ``verify_self_report_consistency``. That helper catches
    the case where the agent under-reports (claims a declared tool is
    missing); this helper catches the over-report — the agent's output says
    "I used WebFetch" but its frontmatter does not declare WebFetch. Two
    possible causes:

    1. The agent is hallucinating tool usage (LLM fabrication) — verdict
       reliability suffers.
    2. The agent actually invoked an undeclared tool — platform isolation
       escalation, indicates frontmatter gating was not enforced.

    Either way the gap is worth surfacing. Returns empty list when no
    frontmatter is parseable for the agent (we have nothing to compare
    against).
    """
    expected = expected_tools(agent_name)
    if not expected:
        return []
    claimed = {t.strip() for t in self_reported_used if t.strip()}
    return sorted(claimed - expected)


def classify_severity(
    mismatches: list[str],
    *,
    has_research_citations: bool,
) -> VerdictSeverity:
    """Decide how serious a self-report mismatch is.

    - ``clean``: no mismatch — verification verdict trusted as-is.
    - ``advisory``: mismatch present but no research_citations were
      claimed verified this generation — operator surfaces gap, no
      verdict change.
    - ``invalidate``: mismatch present AND citations were claimed
      verified — the verification path itself may have been silently
      skipped, so verdict cannot be trusted. Caller MUST treat verdict
      as ``rejected`` regardless of architect output.
    """
    if not mismatches:
        return "clean"
    return "invalidate" if has_research_citations else "advisory"


def render_advisory(
    agent_name: str,
    mismatches: list[str],
    *,
    severity: VerdictSeverity = "advisory",
) -> str:
    """One-line advisory text suitable for orchestrator log/event payload.

    The default ``severity="advisory"`` preserves the pre-2026-05-10
    behavior for callers that have not yet adopted ``classify_severity``.
    """
    if not mismatches or severity == "clean":
        return ""
    if severity == "invalidate":
        return (
            f"[self-report-mismatch:INVALIDATE] agent={agent_name} "
            f"claimed_missing={mismatches} but frontmatter declares them — "
            "citations were claimed verified; verification verdict CANNOT "
            "be trusted. Caller must treat verdict as rejected."
        )
    return (
        f"[self-report-mismatch] agent={agent_name} "
        f"claimed_missing={mismatches} but frontmatter declares them — "
        "verification verdict may be unreliable."
    )
