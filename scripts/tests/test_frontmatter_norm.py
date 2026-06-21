#!/usr/bin/env python3
"""Tests for lib/frontmatter_norm.py — split_list_field tokenizer."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def test_empty_returns_empty_list():
    from lib.frontmatter_norm import split_list_field
    assert split_list_field("") == []


def test_blank_returns_empty_list():
    from lib.frontmatter_norm import split_list_field
    assert split_list_field("   \t\n  ") == []


def test_whitespace_separated_legacy():
    from lib.frontmatter_norm import split_list_field
    assert split_list_field("a b c") == ["a", "b", "c"]


def test_yaml_inline_list_with_spaces():
    from lib.frontmatter_norm import split_list_field
    assert split_list_field("[a, b, c]") == ["a", "b", "c"]


def test_yaml_inline_list_compact():
    from lib.frontmatter_norm import split_list_field
    assert split_list_field("[a,b,c]") == ["a", "b", "c"]


def test_yaml_list_strips_trailing_punctuation():
    from lib.frontmatter_norm import split_list_field
    assert split_list_field("[a,, b,]") == ["a", "b"]


def test_yaml_list_with_inner_whitespace():
    from lib.frontmatter_norm import split_list_field
    assert split_list_field("[  alpha  ,  beta  ]") == ["alpha", "beta"]


def test_single_item_whitespace_form():
    from lib.frontmatter_norm import split_list_field
    assert split_list_field("solo") == ["solo"]


def test_single_item_yaml_form():
    from lib.frontmatter_norm import split_list_field
    assert split_list_field("[solo]") == ["solo"]


def test_yaml_list_empty_inner_returns_empty():
    from lib.frontmatter_norm import split_list_field
    assert split_list_field("[]") == []


def test_yaml_list_with_only_commas_returns_empty():
    from lib.frontmatter_norm import split_list_field
    assert split_list_field("[, , ,]") == []


# --- has_section / ensure_field (centralized from cli/*_normalize.py) ---

def test_has_section_detects_exact_header():
    from lib.frontmatter_norm import has_section
    assert has_section("intro\n## Output\nbody", "Output") is True


def test_has_section_case_sensitive_and_anchored():
    from lib.frontmatter_norm import has_section
    assert has_section("## output", "Output") is False        # case-sensitive
    assert has_section("text ## Output inline", "Output") is False  # not line-anchored
    assert has_section("### Output", "Output") is False        # H3 != H2


def test_ensure_field_appends_when_missing():
    from lib.frontmatter_norm import ensure_field
    assert ensure_field("name: x", "category", "run") == "name: x\ncategory: run"


def test_ensure_field_replaces_first_when_present():
    from lib.frontmatter_norm import ensure_field
    assert ensure_field("name: x\ncategory: old", "category", "new") == "name: x\ncategory: new"


def test_ensure_field_strips_trailing_before_append():
    from lib.frontmatter_norm import ensure_field
    assert ensure_field("name: x\n\n", "mutates", "yes") == "name: x\nmutates: yes"


# --- parse_frontmatter BOM tolerance (lib/frontmatter.py — utf-8-sig) ---

def test_parse_frontmatter_tolerates_utf8_bom():
    """A BOM-prefixed .md must still parse — without utf-8-sig the leading \\ufeff
    makes startswith('---') False and the parser silently returns None, dropping
    the skill/agent's metadata from matching (audit footgun)."""
    import tempfile
    from lib.frontmatter import parse_frontmatter
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "withbom.md"
        p.write_text("---\nname: bomtest\ndescription: d\n---\nbody\n",
                     encoding="utf-8-sig")  # writes a leading BOM
        result = parse_frontmatter(p)
        assert result is not None, "BOM-prefixed frontmatter must parse, not return None"
        fm, _ = result
        assert fm.get("name") == "bomtest"


TESTS = [
    test_parse_frontmatter_tolerates_utf8_bom,
    test_empty_returns_empty_list,
    test_blank_returns_empty_list,
    test_whitespace_separated_legacy,
    test_yaml_inline_list_with_spaces,
    test_yaml_inline_list_compact,
    test_yaml_list_strips_trailing_punctuation,
    test_yaml_list_with_inner_whitespace,
    test_single_item_whitespace_form,
    test_single_item_yaml_form,
    test_yaml_list_empty_inner_returns_empty,
    test_yaml_list_with_only_commas_returns_empty,
    test_has_section_detects_exact_header,
    test_has_section_case_sensitive_and_anchored,
    test_ensure_field_appends_when_missing,
    test_ensure_field_replaces_first_when_present,
    test_ensure_field_strips_trailing_before_append,
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
