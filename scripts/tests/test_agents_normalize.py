#!/usr/bin/env python3
"""Unit tests for cli/agents_normalize.py."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cli import agents_normalize as an  # noqa: E402


def test_model_map_has_24():
    assert len(an.MODEL_MAP) == 24


def test_model_map_uses_only_valid_models():
    for name, model in an.MODEL_MAP.items():
        assert model in an.VALID_MODELS, f"{name} -> {model!r} not in {an.VALID_MODELS}"


def test_model_map_distribution():
    """Sanity: 11 opus / 12 sonnet / 1 haiku per design."""
    counts = {"opus": 0, "sonnet": 0, "haiku": 0, "inherit": 0}
    for model in an.MODEL_MAP.values():
        counts[model] += 1
    assert counts["opus"] == 11, counts
    assert counts["sonnet"] == 12, counts
    assert counts["haiku"] == 1, counts


def test_normalize_inserts_model_after_tools():
    content = (
        "---\n"
        "name: kha-planner\n"
        "description: x\n"
        "tools: Read, Write\n"
        "color: green\n"
        "---\n"
        "# body\n"
    )
    new, changed = an.normalize_agent("kha-planner", content)
    assert changed
    assert "tools: Read, Write\nmodel: opus\ncolor: green" in new


def test_normalize_replaces_existing_model():
    content = (
        "---\n"
        "name: kha-planner\n"
        "model: sonnet\n"
        "tools: Read\n"
        "---\n"
    )
    new, changed = an.normalize_agent("kha-planner", content)
    assert changed
    assert "model: opus" in new
    assert "model: sonnet" not in new


def test_normalize_idempotent_when_correct():
    content = (
        "---\n"
        "name: kha-planner\n"
        "model: opus\n"
        "tools: Read\n"
        "---\n"
    )
    new, changed = an.normalize_agent("kha-planner", content)
    assert not changed
    assert new == content


def test_normalize_unknown_agent_returns_unchanged():
    content = (
        "---\n"
        "name: unknown-agent\n"
        "tools: Read\n"
        "---\n"
    )
    new, changed = an.normalize_agent("unknown-agent", content)
    assert not changed
    assert new == content


def test_normalize_no_frontmatter_returns_unchanged():
    content = "# just markdown\nbody\n"
    new, changed = an.normalize_agent("kha-planner", content)
    assert not changed


def test_normalize_inserts_after_description_when_no_tools():
    content = (
        "---\n"
        "name: kha-planner\n"
        "description: x\n"
        "---\n"
    )
    new, changed = an.normalize_agent("kha-planner", content)
    assert changed
    assert "description: x\nmodel: opus" in new


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
