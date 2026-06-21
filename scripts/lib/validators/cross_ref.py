"""cross_ref — summary vs prompt + multi-file consensus checks (v15.19 G).

v15.13 Architect self_doubt 잔여 클래스 부분 해소:
- *plagiarized-summary*: agent가 prompt 내용을 그대로 summary에 인용
  → summary와 prompt 간 lexical overlap 70%+ 이면 의심
- *multi-file inconsistency*: evidence가 여러 file인데 summary가 한 file에만
  매칭 → multi-file consensus check

본 layer는 D2.5 (semantic.py) 다음 단계 — advisory only, breaker trip 안 함.
ledger.verified_by에 새 grade 추가하여 운영자 가시성만 제공.

설계 원칙 (lib.validators invariant 준수):
- NO LLM, NO embedder, NO ML — pure stdlib re + set
- semantic.py의 _tokenize 재사용 (ASCII + CJK union)
- false positive 허용 (정당한 quote / 짧은 prompt 등은 차단 안 함)

검출 가능한 fabrication 클래스:
- summary가 prompt token의 70%+ overlap (plagiarized-summary 후보)
- multi-file evidence에서 summary가 1개 file에만 매칭 (cherry-picked)

검출 불가능한 클래스 (정직):
- prompt가 매우 짧고 summary가 자연스럽게 prompt를 paraphrase → false positive
- prompt 내용을 의도적으로 인용하는 정당 작업 (예: 코드 리뷰 summary)
- 단일 file evidence + plausible summary (D2.5 외 추가 정보 없음)

Public API:
- CrossRefVerdict enum {CLEAN, SUSPICIOUS_PLAGIARIZED, SUSPICIOUS_CHERRY_PICKED,
  STRONG_PLAGIARIZED, SKIPPED}
- CrossRefResult dataclass
- check_summary_vs_prompt(envelope, prompt) -> CrossRefResult
- check_cross_file_consensus(envelope) -> CrossRefResult
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .semantic import _read_file_head, _tokenize, _extract_summary, _iter_evidence_paths


# --- Tunables ---------------------------------------------------------------
DEFAULT_MIN_TOKEN_CHARS: int = 3
DEFAULT_MIN_SUMMARY_TOKENS: int = 3
DEFAULT_MAX_FILE_BYTES: int = 4096

# Plagiarized threshold: summary tokens가 prompt에 얼마나 많이 있는가
PLAGIARIZED_THRESHOLD: float = 0.70
STRONG_PLAGIARIZED_THRESHOLD: float = 0.90

# Cherry-picked threshold: summary가 multi-file 중 1개 file에만 강하게 매칭
CHERRY_PICKED_FILES_MIN: int = 2  # 최소 multi-file 조건
CHERRY_PICKED_RATIO: float = 0.5  # summary tokens의 50%+가 단 한 file에만


class CrossRefVerdict(str, Enum):
    """4-state (+ SKIPPED) cross-reference verdict."""

    CLEAN = "clean"
    SUSPICIOUS_PLAGIARIZED = "suspicious_plagiarized"
    STRONG_PLAGIARIZED = "strong_plagiarized"
    SUSPICIOUS_CHERRY_PICKED = "suspicious_cherry_picked"
    SKIPPED = "skipped"


@dataclass
class CrossRefResult:
    """Aggregate cross-reference check result."""

    verdict: CrossRefVerdict
    summary_token_count: int = 0
    prompt_token_count: int = 0
    overlap_ratio: float = 0.0
    per_file_overlap: dict[str, float] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def check_summary_vs_prompt(
    envelope: Any,
    prompt: str,
    *,
    min_token_chars: int = DEFAULT_MIN_TOKEN_CHARS,
    min_summary_tokens: int = DEFAULT_MIN_SUMMARY_TOKENS,
) -> CrossRefResult:
    """summary token이 prompt token과 얼마나 겹치는지.

    plagiarized-summary: agent가 prompt 내용을 그대로 summary에 copy-paste.
    높은 overlap = 의심. 단 prompt가 매우 짧으면 false positive 위험.

    Returns SKIPPED when:
      - envelope malformed
      - summary < min_summary_tokens
      - prompt empty or < 5 tokens (signal 부족)
    """
    result = CrossRefResult(verdict=CrossRefVerdict.SKIPPED)

    summary = _extract_summary(envelope)
    summary_tokens = _tokenize(summary, min_chars=min_token_chars)
    result.summary_token_count = len(summary_tokens)
    if len(summary_tokens) < min_summary_tokens:
        return result

    if not isinstance(prompt, str) or not prompt.strip():
        return result
    prompt_tokens = _tokenize(prompt, min_chars=min_token_chars)
    result.prompt_token_count = len(prompt_tokens)
    if len(prompt_tokens) < 5:
        # prompt 너무 짧음 — overlap이 자연스럽게 높음, false positive 회피
        return result

    matched = summary_tokens & prompt_tokens
    ratio = len(matched) / max(1, len(summary_tokens))
    result.overlap_ratio = ratio

    if ratio >= STRONG_PLAGIARIZED_THRESHOLD:
        result.verdict = CrossRefVerdict.STRONG_PLAGIARIZED
    elif ratio >= PLAGIARIZED_THRESHOLD:
        result.verdict = CrossRefVerdict.SUSPICIOUS_PLAGIARIZED
    else:
        result.verdict = CrossRefVerdict.CLEAN
    return result


def check_cross_file_consensus(
    envelope: Any,
    *,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    min_token_chars: int = DEFAULT_MIN_TOKEN_CHARS,
    min_summary_tokens: int = DEFAULT_MIN_SUMMARY_TOKENS,
) -> CrossRefResult:
    """Multi-file evidence consensus.

    cherry-picked: agent가 N개 evidence file을 list했지만 summary가 그 중 1개
    file에만 강하게 매칭 → 나머지 files는 padding (가짜 multi-file evidence).

    Returns SKIPPED when:
      - envelope shape malformed
      - < CHERRY_PICKED_FILES_MIN files
      - summary < min_summary_tokens
    """
    result = CrossRefResult(verdict=CrossRefVerdict.SKIPPED)

    summary = _extract_summary(envelope)
    summary_tokens = _tokenize(summary, min_chars=min_token_chars)
    result.summary_token_count = len(summary_tokens)
    if len(summary_tokens) < min_summary_tokens:
        return result

    paths = list(_iter_evidence_paths(envelope))
    if len(paths) < CHERRY_PICKED_FILES_MIN:
        return result

    file_overlaps: dict[str, float] = {}
    for fp in paths:
        excerpt, err = _read_file_head(fp, max_file_bytes)
        if err is not None:
            result.errors.append(err)
            continue
        file_tokens = _tokenize(excerpt, min_chars=min_token_chars)
        if not file_tokens:
            file_overlaps[fp] = 0.0
            continue
        matched = summary_tokens & file_tokens
        ratio = len(matched) / max(1, len(summary_tokens))
        file_overlaps[fp] = ratio

    result.per_file_overlap = file_overlaps
    if not file_overlaps:
        return result  # all unreadable

    # cherry-picked detection: 한 file이 압도적으로 높고 나머지는 매우 낮음
    sorted_ratios = sorted(file_overlaps.values(), reverse=True)
    top = sorted_ratios[0]
    rest_max = sorted_ratios[1] if len(sorted_ratios) > 1 else 0.0
    if top >= CHERRY_PICKED_RATIO and rest_max < CHERRY_PICKED_RATIO / 2:
        result.verdict = CrossRefVerdict.SUSPICIOUS_CHERRY_PICKED
        result.overlap_ratio = top
    else:
        result.verdict = CrossRefVerdict.CLEAN
        result.overlap_ratio = top
    return result
