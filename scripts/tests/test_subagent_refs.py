#!/usr/bin/env python3
"""Unit tests for validators/subagent_refs.py and cli/fix_subagent_refs.py."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from validators import subagent_refs as sr  # noqa: E402
from cli import fix_subagent_refs as fsr  # noqa: E402


def _make_repo(root: Path, agents: list[str]) -> None:
    (root / "agents").mkdir()
    for name in agents:
        (root / "agents" / f"{name}.md").write_text(f"# {name}\n", encoding="utf-8")


def test_validator_passes_clean(tmp_path):
    _make_repo(tmp_path, ["kha-executor", "kha-planner"])
    skill = tmp_path / "skills" / "k" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "Spawn via Task(subagent_type=\"kha-executor\")\n", encoding="utf-8"
    )
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        # capture stdout
        import io
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            sr.main()
        finally:
            sys.stdout = old
        out = buf.getvalue()
        assert "[PASS]" in out, out
        assert "[FAIL]" not in out, out
    finally:
        os.chdir(cwd)


def test_validator_detects_dangling(tmp_path):
    _make_repo(tmp_path, ["kha-executor"])
    skill = tmp_path / "skills" / "k" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "Spawn via Task(subagent_type=gsd-deleted)\n", encoding="utf-8"
    )
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        import io
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            sr.main()
        finally:
            sys.stdout = old
        out = buf.getvalue()
        assert "[FAIL]" in out, out
        assert "gsd-deleted" in out, out
    finally:
        os.chdir(cwd)


def test_validator_skips_builtins(tmp_path):
    _make_repo(tmp_path, ["kha-executor"])
    skill = tmp_path / "skills" / "k" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "Spawn via Task(subagent_type=general-purpose)\n", encoding="utf-8"
    )
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        import io
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            sr.main()
        finally:
            sys.stdout = old
        out = buf.getvalue()
        assert "[PASS]" in out, out
    finally:
        os.chdir(cwd)


def test_validator_skips_template_placeholder(tmp_path):
    """Trailing-hyphen captures (e.g. `kha-{agent}` template) must be ignored."""
    _make_repo(tmp_path, ["kha-executor"])
    skill = tmp_path / "skills" / "k" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        'Use `subagent_type: "kha-{agent}"` — placeholder.\n', encoding="utf-8"
    )
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        import io
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            sr.main()
        finally:
            sys.stdout = old
        out = buf.getvalue()
        assert "[PASS]" in out, out
    finally:
        os.chdir(cwd)


# === fix_subagent_refs ===

def test_fixer_rewrites_when_kha_exists():
    text = "Task(subagent_type=\"gsd-executor\")"
    new, replaced, untouched = fsr._rewrite_text(text, {"kha-executor"})
    assert replaced == 1
    assert untouched == []
    assert "kha-executor" in new
    assert "gsd-executor" not in new


def test_fixer_leaves_unmapped_untouched():
    text = "Task(subagent_type=\"gsd-orphan\")"
    new, replaced, untouched = fsr._rewrite_text(text, {"kha-executor"})
    assert replaced == 0
    assert untouched == ["gsd-orphan"]
    assert "gsd-orphan" in new


def test_fixer_idempotent():
    text = "Task(subagent_type=\"kha-executor\")"
    new, replaced, _ = fsr._rewrite_text(text, {"kha-executor"})
    assert replaced == 0
    assert new == text


def test_fixer_preserves_quote_style():
    """Single quotes, double quotes, and bare must all survive rewrite."""
    cases = [
        ('subagent_type="gsd-executor"', "kha-executor"),
        ("subagent_type='gsd-executor'", "kha-executor"),
        ("subagent_type=gsd-executor", "kha-executor"),
        ("subagent_type: gsd-executor", "kha-executor"),
    ]
    for text, expected_name in cases:
        new, replaced, _ = fsr._rewrite_text(text, {expected_name})
        assert replaced == 1, f"{text!r} not rewritten"
        assert expected_name in new, f"{text!r} → {new!r}"


def main() -> int:
    import inspect
    failures = []
    test_count = 0
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
