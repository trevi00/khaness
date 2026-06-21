#!/usr/bin/env python3
"""Tests for validators/ai_spec_eval_coverage.py (advisory; kha AI-building P1).

Hermetic: the pure extractors/checkers operate on synthetic strings + tmp dirs,
so no real project or AI-SPEC.md is touched. Confirms the LOCK
coverage_validator_contract invariant: STRICT mechanical referential-integrity
ONLY (a non-empty stub PASSES — adequacy is descoped, never judged here).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from validators import ai_spec_eval_coverage as v  # noqa: E402
from validators import VALIDATOR_NAMES  # noqa: E402


_OPEN = "<!-- eval-coverage-manifest -->"
_CLOSE = "<!-- /eval-coverage-manifest -->"


def _spec(manifest_yaml: str) -> str:
    return f"# AI-SPEC\nintro\n{_OPEN}\n```yaml\n{manifest_yaml}\n```\n{_CLOSE}\noutro\n"


# ── pure extractors ──
def test_extract_manifest_present_and_fence_stripped():
    raw = v.extract_manifest(_spec("golden_set_size: 5"))
    assert raw is not None
    assert "golden_set_size: 5" in raw
    assert "```" not in raw, "code fence must be stripped"


def test_extract_manifest_absent():
    assert v.extract_manifest("no manifest at all") is None
    # open without close → None
    assert v.extract_manifest("x " + _OPEN + " unterminated") is None


def test_parse_manifest_fail_soft():
    assert v.parse_manifest("a: 1\nb: 2") == {"a": 1, "b": 2}
    assert v.parse_manifest("- a\n- b") is None, "non-mapping → None"
    assert v.parse_manifest(":\n: :\n:::") is None, "garbled → None (never raises)"


# ── mechanical checks ──
def _clean():
    return {
        "golden_set_size": 3,
        "acceptable_fail_rate": 0.1,
        "failure_modes": [{"id": "fm-a", "artifact_path": "tests/fm_a.py"}],
    }


def test_check_manifest_clean():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "tests").mkdir()
        (base / "tests" / "fm_a.py").write_text("assert True\n", encoding="utf-8")
        assert v.check_manifest(_clean(), base) == []


def test_check_manifest_scalar_violations():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "tests").mkdir()
        (base / "tests" / "fm_a.py").write_text("x\n", encoding="utf-8")
        w = v.check_manifest(dict(_clean(), golden_set_size=0, acceptable_fail_rate=2.0), base)
        assert any("golden_set_size" in x for x in w)
        assert any("acceptable_fail_rate" in x for x in w)
        # bool is a subclass of int — must be rejected
        wb = v.check_manifest(dict(_clean(), golden_set_size=True), base)
        assert any("golden_set_size" in x for x in wb), "bool golden_set_size rejected"
        wf = v.check_manifest(dict(_clean(), acceptable_fail_rate=False), base)
        assert any("acceptable_fail_rate" in x for x in wf), "bool fail_rate rejected"


def test_check_manifest_slug_and_uniqueness():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "tests").mkdir()
        (base / "tests" / "fm_a.py").write_text("x\n", encoding="utf-8")
        w = v.check_manifest(dict(_clean(), failure_modes=[
            {"id": "Bad_Id", "artifact_path": "tests/fm_a.py"},
            {"id": "fm-a", "artifact_path": "tests/fm_a.py"},
            {"id": "fm-a", "artifact_path": "tests/fm_a.py"},
        ]), base)
        assert any("Bad_Id" in x for x in w), "non-slug id warned"
        assert any("duplicate" in x for x in w), "duplicate id warned"


def test_check_manifest_referential_integrity():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "empty.py").write_text("", encoding="utf-8")
        w = v.check_manifest(dict(_clean(), failure_modes=[
            {"id": "fm-missing", "artifact_path": "nope/gone.py"},
            {"id": "fm-empty", "artifact_path": "empty.py"},
        ]), base)
        assert any("not a file" in x for x in w), "missing path warned"
        assert any("empty (0 bytes)" in x for x in w), "empty file warned"


def test_one_byte_stub_passes_descope_boundary():
    """The documented descope boundary: a 1-byte stub PASSES referential
    integrity. This is intentional — adequacy is NEVER judged here."""
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "tests").mkdir()
        (base / "tests" / "fm_a.py").write_text("x", encoding="utf-8")  # 1 byte, semantically empty
        assert v.check_manifest(_clean(), base) == [], "1-byte stub must PASS (referential only)"


def test_empty_failure_modes_warned():
    with tempfile.TemporaryDirectory() as td:
        w = v.check_manifest(dict(_clean(), failure_modes=[]), Path(td))
        assert any("non-empty list" in x for x in w)


# ── scan / discovery ──
def test_scan_no_spec_is_clean_noop():
    with tempfile.TemporaryDirectory() as td:
        r = v.scan(Path(td))
        assert r["specs"] == [] and r["missing_block"] == []


def test_scan_real_spec_clean():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        phase = base / ".planning" / "phases" / "01-ai"
        phase.mkdir(parents=True)
        (base / "tests").mkdir()
        (base / "tests" / "fm_a.py").write_text("assert True\n", encoding="utf-8")
        (phase / "AI-SPEC.md").write_text(_spec(
            "golden_set_size: 3\nacceptable_fail_rate: 0.1\n"
            "failure_modes:\n  - id: fm-a\n    artifact_path: tests/fm_a.py\n"
        ), encoding="utf-8")
        r = v.scan(base)
        assert len(r["specs"]) == 1
        assert r["specs"][0]["warns"] == [], f"expected clean, got {r['specs'][0]['warns']}"


def test_scan_spec_missing_manifest():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        phase = base / ".planning" / "phases" / "01-ai"
        phase.mkdir(parents=True)
        (phase / "AI-SPEC.md").write_text("# AI-SPEC\nno manifest block\n", encoding="utf-8")
        r = v.scan(base)
        assert r["specs"] == []
        assert len(r["missing_block"]) == 1


# ── tier / governance invariants ──
def test_advisory_not_in_builtin():
    """LOCK D4: the validator is advisory — NOT in VALIDATOR_NAMES until a
    graduate-validator-token flip. run_all must not pick it up."""
    assert "ai_spec_eval_coverage" not in VALIDATOR_NAMES


def test_is_graduated_default_false_fail_soft():
    # No graduation state for this validator → advisory by construction.
    assert v._is_graduated() is False


def test_validator_source_is_hermetic():
    """No subprocess/network imports; AST-and-yaml only (matches advisory tier)."""
    src = Path(v.__file__).read_text(encoding="utf-8")
    for forbidden in ("import requests", "import subprocess", "urllib.request", "os.system"):
        assert forbidden not in src, f"advisory validator must not use {forbidden}"


def main() -> int:
    tests = [
        test_extract_manifest_present_and_fence_stripped,
        test_extract_manifest_absent,
        test_parse_manifest_fail_soft,
        test_check_manifest_clean,
        test_check_manifest_scalar_violations,
        test_check_manifest_slug_and_uniqueness,
        test_check_manifest_referential_integrity,
        test_one_byte_stub_passes_descope_boundary,
        test_empty_failure_modes_warned,
        test_scan_no_spec_is_clean_noop,
        test_scan_real_spec_clean,
        test_scan_spec_missing_manifest,
        test_advisory_not_in_builtin,
        test_is_graduated_default_false_fail_soft,
        test_validator_source_is_hermetic,
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


if __name__ == "__main__":
    sys.exit(main())
