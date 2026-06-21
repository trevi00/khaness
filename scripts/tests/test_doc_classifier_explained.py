#!/usr/bin/env python3
"""Tests for doc_classifier transparency (classify_doc_explained / classify_explained)
+ cli.ingest_docs report wiring (kha-ingest-docs opacity gap)."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def test_explained_matches_classify_doc_bucket():
    """The explained bucket MUST equal classify_doc's bucket (it only adds the 'why')."""
    from lib.extractors.doc_classifier import classify_doc, classify_doc_explained
    cases = [
        ("user-story.md", "blah"),                       # filename -> requirement
        ("notes.md", "# Non-functional requirements\nSLA 99.9%"),  # content -> constraint
        ("random.md", "just some prose with nothing"),   # default -> artifact
    ]
    for name, text in cases:
        ex = classify_doc_explained(name, text)
        assert ex["bucket"] == classify_doc(name, text), (name, ex)


def test_explained_surfaces_filename_vs_content_vs_default():
    from lib.extractors.doc_classifier import classify_doc_explained
    fn = classify_doc_explained("PRD-checkout.md", "anything")
    assert fn["matched_by"] == "filename" and fn["bucket"] == "requirement"
    ct = classify_doc_explained("misc.md", "# Glossary\nTerm: definition")
    assert ct["matched_by"] == "content" and ct["bucket"] == "glossary"
    df = classify_doc_explained("misc.md", "nothing classifiable here")
    assert df["matched_by"] == "default" and df["keyword"] is None and df["bucket"] == "artifact"


def test_classify_explained_report_sorted_and_complete():
    from lib.extractors.doc_classifier import classify_explained
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "docs").mkdir()
        (root / "docs" / "prd.md").write_text("# Product Requirements\nuser story", encoding="utf-8")
        (root / "docs" / "nfr.md").write_text("# NFR\nperformance budget 200ms", encoding="utf-8")
        report = classify_explained(root, liberal=True)
        paths = [r["path"] for r in report]
        assert paths == sorted(paths)                       # sorted
        by_path = {r["path"]: r for r in report}
        assert any(r["bucket"] == "requirement" for r in report)
        assert all({"path", "bucket", "matched_by", "keyword", "title"} <= set(r) for r in report)


def test_ingest_docs_emits_report_json():
    from cli.ingest_docs import main
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "docs").mkdir()
        (root / "docs" / "user-story.md").write_text("# Login\nuser story: as a user...", encoding="utf-8")
        out = root / "planning"
        rc = main(["--src", str(root / "docs"), "--out", str(out)])
        assert rc == 0
        report_path = out / ".ingest-classifier-report.json"
        assert report_path.is_file()
        data = json.loads(report_path.read_text(encoding="utf-8"))
        assert isinstance(data, list) and data and data[0]["bucket"] in (
            "requirement", "constraint", "glossary", "artifact")


def main_() -> int:
    tests = [
        test_explained_matches_classify_doc_bucket,
        test_explained_surfaces_filename_vs_content_vs_default,
        test_classify_explained_report_sorted_and_complete,
        test_ingest_docs_emits_report_json,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            import traceback
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failed += 1
    if failed == 0:
        print(f"[OK] {len(tests)} tests passed")
        return 0
    print(f"[FAIL] {failed}/{len(tests)} tests failed")
    return 1


# run_units discovers main()
def main() -> int:
    return main_()


if __name__ == "__main__":
    sys.exit(main())
