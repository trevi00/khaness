#!/usr/bin/env python3
"""Unit tests for lib/skill_token_budget.py — extracted from skill_match.py W2 P1."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import skill_token_budget as stb  # noqa: E402


# === truncate_skill_content ===

def test_truncate_level2_keeps_only_decision_tree():
    content = (
        "## 의사결정 트리\n"
        "decision content here\n\n"
        "## Gotchas\n"
        "gotchas content here\n\n"
        "## Other\n"
        "other content\n"
    )
    result = stb.truncate_skill_content(content, level=2)
    assert "decision content" in result
    assert "gotchas content" not in result
    assert "other content" not in result


def test_truncate_level1_keeps_decision_and_gotchas():
    content = (
        "## 의사결정 트리\n"
        "decision content\n\n"
        "## Gotchas\n"
        "gotchas content\n\n"
        "## Other\n"
        "other content\n"
    )
    result = stb.truncate_skill_content(content, level=1)
    assert "decision content" in result
    assert "gotchas content" in result
    assert "other content" not in result


def test_truncate_no_section_returns_empty():
    content = "## Random Section\nrandom\n"
    assert stb.truncate_skill_content(content, level=2) == ""
    assert stb.truncate_skill_content(content, level=1) == ""


# === apply_token_budget ===

def _skill(score, name, content_len):
    return (score, name, {}, "x" * content_len)


def test_empty_input_returns_empty():
    result, truncated = stb.apply_token_budget([])
    assert result == []
    assert truncated is False


def test_within_budget_returns_unchanged():
    skills = [_skill(10, "a", 1000), _skill(8, "b", 2000), _skill(5, "c", 500)]
    result, truncated = stb.apply_token_budget(skills, max_chars=8000)
    assert len(result) == 3
    assert truncated is False
    assert result == skills


def test_first_skill_always_full_even_over_budget():
    """Highest-scored skill keeps full content even if it alone exceeds budget."""
    skills = [_skill(10, "a", 9000)]
    result, truncated = stb.apply_token_budget(skills, max_chars=8000)
    assert len(result) == 1
    assert len(result[0][3]) == 9000  # full content preserved


def test_lower_skill_truncated_to_level1():
    decision = "## 의사결정 트리\n" + "d" * 500 + "\n"
    gotchas = "## Gotchas\n" + "g" * 500 + "\n"
    other = "## Other\n" + "o" * 5000 + "\n"
    full = decision + "\n" + gotchas + "\n" + other
    skills = [_skill(10, "a", 6000), (8, "b", {}, full)]
    result, truncated = stb.apply_token_budget(skills, max_chars=8000)
    assert len(result) == 2
    assert truncated is True
    # Second skill should be truncated (level 1 = decision + gotchas, ~1000 chars)
    assert len(result[1][3]) < len(full)
    assert "의사결정 트리" in result[1][3]


def test_skill_dropped_when_no_budget_for_level2():
    decision = "## 의사결정 트리\n" + "d" * 500 + "\n"
    full = decision + "\n## Other\n" + "o" * 5000 + "\n"
    skills = [_skill(10, "a", 7900), (8, "b", {}, full)]
    # Budget 8000, first skill takes 7900, only 100 budget left for second (which is min ~500)
    result, truncated = stb.apply_token_budget(skills, max_chars=8000)
    assert truncated is True
    # Second skill dropped entirely
    assert len(result) == 1
    assert result[0][1] == "a"


def test_multiple_lower_skills_truncated_progressively():
    decision = "## 의사결정 트리\n" + "d" * 200 + "\n"
    gotchas = "## Gotchas\n" + "g" * 200 + "\n"
    full = decision + "\n" + gotchas + "\n## Other\n" + "o" * 5000 + "\n"
    skills = [
        _skill(10, "a", 4000),
        (8, "b", {}, full),
        (6, "c", {}, full),
    ]
    result, truncated = stb.apply_token_budget(skills, max_chars=8000)
    assert truncated is True
    # All 3 retained, lower 2 truncated
    assert len(result) == 3
    assert "의사결정 트리" in result[1][3]
    assert "의사결정 트리" in result[2][3]


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
