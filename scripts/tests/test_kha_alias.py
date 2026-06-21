#!/usr/bin/env python3
"""Unit tests for cli/kha_alias.py — frontmatter rewrite + idempotency + map shape."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cli import kha_alias as ka  # noqa: E402


def test_rename_map_has_68_entries():
    assert len(ka.RENAME_MAP) == 68, f"expected 68 renames, got {len(ka.RENAME_MAP)}"


def test_rename_map_no_duplicate_targets():
    targets = list(ka.RENAME_MAP.values())
    assert len(targets) == len(set(targets)), "duplicate kha-* targets"


def test_rename_map_all_kha_prefix():
    for kha in ka.RENAME_MAP.values():
        assert kha.startswith("kha-"), f"target missing prefix: {kha}"


def test_rename_map_all_gsd_prefix():
    for gsd in ka.RENAME_MAP.keys():
        assert gsd.startswith("gsd-"), f"source missing prefix: {gsd}"


def test_simple_swap_count():
    # 24 simple + 44 semantic = 68
    assert len(ka.SIMPLE_SWAP) == 24
    assert len(ka.SEMANTIC) == 44


def test_simple_swap_no_overlap_with_semantic():
    overlap = set(ka.SIMPLE_SWAP) & set(ka.SEMANTIC.keys())
    assert overlap == set(), f"overlap between SIMPLE_SWAP and SEMANTIC: {overlap}"


# === rewrite_frontmatter ===

def test_rewrite_frontmatter_replaces_name():
    content = "---\nname: gsd-foo\ndescription: x\n---\n# body\n"
    out = ka.rewrite_frontmatter(content, "kha-bar", "gsd-foo")
    assert "name: kha-bar" in out
    assert "name: gsd-foo" not in out
    assert "description: x" in out
    assert "# body" in out


def test_rewrite_frontmatter_preserves_other_fields():
    content = (
        "---\n"
        "name: gsd-foo\n"
        "description: my description\n"
        "argument-hint: <arg>\n"
        "allowed-tools:\n"
        "  - Read\n"
        "  - Write\n"
        "---\n"
        "# body\n"
    )
    out = ka.rewrite_frontmatter(content, "kha-bar", "gsd-foo")
    assert "argument-hint: <arg>" in out
    assert "- Read" in out
    assert "- Write" in out


def test_rewrite_frontmatter_quoted_name_replaced():
    content = '---\nname: "gsd-foo"\n---\nbody\n'
    out = ka.rewrite_frontmatter(content, "kha-bar", "gsd-foo")
    assert "name: kha-bar" in out


def test_rewrite_frontmatter_no_frontmatter_synthesized():
    content = "# Just a body without frontmatter\n"
    out = ka.rewrite_frontmatter(content, "kha-bar", "gsd-foo")
    assert out.startswith("---\nname: kha-bar\n---\n")


def test_rewrite_frontmatter_no_name_field_inserted():
    content = "---\ndescription: only description\n---\nbody\n"
    out = ka.rewrite_frontmatter(content, "kha-bar", "gsd-foo")
    assert "name: kha-bar" in out
    assert "description: only description" in out


# === add_deprecation_banner ===

def test_deprecation_banner_added_after_frontmatter():
    content = "---\nname: gsd-foo\n---\n# Original body\n"
    out = ka.add_deprecation_banner(content, "gsd-foo", "kha-bar", "2026-07-29")
    # frontmatter intact
    assert out.startswith("---\nname: gsd-foo\n---\n")
    # banner present
    assert "DEPRECATED" in out
    assert "/kha-bar" in out
    assert "2026-07-29" in out
    # original body preserved
    assert "# Original body" in out


def test_deprecation_banner_idempotent():
    content = "---\nname: gsd-foo\n---\n# body\n"
    once = ka.add_deprecation_banner(content, "gsd-foo", "kha-bar", "2026-07-29")
    twice = ka.add_deprecation_banner(once, "gsd-foo", "kha-bar", "2026-07-29")
    assert once.count("DEPRECATED") == 1
    assert twice.count("DEPRECATED") == 1


# === plan_actions / apply_actions integration ===

def test_apply_creates_kha_dir_with_correct_frontmatter():
    with tempfile.TemporaryDirectory() as td:
        skills = Path(td)
        original = ka.SKILLS_DIR
        try:
            ka.SKILLS_DIR = skills
            # Set up a tiny rename map for this test
            test_map = {"gsd-foo": "kha-bar"}
            original_map = ka.RENAME_MAP
            ka.RENAME_MAP = test_map

            # Source
            (skills / "gsd-foo").mkdir()
            (skills / "gsd-foo" / "SKILL.md").write_text(
                "---\nname: gsd-foo\ndescription: src\n---\n# body\n",
                encoding="utf-8",
            )

            created, skipped, failures = ka.apply_actions(False, "2026-07-29")
            assert created == 1
            assert skipped == 0
            assert failures == []

            kha_skill = skills / "kha-bar" / "SKILL.md"
            assert kha_skill.is_file()
            content = kha_skill.read_text(encoding="utf-8")
            assert "name: kha-bar" in content
            assert "name: gsd-foo" not in content
            assert "# body" in content
        finally:
            ka.SKILLS_DIR = original
            ka.RENAME_MAP = original_map


def test_apply_idempotent_skips_unchanged():
    with tempfile.TemporaryDirectory() as td:
        skills = Path(td)
        original = ka.SKILLS_DIR
        original_map = ka.RENAME_MAP
        try:
            ka.SKILLS_DIR = skills
            ka.RENAME_MAP = {"gsd-foo": "kha-bar"}
            (skills / "gsd-foo").mkdir()
            (skills / "gsd-foo" / "SKILL.md").write_text(
                "---\nname: gsd-foo\n---\nbody\n", encoding="utf-8",
            )
            ka.apply_actions(False, "2026-07-29")
            # Second call should skip
            created, skipped, failures = ka.apply_actions(False, "2026-07-29")
            assert created == 0
            assert skipped == 1
        finally:
            ka.SKILLS_DIR = original
            ka.RENAME_MAP = original_map


def test_check_passes_when_all_aliases_present_and_correct():
    with tempfile.TemporaryDirectory() as td:
        skills = Path(td)
        original = ka.SKILLS_DIR
        original_map = ka.RENAME_MAP
        try:
            ka.SKILLS_DIR = skills
            ka.RENAME_MAP = {"gsd-foo": "kha-bar"}
            (skills / "gsd-foo").mkdir()
            (skills / "gsd-foo" / "SKILL.md").write_text(
                "---\nname: gsd-foo\n---\nbody\n", encoding="utf-8",
            )
            ka.apply_actions(False, "2026-07-29")
            ok, errs = ka.check()
            assert ok, f"check failed: {errs}"
        finally:
            ka.SKILLS_DIR = original
            ka.RENAME_MAP = original_map


def test_check_reports_missing_alias():
    with tempfile.TemporaryDirectory() as td:
        skills = Path(td)
        original = ka.SKILLS_DIR
        original_map = ka.RENAME_MAP
        try:
            ka.SKILLS_DIR = skills
            ka.RENAME_MAP = {"gsd-foo": "kha-missing"}
            ok, errs = ka.check()
            assert not ok
            assert any("missing:" in e for e in errs)
        finally:
            ka.SKILLS_DIR = original
            ka.RENAME_MAP = original_map


def main() -> int:
    tests = [
        test_rename_map_has_68_entries,
        test_rename_map_no_duplicate_targets,
        test_rename_map_all_kha_prefix,
        test_rename_map_all_gsd_prefix,
        test_simple_swap_count,
        test_simple_swap_no_overlap_with_semantic,
        test_rewrite_frontmatter_replaces_name,
        test_rewrite_frontmatter_preserves_other_fields,
        test_rewrite_frontmatter_quoted_name_replaced,
        test_rewrite_frontmatter_no_frontmatter_synthesized,
        test_rewrite_frontmatter_no_name_field_inserted,
        test_deprecation_banner_added_after_frontmatter,
        test_deprecation_banner_idempotent,
        test_apply_creates_kha_dir_with_correct_frontmatter,
        test_apply_idempotent_skips_unchanged,
        test_check_passes_when_all_aliases_present_and_correct,
        test_check_reports_missing_alias,
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
