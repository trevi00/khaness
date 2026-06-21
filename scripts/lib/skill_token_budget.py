"""skill_token_budget — context budget enforcement for activated skills (Round 6 W2 P1).

Extracted from handlers/prompt/skill_match.py. Pure functions: takes a sorted
list of (score, name, dims, content) tuples + budget cap, returns truncated
list + truncation flag. No I/O, no side effects.

## Strategy
- First (highest-scored) skill always keeps full content.
- For lower-scored skills: try level-1 truncation (decision tree + gotchas)
  then level-2 (decision tree only). Drop entirely if still over budget.
"""
from __future__ import annotations

from typing import Sequence

from .frontmatter import extract_section


# Default budget — caller can override via apply_token_budget(skills, max_chars=N)
DEFAULT_MAX_CONTEXT_CHARS = 8000


def truncate_skill_content(content: str, level: int) -> str:
    """Truncate skill content based on budget level.

    level 1: Keep only `의사결정 트리` + `Gotchas` sections.
    level 2: Keep only `의사결정 트리` section.
    """
    decision_tree = extract_section(content, "의사결정 트리")
    if level == 2:
        return decision_tree if decision_tree else ""

    # level 1: decision tree + gotchas
    gotchas = extract_section(content, "Gotchas")
    parts = [s for s in [decision_tree, gotchas] if s]
    return "\n\n".join(parts) if parts else ""


def apply_token_budget(
    matched_skills: Sequence[tuple[float, str, dict, str]],
    max_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> tuple[list[tuple[float, str, dict, str]], bool]:
    """Apply token budget to matched skills.

    Skills are already sorted by score (highest first).
    Returns (skill_entries, was_truncated) where skill_entries may have content
    truncated or skills dropped entirely to fit within max_chars.
    """
    if not matched_skills:
        return list(matched_skills), False

    # Within budget with full content?
    total_chars = sum(len(content) for _, _, _, content in matched_skills)
    if total_chars <= max_chars:
        return list(matched_skills), False

    # Highest-scored skill keeps full content.
    result: list[tuple[float, str, dict, str]] = [matched_skills[0]]
    remaining_budget = max_chars - len(matched_skills[0][3])
    was_truncated = False

    # Lower skills: try level 1 → level 2 → drop.
    for score, name, dims, content in matched_skills[1:]:
        if remaining_budget >= len(content):
            result.append((score, name, dims, content))
            remaining_budget -= len(content)
            continue

        truncated = truncate_skill_content(content, level=1)
        if truncated and remaining_budget >= len(truncated):
            result.append((score, name, dims, truncated))
            remaining_budget -= len(truncated)
            was_truncated = True
            continue

        truncated2 = truncate_skill_content(content, level=2)
        if truncated2 and remaining_budget >= len(truncated2):
            result.append((score, name, dims, truncated2))
            remaining_budget -= len(truncated2)
            was_truncated = True
            continue

        # Skip this skill entirely — over budget even at level 2.
        was_truncated = True

    return result, was_truncated
