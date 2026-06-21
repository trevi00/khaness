"""Frontmatter field normalization helpers — use-site layer.

parse_frontmatter (lib/frontmatter.py) is locked to return raw strings per
its docstring contract. This module provides use-site normalization for
consumers that need tokenized lists.

Centralized here (not duplicated per-consumer) so YAML list bug fix happens
in one place. History: discovered 2026-05-05 in lib/skill_score.py for
keywords/intent/paths/patterns; later expanded to lib/skill_match_render
(requires field) and handlers/prompt/skill_match (phase field).
"""
from __future__ import annotations

import re


def split_list_field(value: str) -> list[str]:
    """Tokenize a frontmatter field that may use either:
      - whitespace-separated:  `a b c`  (legacy convention)
      - YAML inline list:      `[a, b, c]` or `[a,b,c]`

    Without this, YAML-list skills silently score 0 because `.split()`
    produces `['[a,', 'b,', 'c]']` which never matches clean prompt tokens.

    Returns empty list on empty/blank input.
    """
    s = value.strip()
    if not s:
        return []
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
        return [
            t.strip().rstrip(",").rstrip(";")
            for t in s.split(",")
            if t.strip().strip(",")
        ]
    return s.split()


def has_section(body: str, header: str) -> bool:
    """Detect a `## <header>` markdown section (case-sensitive, exact).

    Centralized here from the byte-identical _has_section copies in
    cli/harness_normalize.py + cli/kha_normalize.py (hygiene Tier-2 dedup).
    """
    return bool(re.search(rf"^##\s+{re.escape(header)}\s*$", body, re.MULTILINE))


def ensure_field(fm_body: str, key: str, value: str) -> str:
    """Add or update a single `key: value` line in a frontmatter body.

    If `key:` already present, replace its first occurrence; else append at the
    end of the frontmatter body (preserving trailing newline structure).
    Centralized from the byte-identical _ensure_field / _ensure_frontmatter_field
    copies in cli/harness_normalize.py + cli/kha_normalize.py.
    """
    pattern = re.compile(rf"^{re.escape(key)}\s*:\s*.*$", re.MULTILINE)
    if pattern.search(fm_body):
        return pattern.sub(f"{key}: {value}", fm_body, count=1)
    return fm_body.rstrip() + f"\n{key}: {value}"
