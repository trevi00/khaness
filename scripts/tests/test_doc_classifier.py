#!/usr/bin/env python3
"""Tests for lib/extractors/doc_classifier.py — prose-doc ingest (P2 D2)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.extractors import doc_classifier as dc  # noqa: E402
from lib.extractors import get_extractor, list_extractors  # noqa: E402
from cli import ingest_docs as ingest_cli  # noqa: E402


def _mk(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_classify_doc_by_filename():
    assert dc.classify_doc("PRD.md", "") == "requirement"
    assert dc.classify_doc("ADR-001-db.md", "") == "artifact"
    assert dc.classify_doc("glossary.md", "") == "glossary"
    assert dc.classify_doc("nfr-constraints.md", "") == "constraint"


def test_classify_doc_by_content_when_name_neutral():
    assert dc.classify_doc("notes.md", "# Acceptance criteria\nThe system shall...") == "requirement"
    assert dc.classify_doc("notes.md", "# Architecture decision record\n") == "artifact"


def test_classify_doc_defaults_to_artifact():
    assert dc.classify_doc("random.md", "some prose with no signal") == "artifact"


def test_find_doc_sources_excludes_readme():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mk(root, "README.md", "# readme")
        _mk(root, "docs/adr-001.md", "# ADR 1")
        found = {p.name for p in dc.find_doc_sources(root)}
        assert "README.md" not in found
        assert "adr-001.md" in found


def test_find_doc_sources_conservative_no_signal():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mk(root, "notes.md", "random")  # no strong name, not in doc dir
        assert dc.find_doc_sources(root) == []


def test_can_extract_gated_on_strong_signal():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        assert dc.DocClassifier().can_extract(root) is False
        _mk(root, "docs/PRD.md", "# PRD")
        assert dc.DocClassifier().can_extract(root) is True


def test_classify_buckets_and_terms():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mk(root, "docs/PRD.md", "# Product Requirements\nUser shall log in.")
        _mk(root, "docs/nfr.md", "# Non-functional constraints\nLatency < 100ms")
        _mk(root, "docs/glossary.md", "# Glossary\n- **SLA** — service level agreement\n")
        _mk(root, "docs/adr-1.md", "# Architecture Decision\nUse Postgres.")
        b = dc.classify(root)
        assert len(b["requirement"]) == 1
        assert len(b["constraint"]) == 1
        assert len(b["glossary"]) == 1
        assert len(b["artifact"]) == 1
        terms = b["_terms"]
        assert any(t["term"] == "SLA" for t in terms), terms


def test_render_spec_seed_and_glossary():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mk(root, "docs/PRD.md", "# Login PRD\nshall authenticate")
        _mk(root, "docs/glossary.md", "# Glossary\n- **token** — an auth credential\n")
        b = dc.classify(root)
        spec = dc.render_spec_seed(b)
        assert "# SPEC seed (ingested)" in spec
        assert "Login PRD" in spec
        gloss = dc.render_glossary(b)
        assert "**token**" in gloss


def test_render_handles_empty_buckets():
    empty = {bk: [] for bk in dc.BUCKETS}
    empty["_terms"] = []
    assert "_(none classified)_" in dc.render_spec_seed(empty)
    assert "_(no glossary terms extracted)_" in dc.render_glossary(empty)


def test_extract_protocol_conformance():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mk(root, "docs/SPEC.md", "# Spec\nrequirement: must work")
        ex = dc.DocClassifier()
        res = ex.extract(root)
        assert res.extractor == "doc_classifier"
        assert res.target == ".planning/SPEC-seed.md"
        assert res.confidence > 0.0
        assert "SPEC seed" in res.content


def test_registered_in_ocp_registry():
    assert "doc_classifier" in list_extractors()
    assert isinstance(get_extractor("doc_classifier"), dc.DocClassifier)


def test_liberal_mode_ingests_bucket_named_files():
    """Explicit --src: liberal scan picks up nfr.md (constraint keyword, not a
    discovery keyword) that conservative discovery would drop."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mk(root, "nfr.md", "# Non-functional\nlatency budget")
        _mk(root, "random-notes.md", "# Notes\nmisc")
        # conservative: nfr.md is root-level + name not a strong signal -> dropped
        assert dc.find_doc_sources(root) == []
        # liberal: both ingested (minus boilerplate)
        b = dc.classify(root, liberal=True)
        all_paths = {it["path"] for bk in dc.BUCKETS for it in b[bk]}
        assert "nfr.md" in all_paths, all_paths
        assert len(b["constraint"]) == 1, b["constraint"]


def test_liberal_excludes_boilerplate():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mk(root, "README.md", "# readme")
        _mk(root, "spec.md", "# spec")
        paths = {p.name for p in dc.find_doc_sources(root, liberal=True)}
        assert "README.md" not in paths
        assert "spec.md" in paths


def test_cli_main_wires_liberal_discovery():
    """Regression guard for the CLI last-mile wiring (wave-30 f/u 1e15bd4 added
    the ``liberal`` param to classify()/find_doc_sources() + function-level tests,
    but the CLI call site must actually PASS liberal=True for explicit ingest).

    Probe: a lone top-level ``nfr.md`` is dropped by conservative discovery (stem
    not a strong-name signal, not under a doc dir) but kept by liberal. So if the
    CLI ever reverts to ``dc.classify(src)`` (conservative), main() finds nothing
    and returns 1 — this asserts exit 0 + the doc reaching SPEC-seed.md."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mk(root, "src/nfr.md", "# Non-functional\nlatency budget < 100ms")
        # Sanity: conservative discovery alone would drop nfr.md -> nothing to ingest.
        assert dc.find_doc_sources(root / "src") == []
        out = root / ".planning"
        rc = ingest_cli.main(["--src", str(root / "src"), "--out", str(out)])
        assert rc == 0, "CLI must pass liberal=True so explicit ingest keeps nfr.md"
        spec = (out / "SPEC-seed.md").read_text(encoding="utf-8")
        assert "nfr.md" in spec, spec


def test_cli_main_dry_run_liberal_counts():
    """--dry-run must also reflect liberal discovery (exit 0, no files written)."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mk(root, "src/nfr.md", "# Non-functional\nlatency budget")
        out = root / ".planning"
        rc = ingest_cli.main(["--src", str(root / "src"), "--out", str(out), "--dry-run"])
        assert rc == 0
        assert not out.exists(), "dry-run must not write the planning dir"


def test_deterministic_classification():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mk(root, "docs/b-PRD.md", "# B")
        _mk(root, "docs/a-PRD.md", "# A")
        r1 = dc.render_spec_seed(dc.classify(root))
        r2 = dc.render_spec_seed(dc.classify(root))
        assert r1 == r2


def main() -> int:
    tests = [
        test_classify_doc_by_filename,
        test_classify_doc_by_content_when_name_neutral,
        test_classify_doc_defaults_to_artifact,
        test_find_doc_sources_excludes_readme,
        test_find_doc_sources_conservative_no_signal,
        test_can_extract_gated_on_strong_signal,
        test_classify_buckets_and_terms,
        test_render_spec_seed_and_glossary,
        test_render_handles_empty_buckets,
        test_extract_protocol_conformance,
        test_registered_in_ocp_registry,
        test_liberal_mode_ingests_bucket_named_files,
        test_liberal_excludes_boilerplate,
        test_cli_main_wires_liberal_discovery,
        test_cli_main_dry_run_liberal_counts,
        test_deterministic_classification,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    if failed == 0:
        print(f"[OK] {len(tests)} tests passed")
        return 0
    print(f"[FAIL] {failed}/{len(tests)} tests failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
