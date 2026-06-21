#!/usr/bin/env python3
"""Tests for lib.validators.semantic (v15.13).

Coverage:
  - malformed/empty envelope → SKIPPED
  - summary too short → SKIPPED
  - no evidence → SKIPPED
  - all file_paths missing → SKIPPED + errors recorded
  - empty file → no signal, breakdown 0 ratio (worst stays SKIPPED if no signal)
  - perfect overlap → CLEAN
  - partial overlap (> 20%) → CLEAN
  - tiny overlap (< 20%, > 0) → SUSPICIOUS
  - zero overlap → STRONG_SUSPICION
  - worst-case aggregation across entries
  - tokenizer: ≥ 3 char alphanumeric only, lowercase normalized, set dedup
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.validators.semantic import (  # noqa: E402
    SUSPICION_THRESHOLD,
    SemanticResult,
    SemanticVerdict,
    check,
)


def _write(path: Path, content: str) -> str:
    path.write_text(content, encoding="utf-8")
    return str(path)


# ---- SKIPPED paths ----

def test_malformed_envelope_is_skipped():
    assert check(None).verdict == SemanticVerdict.SKIPPED
    assert check("not-a-dict").verdict == SemanticVerdict.SKIPPED
    assert check({}).verdict == SemanticVerdict.SKIPPED


def test_summary_too_short_is_skipped():
    # Only 2 tokens — below DEFAULT_MIN_SUMMARY_TOKENS=3
    env = {"summary": "one two", "evidence": [{"file_path": "x"}]}
    assert check(env).verdict == SemanticVerdict.SKIPPED


def test_no_evidence_is_skipped():
    env = {"summary": "alpha beta gamma delta epsilon"}
    assert check(env).verdict == SemanticVerdict.SKIPPED


def test_missing_files_only_is_skipped_with_errors():
    env = {
        "summary": "alpha beta gamma delta epsilon",
        "evidence": [
            {"file_path": "C:/no/such/file__semantic_test_1.txt"},
            {"file_path": "C:/no/such/file__semantic_test_2.txt"},
        ],
    }
    r = check(env)
    assert r.verdict == SemanticVerdict.SKIPPED
    assert len(r.errors) == 2
    assert all("file not found" in e for e in r.errors)


# ---- Overlap classification ----

def test_perfect_overlap_is_clean():
    with tempfile.TemporaryDirectory() as td:
        path = _write(Path(td) / "f.txt", "alpha beta gamma delta epsilon zeta")
        env = {
            "summary": "alpha beta gamma delta epsilon",
            "evidence": [{"file_path": path}],
        }
        r = check(env)
        assert r.verdict == SemanticVerdict.CLEAN
        assert r.evidence_breakdown[0].overlap_ratio == 1.0


def test_partial_above_threshold_is_clean():
    """3 of 5 summary tokens present in file = 0.60 → CLEAN."""
    with tempfile.TemporaryDirectory() as td:
        path = _write(Path(td) / "f.txt", "alpha beta gamma other words here")
        env = {
            "summary": "alpha beta gamma delta epsilon",
            "evidence": [{"file_path": path}],
        }
        r = check(env)
        assert r.verdict == SemanticVerdict.CLEAN


def test_tiny_overlap_above_zero_is_suspicious():
    """1 of 5 summary tokens = 0.20 — at exact threshold, classified CLEAN.

    Below threshold (0 of 5 → STRONG; >0 but <20% → SUSPICIOUS).
    Need a summary with more tokens so 1 match falls under 20%.
    """
    with tempfile.TemporaryDirectory() as td:
        # 10 summary tokens, only 1 match → 0.10 ratio
        path = _write(Path(td) / "f.txt", "alpha")
        env = {
            "summary": "alpha bravo charlie delta echo foxtrot golf hotel india juliet",
            "evidence": [{"file_path": path}],
        }
        r = check(env)
        assert r.verdict == SemanticVerdict.SUSPICIOUS


def test_zero_overlap_is_strong_suspicion():
    with tempfile.TemporaryDirectory() as td:
        path = _write(Path(td) / "f.txt", "completely unrelated words here zero overlap")
        env = {
            "summary": "alpha beta gamma delta epsilon",
            "evidence": [{"file_path": path}],
        }
        r = check(env)
        assert r.verdict == SemanticVerdict.STRONG_SUSPICION
        assert r.evidence_breakdown[0].overlap_ratio == 0.0


# ---- Worst-case aggregation ----

def test_worst_case_across_entries():
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        clean = _write(td_path / "clean.txt", "alpha beta gamma delta epsilon")
        bad = _write(td_path / "bad.txt", "completely different words present here")
        env = {
            "summary": "alpha beta gamma delta epsilon",
            "evidence": [{"file_path": clean}, {"file_path": bad}],
        }
        r = check(env)
        assert r.verdict == SemanticVerdict.STRONG_SUSPICION  # worst-case wins
        assert len(r.evidence_breakdown) == 2


# ---- Tokenizer ----

def test_tokenizer_min_chars_and_case_insensitive():
    """≥3 char alphanumeric tokens only; case folded for matching."""
    with tempfile.TemporaryDirectory() as td:
        # file uses UPPERCASE; summary uses lowercase — should match after folding
        path = _write(Path(td) / "f.txt", "ALPHA BETA GAMMA DELTA EPSILON x yy")
        env = {
            "summary": "alpha beta gamma delta epsilon",
            "evidence": [{"file_path": path}],
        }
        r = check(env)
        assert r.verdict == SemanticVerdict.CLEAN  # case folding worked


def test_short_tokens_ignored():
    """1-2 char tokens never count (CJK / abbreviation noise reduction)."""
    with tempfile.TemporaryDirectory() as td:
        path = _write(Path(td) / "f.txt", "x y z")
        env = {
            # Summary has only short tokens — falls below min_summary_tokens=3 after filtering
            "summary": "x y z aa bb cc",
            "evidence": [{"file_path": path}],
        }
        r = check(env)
        assert r.verdict == SemanticVerdict.SKIPPED  # no ≥3-char tokens in summary


# ---- Empty file edge ----

def test_empty_file_records_zero_overlap_but_no_verdict_signal():
    with tempfile.TemporaryDirectory() as td:
        path = _write(Path(td) / "f.txt", "")
        env = {
            "summary": "alpha beta gamma delta epsilon",
            "evidence": [{"file_path": path}],
        }
        r = check(env)
        # Empty file produces breakdown with ratio 0 but does NOT mark saw_signal
        # → SKIPPED (no penalty for empty files like LICENSE.gitkeep boilerplate)
        assert r.verdict == SemanticVerdict.SKIPPED
        assert len(r.evidence_breakdown) == 1
        assert r.evidence_breakdown[0].file_excerpt_len == 0


def test_cjk_korean_overlap_clean():
    """한국어 summary + 한국어 file 내용 — bigram overlap CLEAN."""
    with tempfile.TemporaryDirectory() as td:
        path = _write(Path(td) / "f.txt", "주문 처리 완료 결제 승인 검증")
        env = {
            "summary": "주문 처리 결제 승인 완료",
            "evidence": [{"file_path": path}],
        }
        r = check(env)
        assert r.verdict == SemanticVerdict.CLEAN


def test_cjk_korean_zero_overlap_strong_suspicion():
    """한국어 summary vs 무관한 한국어 file → STRONG_SUSPICION."""
    with tempfile.TemporaryDirectory() as td:
        path = _write(Path(td) / "f.txt", "날씨가 좋다 산책 가자 공원에서")
        env = {
            "summary": "주문 처리 결제 승인 완료 검증 트랜잭션",
            "evidence": [{"file_path": path}],
        }
        r = check(env)
        assert r.verdict == SemanticVerdict.STRONG_SUSPICION


def test_cjk_japanese_overlap():
    """일본어 (히라가나 + 한자) summary와 file overlap."""
    with tempfile.TemporaryDirectory() as td:
        path = _write(Path(td) / "f.txt", "注文 処理 完了 決済")
        env = {
            "summary": "注文 処理 決済 完了",
            "evidence": [{"file_path": path}],
        }
        r = check(env)
        assert r.verdict == SemanticVerdict.CLEAN


def test_mixed_ascii_and_cjk():
    """ASCII + CJK 혼합 summary — 둘 다 union으로 동작."""
    with tempfile.TemporaryDirectory() as td:
        path = _write(Path(td) / "f.txt", "OrderService 주문 처리 결제 PaymentGateway")
        env = {
            "summary": "OrderService 주문 처리 PaymentGateway 결제",
            "evidence": [{"file_path": path}],
        }
        r = check(env)
        assert r.verdict == SemanticVerdict.CLEAN


def test_cjk_short_run_is_not_tokenized_for_noise_reduction():
    """1-char CJK run은 token 생성 안 함 (조사/외자 noise 제거).

    summary = ["a", "b", "c"] (각각 한 한글자) → CJK token 0, ASCII 0 →
    min_summary_tokens 미달 → SKIPPED.
    """
    with tempfile.TemporaryDirectory() as td:
        path = _write(Path(td) / "f.txt", "가 나 다 라 마")  # 1-char runs only
        env = {
            "summary": "가 나 다 라 마",
            "evidence": [{"file_path": path}],
        }
        r = check(env)
        assert r.verdict == SemanticVerdict.SKIPPED  # 0 tokens


TESTS = [
    test_malformed_envelope_is_skipped,
    test_summary_too_short_is_skipped,
    test_no_evidence_is_skipped,
    test_missing_files_only_is_skipped_with_errors,
    test_perfect_overlap_is_clean,
    test_partial_above_threshold_is_clean,
    test_tiny_overlap_above_zero_is_suspicious,
    test_zero_overlap_is_strong_suspicion,
    test_worst_case_across_entries,
    test_tokenizer_min_chars_and_case_insensitive,
    test_short_tokens_ignored,
    test_empty_file_records_zero_overlap_but_no_verdict_signal,
    test_cjk_korean_overlap_clean,
    test_cjk_korean_zero_overlap_strong_suspicion,
    test_cjk_japanese_overlap,
    test_mixed_ascii_and_cjk,
    test_cjk_short_run_is_not_tokenized_for_noise_reduction,
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
