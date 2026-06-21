"""changelog_io — per-project changelog.md append/read helpers (Round 6 W2 P1).

Extracted from handlers/post_tool/reviewer.py. Maintains a project-local
`<.claude>/changelog.md` of file modifications (CREATE/MODIFY) for review
context. Append-only with size cap; oldest entries trimmed when exceeded.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


CHANGELOG_MAX_RECENT = 20
CHANGELOG_MAX_LINES = 500  # Trim changelog if it exceeds this


def _is_harness_home(claude_dir: str | Path) -> bool:
    """True when claude_dir resolves to the harness HOME/.claude (not a project).

    `find_claude_dir(cwd)` returns `HOME/.claude` when cwd=HOME (no project
    .claude/ traversal hit). In that mode, file edits across the entire
    home tree (e.g. ~/Downloads/some-project/...) get logged into the
    harness changelog — cross-project pollution.

    Per wave 7 후속 14: skip auto-append when claude_dir IS the harness home.
    Project-scoped claude_dir (cwd inside a project with its own .claude/)
    continues to log normally.
    """
    try:
        from .paths import CLAUDE_HOME
        resolved = Path(str(claude_dir)).resolve()
        return resolved == CLAUDE_HOME.resolve()
    except Exception:
        return False


def log_change(claude_dir: str | Path | None, tool_name: str, file_path: str) -> None:
    """Append a change entry to <claude_dir>/changelog.md.

    No-op when:
    - claude_dir is None/empty
    - claude_dir == HOME/.claude (harness home — cross-project pollution guard,
      wave 7 후속 14)
    - filesystem ops fail (fail-open)
    """
    if not claude_dir:
        return
    if _is_harness_home(claude_dir):
        return  # cross-project pollution guard

    changelog_path = os.path.join(str(claude_dir), "changelog.md")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rel_path = (file_path or "").replace("\\", "/")
    # Derive basename from the NORMALIZED path, not os.path.basename — the latter
    # is platform-dependent (on POSIX a backslash is an ordinary char, so a
    # Windows-style "src\\a\\b.py" would not be split, leaking separators).
    basename = rel_path.rsplit("/", 1)[-1]

    action = {
        "Write": "CREATE",
        "Edit": "MODIFY",
        "MultiEdit": "MODIFY",
    }.get(tool_name, "CHANGE")

    entry = f"- `[{now}]` **{action}** `{rel_path}` ({basename})\n"

    try:
        existing = ""
        if os.path.isfile(changelog_path):
            with open(changelog_path, "r", encoding="utf-8") as f:
                existing = f.read()

        if not existing.strip():
            existing = "# Change Log\n\n"

        # Insert new entry after header.
        lines = existing.split("\n", 2)
        if len(lines) >= 2:
            header = lines[0] + "\n" + lines[1] + "\n"
            rest = lines[2] if len(lines) > 2 else ""
        else:
            header = existing + "\n"
            rest = ""

        new_content = header + entry + rest

        # Trim if too long.
        content_lines = new_content.split("\n")
        if len(content_lines) > CHANGELOG_MAX_LINES:
            new_content = "\n".join(content_lines[:CHANGELOG_MAX_LINES])
            new_content += "\n\n...(older entries trimmed)\n"

        with open(changelog_path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except Exception:
        pass  # fail-open


def get_recent_changes(claude_dir: str | Path | None, max_entries: int = CHANGELOG_MAX_RECENT) -> str:
    """Read recent entries from <claude_dir>/changelog.md.

    Returns joined string of changelog bullet lines or empty string on missing/error.
    """
    if not claude_dir:
        return ""
    changelog_path = os.path.join(str(claude_dir), "changelog.md")
    if not os.path.isfile(changelog_path):
        return ""
    try:
        with open(changelog_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        changes = [l.rstrip() for l in lines if l.startswith("- ")]
        return "\n".join(changes[:max_entries]) if changes else ""
    except Exception:
        return ""
