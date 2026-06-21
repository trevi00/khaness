#!/usr/bin/env python3
"""Unit tests for lib/changelog_io.py."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import changelog_io as cl  # noqa: E402


def test_log_change_creates_file(tmp_path):
    cl.log_change(str(tmp_path), "Write", "src/foo.py")
    f = tmp_path / "changelog.md"
    assert f.is_file()
    content = f.read_text(encoding="utf-8")
    assert "CREATE" in content
    assert "src/foo.py" in content
    assert "# Change Log" in content


def test_log_change_appends_top(tmp_path):
    cl.log_change(str(tmp_path), "Write", "src/a.py")
    cl.log_change(str(tmp_path), "Edit", "src/b.py")
    content = (tmp_path / "changelog.md").read_text(encoding="utf-8")
    # b is more recent → should appear before a
    assert content.index("src/b.py") < content.index("src/a.py")


def test_log_change_action_mapping(tmp_path):
    cl.log_change(str(tmp_path), "Write", "a.py")
    cl.log_change(str(tmp_path), "Edit", "b.py")
    cl.log_change(str(tmp_path), "MultiEdit", "c.py")
    cl.log_change(str(tmp_path), "Bash", "d.py")
    content = (tmp_path / "changelog.md").read_text(encoding="utf-8")
    assert "**CREATE**" in content
    assert "**MODIFY**" in content
    assert "**CHANGE**" in content


def test_log_change_no_op_on_none():
    """No exception when claude_dir is None."""
    cl.log_change(None, "Write", "x.py")
    cl.log_change("", "Write", "x.py")


def test_log_change_normalizes_backslash_path(tmp_path):
    cl.log_change(str(tmp_path), "Edit", "src\\windows\\path.py")
    content = (tmp_path / "changelog.md").read_text(encoding="utf-8")
    assert "src/windows/path.py" in content
    assert "src\\windows" not in content


def test_get_recent_changes_returns_empty_when_missing():
    with tempfile.TemporaryDirectory() as td:
        assert cl.get_recent_changes(td) == ""


def test_get_recent_changes_returns_bullets_only(tmp_path):
    f = tmp_path / "changelog.md"
    f.write_text(
        "# Change Log\n\n"
        "- `[2026-04-30 12:00:00]` **CREATE** `a.py`\n"
        "Some non-bullet line\n"
        "- `[2026-04-30 12:01:00]` **EDIT** `b.py`\n",
        encoding="utf-8",
    )
    result = cl.get_recent_changes(str(tmp_path))
    assert "a.py" in result
    assert "b.py" in result
    assert "Some non-bullet line" not in result


def test_get_recent_changes_respects_limit(tmp_path):
    f = tmp_path / "changelog.md"
    body = "\n".join(f"- entry {i}" for i in range(50))
    f.write_text("# Change Log\n\n" + body, encoding="utf-8")
    result = cl.get_recent_changes(str(tmp_path), max_entries=5)
    lines = result.split("\n")
    assert len(lines) == 5


def test_log_change_skips_when_claude_dir_is_harness_home():
    """wave 7 후속 14 — cross-project pollution guard.

    `find_claude_dir(cwd=HOME)` returns CLAUDE_HOME itself. Edits to files
    outside any project (under HOME tree) would otherwise pollute the
    global harness changelog. Guard MUST fire on this specific path."""
    from lib.paths import CLAUDE_HOME
    # Snapshot the actual harness changelog before/after — guarded call
    # must NOT modify it.
    cl_path = CLAUDE_HOME / "changelog.md"
    before = cl_path.read_bytes() if cl_path.exists() else None
    cl.log_change(str(CLAUDE_HOME), "Edit", "/some/cross-project/file.py")
    after = cl_path.read_bytes() if cl_path.exists() else None
    assert before == after, "harness changelog must be UNCHANGED when guard fires"


def test_log_change_proceeds_for_project_claude_dir(tmp_path):
    """Inverse of the harness-home guard — project-scoped .claude/ logs normally."""
    project_claude = tmp_path / "myproj" / ".claude"
    project_claude.mkdir(parents=True)
    cl.log_change(str(project_claude), "Write", "src/foo.py")
    f = project_claude / "changelog.md"
    assert f.is_file()
    assert "src/foo.py" in f.read_text(encoding="utf-8")


def test_is_harness_home_predicate():
    """Predicate boundary check — CLAUDE_HOME matches, sub-dirs and other paths don't."""
    from lib.paths import CLAUDE_HOME
    assert cl._is_harness_home(str(CLAUDE_HOME)) is True
    assert cl._is_harness_home(str(CLAUDE_HOME / "scripts")) is False
    assert cl._is_harness_home("/nonexistent/path/.claude") is False
    assert cl._is_harness_home("") is False  # bad input → safe False


def test_log_change_trims_when_over_max(tmp_path):
    """Beyond CHANGELOG_MAX_LINES, oldest entries trimmed."""
    f = tmp_path / "changelog.md"
    # Pre-fill with > MAX lines
    body = "\n".join(f"- entry {i}" for i in range(cl.CHANGELOG_MAX_LINES + 50))
    f.write_text("# Change Log\n\n" + body, encoding="utf-8")
    cl.log_change(str(tmp_path), "Write", "new.py")
    content = (tmp_path / "changelog.md").read_text(encoding="utf-8")
    line_count = content.count("\n")
    assert line_count <= cl.CHANGELOG_MAX_LINES + 5  # allow trim message slack
    assert "older entries trimmed" in content


def main() -> int:
    failures = []
    test_count = 0
    import inspect
    for name, obj in list(globals().items()):
        if not name.startswith("test_"):
            continue
        test_count += 1
        sig = inspect.signature(obj)
        try:
            if "tmp_path" in sig.parameters:
                with tempfile.TemporaryDirectory() as td:
                    obj(Path(td))
            else:
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
