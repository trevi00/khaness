#!/usr/bin/env python3
"""Tests for lib.validators.cross_ref (v15.19 G).

Coverage:
  check_summary_vs_prompt:
    - malformed envelope / short summary / empty prompt / short prompt → SKIPPED
    - low overlap → CLEAN
    - overlap >= 70% → SUSPICIOUS_PLAGIARIZED
    - overlap >= 90% → STRONG_PLAGIARIZED
  check_cross_file_consensus:
    - < 2 files → SKIPPED
    - all files balanced overlap → CLEAN
    - top file dominates, others < half → SUSPICIOUS_CHERRY_PICKED
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.validators.cross_ref import (  # noqa: E402
    CrossRefVerdict,
    check_cross_file_consensus,
    check_summary_vs_prompt,
)


def _write(path: Path, content: str) -> str:
    path.write_text(content, encoding="utf-8")
    return str(path)


# ---- summary_vs_prompt SKIPPED branches ----

def test_summary_vs_prompt_malformed_skipped():
    assert check_summary_vs_prompt(None, "x").verdict == CrossRefVerdict.SKIPPED
    assert check_summary_vs_prompt({}, "x").verdict == CrossRefVerdict.SKIPPED


def test_summary_vs_prompt_short_summary_skipped():
    env = {"summary": "a b"}  # 0 tokens >= 3 chars
    assert check_summary_vs_prompt(env, "alpha beta gamma delta epsilon zeta").verdict == CrossRefVerdict.SKIPPED


def test_summary_vs_prompt_empty_prompt_skipped():
    env = {"summary": "alpha beta gamma delta epsilon"}
    assert check_summary_vs_prompt(env, "").verdict == CrossRefVerdict.SKIPPED


def test_summary_vs_prompt_short_prompt_skipped():
    """prompt < 5 tokens → SKIPPED (false positive avoidance)."""
    env = {"summary": "alpha beta gamma delta epsilon"}
    assert check_summary_vs_prompt(env, "tiny").verdict == CrossRefVerdict.SKIPPED


# ---- summary_vs_prompt overlap classification ----

def test_low_overlap_is_clean():
    env = {"summary": "alpha beta gamma delta epsilon"}
    prompt = "completely different words present here and elsewhere everywhere"
    r = check_summary_vs_prompt(env, prompt)
    assert r.verdict == CrossRefVerdict.CLEAN


def test_high_overlap_70_is_suspicious_plagiarized():
    """3 of 5 = 60% < 70%; 4 of 5 = 80% → SUSPICIOUS."""
    env = {"summary": "alpha beta gamma delta epsilon"}
    prompt = "alpha beta gamma delta foo bar baz qux quux"
    r = check_summary_vs_prompt(env, prompt)
    assert r.verdict == CrossRefVerdict.SUSPICIOUS_PLAGIARIZED
    assert r.overlap_ratio >= 0.70


def test_perfect_overlap_is_strong_plagiarized():
    env = {"summary": "alpha beta gamma delta epsilon"}
    prompt = "alpha beta gamma delta epsilon zeta eta theta iota"
    r = check_summary_vs_prompt(env, prompt)
    assert r.verdict == CrossRefVerdict.STRONG_PLAGIARIZED
    assert r.overlap_ratio == 1.0


# ---- cross_file_consensus ----

def test_single_file_is_skipped():
    with tempfile.TemporaryDirectory() as td:
        path = _write(Path(td) / "f.txt", "x y z")
        env = {
            "summary": "alpha beta gamma delta epsilon",
            "evidence": [{"file_path": path}],
        }
        assert check_cross_file_consensus(env).verdict == CrossRefVerdict.SKIPPED


def test_no_evidence_is_skipped():
    env = {"summary": "alpha beta gamma delta epsilon"}
    assert check_cross_file_consensus(env).verdict == CrossRefVerdict.SKIPPED


def test_balanced_overlap_is_clean():
    """3 files all matching summary equally → CLEAN."""
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        same_content = "alpha beta gamma delta epsilon"
        paths = [_write(td_path / f"f{i}.txt", same_content) for i in range(3)]
        env = {
            "summary": same_content,
            "evidence": [{"file_path": p} for p in paths],
        }
        r = check_cross_file_consensus(env)
        assert r.verdict == CrossRefVerdict.CLEAN


def test_top_file_dominates_is_cherry_picked():
    """1 file matches strongly, others empty/unrelated → CHERRY_PICKED."""
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        rich = _write(td_path / "rich.txt", "alpha beta gamma delta epsilon zeta eta")
        empty = _write(td_path / "empty1.txt", "completely unrelated text here")
        empty2 = _write(td_path / "empty2.txt", "another irrelevant content block")
        env = {
            "summary": "alpha beta gamma delta epsilon",
            "evidence": [
                {"file_path": rich},
                {"file_path": empty},
                {"file_path": empty2},
            ],
        }
        r = check_cross_file_consensus(env)
        assert r.verdict == CrossRefVerdict.SUSPICIOUS_CHERRY_PICKED
        assert r.per_file_overlap[rich] >= 0.5


TESTS = [
    test_summary_vs_prompt_malformed_skipped,
    test_summary_vs_prompt_short_summary_skipped,
    test_summary_vs_prompt_empty_prompt_skipped,
    test_summary_vs_prompt_short_prompt_skipped,
    test_low_overlap_is_clean,
    test_high_overlap_70_is_suspicious_plagiarized,
    test_perfect_overlap_is_strong_plagiarized,
    test_single_file_is_skipped,
    test_no_evidence_is_skipped,
    test_balanced_overlap_is_clean,
    test_top_file_dominates_is_cherry_picked,
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
