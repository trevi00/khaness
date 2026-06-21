#!/usr/bin/env python3
"""Unit tests for lib/skill_match_render.py — render helpers."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import skill_match_render as smr  # noqa: E402


# --- detect_tool_routing_hints ---

def test_detect_routing_korean_find():
    hints = smr.detect_tool_routing_hints("파일 검색 좀 해줘")
    assert any("Glob" in h for h in hints)


def test_detect_routing_english_grep():
    hints = smr.detect_tool_routing_hints("search for token")
    assert any("Grep" in h for h in hints)


def test_detect_routing_korean_read():
    hints = smr.detect_tool_routing_hints("파일을 읽어줘")
    assert any("Read" in h for h in hints)


def test_detect_routing_korean_edit():
    hints = smr.detect_tool_routing_hints("파일 수정 좀")
    assert any("Edit" in h for h in hints)


def test_detect_routing_no_match():
    assert smr.detect_tool_routing_hints("hello world") == []


def test_detect_routing_one_per_rule():
    """Multiple signals in one rule should produce only one hint per rule."""
    hints = smr.detect_tool_routing_hints("파일 검색 좀, 파일을 찾아줘")
    glob_hints = [h for h in hints if "Glob" in h]
    assert len(glob_hints) == 1


# --- build_sensor_reminder ---

def test_sensor_reminder_implement():
    reminders = smr.build_sensor_reminder({"implement"})
    assert len(reminders) == 1
    assert "테스트" in reminders[0]


def test_sensor_reminder_review():
    reminders = smr.build_sensor_reminder({"review"})
    assert len(reminders) == 1
    assert "정적 분석" in reminders[0]


def test_sensor_reminder_both_phases():
    reminders = smr.build_sensor_reminder({"implement", "review"})
    assert len(reminders) == 2


def test_sensor_reminder_other_phase_no_match():
    assert smr.build_sensor_reminder({"plan"}) == []


def test_sensor_reminder_empty():
    assert smr.build_sensor_reminder(set()) == []


# --- build_phase_guidance ---

def test_phase_guidance_empty_returns_empty_string():
    assert smr.build_phase_guidance(set(), []) == ""


def test_phase_guidance_implement_includes_korean_label():
    out = smr.build_phase_guidance({"implement"}, [])
    assert "구현 (Implement)" in out


def test_phase_guidance_unknown_phase_uses_phase_name_as_label():
    """Unknown phase: name falls back to the phase string itself, guidance empty."""
    out = smr.build_phase_guidance({"unknown_phase"}, [])
    assert "unknown_phase:" in out


def test_phase_guidance_sorted_alphabetically():
    """Multiple phases concatenated in sorted order."""
    out = smr.build_phase_guidance({"review", "implement"}, [])
    impl_pos = out.find("구현 (Implement)")
    rev_pos = out.find("검토/리뷰 (Review)")
    assert impl_pos != -1
    assert rev_pos != -1
    assert impl_pos < rev_pos  # 'implement' < 'review' alphabetically


def test_phase_guidance_matched_skills_unused():
    """Result is independent of matched_skills argument."""
    a = smr.build_phase_guidance({"implement"}, [])
    b = smr.build_phase_guidance({"implement"}, [("x", "y", "z", "w")])
    assert a == b


# --- build_cross_references ---

def test_cross_refs_empty_inputs():
    assert smr.build_cross_references([], {}) == []


def test_cross_refs_recommends_required_skill():
    matched = [(5, "auth.md", [], None)]
    all_meta = {
        "auth.md": {"requires": "session", "keywords": ""},
        "session.md": {"keywords": "session token cookie state extra"},
    }
    recs = smr.build_cross_references(matched, all_meta)
    assert len(recs) == 1
    origin, suggested, kws = recs[0]
    assert origin == "auth.md"
    assert suggested == "session.md"
    # First 3 keywords joined
    assert kws == "session token cookie"


def test_cross_refs_skips_already_matched():
    """If the required skill is already matched, don't re-suggest it."""
    matched = [(5, "auth.md", [], None), (3, "session.md", [], None)]
    all_meta = {
        "auth.md": {"requires": "session", "keywords": ""},
        "session.md": {"keywords": "session"},
    }
    recs = smr.build_cross_references(matched, all_meta)
    assert recs == []


def test_cross_refs_dedupe_across_matches():
    """Two matched skills both requiring the same skill → suggested once."""
    matched = [(5, "a.md", [], None), (4, "b.md", [], None)]
    all_meta = {
        "a.md": {"requires": "shared", "keywords": ""},
        "b.md": {"requires": "shared", "keywords": ""},
        "shared.md": {"keywords": "common util"},
    }
    recs = smr.build_cross_references(matched, all_meta)
    assert len(recs) == 1
    # First matched wins (a.md)
    assert recs[0][0] == "a.md"


def test_cross_refs_skips_unknown_required():
    """If `required` skill doesn't exist in all_meta, no recommendation."""
    matched = [(5, "auth.md", [], None)]
    all_meta = {
        "auth.md": {"requires": "missing", "keywords": ""},
    }
    assert smr.build_cross_references(matched, all_meta) == []


# --- PROMPT_TOOL_ROUTING_HINTS sanity ---

def test_prompt_tool_routing_hints_shape():
    """4 rules — Glob / Grep / Read / Edit."""
    assert len(smr.PROMPT_TOOL_ROUTING_HINTS) == 4
    tools = {"Glob", "Grep", "Read", "Edit"}
    seen = set()
    for _, msg in smr.PROMPT_TOOL_ROUTING_HINTS:
        for t in tools:
            if t in msg:
                seen.add(t)
                break
    assert seen == tools


def main() -> int:
    failures = []
    test_count = 0
    for name, obj in list(globals().items()):
        if not name.startswith("test_"):
            continue
        test_count += 1
        try:
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
