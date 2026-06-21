#!/usr/bin/env python3
"""Unit tests for cli/kha_migrate.py — agents rename + reference rewrite + delete."""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cli import kha_migrate as km  # noqa: E402


def _fake_home(td: Path):
    """Set CLAUDE_HOME-derived paths to a tempdir for isolated testing."""
    saved = (km.CLAUDE_HOME, km.AGENTS_DIR, km.SKILLS_DIR, km.HARNESS_GUIDE,
             km.COMMANDS_DIR)
    km.CLAUDE_HOME = td
    km.AGENTS_DIR = td / "agents"
    km.SKILLS_DIR = td / "skills"
    km.HARNESS_GUIDE = td / "HARNESS-GUIDE.md"
    km.COMMANDS_DIR = td / "commands"
    return saved


def _restore(saved):
    km.CLAUDE_HOME, km.AGENTS_DIR, km.SKILLS_DIR, km.HARNESS_GUIDE, km.COMMANDS_DIR = saved


def test_substitution_map_includes_all_agents():
    sub = km.build_substitution_map()
    for name in km.AGENT_NAMES:
        assert f"gsd-{name}" in sub
        assert sub[f"gsd-{name}"] == f"kha-{name}"


def test_substitution_map_includes_skill_renames():
    from cli.kha_alias import RENAME_MAP
    sub = km.build_substitution_map()
    for gsd, kha in RENAME_MAP.items():
        assert sub[gsd] == kha


def test_replace_regex_longest_first_no_partial_match():
    rx = km._build_replace_regex({
        "gsd-list-phase-assumptions": "kha-phase-assumptions",
        "gsd-list-workspaces":         "kha-list-workspaces",
        "gsd-plan":                    "kha-plan",
    })
    text = "/gsd-list-phase-assumptions and /gsd-list-workspaces"
    matches = rx.findall(text)
    # Both long names must match, never the short prefix
    assert "gsd-list-phase-assumptions" in matches
    assert "gsd-list-workspaces" in matches
    assert "gsd-list" not in matches


def test_replace_regex_word_boundary():
    rx = km._build_replace_regex({"gsd-foo": "kha-foo"})
    text = "the /gsd-foo command and gsd-foobar variant"
    matches = rx.findall(text)
    # `gsd-foo` matches but NOT inside `gsd-foobar` (followed by 'b' = identifier char)
    assert matches == ["gsd-foo"]


def test_phase_agents_renames_file_and_frontmatter():
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        saved = _fake_home(td_path)
        try:
            (td_path / "agents").mkdir()
            (td_path / "agents" / "gsd-planner.md").write_text(
                "---\nname: gsd-planner\ndescription: x\n---\nbody\n",
                encoding="utf-8",
            )
            saved_names = km.AGENT_NAMES
            km.AGENT_NAMES = ["planner"]
            try:
                renamed, skipped, failures = km.phase_agents(apply=True)
                assert renamed == 1
                assert failures == []
                kha_path = td_path / "agents" / "kha-planner.md"
                assert kha_path.is_file()
                assert not (td_path / "agents" / "gsd-planner.md").exists()
                content = kha_path.read_text(encoding="utf-8")
                assert "name: kha-planner" in content
                assert "description: x" in content
            finally:
                km.AGENT_NAMES = saved_names
        finally:
            _restore(saved)


def test_phase_agents_idempotent_skips_already_renamed():
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        saved = _fake_home(td_path)
        try:
            (td_path / "agents").mkdir()
            (td_path / "agents" / "kha-planner.md").write_text(
                "---\nname: kha-planner\n---\nbody\n", encoding="utf-8",
            )
            saved_names = km.AGENT_NAMES
            km.AGENT_NAMES = ["planner"]
            try:
                renamed, skipped, failures = km.phase_agents(apply=True)
                assert renamed == 0
                assert skipped == 1
                assert failures == []
            finally:
                km.AGENT_NAMES = saved_names
        finally:
            _restore(saved)


def test_phase_references_replaces_in_kha_skill_body():
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        saved = _fake_home(td_path)
        try:
            kha_dir = td_path / "skills" / "kha-foo"
            kha_dir.mkdir(parents=True)
            (kha_dir / "SKILL.md").write_text(
                "---\nname: kha-foo\n---\n"
                "Spawns gsd-planner agent.\n"
                "See also /gsd-discuss-phase for context.\n",
                encoding="utf-8",
            )
            ch, unch, failures, per_file = km.phase_references(apply=True)
            assert failures == []
            assert ch == 1
            content = (kha_dir / "SKILL.md").read_text(encoding="utf-8")
            assert "kha-planner" in content
            assert "kha-clarify-phase" in content  # gsd-discuss-phase → kha-clarify-phase
            assert "gsd-planner" not in content
            assert "gsd-discuss-phase" not in content
        finally:
            _restore(saved)


def test_phase_references_excludes_kha_alias_module():
    """The kha_alias.py source file must NOT be rewritten — it's the substitution source of truth."""
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        saved = _fake_home(td_path)
        try:
            # Set up a scripts/cli/kha_alias.py with gsd-* string literals
            scripts_cli = td_path / "scripts" / "cli"
            scripts_cli.mkdir(parents=True)
            kha_alias = scripts_cli / "kha_alias.py"
            kha_alias.write_text(
                'SEMANTIC = {"discuss-phase": "clarify-phase"}\n'
                '# gsd-discuss-phase becomes kha-clarify-phase\n',
                encoding="utf-8",
            )
            # Phase B should not touch this file
            ch, unch, failures, per_file = km.phase_references(apply=True)
            content = kha_alias.read_text(encoding="utf-8")
            assert "gsd-discuss-phase" in content, "kha_alias.py should be excluded"
        finally:
            _restore(saved)


def test_count_remaining_zero_after_full_rewrite():
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        saved = _fake_home(td_path)
        try:
            kha_dir = td_path / "skills" / "kha-foo"
            kha_dir.mkdir(parents=True)
            (kha_dir / "SKILL.md").write_text(
                "---\nname: kha-foo\n---\nuses gsd-planner\n",
                encoding="utf-8",
            )
            assert km.count_remaining_references() > 0
            km.phase_references(apply=True)
            assert km.count_remaining_references() == 0
        finally:
            _restore(saved)


def test_phase_delete_refuses_when_references_remain():
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        saved = _fake_home(td_path)
        try:
            (td_path / "skills").mkdir()
            (td_path / "skills" / "gsd-foo").mkdir()
            kha_dir = td_path / "skills" / "kha-foo"
            kha_dir.mkdir()
            (kha_dir / "SKILL.md").write_text(
                "---\nname: kha-foo\n---\nuses gsd-planner still\n",
                encoding="utf-8",
            )
            deleted, _, failures = km.phase_delete(apply=True, force=False)
            assert deleted == 0
            assert any("refusing to delete" in f for f in failures)
            assert (td_path / "skills" / "gsd-foo").is_dir()  # not deleted
        finally:
            _restore(saved)


def test_phase_delete_proceeds_with_force():
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        saved = _fake_home(td_path)
        try:
            (td_path / "skills").mkdir()
            (td_path / "skills" / "gsd-foo").mkdir()
            (td_path / "skills" / "gsd-foo" / "SKILL.md").write_text("body", encoding="utf-8")
            deleted, _, failures = km.phase_delete(apply=True, force=True)
            assert deleted == 1
            assert failures == []
            assert not (td_path / "skills" / "gsd-foo").exists()
        finally:
            _restore(saved)


def main() -> int:
    tests = [
        test_substitution_map_includes_all_agents,
        test_substitution_map_includes_skill_renames,
        test_replace_regex_longest_first_no_partial_match,
        test_replace_regex_word_boundary,
        test_phase_agents_renames_file_and_frontmatter,
        test_phase_agents_idempotent_skips_already_renamed,
        test_phase_references_replaces_in_kha_skill_body,
        test_phase_references_excludes_kha_alias_module,
        test_count_remaining_zero_after_full_rewrite,
        test_phase_delete_refuses_when_references_remain,
        test_phase_delete_proceeds_with_force,
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
