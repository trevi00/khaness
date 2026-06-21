#!/usr/bin/env python3
"""Tests for lib.criticism_dedup (M30) — severity normalization + near-duplicate
clustering + the DiversityReport measurement. Pure primitive; the CLI consumers
(cli.debate_aggregate severity-calibration / criticism-diversity) are tested
separately. Auto-discovered by run_units.py via main()->int.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.criticism_dedup import (  # noqa: E402
    analyze_blockers,
    blocker_severity,
    blocker_target,
    blocker_text,
    canonical_severity,
    claim_similarity,
    cluster_blockers,
    jaccard,
    normalize_tokens,
    severity_rank,
)


# ---- severity normalization (the chaotic-vocabulary calibration) ----

def test_canonical_severity_high_family():
    for raw in ("high", "HIGH", "blocker", "major", "critical", "Crit", " H "):
        assert canonical_severity(raw) == "HIGH", raw


def test_canonical_severity_med_low_families():
    for raw in ("medium", "MED", "med", "moderate"):
        assert canonical_severity(raw) == "MED", raw
    for raw in ("low", "minor", "nit", "trivial"):
        assert canonical_severity(raw) == "LOW", raw


def test_canonical_severity_unspec():
    for raw in (None, "", "   ", "weird", 5, "blockerish"):
        assert canonical_severity(raw) == "UNSPEC", raw


def test_severity_rank_ordering():
    assert severity_rank("HIGH") > severity_rank("MED") > severity_rank("LOW") > severity_rank("UNSPEC")


# ---- text / target / severity extraction (19 schema variants) ----

def test_blocker_text_preference_order():
    assert blocker_text({"claim": "C", "attack": "A"}) == "C"
    assert blocker_text({"attack": "A", "summary": "S"}) == "A"
    assert blocker_text({"summary": "S"}) == "S"
    assert blocker_text({"description": "D"}) == "D"
    assert blocker_text({"axis": "failure"}) == ""


def test_blocker_target_preference_order():
    assert blocker_target({"target_decision": "D2", "id": "x"}) == "D2"
    assert blocker_target({"decision_id": "D3"}) == "D3"
    assert blocker_target({"target": "D4"}) == "D4"
    assert blocker_target({"axis": "x"}) == ""


def test_blocker_severity_sev_fallback():
    assert blocker_severity({"severity": "blocker"}) == "HIGH"
    assert blocker_severity({"sev": "major"}) == "HIGH"       # sev fallback
    assert blocker_severity({"axis": "x"}) == "UNSPEC"        # no severity at all


# ---- token + jaccard ----

def test_normalize_tokens_drops_stopwords_and_short():
    toks = normalize_tokens("The citation is NOT a load-bearing claim")
    assert "citation" in toks and "load" in toks and "bearing" in toks and "claim" in toks
    assert "the" not in toks and "is" not in toks and "a" not in toks  # stopwords gone


def test_jaccard_bounds():
    a = normalize_tokens("provider binding violates separation invariant")
    assert jaccard(a, a) == 1.0
    assert jaccard(a, normalize_tokens("completely different unrelated words here")) == 0.0
    assert jaccard(frozenset(), a) == 0.0


def test_claim_similarity_near_duplicate():
    s = claim_similarity(
        "Voyager citation misattributed — uses GPT-4 critic not test replay",
        "Voyager citation misattributed — GPT-4 critic in Minecraft not replay",
    )
    assert s >= 0.5


# ---- clustering ----

def test_cluster_collapses_near_duplicates():
    blockers = [
        {"claim": "provider binding violates judge-generator separation invariant", "severity": "high"},
        {"claim": "provider binding violates the judge-generator separation invariant badly", "severity": "blocker"},
        {"claim": "completely unrelated hallucination detector contradiction", "severity": "med"},
    ]
    clusters = cluster_blockers(blockers, threshold=0.5)
    assert len(clusters) == 2  # first two collapse, third stands alone
    big = max(clusters, key=lambda c: c.multiplicity)
    assert big.multiplicity == 2 and big.max_severity == "HIGH"


def test_cluster_same_target_required_keeps_separate():
    blockers = [
        {"claim": "embedder has no provider binding here", "severity": "high", "target_decision": "D2"},
        {"claim": "embedder has no provider binding here", "severity": "high", "target_decision": "D3"},
    ]
    same = cluster_blockers(blockers, threshold=0.5, same_target_required=True)
    assert len(same) == 2  # identical text but different targets -> not merged
    merged = cluster_blockers(blockers, threshold=0.5, same_target_required=False)
    assert len(merged) == 1


def test_cluster_order_stable_representative_is_first():
    blockers = [
        {"claim": "alpha beta gamma delta epsilon", "severity": "low"},
        {"claim": "alpha beta gamma delta epsilon zeta", "severity": "high"},
    ]
    clusters = cluster_blockers(blockers, threshold=0.5)
    assert len(clusters) == 1
    assert clusters[0].representative.startswith("alpha beta gamma")  # first member is rep


# ---- analyze_blockers (the DiversityReport measurement) ----

def test_analyze_overlap_rate_and_distribution():
    blockers = [
        {"claim": "shared token alpha beta gamma", "severity": "high"},
        {"claim": "shared token alpha beta gamma delta", "severity": "high"},  # dup of #1
        {"claim": "orthogonal unrelated unique phrase", "severity": "medium"},
        {"axis": "x"},  # UNSPEC, empty text -> own cluster
    ]
    r = analyze_blockers(blockers, threshold=0.5)
    assert r.total_blockers == 4
    assert r.unique_criticisms == 3                 # two collapse
    assert abs(r.overlap_rate - 0.25) < 1e-9        # (4-3)/4
    assert r.severity_distribution["HIGH"] == 2 and r.severity_distribution["MED"] == 1
    assert r.severity_distribution["UNSPEC"] == 1
    assert abs(r.unspec_severity_rate - 0.25) < 1e-9
    assert len(r.redundant_clusters) == 1 and r.redundant_clusters[0].multiplicity == 2


def test_analyze_empty():
    r = analyze_blockers([])
    assert r.total_blockers == 0 and r.overlap_rate == 0.0 and r.unspec_severity_rate == 0.0


def test_analyze_zero_overlap_when_all_distinct():
    blockers = [{"claim": f"unique phrase number {w}", "severity": "high"} for w in
                ("alpha", "bravo", "charlie", "delta")]
    r = analyze_blockers(blockers, threshold=0.5)
    # "unique phrase number" is shared -> they may cluster; use clearly disjoint texts
    blockers2 = [
        {"claim": "alpha alpha alpha", "severity": "high"},
        {"claim": "bravo bravo bravo", "severity": "high"},
        {"claim": "charlie charlie charlie", "severity": "high"},
    ]
    r2 = analyze_blockers(blockers2, threshold=0.5)
    assert r2.overlap_rate == 0.0 and r2.unique_criticisms == 3


def main() -> int:
    failed = 0
    n = 0
    for name, obj in list(globals().items()):
        if not name.startswith("test_"):
            continue
        n += 1
        try:
            obj()
            print(f"  [OK] {name}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [ERR] {name}: {e!r}")
    if failed:
        print(f"\n{failed}/{n} failed")
        return 1
    print(f"\n[OK] {n} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
