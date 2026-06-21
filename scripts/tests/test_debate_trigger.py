#!/usr/bin/env python3
"""Unit tests for handlers/prompt/debate_trigger.py — P5c graph-enriched advisory."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from handlers.prompt import debate_trigger as dt  # noqa: E402


def _setup_skill_graph(state_dir: Path, nodes: list[dict]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = {"skill_count": len(nodes), "edges": [], "nodes": nodes, "subtrees": []}
    (state_dir / "skill-graph.json").write_text(json.dumps(payload), encoding="utf-8")


def _patch_state_dir(monkeypatch_state: Path):
    """Swap lib.paths.STATE_DIR for the duration of a test. Returns saved value."""
    from lib import paths
    saved = paths.STATE_DIR
    paths.STATE_DIR = monkeypatch_state
    return saved


def _restore_state_dir(saved: Path) -> None:
    from lib import paths
    paths.STATE_DIR = saved


def _reset_cache():
    """Skill graph is module-cached — reset between tests."""
    dt._SKILL_GRAPH_CACHE = None


# === _top_relevant_skills ===

def test_top_relevant_skills_keyword_overlap():
    with tempfile.TemporaryDirectory() as td:
        saved = _patch_state_dir(Path(td))
        try:
            _reset_cache()
            _setup_skill_graph(Path(td), [
                {"name": "react", "description": "React patterns",
                 "keywords": ["react", "useEffect", "hooks"]},
                {"name": "spring", "description": "Spring backend",
                 "keywords": ["spring", "controller", "service"]},
                {"name": "nothing", "description": "irrelevant",
                 "keywords": ["zzz"]},
            ])
            results = dt._top_relevant_skills("React useEffect 무한루프 fix", n=3)
            names = [r[0] for r in results]
            assert "react" in names
            assert "spring" not in names
        finally:
            _restore_state_dir(saved)
            _reset_cache()


def test_top_relevant_skills_empty_graph_returns_empty():
    with tempfile.TemporaryDirectory() as td:
        saved = _patch_state_dir(Path(td) / "missing")
        try:
            _reset_cache()
            results = dt._top_relevant_skills("anything", n=3)
            assert results == []
        finally:
            _restore_state_dir(saved)
            _reset_cache()


def test_top_relevant_skills_caps_at_n():
    with tempfile.TemporaryDirectory() as td:
        saved = _patch_state_dir(Path(td))
        try:
            _reset_cache()
            nodes = [
                {"name": f"skill{i}", "description": "x",
                 "keywords": ["common"]}
                for i in range(10)
            ]
            _setup_skill_graph(Path(td), nodes)
            results = dt._top_relevant_skills("common usage", n=3)
            assert len(results) == 3
        finally:
            _restore_state_dir(saved)
            _reset_cache()


def test_top_relevant_skills_short_keywords_ignored():
    """Keywords len <= 1 must not contribute (avoids noise from 'a', 'i', etc.)."""
    with tempfile.TemporaryDirectory() as td:
        saved = _patch_state_dir(Path(td))
        try:
            _reset_cache()
            _setup_skill_graph(Path(td), [
                {"name": "noisy", "description": "x", "keywords": ["a", "i", "n"]},
            ])
            results = dt._top_relevant_skills("a single character prompt", n=3)
            assert results == []
        finally:
            _restore_state_dir(saved)
            _reset_cache()


# === _recent_debate_count ===

def test_recent_debate_count_counts_mtime_in_window():
    with tempfile.TemporaryDirectory() as td:
        saved = _patch_state_dir(Path(td))
        try:
            debates = Path(td) / "debates"
            debates.mkdir()
            # Recent
            (debates / "debate-fresh").mkdir()
            # Stale (mtime older than window)
            old = debates / "debate-old"
            old.mkdir()
            old_time = time.time() - (30 * 86400)
            os.utime(old, (old_time, old_time))

            assert dt._recent_debate_count(window_days=14) == 1
        finally:
            _restore_state_dir(saved)


def test_recent_debate_count_no_debates_dir_returns_zero():
    with tempfile.TemporaryDirectory() as td:
        saved = _patch_state_dir(Path(td))
        try:
            assert dt._recent_debate_count() == 0
        finally:
            _restore_state_dir(saved)


# === _build_advisory ===

def test_build_advisory_contains_required_sections():
    with tempfile.TemporaryDirectory() as td:
        saved = _patch_state_dir(Path(td))
        try:
            _reset_cache()
            _setup_skill_graph(Path(td), [
                {"name": "alpha", "description": "Alpha guide",
                 "keywords": ["arch", "design"]},
            ])
            (Path(td) / "debates" / "d1").mkdir(parents=True)
            advisory = dt._build_advisory("architecture redesign")
            assert "<harness-debate-suggestion>" in advisory
            assert "/harness-debate" in advisory
            assert "alpha" in advisory  # top relevant skill surfaced
            assert "최근 14일" in advisory
            assert "</harness-debate-suggestion>" in advisory
        finally:
            _restore_state_dir(saved)
            _reset_cache()


def test_build_advisory_no_relevant_skills_skips_section():
    """When no skill keyword overlaps, the 'related skills' section is omitted."""
    with tempfile.TemporaryDirectory() as td:
        saved = _patch_state_dir(Path(td))
        try:
            _reset_cache()
            _setup_skill_graph(Path(td), [])  # empty graph
            advisory = dt._build_advisory("architecture redesign")
            assert "관련 스킬 후보" not in advisory
            # but the base advisory is always there
            assert "/harness-debate" in advisory
        finally:
            _restore_state_dir(saved)
            _reset_cache()


# === _is_system_reinvocation (telemetry FP guard, 2026-06-02) ===

def test_system_reinvocation_detected():
    assert dt._is_system_reinvocation("<task-notification> <task-id>abc</task-id> done")
    assert dt._is_system_reinvocation("   \n<task-notification>leading ws</task-notification>")


def test_system_reinvocation_false_for_user_prompt():
    assert not dt._is_system_reinvocation("아키텍처 리팩토링 구조 설계 어떻게 하지")
    assert not dt._is_system_reinvocation("normal question about <task-notification> mention mid-text")


def test_task_notification_with_design_keyword_gated_out():
    """The FP this guard fixes: a task-notification whose summary carries a design
    keyword matches the RAW matcher, but must be gated out as system-origin so it
    is never logged/advised as strict-design intent."""
    from lib.phase_detector import is_strict_design_intent
    fp_prompt = "<task-notification> ... 아키텍처 리팩토링 구조 설계 완료 ..."
    # raw matcher fires (design keywords present) ...
    assert is_strict_design_intent(fp_prompt)
    # ... but the system-origin guard catches it, so the gated result is False.
    system_origin = dt._is_system_reinvocation(fp_prompt)
    assert system_origin
    gated_strict = is_strict_design_intent(fp_prompt) and not system_origin
    assert gated_strict is False


def main() -> int:
    tests = [
        test_top_relevant_skills_keyword_overlap,
        test_top_relevant_skills_empty_graph_returns_empty,
        test_top_relevant_skills_caps_at_n,
        test_top_relevant_skills_short_keywords_ignored,
        test_recent_debate_count_counts_mtime_in_window,
        test_recent_debate_count_no_debates_dir_returns_zero,
        test_build_advisory_contains_required_sections,
        test_build_advisory_no_relevant_skills_skips_section,
        test_system_reinvocation_detected,
        test_system_reinvocation_false_for_user_prompt,
        test_task_notification_with_design_keyword_gated_out,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    if failed == 0:
        print(f"[OK] {len(tests)} tests passed")
        return 0
    print(f"[FAIL] {failed}/{len(tests)} tests failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
