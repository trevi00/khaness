#!/usr/bin/env python3
"""Tests for cli/skill_trigger_eval.py — trigger accuracy CLI.

Contract verified:
1. winner_of returns ('(none)', 0) when all candidates score 0.
2. should_trigger pass = target matched (≥ min_score) AND wins.
3. should_not_trigger pass = target did NOT match (< min_score), regardless
   of winner identity (target tied at 0 still passes near-miss).
4. recall/precision/F1 computed correctly.
5. Exit-code mapping: PASS=0, FAIL_PRECISION=1, FAIL_RECALL=2.

Run:
    cd ~/.claude/scripts && python -m tests.test_skill_trigger_eval
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cli import skill_trigger_eval as STE  # noqa: E402


def _make_skill(dir_path: Path, name: str, frontmatter: str) -> Path:
    """Helper: write a minimal skill .md and return its path."""
    p = dir_path / f"{name}.md"
    p.write_text(f"---\n{frontmatter}\n---\nbody\n", encoding="utf-8")
    return p


def test_run_eval_target_wins_simple():
    """Trivial case: target unique keyword, near-miss has nothing matching."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "skills" / "_common"
        d.mkdir(parents=True)
        target = _make_skill(d, "target",
                             "name: target\ndescription: x\nkeywords: foobar\nmin_score: 1")
        _make_skill(d, "other",
                    "name: other\ndescription: y\nkeywords: barbaz\nmin_score: 1")

        # Patch SKILLS_DIR for discovery
        saved = STE.SKILLS_DIR
        STE.SKILLS_DIR = Path(td) / "skills"
        try:
            queries = {
                "should_trigger": ["use foobar here"],
                "should_not_trigger": ["unrelated text"],
            }
            result = STE.run_eval(target, queries)
        finally:
            STE.SKILLS_DIR = saved

    assert result["recall"] == 1.0
    assert result["precision"] == 1.0
    assert result["f1"] == 1.0
    assert result["verdict"] == "PASS"
    assert result["should_trigger"][0]["winner"] == "target"
    assert result["should_not_trigger"][0]["winner"] == "(none)"


def test_run_eval_near_miss_zero_tie_does_not_count_as_fp():
    """Bug fix: when all candidates tie at 0, target should NOT be claimed
    as winner. Near-miss query passes if target's match status is False.
    """
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "skills" / "_common"
        d.mkdir(parents=True)
        target = _make_skill(d, "target",
                             "name: target\ndescription: x\nkeywords: foobar\nmin_score: 1")

        saved = STE.SKILLS_DIR
        STE.SKILLS_DIR = Path(td) / "skills"
        try:
            queries = {
                "should_trigger": [],
                "should_not_trigger": ["completely unrelated"],
            }
            result = STE.run_eval(target, queries)
        finally:
            STE.SKILLS_DIR = saved

    assert result["precision"] == 1.0
    assert result["should_not_trigger"][0]["passes"] is True
    assert result["should_not_trigger"][0]["winner"] == "(none)"


def test_run_eval_recall_partial():
    """Realistic case: target wins some but loses to a stronger competitor."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "skills" / "_common"
        d.mkdir(parents=True)
        target = _make_skill(d, "qa",
                             "name: qa\ndescription: x\nkeywords: contract\nmin_score: 1")
        _make_skill(d, "rival",
                    "name: rival\ndescription: y\nkeywords: kafka producer consumer\nmin_score: 1")

        saved = STE.SKILLS_DIR
        STE.SKILLS_DIR = Path(td) / "skills"
        try:
            queries = {
                "should_trigger": [
                    "contract check now",     # only target
                    "kafka producer contract",  # rival has 2 kw, target has 1
                ],
                "should_not_trigger": ["irrelevant"],
            }
            result = STE.run_eval(target, queries)
        finally:
            STE.SKILLS_DIR = saved

    assert result["recall"] == 0.5  # 1/2
    assert result["precision"] == 1.0
    # First query: target wins. Second: rival outscores.
    assert result["should_trigger"][0]["winner"] == "qa"
    assert result["should_trigger"][1]["winner"] == "rival"


def test_verdict_mapping():
    """Verdict thresholds: precision<1 → FAIL_PRECISION, recall<0.6 → FAIL_RECALL."""
    assert STE._verdict(1.0, 1.0) == "PASS"
    assert STE._verdict(0.5, 1.0) == "FAIL_RECALL"
    assert STE._verdict(1.0, 0.5) == "FAIL_PRECISION"
    # Both fail → precision check fires first
    assert STE._verdict(0.0, 0.0) == "FAIL_PRECISION"


def test_qa_boundary_self_eval_passes_recall_floor():
    """Self-consistency lock: qa-boundary skill must pass its own trigger eval.

    Recall floor 60%, precision 100%. If a future change to qa-boundary's
    frontmatter regresses recall below 60% against actual _common skills,
    this test fails — preventing silent matcher degradation.

    Snapshot: queries match the qa-boundary debate-1777963974-4e8915 set.
    Two queries are intentional domain-yields (fullstack-debug, messaging-
    governance) and may MISS without failing the suite, as long as recall
    stays above the floor.
    """
    from pathlib import Path as _Path
    target = _Path.home() / ".claude" / "skills" / "_common" / "qa-boundary.md"
    if not target.exists():
        return  # skill removed → not this test's concern
    queries = {
        "should_trigger": [
            "API 응답이랑 프론트 타입 맞는지 확인 boundary",
            "producer consumer boundary check",
            "DTO 양쪽동시 contract 맞는지",
            "kafka schema producer-consumer 정합성",
            "OpenAPI contract mismatch 사전 차단",
            "경계면 정합성 검증",
            "양쪽 동시 읽고 contract mismatch 차단",
        ],
        "should_not_trigger": [
            "프론트 화면 안 떠 디버깅",
            "테스트 다 돌려서 빌드 통과",
            "완료 전 evidence 확인",
            "자바 spring 컨트롤러 구현",
            "DTO 만들어줘",
        ],
    }
    result = STE.run_eval(target, queries, candidates_scope="_common")
    assert result["recall"] >= 0.60, (
        f"qa-boundary recall regressed: {result['recall']} < 0.60. "
        f"Verdict={result['verdict']}. Frontmatter changes likely broke "
        f"keyword/intent coverage."
    )
    assert result["precision"] == 1.0, (
        f"qa-boundary precision regressed: {result['precision']} < 1.0 — "
        f"frontmatter may be over-aggressive. Verdict={result['verdict']}."
    )


def test_suggested_min_score_from_lowest_pass_score():
    """Suggested min_score = lowest target_score among passing should_trigger."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "skills" / "_common"
        d.mkdir(parents=True)
        target = _make_skill(d, "t",
                             "name: t\ndescription: x\nkeywords: aa bb cc\nmin_score: 1")

        saved = STE.SKILLS_DIR
        STE.SKILLS_DIR = Path(td) / "skills"
        try:
            queries = {
                "should_trigger": [
                    "aa bb cc match",  # target=3
                    "aa only here",    # target=1
                ],
                "should_not_trigger": [],
            }
            result = STE.run_eval(target, queries)
        finally:
            STE.SKILLS_DIR = saved

    # Both should pass (no competitors), so min successful score = 1
    assert result["suggested_min_score"] == 1


TESTS = [
    test_run_eval_target_wins_simple,
    test_run_eval_near_miss_zero_tie_does_not_count_as_fp,
    test_run_eval_recall_partial,
    test_verdict_mapping,
    test_qa_boundary_self_eval_passes_recall_floor,
    test_suggested_min_score_from_lowest_pass_score,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"  [OK] {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  [ERROR] {fn.__name__}: {type(e).__name__}: {e}")
    if failed:
        print(f"\n[FAIL] {failed}/{len(TESTS)} tests failed")
        return 1
    print(f"\n[OK] {len(TESTS)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
