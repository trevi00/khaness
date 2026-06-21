#!/usr/bin/env python3
"""Tests for lib/harness_audit.py — deterministic IMPACT-axis evidence."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _make_home(td: Path) -> Path:
    h = td / "home"
    (h / "commands").mkdir(parents=True)
    (h / "commands" / "a.md").write_text("x", encoding="utf-8")
    (h / "commands" / "b.md").write_text("x", encoding="utf-8")
    (h / "agents").mkdir()
    (h / "agents" / "x.md").write_text("x", encoding="utf-8")
    (h / "skills" / "_common").mkdir(parents=True)
    (h / "skills" / "_common" / "s.md").write_text("x", encoding="utf-8")
    (h / "brain" / "l1").mkdir(parents=True)
    (h / "brain" / "l1" / "insight-index.jsonl").write_text('{"id":"a"}\n{"id":"b"}\n', encoding="utf-8")
    (h / "CLAUDE.md").write_text("# rules\n" * 50, encoding="utf-8")
    (h / "HANDOFF.md").write_text("state", encoding="utf-8")
    (h / "settings.json").write_text(json.dumps({
        "permissions": {"allow": ["Bash(ls)", "Read"], "deny": ["Bash(rm -rf /)"]},
        "hooks": {"PostToolUse": [{"x": 1}], "Stop": [{"y": 2}]},
    }), encoding="utf-8")
    return h


def test_evidence_axes_present_and_measured():
    from lib.harness_audit import impact_evidence
    with tempfile.TemporaryDirectory() as td:
        h = _make_home(Path(td))
        ev = impact_evidence(home=h)
        assert set(ev) == {"Intent", "Memory", "Planning", "Authority", "Control", "Tools"}
        assert ev["Intent"]["claude_md_exists"] is True and ev["Intent"]["claude_md_bytes"] > 0
        assert ev["Intent"]["commands_count"] == 2
        assert ev["Memory"]["brain_l1_lines"] == 2
        assert ev["Planning"]["handoff_exists"] is True
        assert ev["Authority"]["allow_rules"] == 2 and ev["Authority"]["deny_rules"] == 1
        assert ev["Control"]["hook_events_registered"] == 2
        assert ev["Tools"]["agents_count"] == 1 and ev["Tools"]["skills_count"] >= 1


def test_failsoft_empty_home():
    from lib.harness_audit import impact_evidence
    with tempfile.TemporaryDirectory() as td:
        empty = Path(td) / "nothing"
        empty.mkdir()
        ev = impact_evidence(home=empty)
        assert ev["Intent"]["claude_md_exists"] is False
        assert ev["Intent"]["commands_count"] == 0
        assert ev["Authority"]["allow_rules"] == 0


def test_render_lists_all_axes():
    from lib.harness_audit import render_evidence
    with tempfile.TemporaryDirectory() as td:
        h = _make_home(Path(td))
        out = render_evidence(home=h)
        for ax in ("Intent", "Memory", "Planning", "Authority", "Control", "Tools"):
            assert ax in out


def main() -> int:
    tests = [
        test_evidence_axes_present_and_measured,
        test_failsoft_empty_home,
        test_render_lists_all_axes,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            import traceback
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failed += 1
    if failed == 0:
        print(f"[OK] {len(tests)} tests passed")
        return 0
    print(f"[FAIL] {failed}/{len(tests)} tests failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
