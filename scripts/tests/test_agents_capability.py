#!/usr/bin/env python3
"""Unit tests for cli/agents_capability.py."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cli import agents_capability as ac  # noqa: E402


def test_detect_planning_only():
    body = "Read .planning/STATE.md to load context."
    assert ac.detect_expected_paths(body) == [".planning/"]


def test_detect_get_shit_done_only():
    body = "Use $HOME/.claude/get-shit-done/bin/gsd-tools.cjs."
    assert ac.detect_expected_paths(body) == ["$HOME/.claude/get-shit-done/"]


def test_detect_both():
    body = "Read .planning/PROJECT.md and run $HOME/.claude/get-shit-done/bin/x."
    paths = ac.detect_expected_paths(body)
    assert ".planning/" in paths
    assert "$HOME/.claude/get-shit-done/" in paths


def test_detect_tilde_form():
    body = "Source from ~/.claude/get-shit-done/templates/."
    assert "$HOME/.claude/get-shit-done/" in ac.detect_expected_paths(body)


def test_detect_none():
    body = "Read README.md and config.json."
    assert ac.detect_expected_paths(body) == []


def test_format_paths_empty():
    assert ac._format_paths([]) == "[]"


def test_format_paths_quoted():
    assert ac._format_paths([".planning/"]) == '[".planning/"]'


def test_normalize_inserts_after_model():
    content = (
        "---\n"
        "name: kha-test\n"
        "description: x\n"
        "tools: Read\n"
        "model: opus\n"
        "---\n"
        "Read .planning/STATE.md\n"
    )
    new, paths, changed = ac.normalize_agent(content)
    assert changed
    assert paths == [".planning/"]
    assert "model: opus\nexpects_paths:" in new


def test_normalize_idempotent_after_apply():
    content = (
        "---\n"
        "name: kha-test\n"
        "tools: Read\n"
        "model: opus\n"
        'expects_paths: [".planning/"]\n'
        "---\n"
        "Read .planning/STATE.md\n"
    )
    new, paths, changed = ac.normalize_agent(content)
    assert not changed
    assert paths == [".planning/"]


def test_normalize_updates_when_path_added():
    content = (
        "---\n"
        "name: kha-test\n"
        "tools: Read\n"
        'expects_paths: [".planning/"]\n'
        "---\n"
        "Read .planning/STATE.md and ~/.claude/get-shit-done/bin/x\n"
    )
    new, paths, changed = ac.normalize_agent(content)
    assert changed
    assert paths == ["$HOME/.claude/get-shit-done/", ".planning/"]


def test_normalize_strips_stale_when_no_paths():
    content = (
        "---\n"
        "name: kha-test\n"
        "tools: Read\n"
        'expects_paths: [".planning/"]\n'
        "---\n"
        "Generic body, no path conventions.\n"
    )
    new, paths, changed = ac.normalize_agent(content)
    assert changed
    assert paths == []
    assert "expects_paths" not in new


def main() -> int:
    failures = []
    test_count = 0
    for name, obj in list(globals().items()):
        if not name.startswith("test_"):
            continue
        test_count += 1
        try:
            obj()
            print(f"  [OK] {name}")
        except AssertionError as e:
            failures.append((name, str(e)))
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:
            failures.append((name, repr(e)))
            print(f"  [ERR]  {name}: {e!r}")
    if failures:
        print(f"\n{len(failures)} test(s) failed")
        return 1
    print(f"\n[OK] {test_count} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
