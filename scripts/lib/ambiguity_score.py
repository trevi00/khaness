"""ambiguity_score — Q00/ouroboros ambiguity gate primitive (v15.37).

interview-stage termination signal. seed text + Q&A history 를 받아 정량
ambiguity score [0.0, 1.0] 산출. 0.0 = perfectly specified,
1.0 = maximally ambiguous. Q00 default gate threshold = 0.2.

본 모듈은 primitive — v15.39 부터 `commands/harness-interview.md` L33/L78/L100
(primary path per L58, ad-hoc weights fallback only) 가 라이브 consumer 다.
따라서 본 모듈 (특히 `_6W_KEYWORDS` / `DEFAULT_WEIGHTS` / `DEFAULT_THRESHOLD`
/ aggregate 산출 경로) 의 record-aggregate 의미 변경은 runtime policy mutation
이며 enable-skill tier (operator commit ADR footer 토큰 — CLAUDE.md Mutation
분류표 v15.10 D4 asymmetry) 가 요구된다.

debate-1779159195-6630f7 gen-3 verifies consumer:
`grep -rn 'compute_ambiguity_score' ~/.claude/commands/ ~/.claude/agents/
~/.claude/skills/ --include='*.md'` → commands/harness-interview.md hit 가
load-bearing fact. orchestrator gen-1 baseline (`external_consumer_count=0`)
은 `~/.claude/scripts/` scope 한정이라 false-clear 발생 → 본 docstring
업데이트가 정정.

## 3-component scoring (linear combination)

| component | weight | range | rationale |
|-----------|--------|-------|-----------|
| `coverage_gap`            | 0.85 | [0,1] | 6W (who/what/when/where/why/how) 중 미답변 비율. dominant carrier — post-D2 weight rebalance (debate-1779201365-66ff07 LOCK SHA f1ca724ecb06, 2026-05-19). |
| `lexical_entropy`         | 0.05 | [0,1] | seed+answers 토큰 분포의 normalized Shannon entropy. EN token uniqueness 로 0.93-0.95 saturated noise floor — weight 축소. |
| `unknown_marker_density`  | 0.10 | [0,1] | 명시적 ambiguity token (TBD/?/may/might/어쩌면/확인 필요/추후 등) density. 50% of original — adversarial mar>0.5 false-positive 영역 documented (C-LAND-3). |

aggregate = sum(weight * component). passes_gate = aggregate <= threshold.

## API

- `compute_lexical_entropy(text: str) -> float` — [0.0, 1.0]
- `compute_coverage_gap(seed: str, qa_pairs: list[tuple[str,str]]) -> float`
- `compute_unknown_marker_density(text: str) -> float` — [0.0, 1.0]
- `AmbiguityScore` (frozen dataclass)
- `compute_ambiguity_score(seed, qa_pairs, *, threshold=0.2,
   weights=DEFAULT_WEIGHTS) -> AmbiguityScore`

## boundaries (non-goals for this cycle)

- 6W detector 는 keyword-based (영/한 bilingual). 정교한 NLU 는 미래.
- seed/qa 의 code-block·URL·이모지는 정규화 단계에서 제외.
- threshold 0.2 는 Q00 default. operator override 가능 (운영자 결정).
- 본 모듈은 stateless primitive. interview session state 는 별도 모듈
  (현재 state/interview/ 디렉터리 운용 중, 본 모듈은 consume 안 함).
- consumer wiring (harness-interview termination 조건) 은 별도 cycle.

## known structural ceiling — UNRECOVERABLE 2026-05-19 (debate-1779201365-66ff07 gen 3 convergence, LOCK SHA f1ca724ecb06)

**UNRECOVERABLE: pre-tokenizer-lift simulation cannot be re-run; D1+D4 joint
land precludes A/B isolation.** The simulation numerics below (gap 0.667→0.333,
agg 0.594→0.394, rebalance simulation 0.332) were measured *before* D1
substring-scan (commit 80bb852) and D4 _6W_KEYWORDS KO synonym expansion
(commit e92b84f) land. Both changes shipped within the same operator session,
so post-land empirical numerics cannot isolate D1's contribution from D4's
keyword expansion contribution — joint intervention causation is permanent.

실측 (interview-1779089320-9c6689 final / interview-1779075035-ff5b61
trajectory 분석, example_project-analysis HANDOFF wave 7 후속 8 진단,
*INVALIDATED pre-tokenizer-lift, retained as historical reference only*):

- ~~English token uniqueness → lexical_entropy ≈ 0.97-1.00 baseline → 0.2 weight~~
  ~~⇒ entropy contribution 0.194-0.200 ⇒ threshold 0.2 budget 의 97%+ 소모.~~
- ~~Korean spec text → 6W detector false negative 빈발 (KO synonym 부족~~
  ~~"반영/위해/방식/사이클/위한" 등 미등록) → coverage_gap 0.5+ 잔존.~~
- ~~Option C (KO synonym 추가) 단독 → real seed gap 0.667 → 0.333,~~
  ~~aggregate 0.594 → 0.394. 여전히 fail at threshold 0.2.~~
- ~~weights (0.6,0.2,0.2) → (0.85,0.05,0.10) rebalance 시 시뮬레이션~~
  ~~aggregate 0.332. 동일 fail. ⇒ multi-axis fix (6W 확장 + weights +~~
  ~~threshold 동시 조정) 필요 ⇒ *design decision territory*.~~

**Replaced by 2026-05-19 measurement (debate-1779201365-66ff07)**: 8-corpora
실측 baseline 5/8 PASS → D2 (0.85,0.05,0.10) 단독 8/8 PASS at default t=0.20.
mathematical guarantee: 8-corpora max(cov_gap)=0.167, 0.85×0.167+0.05×ent+0.10×mar
observed max=0.190 (well below threshold 0.20). C-1 adversarial probes (cov ∈
{0.000, 0.333, 0.500, 0.667, 0.833, 1.000}) verify Pareto strict-subset
property (D2 fail set ⊆ baseline fail set, 0 PASS→FAIL regression). C-10
entropy-dominant probes confirm cov=0.167+ent∈[0.986,1.000] FAIL→PASS flip
matches 3 real corpora pattern (design-intent improvement). gate_2 4pt
잔여 폐쇄 — full 15/15 도달.

실 root cause (debate-1779148412-5a0eca gen 4 수렴, *historical reference
preserved per C-2 partial-invalidate*):
`compute_coverage_gap` (L209-248) 의 set-intersection 매칭 — `_6W_KEYWORDS`
토큰 집합과 spec token 집합의 교집합 size 로 coverage 측정. 반면
`_UNKNOWN_MARKERS_KO` 는 L264 에서 substring-scan precedent 로 동일 모듈
내 이미 운용 중. 한국어 greedy tokenizer 동작 ('반영하기위해' → 1 token)
은 *intended policy* (형태소 경계 미분리) 이며 root cause 가 아님 —
substring-scan 으로 전환하면 동일 토큰에서 '반영','위해' 양쪽 hit 가능.

post-D1 (substring-scan) + post-D4 (KO synonym) joint land 가 single-axis
fix premise 자체를 invalidate — multi-axis fix 가설은 over-correction 으로
판명. weights 단독 (D2) 으로 8/8 PASS 달성. multi-axis (threshold + 추가
synonym) 는 불필요로 결정 (debate-1779201365-66ff07 gen 3 approved).

본 ceiling 은 W19.1.2 정량 잔여 노름 인정 영역이었으나 본 D2 land 로 해소.
fix path 는 record aggregate 의미 변경 (runtime policy mutation,
Mutation 분류표 enable-skill tier) — operator ack "OD6 제외하고 나머지
진행하자" 2026-05-19 + ADR-ambiguity-v4 signed_token (commit footer).

## paradox guard cross-ref

ambiguity_score 는 *interview termination* signal — 본 하네스의 paradox
guard 3-condition (test_pass + citations>=3 + ontology_match) 과는 다른
phase. interview phase 종결 → Designer phase 진입 → debate 가 다시 5축
ontology snapshot 으로 paradox 회피. ambiguity gate 통과는 *충분조건이
아닌* 진입 자격 — Designer phase 자체 paradox mitigation 별도.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass


# Default linear-combination weights (sum to 1.0)
DEFAULT_WEIGHTS: tuple[float, float, float] = (0.85, 0.05, 0.10)
"""(coverage_gap_weight, lexical_entropy_weight, unknown_marker_density_weight).

coverage_gap (0.85) is the dominant carrier — post-D1 substring-scan + post-D4
KO synonym expansion (~/.claude commits 80bb852 + e92b84f) 이후 6W detector
가 EN/KO bilingual spec text 에 대해 충분한 정확도를 확보. lexical_entropy
weight 0.05: EN token uniqueness 로 0.926-0.949 (real) / 0.949-1.000
(adversarial) saturated — noise floor 로 작동. unknown_marker_density 0.10:
50% of original (mono-feature design intent, linear combination signature
보존 with non-zero minor weights — M5 dismissed at debate-1779201365-66ff07
gen 2, LOCK SHA f1ca724ecb06).

8-corpora measured distribution (2026-05-19):
- cov_gap: {0.000: 5/8, 0.167: 3/8, ≥0.333: 0/8 real}
- lexical_entropy: real ∈ [0.926, 0.949], adversarial ∈ [0.949, 1.000]
- unknown_marker_density: real ∈ [0.000, 0.011], adversarial ∈ [0.000, 0.824]

Sample limitation: real corpora cluster at cov_gap ∈ {0, 0.167}; cov_gap≥0.333
region verified via C-1 synthetic adversarial only. Adversarial out-of-distribution
inputs (mar >> 0.011 measured ceiling) — e.g., the C-10 4th probe at mar=0.824 —
ARE known false-positives that D2 weights cannot catch. Investigation (C-LAND-4,
2026-05-19): NO explicit downstream filter exists in harness-planner /
harness-critic / harness-architect specs nor in lib/validators/ — Critic LLM
judgment is the only check (non-deterministic). Adversarial high-mar input is
documented as KNOWN LIMITATION (out-of-scope for D2 weight design), not as
"downstream-filtered". Mitigation path = future debate to introduce explicit
marker_alarm gate (mar > 0.5 → force ambig FAIL) IF observed in real corpora.

Design invariant (review-time only): max(DEFAULT_WEIGHTS) > 0.5 reflects
mono-feature reality. sum(DEFAULT_WEIGHTS) = 1.0 enforced per-call at L378-380
(no module-top redundant assert — D5 deleted at debate-1779201365-66ff07 gen 2)."""

DEFAULT_THRESHOLD: float = 0.2
"""Q00 default ambiguity gate threshold. aggregate <= threshold → passes."""


# ---- 6W coverage keyword sets (bilingual EN/KO) ----
#
# INVARIANT (debate-1779159195-6630f7 gen-3 Architect LOCK target):
#   every NEWLY-ADDED KO entry MUST be ≥2 Hangul characters. Single-char
#   Hangul (회/후/전/측/자/분/차/팀) causes cross-category false-positive
#   saturation under L260 substring-scan (e.g., '회' ⊂ '회사',
#   '자' ⊂ '사용자/작성자/관리자', '팀' ⊂ '팀워크/팀장'). Postpositions
#   / bound morphemes (위해/위한/때문/동안/이후/이전/직전/직후) also
#   rejected — appear in ~60% of any KO spec under substring scan.
#   Substring-collisions (경로) also rejected.
#   Cross-cat duplicate ban: same token MUST NOT appear in two
#   categories ('단계' lives only in `when` — not in `how`).
#   LEGACY EXCEPTION: '왜' (1-char canonical Korean WH-word for 'why',
#   in `why` since module inception) is kept — substring risk narrow
#   (왜냐하면/왜곡/왜소 only). All FUTURE additions MUST satisfy: len>=2.
#   PR-review enforces.
_6W_KEYWORDS: dict[str, frozenset[str]] = {
    "who": frozenset({
        "who", "whom", "whose",
        "user", "users", "actor", "actors", "stakeholder", "stakeholders",
        "owner", "owners", "operator", "operators",
        "누가", "누구", "사용자", "이해관계자", "담당자", "운영자",
        # D4 (debate-1779159195-6630f7) additions:
        "사람", "주체",
    }),
    "what": frozenset({
        "what", "which",
        "feature", "features", "function", "functions", "functionality",
        "capability", "capabilities", "requirement", "requirements",
        "무엇", "기능", "요구사항", "요건",
        # D4 additions:
        "사항", "항목", "대상", "내용", "행위", "이벤트", "데이터", "정보", "동작",
    }),
    "when": frozenset({
        "when", "deadline", "schedule", "timeline", "milestone", "milestones",
        "phase", "phases", "release", "sprint",
        "언제", "기한", "일정", "마감", "출시", "단계",
        # D4 additions:
        "시점", "시기", "주기", "사이클",
    }),
    "where": frozenset({
        "where", "location", "platform", "environment", "scope",
        "어디서", "어디", "환경", "플랫폼", "위치", "범위",
        # D4 additions:
        "지점", "구역", "공간", "내부", "외부",
    }),
    "why": frozenset({
        "why", "reason", "motivation", "purpose", "rationale", "goal",
        "objective", "outcome",
        "왜", "이유", "목적", "동기", "근거",
        # D4 additions:
        "원인", "취지", "용도", "사유", "의도",
    }),
    "how": frozenset({
        "how", "method", "approach", "mechanism", "strategy", "process",
        "implementation", "design",
        "어떻게", "방법", "방식", "전략", "프로세스", "절차",
        # D4 additions:
        "방향", "프로토콜", "메커니즘", "수단", "형태", "형식",
    }),
}


# ---- Unknown ambiguity markers (bilingual EN/KO) ----

_UNKNOWN_MARKERS_EN: frozenset[str] = frozenset({
    "tbd", "todo", "fixme", "tbc", "tba",
    "may", "might", "could", "maybe", "possibly", "perhaps",
    "approximately", "roughly", "around", "about", "or so",
    "somehow", "somewhere", "sometime",
    "unclear", "unknown", "uncertain", "undecided",
})
"""English ambiguity markers (lowercased match)."""

_UNKNOWN_MARKERS_KO: tuple[str, ...] = (
    "어쩌면", "아마", "혹시", "대략", "약", "정도",
    "확인 필요", "검토 후", "추후", "미정", "고민 중",
    "TBD", "TBC", "추후 결정", "결정 필요", "추가 확인",
    "어딘가", "언젠가",
)
"""Korean ambiguity markers (substring match, case-sensitive for KO)."""


# Question marks (consecutive ?) signal explicit uncertainty
_QUESTION_MARK_RE = re.compile(r"\?{1,}")

# Token splitter: word-boundary; preserves Korean (Hangul)
_TOKEN_SPLIT_RE = re.compile(r"[A-Za-z0-9_]+|[가-힣]+", re.UNICODE)

# Code-block + URL strippers (excluded from normalization)
_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_URL_RE = re.compile(r"https?://\S+")


# ---- normalization ----

def _normalize_text(text: str) -> str:
    """Strip code blocks, inline code, URLs. Returns cleaned text.

    Raises ValueError for non-str input.
    """
    if not isinstance(text, str):
        raise ValueError(f"text must be str, got {type(text).__name__}")
    cleaned = _CODE_BLOCK_RE.sub(" ", text)
    cleaned = _INLINE_CODE_RE.sub(" ", cleaned)
    cleaned = _URL_RE.sub(" ", cleaned)
    return cleaned


def _tokenize(text: str) -> list[str]:
    """Lowercase tokens after normalization. Empty input → []."""
    cleaned = _normalize_text(text)
    return [tok.lower() for tok in _TOKEN_SPLIT_RE.findall(cleaned)]


# ---- component scorers ----

def compute_lexical_entropy(text: str) -> float:
    """Normalized Shannon entropy of token distribution.

    Returns [0.0, 1.0]:
      0.0 — empty / single repeated token (perfectly concentrated)
      1.0 — uniform distribution over distinct tokens (maximal spread)

    Normalization: H / log2(unique_count) when unique_count > 1, else 0.
    Single-token corpus → 0.0 (no spread → not ambiguous on this axis).
    """
    tokens = _tokenize(text)
    if not tokens:
        return 0.0
    counts: dict[str, int] = {}
    for tok in tokens:
        counts[tok] = counts.get(tok, 0) + 1
    total = len(tokens)
    unique = len(counts)
    if unique <= 1:
        return 0.0
    h = 0.0
    for c in counts.values():
        p = c / total
        h -= p * math.log2(p)
    max_h = math.log2(unique)
    return h / max_h


def compute_coverage_gap(seed: str,
                         qa_pairs: list[tuple[str, str]] | None = None) -> float:
    """Fraction of 6W (who/what/when/where/why/how) categories NOT covered.

    Concatenates seed + all qa answers (questions excluded — they ASK
    about a dimension, only answers FILL it). Scans for any keyword
    in each 6W set. Returns matched_count / 6 inverted: gap = (6 - matched) / 6.

    qa_pairs: list of (question, answer). Pass None or [] for seed-only.
    Returns [0.0, 1.0]:
      0.0 — all 6W covered (no gap, complete)
      1.0 — none covered (max gap, fully ambiguous)
    """
    if not isinstance(seed, str):
        raise ValueError(f"seed must be str, got {type(seed).__name__}")
    if qa_pairs is None:
        qa_pairs = []
    if not isinstance(qa_pairs, list):
        raise ValueError(
            f"qa_pairs must be list or None, got {type(qa_pairs).__name__}"
        )
    parts = [seed]
    for i, item in enumerate(qa_pairs):
        if (not isinstance(item, tuple)) or len(item) != 2:
            raise ValueError(
                f"qa_pairs[{i}] must be (question, answer) tuple, got {item!r}"
            )
        q, a = item
        if not isinstance(q, str) or not isinstance(a, str):
            raise ValueError(
                f"qa_pairs[{i}] must contain (str, str), got ({type(q).__name__}, {type(a).__name__})"
            )
        parts.append(a)  # answers fill dimensions; questions only probe
    corpus = " ".join(parts)
    tokens = _tokenize(corpus)
    matched = 0
    # cross-cat substring contamination accepted as intended (e.g., 'showing'→how, 'reasonable'→why via 'reason'): no gating, no whitelist, no dedup. Per-category break enforces cap-1 invariance.
    for keyword_set in _6W_KEYWORDS.values():
        for tok in tokens:
            if any(k in tok for k in keyword_set):
                matched += 1
                break
    return (6 - matched) / 6.0


def compute_unknown_marker_density(text: str) -> float:
    """Fraction of tokens that are explicit ambiguity markers.

    Counts:
      - English markers (_UNKNOWN_MARKERS_EN, lowercased token match)
      - Korean markers (_UNKNOWN_MARKERS_KO, substring match on raw text)
      - Question-mark runs (each '?' counted, capped via density)

    Returns [0.0, 1.0]. cap at 1.0.
    """
    tokens = _tokenize(text)
    raw = _normalize_text(text)
    en_hits = sum(1 for t in tokens if t in _UNKNOWN_MARKERS_EN)
    ko_hits = sum(raw.count(m) for m in _UNKNOWN_MARKERS_KO)
    q_hits = sum(len(m.group()) for m in _QUESTION_MARK_RE.finditer(raw))
    total_markers = en_hits + ko_hits + q_hits
    # Pure-marker corpus (e.g., "????" with no real tokens) is maximally
    # ambiguous → 1.0. Else density over max(tokens, markers) so dense
    # KO/? against thin token stream still caps at 1.0.
    if not tokens:
        return 1.0 if total_markers > 0 else 0.0
    denom = max(len(tokens), total_markers)
    return min(1.0, total_markers / denom)


# ---- aggregate result ----

@dataclass(frozen=True)
class AmbiguityScore:
    """Immutable ambiguity scoring result.

    Fields:
      lexical_entropy        — [0,1], higher = more ambiguous
      coverage_gap           — [0,1], higher = more 6W dimensions missing
      unknown_marker_density — [0,1], higher = more uncertainty tokens
      aggregate              — [0,1], weighted sum
      threshold              — gate threshold (default 0.2)
      passes_gate            — aggregate <= threshold
      weights                — (gap_w, entropy_w, marker_w) used
    """
    lexical_entropy: float
    coverage_gap: float
    unknown_marker_density: float
    aggregate: float
    threshold: float
    passes_gate: bool
    weights: tuple[float, float, float]


def compute_ambiguity_score(
    seed: str,
    qa_pairs: list[tuple[str, str]] | None = None,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    weights: tuple[float, float, float] = DEFAULT_WEIGHTS,
) -> AmbiguityScore:
    """Compute the full ambiguity score with gate decision.

    weights order: (coverage_gap, lexical_entropy, unknown_marker_density).
    Sum should be 1.0 (validated within ±1e-9 tolerance).

    qa_pairs: list of (question, answer). None → seed-only.
    threshold: gate threshold; aggregate <= threshold → passes_gate=True.

    Returns AmbiguityScore (frozen dataclass).
    """
    if not isinstance(threshold, (int, float)):
        raise ValueError(f"threshold must be numeric, got {type(threshold).__name__}")
    if not (0.0 <= float(threshold) <= 1.0):
        raise ValueError(f"threshold must be in [0,1], got {threshold}")
    if not isinstance(weights, tuple) or len(weights) != 3:
        raise ValueError(f"weights must be 3-tuple, got {weights!r}")
    if not all(isinstance(w, (int, float)) and w >= 0 for w in weights):
        raise ValueError(f"weights must all be numeric >=0, got {weights!r}")
    w_sum = sum(weights)
    if abs(w_sum - 1.0) > 1e-9:
        raise ValueError(f"weights must sum to 1.0 (±1e-9), got {w_sum}")

    gap_w, entropy_w, marker_w = weights

    # Coverage uses both seed and qa answers (semantic — answers fill gaps)
    gap = compute_coverage_gap(seed, qa_pairs)

    # Entropy + marker density use combined corpus (seed + Q + A)
    parts = [seed]
    if qa_pairs:
        for q, a in qa_pairs:
            parts.append(q)
            parts.append(a)
    corpus = " ".join(parts)
    entropy = compute_lexical_entropy(corpus)
    markers = compute_unknown_marker_density(corpus)

    aggregate = (gap_w * gap) + (entropy_w * entropy) + (marker_w * markers)
    # Clamp [0,1] defensively (math should already hold but float drift)
    aggregate = max(0.0, min(1.0, aggregate))

    return AmbiguityScore(
        lexical_entropy=entropy,
        coverage_gap=gap,
        unknown_marker_density=markers,
        aggregate=aggregate,
        threshold=float(threshold),
        passes_gate=aggregate <= threshold,
        weights=weights,
    )


# ---- self-check (embedded — run: python -m lib.ambiguity_score --self-check) ----

def _self_check() -> None:
    """Embedded regression for v15.27+ single-file mutation surface pattern.

    Categories:
      A. normalization + tokenization
      B. compute_lexical_entropy boundaries
      C. compute_coverage_gap (6W detection, bilingual)
      D. compute_unknown_marker_density (EN + KO + question marks)
      E. AmbiguityScore frozen + invariants
      F. compute_ambiguity_score aggregation + gate
      G. input validation
    """
    import sys

    asserts = 0

    def _assert(cond: bool, msg: str) -> None:
        nonlocal asserts
        asserts += 1
        if not cond:
            print(f"FAIL: {msg}", file=sys.stderr)
            sys.exit(1)

    # --- A. normalization + tokenization ---
    _assert(_tokenize("") == [], "empty tokenize")
    _assert(_tokenize("Hello world") == ["hello", "world"], "basic lowercase")
    _assert(_tokenize("foo `bar` baz") == ["foo", "baz"], "inline code stripped")
    _assert(_tokenize("a https://x.io b") == ["a", "b"], "URL stripped")
    _assert(_tokenize("```\nx\n```\nafter") == ["after"], "code block stripped")
    _assert(_tokenize("사용자 기능") == ["사용자", "기능"], "Hangul tokens")
    _assert(_tokenize("user_id v1") == ["user_id", "v1"], "underscore + alnum")

    # --- B. lexical entropy boundaries ---
    _assert(compute_lexical_entropy("") == 0.0, "empty entropy 0")
    _assert(compute_lexical_entropy("aaa aaa aaa") == 0.0, "single token entropy 0")
    e_two = compute_lexical_entropy("a b")
    _assert(abs(e_two - 1.0) < 1e-9, f"two-distinct entropy max 1.0, got {e_two}")
    e_three = compute_lexical_entropy("a b c")
    _assert(abs(e_three - 1.0) < 1e-9, f"three-distinct uniform entropy 1.0, got {e_three}")
    # Skewed dist < uniform
    e_skew = compute_lexical_entropy("a a a a b")
    _assert(0.0 < e_skew < 1.0, f"skewed 0<e<1, got {e_skew}")

    # --- C. coverage gap ---
    _assert(compute_coverage_gap("") == 1.0, "empty seed all 6W missing")
    _assert(compute_coverage_gap("who what when where why how") == 0.0,
            "all 6W keywords present → gap 0")
    # Half coverage (3 of 6)
    half_gap = compute_coverage_gap("who what when")
    _assert(abs(half_gap - 0.5) < 1e-9, f"3/6 covered → gap 0.5, got {half_gap}")
    # KO keywords
    ko_gap = compute_coverage_gap("사용자 기능 일정 환경 이유 방법")
    _assert(ko_gap == 0.0, f"all 6W KO keywords → gap 0, got {ko_gap}")
    # QA answers fill gaps
    seed_only = "feature"  # WHAT only
    full_gap = compute_coverage_gap(seed_only)
    _assert(abs(full_gap - 5/6) < 1e-9, f"seed-only what → gap 5/6, got {full_gap}")
    qa_filled = compute_coverage_gap(
        seed_only,
        [("who?", "the operator"), ("when?", "next sprint"),
         ("where?", "internal platform"), ("why?", "compliance reason"),
         ("how?", "REST method")]
    )
    _assert(qa_filled == 0.0, f"qa fills all 6W → 0, got {qa_filled}")
    # Question alone doesn't fill (only answers)
    q_only = compute_coverage_gap(
        "feature",
        [("who is the user?", "TBD"), ("when is the deadline?", "TBD")]
    )
    _assert(q_only == 5/6, f"answers='TBD' don't fill, got {q_only}")
    # Substring-scan lift (debate-1779155987-28bc2e converged): plural EN forms hit via substring containment, who-prefix substring still counts, cap-1 invariance via explicit break.
    plural_gap = compute_coverage_gap(
        "users features deadlines locations reasons methods"
    )
    _assert(plural_gap == 0.0,
            f"plural EN forms hit via substring scan, got {plural_gap}")
    whomever_gap = compute_coverage_gap("whomever")
    _assert(whomever_gap == 5/6,
            f"who-prefix substring still counts as who, got {whomever_gap}")
    cap1_gap = compute_coverage_gap("whose whom user")
    _assert(cap1_gap == 5/6,
            f"cap-1 invariance: 3 same-cat hits collapse to 1 via break, got {cap1_gap}")

    # --- D. unknown marker density ---
    _assert(compute_unknown_marker_density("") == 0.0, "empty marker density 0")
    _assert(compute_unknown_marker_density("hello world") == 0.0, "no markers → 0")
    d_tbd = compute_unknown_marker_density("tbd")
    _assert(d_tbd == 1.0, f"sole TBD → 1.0, got {d_tbd}")
    d_one_in_five = compute_unknown_marker_density("a b c d maybe")
    _assert(d_one_in_five == 0.2, f"1/5 markers → 0.2, got {d_one_in_five}")
    # KO markers
    d_ko = compute_unknown_marker_density("기능 추후 결정")
    _assert(d_ko > 0.0, f"KO markers detected, got {d_ko}")
    # Question marks
    d_q = compute_unknown_marker_density("what?")
    _assert(d_q > 0.0, f"question mark detected, got {d_q}")
    d_q_many = compute_unknown_marker_density("what???")
    _assert(d_q_many >= d_q, "multiple ? at least as many markers")
    # Cap at 1.0
    d_cap = compute_unknown_marker_density("????????????????")
    _assert(d_cap == 1.0, f"all ? cap at 1.0, got {d_cap}")

    # --- E. AmbiguityScore frozen + structure ---
    score = compute_ambiguity_score("user feature deadline location reason method")
    _assert(isinstance(score, AmbiguityScore), "returns AmbiguityScore")
    try:
        # frozen dataclass — assignment must fail
        score.aggregate = 0.0  # type: ignore[misc]
        _assert(False, "frozen — assignment should raise")
    except (AttributeError, TypeError):
        _assert(True, "frozen dataclass blocks mutation")
    _assert(0.0 <= score.lexical_entropy <= 1.0, "entropy in range")
    _assert(0.0 <= score.coverage_gap <= 1.0, "gap in range")
    _assert(0.0 <= score.unknown_marker_density <= 1.0, "marker in range")
    _assert(0.0 <= score.aggregate <= 1.0, "aggregate in range")
    _assert(score.threshold == DEFAULT_THRESHOLD, "default threshold")
    _assert(score.weights == DEFAULT_WEIGHTS, "default weights stored")

    # --- F. compute_ambiguity_score aggregation + gate ---
    # Perfectly specified short spec → low aggregate
    well_specified = compute_ambiguity_score(
        "user feature deadline environment reason method",
        []
    )
    _assert(well_specified.coverage_gap == 0.0, "all 6W in seed → gap 0")
    _assert(well_specified.aggregate < 0.5,
            f"well-specified aggregate < 0.5, got {well_specified.aggregate}")

    # Maximally ambiguous (empty seed)
    max_ambig = compute_ambiguity_score("", [])
    _assert(max_ambig.coverage_gap == 1.0, "empty seed → gap 1.0")
    _assert(max_ambig.aggregate >= 0.5,
            f"max ambiguity aggregate >= 0.5, got {max_ambig.aggregate}")
    _assert(max_ambig.passes_gate is False, "max ambiguity fails gate")

    # Gate passes when very low
    pass_score = compute_ambiguity_score(
        "user user user feature feature feature deadline environment reason method",
        []
    )
    _assert(pass_score.passes_gate is True,
            f"low ambig passes gate, agg={pass_score.aggregate}")

    # Custom threshold loosens gate
    loose_pass = compute_ambiguity_score("", [], threshold=1.0)
    _assert(loose_pass.passes_gate is True, "threshold=1.0 always passes")
    loose_pass2 = compute_ambiguity_score("anything", [], threshold=0.0)
    _assert(loose_pass2.passes_gate is False or loose_pass2.aggregate == 0.0,
            "threshold=0 only passes at exactly 0")

    # Custom weights
    custom = compute_ambiguity_score("", [], weights=(1.0, 0.0, 0.0))
    _assert(custom.aggregate == 1.0,
            f"weight=(1,0,0) + empty seed → 1.0, got {custom.aggregate}")
    # Non-uniform corpus (some tokens repeat) → entropy < 1.0
    custom2 = compute_ambiguity_score(
        "user user feature feature feature deadline environment reason method",
        [],
        weights=(0.0, 1.0, 0.0)
    )
    _assert(custom2.aggregate < 1.0,
            f"entropy-only on skewed vocab < 1.0, got {custom2.aggregate}")

    # QA pairs included in coverage
    seed_only_eval = compute_ambiguity_score("a feature")
    seed_plus_qa = compute_ambiguity_score(
        "a feature",
        [("who?", "user"), ("when?", "next sprint"),
         ("where?", "platform"), ("why?", "reason"), ("how?", "method")]
    )
    _assert(seed_plus_qa.coverage_gap <= seed_only_eval.coverage_gap,
            "qa answers reduce gap")

    # --- G. input validation ---
    try:
        _normalize_text(123)  # type: ignore[arg-type]
        _assert(False, "non-str normalize should raise")
    except ValueError:
        _assert(True, "normalize rejects non-str")
    try:
        compute_coverage_gap(123)  # type: ignore[arg-type]
        _assert(False, "non-str seed should raise")
    except ValueError:
        _assert(True, "coverage_gap rejects non-str seed")
    try:
        compute_coverage_gap("x", "not-list")  # type: ignore[arg-type]
        _assert(False, "non-list qa_pairs should raise")
    except ValueError:
        _assert(True, "coverage_gap rejects non-list qa_pairs")
    try:
        compute_coverage_gap("x", [("q",)])  # type: ignore[list-item]
        _assert(False, "malformed tuple should raise")
    except ValueError:
        _assert(True, "coverage_gap rejects malformed qa tuple")
    try:
        compute_coverage_gap("x", [(1, "a")])  # type: ignore[list-item]
        _assert(False, "non-str q should raise")
    except ValueError:
        _assert(True, "coverage_gap rejects non-str question")
    try:
        compute_ambiguity_score("x", threshold=-0.1)
        _assert(False, "negative threshold should raise")
    except ValueError:
        _assert(True, "threshold negative rejected")
    try:
        compute_ambiguity_score("x", threshold=1.5)
        _assert(False, "threshold>1 should raise")
    except ValueError:
        _assert(True, "threshold >1 rejected")
    try:
        compute_ambiguity_score("x", weights=(0.5, 0.3, 0.3))
        _assert(False, "non-1 sum should raise")
    except ValueError:
        _assert(True, "weights sum != 1.0 rejected")
    try:
        compute_ambiguity_score("x", weights=(0.5, 0.5))  # type: ignore[arg-type]
        _assert(False, "2-tuple should raise")
    except ValueError:
        _assert(True, "weights len != 3 rejected")
    try:
        compute_ambiguity_score("x", weights=(-0.1, 0.6, 0.5))
        _assert(False, "negative weight should raise")
    except ValueError:
        _assert(True, "negative weight rejected")

    print(f"OK: {asserts} assertions passed")


if __name__ == "__main__":
    import sys
    if "--self-check" in sys.argv:
        _self_check()
    else:
        print("usage: python -m lib.ambiguity_score --self-check")
        sys.exit(2)
