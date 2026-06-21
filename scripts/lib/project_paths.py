"""project_paths — walk-up directory discovery helpers.

Three pure functions used across handlers (context_load, reviewer, init):
- `walk_up(cwd, predicate, max_levels)`: generic walk-up.
- `find_claude_dir(cwd, *, content_files, max_levels)`: nearest `.claude/`,
  optionally gated on content files (plan/context/checklist/tech-stack).
- `find_project_root(cwd, markers, max_levels)`: nearest dir holding a
  language-marker file (package.json, pom.xml, pubspec.yaml, ...).

Replaces duplicated walk-up loops in handlers/prompt/context_load.py and
handlers/post_tool/reviewer.py. session/init.py keeps its own loop because
it needs multiple WATCH_PATTERNS per level (different cohesion).
"""
from __future__ import annotations

import os
from typing import Callable, Sequence


PROJECT_MARKERS: tuple[str, ...] = (
    "package.json", "pom.xml", "build.gradle", "build.gradle.kts",
    "pubspec.yaml", "Cargo.toml", "go.mod", "pyproject.toml",
    "requirements.txt", "setup.py", "composer.json",
)

DEFAULT_MAX_LEVELS: int = 5


def walk_up(
    cwd: str,
    predicate: Callable[[str], bool],
    *,
    max_levels: int = DEFAULT_MAX_LEVELS,
) -> str | None:
    """Walk upward from `cwd` calling `predicate(dir)`. Return first match
    or None. Stops when `dirname(current) == current` (filesystem root).

    `max_levels` is the cap on iterations including `cwd` itself.
    """
    current = os.path.normpath(cwd)
    for _ in range(max_levels):
        if predicate(current):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


def find_claude_dir(
    cwd: str,
    *,
    content_files: Sequence[str] = (),
    max_levels: int = DEFAULT_MAX_LEVELS,
) -> str | None:
    """Find nearest `.claude/` directory.

    If `content_files` is non-empty, the directory must contain at least one
    of those files (relative to .claude/). Otherwise just `.claude/` existing
    is enough — used by reviewer.py which only needs the marker.
    """
    def _matches(d: str) -> bool:
        claude_dir = os.path.join(d, ".claude")
        if not os.path.isdir(claude_dir):
            return False
        if not content_files:
            return True
        for fname in content_files:
            if os.path.isfile(os.path.join(claude_dir, fname)):
                return True
        return False

    base = walk_up(cwd, _matches, max_levels=max_levels)
    return os.path.join(base, ".claude") if base else None


def find_project_root(
    cwd: str,
    *,
    markers: Sequence[str] = PROJECT_MARKERS,
    max_levels: int = DEFAULT_MAX_LEVELS,
) -> str | None:
    """Walk up looking for any of `markers` (file existence). Returns the
    directory holding the marker, or None.
    """
    def _has_marker(d: str) -> bool:
        for m in markers:
            if os.path.isfile(os.path.join(d, m)):
                return True
        return False

    return walk_up(cwd, _has_marker, max_levels=max_levels)
