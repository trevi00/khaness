#!/usr/bin/env python3
"""Tests for lib.research_provenance (M31) — discover-vs-confirm provenance
classification (IKD proxy). Pure primitive; the cross-session CLI consumer
(cli.debate_aggregate --format research-provenance) is tested separately.
Auto-discovered by run_units.py via main()->int.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.research_provenance import (  # noqa: E402
    ORIGIN_ACADEMIC,
    ORIGIN_CONTEXT7,
    ORIGIN_EXTERNAL,
    ORIGIN_LOCAL,
    ORIGIN_NONE,
    ORIGIN_UNKNOWN,
    analyze_citations,
    classify_citation,
    classify_origin,
    classify_source_line,
)


# ---- classify_origin ----

def test_classify_origin_external_url():
    assert classify_origin("https://serde.rs/impl-deserialize.html") == ORIGIN_EXTERNAL
    assert classify_origin("http://example.com/x") == ORIGIN_EXTERNAL


def test_classify_origin_academic():
    assert classify_origin("https://arxiv.org/abs/2303.11366") == ORIGIN_ACADEMIC
    assert classify_origin("https://doi.org/10.1/x") == ORIGIN_ACADEMIC


def test_classify_origin_local_path():
    assert classify_origin("scripts/lib/foo.py") == ORIGIN_LOCAL
    assert classify_origin("commands/harness-debate.md") == ORIGIN_LOCAL


def test_classify_origin_context7():
    assert classify_origin("/org/project") == ORIGIN_CONTEXT7          # bare id, no extension
    assert classify_origin("context7: /vercel/next.js") == ORIGIN_CONTEXT7  # explicit marker wins
    # honest limitation: a bare "/vercel/next.js" (extension) is indistinguishable
    # from a local path and classifies as local
    assert classify_origin("/vercel/next.js") == ORIGIN_LOCAL


def test_classify_origin_none_and_unknown():
    assert classify_origin("") == ORIGIN_NONE
    assert classify_origin("   ") == ORIGIN_NONE
    assert classify_origin(None) == ORIGIN_NONE
    assert classify_origin("Reflexion provider-separation precedent") == ORIGIN_UNKNOWN


# ---- classify_citation (dict / str) ----

def test_classify_citation_dict_url():
    assert classify_citation({"url": "https://docs.rs/proptest/", "load_bearing_for": "D7"}) == ORIGIN_EXTERNAL


def test_classify_citation_dict_source_url_academic():
    assert classify_citation({"source_url": "https://arxiv.org/abs/2303.11366"}) == ORIGIN_ACADEMIC


def test_classify_citation_str():
    assert classify_citation("https://example.com") == ORIGIN_EXTERNAL
    assert classify_citation({"claim": "no url here just prose"}) == ORIGIN_UNKNOWN


# ---- classify_source_line (researcher ## Sources markdown — dormant path) ----

def test_classify_source_line_handles_bullet_and_separator():
    assert classify_source_line("- https://x.com — what it establishes") == ORIGIN_EXTERNAL
    assert classify_source_line("- scripts/lib/foo.py — establishes the bug") == ORIGIN_LOCAL
    assert classify_source_line("* /org/proj — library docs") == ORIGIN_CONTEXT7
    assert classify_source_line("") == ORIGIN_NONE


# ---- analyze_citations (the ProvenanceReport verdict) ----

def test_analyze_no_citations():
    r = analyze_citations([])
    assert r.verdict == "no_citations" and r.total == 0 and r.external_ratio == 0.0


def test_analyze_discovered():
    r = analyze_citations([
        {"url": "https://serde.rs/x", "load_bearing_for": "D4"},
        {"source_url": "https://arxiv.org/abs/1", "load_bearing_for": "D5"},
    ])
    assert r.verdict == "discovered" and r.external == 2 and r.academic == 1
    assert r.has_load_bearing is True and abs(r.external_ratio - 1.0) < 1e-9


def test_analyze_confirm_only_all_local():
    r = analyze_citations([
        {"source": "scripts/lib/foo.py"},
        {"source": "commands/harness-debate.md"},
    ])
    assert r.verdict == "confirm_only" and r.external == 0 and r.local == 2


def test_analyze_mixed_is_discovered():
    r = analyze_citations([
        {"source": "scripts/lib/foo.py"},
        {"url": "https://docs.rs/x"},
    ])
    assert r.verdict == "discovered" and r.external == 1 and r.local == 1


def test_analyze_non_list_input_hardened():
    # Live data carried a malformed int research_citations -> must not crash.
    assert analyze_citations(5).verdict == "no_citations"
    assert analyze_citations(None).verdict == "no_citations"


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
