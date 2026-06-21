"""criticism_dedup — severity normalization + near-duplicate criticism clustering (M30).

Grounding (AI-Reviewers, arxiv 2605.28655-adjacent survey): LLM jurors overlap on
~21% of criticisms (vs ~3% for humans) and over-flag minor issues. Our harness has
the same shape but worse-measured: across 77 debate sessions, 134 critique events
carry blockers in **19 heterogeneous schema variants** with a chaotic severity
vocabulary (`high`/`HIGH`/`blocker`/`major` all mean the same; `med`/`MED`/`medium`
likewise). M8 only counts the coarse 3-axis label; the finer blocker CONTENT — the
actual repeated criticisms and their (uncalibrated) severity — is collected but
never spent.

This module is the gate-free ANALYSIS primitive (pure, no IO): canonicalize the
severity vocabulary, extract the criticism text out of whichever schema variant a
blocker uses, and cluster near-duplicate criticisms by token-Jaccard so a multi-gen
(or future multi-juror) critique set collapses to UNIQUE criticisms with a
multiplicity count. Multiplicity is itself signal — a criticism raised 3× across
generations is consensus, not 3 separate problems. The application seam (where the
deduped/calibrated view is consumed) is decided by /harness-debate; this module
only provides the deterministic math + the measurement surface.

Consumers (converged design debate-1781617065-m30a01 gen-3, LOCK sha1 f28a57e4):
  - ADVISORY (live): cli.debate_aggregate --format severity-calibration (per-debate
    calibrated-severity table for the Architect prompt) + --format criticism-diversity
    (cross-session overlap_rate + UNSPEC_UNCALIBRATED measurement for the gen-1 Planner).
    Both read-only, append no events, never gate.
  - DEDUP ACTION (deferred — cross-ref only): collapsing redundant criticisms into one
    vote belongs at the MULTI-juror seam lib.ensemble_evaluator.aggregate (and the
    built-but-unwired engine.external_jury). NOT wired here because measured single-critic
    content overlap is 0.0% — nothing to dedup until --ensemble adoption makes inter-juror
    overlap real. cluster_blockers / analyze_blockers are the one-import primitive to fold
    into that aggregation path when it happens.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ============================================================================
# Severity normalization (the chaotic-vocabulary calibration)
# ============================================================================

# Canonical ordered scale. Higher index = more severe.
SEVERITY_SCALE: tuple[str, ...] = ("UNSPEC", "LOW", "MED", "HIGH")
_SEVERITY_RANK: dict[str, int] = {s: i for i, s in enumerate(SEVERITY_SCALE)}

# Observed raw values (from a live survey of state/debates) -> canonical bucket.
_SEVERITY_MAP: dict[str, str] = {
    # HIGH family
    "high": "HIGH", "blocker": "HIGH", "block": "HIGH", "major": "HIGH",
    "critical": "HIGH", "crit": "HIGH", "severe": "HIGH", "h": "HIGH",
    # MED family
    "medium": "MED", "med": "MED", "moderate": "MED", "mod": "MED", "m": "MED",
    # LOW family
    "low": "LOW", "minor": "LOW", "nit": "LOW", "nitpick": "LOW",
    "trivial": "LOW", "l": "LOW",
}


def canonical_severity(raw) -> str:
    """Normalize a free-text severity into the canonical SEVERITY_SCALE.

    Case-insensitive, whitespace-trimmed. Unknown / missing / empty → 'UNSPEC'
    (never silently bucketed as LOW — an unlabeled blocker is not a minor one).
    """
    if not isinstance(raw, str):
        return "UNSPEC"
    key = raw.strip().lower()
    return _SEVERITY_MAP.get(key, "UNSPEC")


def severity_rank(canon: str) -> int:
    """Ordinal rank of a canonical severity (UNSPEC=0 .. HIGH=3)."""
    return _SEVERITY_RANK.get(canon, 0)


# ============================================================================
# Criticism text extraction (across the 19 schema variants)
# ============================================================================

# Preference order for the human-readable criticism text. The first present,
# non-empty field wins. Covers every variant seen in the live survey.
_TEXT_FIELDS: tuple[str, ...] = (
    "claim", "attack", "summary", "description", "decision",
)
# Fields identifying WHAT the criticism targets (for display / grouping).
_TARGET_FIELDS: tuple[str, ...] = (
    "target_decision", "decision_id", "target", "target_decision_id", "id",
)


def blocker_text(blocker: dict) -> str:
    """Extract the criticism text from a heterogeneous blocker dict."""
    if not isinstance(blocker, dict):
        return ""
    for f in _TEXT_FIELDS:
        v = blocker.get(f)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def blocker_target(blocker: dict) -> str:
    """Extract the target id (e.g. 'D2') from a heterogeneous blocker dict."""
    if not isinstance(blocker, dict):
        return ""
    for f in _TARGET_FIELDS:
        v = blocker.get(f)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def blocker_severity(blocker: dict) -> str:
    """Canonical severity from either the `severity` or short `sev` field."""
    if not isinstance(blocker, dict):
        return "UNSPEC"
    raw = blocker.get("severity")
    if raw is None:
        raw = blocker.get("sev")
    return canonical_severity(raw)


# ============================================================================
# Near-duplicate clustering (token-Jaccard)
# ============================================================================

_TOKEN_RE = re.compile(r"[a-z0-9_]+")
# Minimal English stopword set — drop high-frequency glue that inflates overlap.
_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "is", "are", "be", "to", "of", "and", "or", "in", "on",
    "for", "with", "no", "not", "has", "have", "had", "as", "at", "by", "it",
    "its", "this", "that", "may", "can", "but", "if", "then", "than", "so",
    "does", "do", "which", "what", "when", "where", "use", "uses", "used",
})
_MIN_TOKEN_LEN = 2


def normalize_tokens(text: str) -> frozenset[str]:
    """Lowercase, split on non-alphanumeric, drop stopwords + very short tokens."""
    if not text:
        return frozenset()
    toks = {
        t for t in _TOKEN_RE.findall(text.lower())
        if len(t) >= _MIN_TOKEN_LEN and t not in _STOPWORDS
    }
    return frozenset(toks)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard similarity |a∩b| / |a∪b|. Two empties → 0.0 (no evidence of overlap)."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


def claim_similarity(text_a: str, text_b: str) -> float:
    """Token-Jaccard similarity of two criticism texts."""
    return jaccard(normalize_tokens(text_a), normalize_tokens(text_b))


DEFAULT_DEDUP_THRESHOLD: float = 0.5
"""Jaccard ≥ this ⇒ same criticism. 0.5 = majority of distinctive tokens shared."""


@dataclass(frozen=True)
class CriticismCluster:
    """A set of near-duplicate blockers collapsed into one criticism."""
    representative: str           # the text of the first (canonical) member
    target: str                   # target id of the representative
    members: tuple[int, ...]      # indices into the input blocker list
    multiplicity: int             # len(members) — how many times this was raised
    max_severity: str             # highest canonical severity among members
    axes: tuple[str, ...]         # distinct axes among members


def cluster_blockers(
    blockers: list[dict],
    *,
    threshold: float = DEFAULT_DEDUP_THRESHOLD,
    same_target_required: bool = False,
) -> list[CriticismCluster]:
    """Greedy single-pass clustering of near-duplicate blockers.

    Each blocker joins the FIRST existing cluster whose representative text it
    matches at Jaccard ≥ threshold (optionally also requiring the same target id);
    otherwise it seeds a new cluster. Order-stable: the first occurrence is the
    representative, so clustering is deterministic given input order. Returns
    clusters in first-seen order.
    """
    reps: list[frozenset[str]] = []
    rep_text: list[str] = []
    rep_target: list[str] = []
    members: list[list[int]] = []
    sev: list[list[str]] = []
    axes: list[list[str]] = []

    for i, b in enumerate(blockers):
        text = blocker_text(b)
        toks = normalize_tokens(text)
        tgt = blocker_target(b)
        s = blocker_severity(b)
        ax = b.get("axis") if isinstance(b, dict) else None
        ax = ax.strip().lower() if isinstance(ax, str) and ax.strip() else ""

        placed = False
        for c in range(len(reps)):
            if same_target_required and rep_target[c] and tgt and rep_target[c] != tgt:
                continue
            if jaccard(toks, reps[c]) >= threshold:
                members[c].append(i)
                sev[c].append(s)
                if ax:
                    axes[c].append(ax)
                placed = True
                break
        if not placed:
            reps.append(toks)
            rep_text.append(text)
            rep_target.append(tgt)
            members.append([i])
            sev.append([s])
            axes.append([ax] if ax else [])

    out: list[CriticismCluster] = []
    for c in range(len(reps)):
        max_sev = max(sev[c], key=severity_rank) if sev[c] else "UNSPEC"
        distinct_axes = tuple(sorted(set(axes[c])))
        out.append(CriticismCluster(
            representative=rep_text[c], target=rep_target[c],
            members=tuple(members[c]), multiplicity=len(members[c]),
            max_severity=max_sev, axes=distinct_axes,
        ))
    return out


# ============================================================================
# Aggregate measurement (the gate-free analysis surface)
# ============================================================================


@dataclass(frozen=True)
class DiversityReport:
    total_blockers: int
    unique_criticisms: int
    overlap_rate: float                 # (total - unique) / total ∈ [0,1)
    severity_distribution: dict[str, int]
    redundant_clusters: tuple[CriticismCluster, ...]   # multiplicity >= 2
    unspec_severity_rate: float         # fraction of blockers with no usable severity


def analyze_blockers(
    blockers: list[dict],
    *,
    threshold: float = DEFAULT_DEDUP_THRESHOLD,
    same_target_required: bool = False,
) -> DiversityReport:
    """Measure overlap + severity-vocabulary health of a blocker set. Pure.

    overlap_rate is the fraction of blockers that are near-duplicates of an
    earlier one — our analog to the AI-Reviewers 21% inter-juror overlap. A high
    unspec_severity_rate signals an uncalibrated severity vocabulary (the
    over-flagging surface): blockers that should be triaged by severity but cannot
    be, because they carry an unrecognized / missing label.
    """
    total = len(blockers)
    clusters = cluster_blockers(blockers, threshold=threshold,
                                same_target_required=same_target_required)
    unique = len(clusters)
    overlap = (total - unique) / total if total else 0.0

    sev_dist: dict[str, int] = {s: 0 for s in SEVERITY_SCALE}
    for b in blockers:
        sev_dist[blocker_severity(b)] += 1
    unspec_rate = sev_dist["UNSPEC"] / total if total else 0.0

    redundant = tuple(c for c in clusters if c.multiplicity >= 2)
    return DiversityReport(
        total_blockers=total, unique_criticisms=unique, overlap_rate=overlap,
        severity_distribution=sev_dist, redundant_clusters=redundant,
        unspec_severity_rate=unspec_rate,
    )
