"""skill_structure_depth — structure-DEPTH bar for skill bodies (M21).

validators/skill_quality_axes.py G4 already gates section PRESENCE (the 5 standard
sections must exist) and G5 gates Gotchas COUNT. This module adds the orthogonal
DEPTH check: a present section must not be HOLLOW (a bare header with no substance).
A skill body can pass G4 with five empty `## ...` headers; the depth bar catches that.

Scope discipline (informed by the M27 finding): this bar is meant for skill
CANDIDATES being promoted (cli.promote_skill / a staged skill-candidates/ body), NOT
the built-in gate-exempt kha-* skills, many of which are intentionally concise
dispatch/status commands. The validator (validators/skill_structure_depth.py) scopes
to skill-candidates/, and promote_skill surfaces gaps at promotion time — so the bar
raises quality on NEW promotions without false-flagging legitimately-thin built-ins.

The standard-section names + min-Gotchas mirror validators.skill_quality_axes; they
are redefined here (NOT imported) because `lib/` must not import `validators/` (layer
adjacency — lib is the bottom layer). tests/test_skill_structure_depth.py asserts they
stay equal to skill_quality_axes's, so drift is caught at the test layer (which may
import both).
"""
from __future__ import annotations

import re

# Mirror of validators.skill_quality_axes.{REQUIRED_SECTIONS, MIN_GOTCHAS} — kept in
# sync by test_skill_structure_depth.test_constants_match_skill_quality_axes (lib may
# not import validators; the test layer cross-checks both).
REQUIRED_SECTIONS: tuple[str, ...] = (
    "## 의사결정 트리",
    "## 가이드",
    "## Gotchas",
    "## 9축 품질 체크",
    "## Source",
)
MIN_GOTCHAS: int = 3

# A non-hollow section needs at least this many substantive content lines (non-blank,
# non-sub-header) after its header. 2 = "more than a one-liner stub".
MIN_SECTION_CONTENT_LINES: int = 2

_NEXT_H2 = re.compile(r"^##\s", re.MULTILINE)
_BULLET = re.compile(r"^\s*(?:[-*]\s|\d+[.)]\s)")


def _section_body(text: str, header: str) -> str | None:
    """The text under `header` up to the next `## ` header, or None if absent."""
    idx = text.find(header)
    if idx < 0:
        return None
    after = text[idx + len(header):]
    m = _NEXT_H2.search(after)
    return after[: m.start()] if m else after


def _content_lines(body: str) -> list[str]:
    """Substantive lines: non-blank and not themselves a markdown header."""
    out = []
    for ln in body.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    return out


def _bullet_count(body: str) -> int:
    return sum(1 for ln in body.splitlines() if _BULLET.match(ln))


def structure_depth_gaps(text: str) -> list[str]:
    """Return a list of structure-depth gaps (empty = passes the bar). Pure.

    A gap is: a missing standard section, a present-but-hollow section (< MIN content
    lines), or a Gotchas section with fewer than MIN_GOTCHAS bullet items (depth, not
    just the G5 substring presence). Order-stable for deterministic output.
    """
    if not isinstance(text, str) or not text.strip():
        return ["empty skill body"]
    gaps: list[str] = []
    for sec in REQUIRED_SECTIONS:
        body = _section_body(text, sec)
        if body is None:
            gaps.append(f"missing section '{sec}'")
            continue
        n = len(_content_lines(body))
        if n < MIN_SECTION_CONTENT_LINES:
            gaps.append(f"hollow section '{sec}' ({n} content line(s) < {MIN_SECTION_CONTENT_LINES})")
    gotchas = _section_body(text, "## Gotchas")
    if gotchas is not None:
        nb = _bullet_count(gotchas)
        if nb < MIN_GOTCHAS:
            gaps.append(f"'## Gotchas' has {nb} item(s) < {MIN_GOTCHAS}")
    return gaps


def passes_depth_bar(text: str) -> bool:
    return not structure_depth_gaps(text)
