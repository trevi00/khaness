"""Smoke tests for handlers/prompt/handoff_resume.py — debate-1778987087-311613 D5.

Targets the parse/find/staleness helpers; main() goes through hook stdin/stdout
plumbing and is exercised by lib.io contract elsewhere. Tests here keep scope
narrow to the pure functions so the hook can be wired or unwired without
disturbing the regression suite.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load_module():
    """Load via spec so we don't import handlers.prompt package (which has
    other handler siblings the test does not need)."""
    scripts = Path(__file__).resolve().parent.parent
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    src = scripts / "handlers" / "prompt" / "handoff_resume.py"
    spec = importlib.util.spec_from_file_location("handoff_resume_under_test", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load_module()


def _write_handoff(dir_path: Path, content: str) -> Path:
    p = dir_path / "HANDOFF.md"
    p.write_text(content, encoding="utf-8")
    return p


def test_find_handoff_returns_path_when_present():
    with tempfile.TemporaryDirectory() as td:
        _write_handoff(Path(td), "stub")
        assert _mod.find_handoff(td) is not None


def test_find_handoff_returns_none_when_absent():
    with tempfile.TemporaryDirectory() as td:
        assert _mod.find_handoff(td) is None


def test_find_handoff_returns_none_on_empty_cwd():
    assert _mod.find_handoff("") is None


def test_find_handoff_walks_up_to_parent():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        nested = root / "a" / "b"
        nested.mkdir(parents=True)
        _write_handoff(root, "stub")
        assert _mod.find_handoff(str(nested)) is not None


def test_parse_resume_pointer_valid_block():
    text = (
        "# HANDOFF\n\n```yaml\n"
        "last_completed: cycle-99\n"
        "next_action:\n"
        "  cycle: cycle-100\n"
        "  decision_id: D1\n"
        "```\n"
    )
    info = _mod.parse_resume_pointer(text)
    assert info["has_block"] is True
    assert info["has_last"] is True
    assert info["has_next"] is True
    assert info["cycle"] == "cycle-100"
    assert info["decision"] == "D1"


def test_parse_resume_pointer_no_block():
    info = _mod.parse_resume_pointer("# HANDOFF\n\nNo YAML block here.\n")
    assert info["has_block"] is False


def test_parse_resume_pointer_partial_block():
    # Block exists but only last_completed (no next_action body)
    text = (
        "# HANDOFF\n\n```yaml\n"
        "last_completed: cycle-99\n"
        "```\n"
    )
    info = _mod.parse_resume_pointer(text)
    assert info["has_block"] is True
    assert info["has_last"] is True
    # next_action regex requires the key + a body — absent here
    assert info["has_next"] is False


def test_is_stale_returns_false_for_fresh_file():
    with tempfile.TemporaryDirectory() as td:
        p = _write_handoff(Path(td), "stub")
        stale, days = _mod.is_stale(p)
        assert stale is False
        assert days == 0


def test_is_stale_returns_true_when_mtime_old():
    import os
    with tempfile.TemporaryDirectory() as td:
        p = _write_handoff(Path(td), "stub")
        old = (datetime.now(timezone.utc) - timedelta(days=10)).timestamp()
        os.utime(p, (old, old))
        stale, days = _mod.is_stale(p)
        assert stale is True
        assert days >= 8


def test_build_status_advisory_includes_cycle_and_decision():
    info = {"has_block": True, "has_last": True, "has_next": True,
            "cycle": "cycle-100", "decision": "D5"}
    out = _mod.build_status_advisory(info, age_days=2, path=Path("/tmp/HANDOFF.md"))
    assert "<handoff-status" in out
    assert "cycle-100" in out
    assert "D5" in out
    assert "age_days: 2" in out
    assert "</handoff-status>" in out


def test_build_warn_advisory_lists_missing_fields():
    info = {"has_block": True, "has_last": True, "has_next": False}
    out = _mod.build_warn_advisory(Path("/tmp/HANDOFF.md"), info)
    assert "<handoff-warn" in out
    assert "next_action" in out
    assert "</handoff-warn>" in out


TESTS = [
    test_find_handoff_returns_path_when_present,
    test_find_handoff_returns_none_when_absent,
    test_find_handoff_returns_none_on_empty_cwd,
    test_find_handoff_walks_up_to_parent,
    test_parse_resume_pointer_valid_block,
    test_parse_resume_pointer_no_block,
    test_parse_resume_pointer_partial_block,
    test_is_stale_returns_false_for_fresh_file,
    test_is_stale_returns_true_when_mtime_old,
    test_build_status_advisory_includes_cycle_and_decision,
    test_build_warn_advisory_lists_missing_fields,
]


def main() -> int:
    failed = 0
    for t in TESTS:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  [ERROR] {t.__name__}: {type(e).__name__}: {e}")
    print(f"[{'FAIL' if failed else 'OK'}] {len(TESTS) - failed}/{len(TESTS)} tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
