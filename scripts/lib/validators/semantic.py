"""semantic — deterministic lexical overlap layer (v15.13, Architect self_doubt partial mitigation).

목적 — Architect self_doubt 시나리오 부분 해소:

> "schema-conforming hallucination이 output_schema + tool_allowlist 만 충족하는
>  거짓 산출물은 D2 structural validator를 통과"
>  — debate-1778946602-jj7vxk D2 self_doubt

D2 structural은 file_path가 *존재*하는지만 확인. agent가 schema에 맞게 가짜
envelope을 만들면서 *임의의 존재 파일* (예: README.md)을 file_path로 박으면
통과. 본 layer는 evidence file 내용과 envelope.summary 간 lexical overlap을
검사하여 *완전히 무관한* fabrication을 일부 검출.

설계 원칙 (lib.validators.__init__ 명시 정책 준수):
1. **NO LLM, NO embedder, NO statistical model** — pure stdlib, deterministic.
2. **Advisory only** — block 안 함, breaker trip 안 함. operator-ledger의
   `verified_by` 필드를 `evidence_validator_lexical_clean`/`_suspicious` 등
   세분화 신호로만 사용.
3. **False positive 허용** — summary가 의도적으로 file content와 다른
   case (예: 코드 리뷰 summary vs raw code) 차단 안 함.

검출 가능한 fabrication 클래스:
- file_path = 임의 존재 파일 + summary가 file content와 lexical overlap 0%
- v15.15+: CJK (한국어 한글 / 일본어 가나·한자 / 중국어 한자) bigram n-gram
  tokenizer로 ASCII와 동등하게 작동. ASCII union으로 mixed 텍스트 처리.

검출 불가능한 fabrication 클래스 (정직):
- agent가 file 내용을 prompt에 인용 + summary를 그 키워드로 작성 = 통과
  (이건 LLM critic 또는 cross-reference graph가 필요)
- file_path가 boilerplate (LICENSE, .gitkeep) + summary가 자연스러운 작업 서술 =
  통과 (이건 file 의미적 무관성 검출이 필요)

본 layer는 *strong* 해소가 아닌 *partial mitigation*. R4b note의 fabrication
trigger 시 추가 신호 surface 용도.

Public API:
- SemanticVerdict: enum {CLEAN, SUSPICIOUS, STRONG_SUSPICION, SKIPPED}
- SemanticResult: dataclass {verdict, evidence_breakdown, errors}
- check(envelope, *, max_file_bytes, min_token_chars) -> SemanticResult
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# --- Tunables (conservative) -----------------------------------------------------

DEFAULT_MAX_FILE_BYTES: int = 4096
DEFAULT_MIN_TOKEN_CHARS: int = 3
DEFAULT_MIN_SUMMARY_TOKENS: int = 3  # summary 너무 짧으면 신호 없음

# Threshold mapping (overlap_ratio = matched_tokens / summary_tokens):
#   overlap_ratio == 0     → STRONG_SUSPICION
#   0 < overlap < 0.20     → SUSPICIOUS
#   overlap >= 0.20        → CLEAN
SUSPICION_THRESHOLD: float = 0.20


# ASCII token regex — alphanumeric (≥ min_chars으로 추가 필터).
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")

# CJK character ranges (v15.15) — Hangul Syllables + CJK Unified Ideographs +
# Hiragana + Katakana. 연속된 CJK character sequence를 추출하여 bigram (n-gram)
# 단위로 token화. 형태소 분석기 없이도 lexical overlap 검출 가능.
#   AC00-D7AF: Hangul Syllables (한글 음절 — 가-힣)
#   4E00-9FFF: CJK Unified Ideographs (한자/汉字/漢字)
#   3040-309F: Hiragana (히라가나)
#   30A0-30FF: Katakana (카타카나)
# Bigram 선택 사유: 1-char은 조사/단일 어휘로 noise 많음. 2-char는 의미 단위
# 근사 (한국어 명사 평균 길이 ≈ 2, 일본어 한자 명사 ≈ 2, 한자 어휘 ≈ 2). 형태소
# 분석기 (mecab/KoNLPy) 도입은 외부 dep 필요 → invariant (NO ML model) 위반.
_CJK_RE = re.compile(
    "["
    "぀-ヿ"   # Hiragana + Katakana
    "一-鿿"   # CJK Unified Ideographs
    "가-힯"   # Hangul Syllables
    "]+"
)
_CJK_NGRAM_SIZE: int = 2


class SemanticVerdict(str, Enum):
    """Tri-state (+ SKIPPED) semantic check verdict.

    str-Enum so JSONL ledger serializes the value directly.
    """

    CLEAN = "clean"
    SUSPICIOUS = "suspicious"
    STRONG_SUSPICION = "strong_suspicion"
    SKIPPED = "skipped"


@dataclass
class EvidenceBreakdown:
    """Per-evidence-entry overlap detail (operator-visible audit trail)."""

    file_path: str
    summary_tokens: int
    matched_tokens: int
    overlap_ratio: float
    file_excerpt_len: int


@dataclass
class SemanticResult:
    """Aggregate semantic check result.

    `verdict`: worst-case across all evidence entries
               (STRONG_SUSPICION > SUSPICIOUS > CLEAN; SKIPPED if no signal).
    `evidence_breakdown`: per-entry detail (operator-visible).
    `errors`: file read failures / shape issues (non-fatal — verdict can
              still be CLEAN if at least one entry produced signal).
    """

    verdict: SemanticVerdict
    evidence_breakdown: list[EvidenceBreakdown] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _tokenize_ascii(text: str, *, min_chars: int) -> set[str]:
    """Lowercase ASCII alphanumeric tokens (≥ min_chars). Set for dedup."""
    return {
        m.group(0).lower()
        for m in _TOKEN_RE.finditer(text)
        if len(m.group(0)) >= min_chars
    }


def _tokenize_cjk(text: str, *, ngram_size: int = _CJK_NGRAM_SIZE) -> set[str]:
    """CJK n-gram tokens (v15.15).

    연속된 CJK character sequence(런)를 추출하여 sliding window n-gram 단위로
    token화. 짧은 run (< ngram_size)는 통째로 token (예: 외자 한자어).

    sliding window 예 (ngram_size=2):
      "주문처리" → {"주문", "문처", "처리"}
      "주문"     → {"주문"}
      "X"        → {} (한국어 외자 음절은 의미 약함 — skip)
    """
    tokens: set[str] = set()
    for run in _CJK_RE.findall(text):
        if len(run) < ngram_size:
            # 외자 한자어 (예: '美', '中')는 의미가 있을 수 있으므로 통째로 보존
            if len(run) >= 1 and ngram_size >= 2 and len(run) >= 1:
                # 1-char run은 noise (대부분 조사/단일 외자) → skip
                # 단 한자 1-char는 의미 있을 수 있으나 false positive 위험 더 큼
                continue
            tokens.add(run)
            continue
        for i in range(len(run) - ngram_size + 1):
            tokens.add(run[i:i + ngram_size])
    return tokens


def _tokenize(text: str, *, min_chars: int) -> set[str]:
    """ASCII tokens + CJK n-gram tokens union (v15.15).

    한국어/일본어/중국어 텍스트가 섞인 envelope에서도 lexical overlap 계산
    가능. ASCII는 case-folded, CJK는 case 무관 (대소문자 없음).
    """
    if not isinstance(text, str):
        return set()
    return _tokenize_ascii(text, min_chars=min_chars) | _tokenize_cjk(text)


def _read_file_head(path: str, max_bytes: int) -> tuple[str, str | None]:
    """Read file head (best-effort).

    Returns (excerpt, error_or_None). Excerpt is empty string on failure.
    Binary files are tolerated via errors='replace'.
    """
    try:
        with open(path, "rb") as f:
            raw = f.read(max_bytes)
        return raw.decode("utf-8", errors="replace"), None
    except FileNotFoundError:
        return "", f"file not found: {path}"
    except OSError as e:
        return "", f"read failed {path}: {type(e).__name__}"


def _extract_summary(envelope: Any) -> str:
    """Pull a 'summary' string from common envelope shapes (tolerant)."""
    if not isinstance(envelope, dict):
        return ""
    for key in ("summary", "description", "_raw_text", "result"):
        v = envelope.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def _iter_evidence_paths(envelope: Any):
    """Yield non-empty string file_path entries from envelope.evidence."""
    if not isinstance(envelope, dict):
        return
    evidence = envelope.get("evidence")
    if not isinstance(evidence, list):
        return
    for entry in evidence:
        if isinstance(entry, dict):
            fp = entry.get("file_path")
            if isinstance(fp, str) and fp:
                yield fp


def _classify_overlap(ratio: float) -> SemanticVerdict:
    if ratio == 0.0:
        return SemanticVerdict.STRONG_SUSPICION
    if ratio < SUSPICION_THRESHOLD:
        return SemanticVerdict.SUSPICIOUS
    return SemanticVerdict.CLEAN


def _worst(a: SemanticVerdict, b: SemanticVerdict) -> SemanticVerdict:
    """Precedence: STRONG_SUSPICION > SUSPICIOUS > CLEAN > SKIPPED."""
    order = {
        SemanticVerdict.SKIPPED: 0,
        SemanticVerdict.CLEAN: 1,
        SemanticVerdict.SUSPICIOUS: 2,
        SemanticVerdict.STRONG_SUSPICION: 3,
    }
    return a if order[a] >= order[b] else b


def check(
    envelope: Any,
    *,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    min_token_chars: int = DEFAULT_MIN_TOKEN_CHARS,
    min_summary_tokens: int = DEFAULT_MIN_SUMMARY_TOKENS,
) -> SemanticResult:
    """Run semantic overlap check across all evidence entries.

    Returns SKIPPED when:
      - envelope shape malformed
      - no evidence entries with file_path
      - summary text < min_summary_tokens tokens (no signal possible)

    Else returns worst-case verdict aggregated across entries.
    """
    result = SemanticResult(verdict=SemanticVerdict.SKIPPED)

    summary = _extract_summary(envelope)
    summary_tokens = _tokenize(summary, min_chars=min_token_chars)
    if len(summary_tokens) < min_summary_tokens:
        return result  # SKIPPED — not enough signal in summary

    paths = list(_iter_evidence_paths(envelope))
    if not paths:
        return result  # SKIPPED — nothing to compare against

    worst = SemanticVerdict.SKIPPED
    saw_signal = False

    for fp in paths:
        excerpt, err = _read_file_head(fp, max_file_bytes)
        if err is not None:
            result.errors.append(err)
            # missing file is layer-2 (structural) territory — skip lexical here.
            continue
        if not excerpt.strip():
            # empty file — no signal, do not penalize
            result.evidence_breakdown.append(EvidenceBreakdown(
                file_path=fp, summary_tokens=len(summary_tokens),
                matched_tokens=0, overlap_ratio=0.0, file_excerpt_len=0,
            ))
            continue

        file_tokens = _tokenize(excerpt, min_chars=min_token_chars)
        matched = summary_tokens & file_tokens
        ratio = len(matched) / max(1, len(summary_tokens))
        verdict = _classify_overlap(ratio)
        worst = _worst(worst, verdict)
        saw_signal = True
        result.evidence_breakdown.append(EvidenceBreakdown(
            file_path=fp,
            summary_tokens=len(summary_tokens),
            matched_tokens=len(matched),
            overlap_ratio=ratio,
            file_excerpt_len=len(excerpt),
        ))

    if saw_signal:
        result.verdict = worst
    # else: SKIPPED (all files unreadable / empty / out of layer)
    return result
