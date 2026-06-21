"""YAML-ish frontmatter parsing for skill and agent files.

Ported from scripts/skill-matcher.py. Minimal parser (no PyYAML dep)
that handles 'key: value' one-per-line frontmatter between `---` fences.
"""
from __future__ import annotations

import re
from pathlib import Path


def parse_frontmatter(filepath: str | Path) -> tuple[dict[str, str], str] | None:
    """Return (frontmatter_dict, body_text) or None if no valid frontmatter.

    YAML contract (minimal subset):
      - Fenced between two `---` markers at file start.
      - One `key: value` per line (split on first `:`).
      - No nesting, no lists, no quoted multilines, no anchors/aliases.
      - Whitespace around key and value is stripped.
      - Returns the raw dict — NO normalization, NO defaults, NO schema validation.
        Callers needing fallbacks MUST `setdefault()` at the use-site
        (e.g. `meta.setdefault("name", path.stem)` in skill_match.py).

    Returns:
      - (meta, body) on valid frontmatter
      - None if file unreadable, missing leading `---`, or malformed fence

    Single source of truth: skill_match.py imports this — do NOT duplicate.
    """
    try:
        text = Path(filepath).read_text(encoding="utf-8")
    except Exception:
        return None

    if not text.startswith("---"):
        return None

    parts = text.split("---", 2)
    if len(parts) < 3:
        return None

    meta: dict[str, str] = {}
    for line in parts[1].strip().split("\n"):
        if ":" in line:
            key, val = line.split(":", 1)
            meta[key.strip()] = val.strip()

    return meta, parts[2].strip()


def extract_section(content: str, heading: str) -> str:
    """Extract a `## heading` section from markdown; returns '' if absent."""
    pattern = re.compile(
        r"(^##\s+" + re.escape(heading) + r".*?)(?=\n##\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(content)
    return m.group(1).strip() if m else ""
