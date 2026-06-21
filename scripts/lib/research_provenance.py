"""research_provenance — discover-vs-confirm provenance classification (M31).

Grounding (LiveBrowseComp): a research/search agent often CONFIRMS what the base
model already knows rather than DISCOVERING new information — high "internal
knowledge dependence" (IKD). The true measurement is a closed-book baseline (re-run
the agent with no web tools and compare), which is expensive; this module is the
deterministic PROXY: classify the provenance of the sources an agent actually cited.
A claim grounded in an EXTERNAL source (a URL / academic paper / library docs) is
discovery evidence; a claim grounded only in LOCAL repo files — or with no citation
at all — leaned on internal knowledge.

Two live-ish citation surfaces share this classifier:
  - the debate Planner's ``research_citations[]`` (live: 20/152 proposals cite, 53
    URL-bearing) — consumed cross-session by cli.debate_aggregate --format
    research-provenance;
  - the harness-researcher ``## Sources`` markdown artifact (state/research/strikes/
    <fp>.md) — DORMANT (0 artifacts to date), so classify_source_line() is provided
    + unit-pinned but deliberately NOT wired into cli.strike_research_consume yet
    (wiring a consumer for a 0-data path is dead infra; this is the M30 measure-
    before-locking discipline).

This is a PROXY for IKD, not a closed-book baseline — an agent citing an external
URL may still have known the answer internally. The proxy is honest about what it
measures: where the agent SAID its grounding came from.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# Origin buckets, ordered weakest→strongest discovery evidence.
ORIGIN_NONE = "none"          # no source string at all
ORIGIN_UNKNOWN = "unknown"    # present but unclassifiable
ORIGIN_LOCAL = "local"        # a repo file path (internal — confirm, not discover)
ORIGIN_CONTEXT7 = "context7"  # a context7 library id (semi-external: published docs)
ORIGIN_EXTERNAL = "external"  # a generic external URL
ORIGIN_ACADEMIC = "academic"  # arxiv / doi / acm / ieee (strongest discovery signal)

# External buckets count as discovery evidence.
_EXTERNAL_ORIGINS = frozenset({ORIGIN_EXTERNAL, ORIGIN_ACADEMIC, ORIGIN_CONTEXT7})

_ACADEMIC_HOSTS = ("arxiv.org", "doi.org", "dl.acm.org", "ieeexplore.ieee.org",
                   "aclanthology.org", "openreview.net", "semanticscholar.org")
_URL_RE = re.compile(r"https?://([^/\s)]+)", re.IGNORECASE)
# A local repo path: contains a slash + a code/doc extension, no scheme.
_LOCAL_PATH_RE = re.compile(r"[\w./\\-]+\.(py|md|ya?ml|json|txt|toml|rs|ts|tsx|js|java|kt)\b",
                            re.IGNORECASE)
# A context7 library id, e.g. "/vercel/next.js" or "context7: /org/project".
_CONTEXT7_RE = re.compile(r"(?:context7[:\s]*)?/[a-z0-9_.-]+/[a-z0-9_.-]+", re.IGNORECASE)


def classify_origin(text: str) -> str:
    """Classify a single source string into an ORIGIN_* bucket. Deterministic."""
    if not isinstance(text, str) or not text.strip():
        return ORIGIN_NONE
    s = text.strip()
    m = _URL_RE.search(s)
    if m:
        host = m.group(1).lower()
        if any(host == h or host.endswith("." + h) for h in _ACADEMIC_HOSTS):
            return ORIGIN_ACADEMIC
        return ORIGIN_EXTERNAL
    # No URL. An explicit context7 marker wins (a bare "/org/proj.js" is genuinely
    # indistinguishable from a local path, so we only claim context7 when marked OR
    # the "/org/project" id carries no file extension).
    if "context7" in s.lower():
        return ORIGIN_CONTEXT7
    if _LOCAL_PATH_RE.search(s):
        return ORIGIN_LOCAL
    if _CONTEXT7_RE.search(s):
        return ORIGIN_CONTEXT7
    return ORIGIN_UNKNOWN


def _citation_source_string(c) -> str:
    """Pull the source string out of a citation (dict or str)."""
    if isinstance(c, str):
        return c
    if isinstance(c, dict):
        for f in ("url", "source_url", "source", "evidence_url", "link", "claim"):
            v = c.get(f)
            if isinstance(v, str) and v.strip():
                return v
    return ""


def classify_citation(c) -> str:
    """Origin bucket for a debate research_citations[] entry (dict or str)."""
    return classify_origin(_citation_source_string(c))


def classify_source_line(line: str) -> str:
    """Origin bucket for a `## Sources` markdown bullet line (researcher artifact).

    Handles the harness-researcher `- <path|libid|URL> — <what it establishes>`
    convention. DORMANT path (0 artifacts) but unit-pinned for when it activates.
    """
    if not isinstance(line, str):
        return ORIGIN_NONE
    s = line.strip().lstrip("-*").strip()
    if not s:
        return ORIGIN_NONE
    # Take the part before an em-dash/hyphen separator (the source token itself).
    head = re.split(r"\s+[—–-]\s+", s, maxsplit=1)[0].strip()
    return classify_origin(head or s)


@dataclass(frozen=True)
class ProvenanceReport:
    total: int
    external: int                 # external + academic + context7
    academic: int
    local: int
    unknown_or_none: int
    external_ratio: float         # external / total (0.0 when total==0)
    has_load_bearing: bool        # any citation tagged load_bearing_for
    verdict: str                  # 'discovered' | 'confirm_only' | 'no_citations'
    reason: str


def analyze_citations(citations) -> ProvenanceReport:
    """Classify a citation list into a discover-vs-confirm ProvenanceReport. Pure.

    verdict:
      - 'no_citations'  : the agent claimed NO sources (total==0). For an internal
        harness-design topic this is normal; for an external-library topic it is an
        IKD red flag — but THIS function does not judge the topic, only the provenance.
      - 'confirm_only'  : the agent DID cite (total>=1) but EVERY source is local/repo
        (external==0) — went through the motions of citing yet discovered nothing
        external. The narrow, defensible flag (it never defames a no-citation
        internal-design debate, only a cited-but-all-internal one).
      - 'discovered'    : at least one external source (URL / academic / context7).
    """
    cits = list(citations) if isinstance(citations, (list, tuple)) else []
    total = len(cits)
    external = academic = local = unk = 0
    has_lb = False
    for c in cits:
        if isinstance(c, dict) and c.get("load_bearing_for"):
            has_lb = True
        origin = classify_citation(c)
        if origin == ORIGIN_ACADEMIC:
            academic += 1
            external += 1
        elif origin in _EXTERNAL_ORIGINS:
            external += 1
        elif origin == ORIGIN_LOCAL:
            local += 1
        else:
            unk += 1

    external_ratio = (external / total) if total else 0.0
    if total == 0:
        verdict, reason = "no_citations", "no sources cited (internal knowledge only)"
    elif external == 0:
        verdict, reason = "confirm_only", (
            f"cited {total} source(s) but 0 external — all local/repo "
            f"(confirm-not-discover)")
    else:
        verdict, reason = "discovered", (
            f"{external}/{total} external source(s) cited (discovery evidence)")

    return ProvenanceReport(
        total=total, external=external, academic=academic, local=local,
        unknown_or_none=unk, external_ratio=external_ratio, has_load_bearing=has_lb,
        verdict=verdict, reason=reason,
    )
