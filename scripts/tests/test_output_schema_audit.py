#!/usr/bin/env python3
"""Tests for cli.output_schema_audit (v15.10 A7).

Coverage:
  - classify_agent: frontmatter form > XML form > missing
  - audit() returns dict shape with counts + missing list + all_covered
  - strict mode treats XML as missing
  - missing files / empty dir → all_covered=True, counts all zero
  - CLI: --json emits valid JSON; non-zero exit when not covered
"""
from __future__ import annotations

import json
import sys
import tempfile
from io import StringIO
from contextlib import redirect_stdout
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cli.output_schema_audit import audit, classify_agent, main as cli_main  # noqa: E402


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# ---- classify_agent --------------------------------------------------------------

def test_frontmatter_form_detected():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "a.md"
        _write(p,
            "---\n"
            "name: foo\n"
            "output_schema: '{\"type\":\"object\"}'\n"
            "---\n"
            "body\n"
        )
        assert classify_agent(p) == "PRESENT_FRONTMATTER"


def test_xml_form_detected():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "a.md"
        _write(p,
            "---\n"
            "name: foo\n"
            "---\n"
            "<output_schema>\nshape here\n</output_schema>\n"
        )
        assert classify_agent(p) == "PRESENT_XML"


def test_missing_form_detected():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "a.md"
        _write(p,
            "---\n"
            "name: foo\n"
            "---\n"
            "body without schema\n"
        )
        assert classify_agent(p) == "MISSING"


def test_no_frontmatter_still_checks_body_for_xml():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "a.md"
        _write(p, "<output_schema>x</output_schema>\n")
        assert classify_agent(p) == "PRESENT_XML"


def test_empty_output_schema_frontmatter_value_is_missing():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "a.md"
        _write(p,
            "---\n"
            "name: foo\n"
            "output_schema: \n"
            "---\n"
            "body\n"
        )
        assert classify_agent(p) == "MISSING"


# ---- audit ----------------------------------------------------------------------

def test_audit_aggregates_counts_and_missing_list():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        _write(base / "a1.md", "---\noutput_schema: '{}'\n---\n")
        _write(base / "a2.md", "---\n---\n<output_schema>x</output_schema>")
        _write(base / "a3.md", "---\n---\nno schema")
        report = audit(base)
        s = report["__summary__"]
        assert s["total"] == 3
        assert s["counts"]["PRESENT_FRONTMATTER"] == 1
        assert s["counts"]["PRESENT_XML"] == 1
        assert s["counts"]["MISSING"] == 1
        assert s["missing"] == ["a3"]
        assert s["all_covered"] is False


def test_audit_strict_mode_treats_xml_as_missing():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        _write(base / "a1.md", "---\noutput_schema: '{}'\n---\n")
        _write(base / "a2.md", "---\n---\n<output_schema>x</output_schema>")
        report = audit(base, strict=True)
        s = report["__summary__"]
        # Only the frontmatter-declared one passes
        assert s["missing"] == ["a2"]
        assert s["all_covered"] is False


def test_audit_empty_dir_is_fully_covered():
    with tempfile.TemporaryDirectory() as td:
        report = audit(Path(td))
        s = report["__summary__"]
        assert s["total"] == 0
        assert s["all_covered"] is True


def test_audit_missing_dir_is_fully_covered():
    report = audit(Path("C:/no/such/dir/for/audit"))
    s = report["__summary__"]
    assert s["total"] == 0
    assert s["all_covered"] is True


# ---- CLI ------------------------------------------------------------------------

def test_cli_json_output_is_valid_json():
    with tempfile.TemporaryDirectory() as td:
        out = StringIO()
        with redirect_stdout(out):
            cli_main(["--json", "--agents-dir", td])
        # empty dir → fully covered, but JSON must still parse
        parsed = json.loads(out.getvalue())
        assert "__summary__" in parsed
        assert parsed["__summary__"]["all_covered"] is True


def test_cli_returns_nonzero_when_not_covered():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        _write(base / "a.md", "---\n---\nno schema")
        out = StringIO()
        with redirect_stdout(out):
            rc = cli_main(["--agents-dir", str(base)])
        assert rc == 1


def test_cli_returns_zero_when_all_covered():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        _write(base / "a.md",
            "---\noutput_schema: '{}'\n---\nbody\n"
        )
        out = StringIO()
        with redirect_stdout(out):
            rc = cli_main(["--agents-dir", str(base)])
        assert rc == 0


TESTS = [
    test_frontmatter_form_detected,
    test_xml_form_detected,
    test_missing_form_detected,
    test_no_frontmatter_still_checks_body_for_xml,
    test_empty_output_schema_frontmatter_value_is_missing,
    test_audit_aggregates_counts_and_missing_list,
    test_audit_strict_mode_treats_xml_as_missing,
    test_audit_empty_dir_is_fully_covered,
    test_audit_missing_dir_is_fully_covered,
    test_cli_json_output_is_valid_json,
    test_cli_returns_nonzero_when_not_covered,
    test_cli_returns_zero_when_all_covered,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"  [OK] {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  [ERROR] {fn.__name__}: {type(e).__name__}: {e}")
    if failed:
        print(f"\n[FAIL] {failed}/{len(TESTS)} tests failed")
        return 1
    print(f"\n[OK] {len(TESTS)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
