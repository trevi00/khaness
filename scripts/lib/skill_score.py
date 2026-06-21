"""skill_score — pure scoring helpers for skill_match handler.

Extracts the multi-dimensional skill scoring algorithm and its matching
helpers (ASCII-vs-Korean keyword detection, Korean verb-stem intent matching)
from `handlers/prompt/skill_match.py`.

Public API:
- `is_ascii(text)`: whether all chars are ASCII.
- `keyword_in_prompt(kw_lower, prompt_lower)`: word-boundary aware match.
- `intent_in_prompt(intent_lower, prompt_lower)`: Korean verb-stem aware.
- `read_file_head(filepath, max_chars)`: best-effort file head reader.
- `score_skill(meta, prompt_lower, detected_paths, file_contents_cache)`:
  returns (is_match, score, matched_dims) — UNCHANGED from original 4-dim
  scoring (keyword/intent/path/pattern).

Pure functions: no module-level state, no I/O beyond `read_file_head`.
"""
from __future__ import annotations

import os
import re
from typing import Any


def is_ascii(text: str) -> bool:
    """True if every char is ASCII (< U+0080)."""
    return all(ord(c) < 128 for c in text)


def keyword_in_prompt(kw_lower: str, prompt_lower: str) -> bool:
    """Match keyword with word-boundary awareness for ASCII, substring for Korean."""
    if is_ascii(kw_lower):
        return bool(re.search(
            r"(?<![a-zA-Z0-9])" + re.escape(kw_lower) + r"(?![a-zA-Z0-9])",
            prompt_lower,
        ))
    return kw_lower in prompt_lower


def intent_in_prompt(intent_lower: str, prompt_lower: str) -> bool:
    """Match intent with Korean verb-stem awareness.

    Compound intents like 'API만들어' should match 'API 만들어' — handled by
    also checking the space-stripped prompt. Korean intents drop the last
    syllable (verb ending) before substring matching.
    """
    prompt_nospace = prompt_lower.replace(" ", "")
    if not is_ascii(intent_lower) and len(intent_lower) >= 2:
        stem = intent_lower[:-1]
        return stem in prompt_lower or stem in prompt_nospace
    if is_ascii(intent_lower):
        return bool(re.search(
            r"(?<![a-zA-Z0-9])" + re.escape(intent_lower) + r"(?![a-zA-Z0-9])",
            prompt_lower,
        ))
    return intent_lower in prompt_lower or intent_lower in prompt_nospace


def read_file_head(filepath: str, max_chars: int = 3000) -> str:
    """Read up to `max_chars` of `filepath`. Returns "" on any error."""
    try:
        normalized = filepath.replace("\\", "/")
        if os.path.isfile(normalized):
            with open(normalized, "r", encoding="utf-8", errors="ignore") as f:
                return f.read(max_chars)
    except Exception:
        pass
    return ""


from .frontmatter_norm import split_list_field as _split_list_field  # noqa: E402

# Backward-compatible alias — keeps existing private name available for
# tests that imported it (test_skill_score.py uses `ss._split_list_field`).
# New code should import split_list_field from lib.frontmatter_norm.


def _intent_covers_keyword(kw_lower: str, matched_intent_lowers: list[str]) -> bool:
    """True if `kw_lower` is the SAME CONCEPT as an already-matched intent — i.e.
    the keyword is the noun-root of an intent verb that fired on the same surface
    token. Prevents double-counting one concept as both keyword(+1) and intent(+2).

    Motivating bug (wave effort-2): the 'example_gateway-example_vendor' skill matched the prompt
    "...승인할게" with keyword '승인' (+1) AND intent '승인해' (stem '승인', +2),
    scoring 3 from a single concept ('승인' = approval) and full-body-injecting an
    irrelevant VAN payment guide. One surface token → one concept → count once at
    the higher (intent +2) value.

    Conservative coverage (avoids over-suppressing genuinely distinct keywords):
      - ASCII intent: exact equality only.
      - Korean intent: equality with the raw form OR its verb-stem (last syllable
        dropped), OR the keyword being a >=2-char prefix of the raw intent token
        (the keyword is the noun the intent verb is built from, e.g. 리뷰/리뷰해).
    """
    if not kw_lower:
        return False
    for it in matched_intent_lowers:
        if is_ascii(it):
            # exact, OR keyword is a delimited token of a compound intent verb
            # (e.g. kw 'target' covered by intent 'pin-target'). Token-membership
            # (split on - _ space) is used instead of raw startswith to avoid
            # English incidental-prefix over-fire (kw 'app' vs intent 'append').
            if kw_lower == it or kw_lower in re.split(r"[-_ ]+", it):
                return True
        else:
            stem = it[:-1] if len(it) >= 2 else it
            if kw_lower == it or kw_lower == stem:
                return True
            if len(kw_lower) >= 2 and it.startswith(kw_lower):
                return True
    return False


def _split_path_segments(p: str) -> list[str]:
    """Lowercase path → non-empty `/`-separated segments (backslashes normalized)."""
    return [s for s in p.lower().replace("\\", "/").strip("/").split("/") if s]


def _path_segment_match(skill_path: str, detected_path: str) -> bool:
    """True iff ``skill_path`` matches ``detected_path`` on SEGMENT boundaries.

    Replaces the old substring check (``sp in dp``) which produced false positives —
    e.g. skill path ``auth`` scoring +2 on ``src/authorized/Login.java``. Now ``auth``
    matches the ``auth`` segment of ``src/auth/Token.java`` (and the file ``auth.java``
    by basename stem) but NOT ``authorized``. A multi-segment skill path (``src/auth``)
    must appear as a contiguous run of the detected path's segments.
    """
    sp = _split_path_segments(skill_path)
    dp = _split_path_segments(detected_path)
    if not sp or len(sp) > len(dp):
        return False

    def seg_eq(skill_seg: str, det_seg: str) -> bool:
        if det_seg == skill_seg:
            return True
        # allow a skill segment to match a file basename: `auth` ~ `auth.java`
        stem = det_seg.rsplit(".", 1)[0] if "." in det_seg else det_seg
        return stem == skill_seg

    return any(
        all(seg_eq(sp[j], dp[i + j]) for j in range(len(sp)))
        for i in range(len(dp) - len(sp) + 1)
    )


def score_skill(
    meta: dict[str, Any],
    prompt_lower: str,
    detected_paths: set[str],
    file_contents_cache: dict[str, str],
) -> tuple[bool, int, list[str]]:
    """Calculate multi-dimensional match score for a skill.

    4 dimensions (UNCHANGED scoring):
    - keywords: +1 each (longest-first, no overlap double-count)
    - intent: +2 each
    - paths: +2 each (first match per skill_path)
    - patterns: +1 each (file contents — uses file_contents_cache)

    Returns (is_match, score, matched_dims). is_match := score >= meta.min_score (default 1).
    """
    score = 0
    matched_dims: list[str] = []

    # 1. Intent (+2 each) — scored FIRST so the keyword pass can dedup any keyword
    #    that is merely the noun-root of an already-counted intent verb (same-token
    #    polysemy; see _intent_covers_keyword). One surface token = one concept.
    intents = _split_list_field(meta.get("intent", ""))
    matched_intent_lowers: list[str] = []
    for intent in intents:
        intent_lower = intent.lower()
        if intent_in_prompt(intent_lower, prompt_lower):
            score += 2
            matched_dims.append(f"intent:{intent}")
            matched_intent_lowers.append(intent_lower)

    # 2. Keywords (+1 each) — longest-first (suppress shorter overlapping keyword)
    #    AND skip any keyword already covered by a matched intent (same-token dedup).
    keywords = _split_list_field(meta.get("keywords", ""))
    matched_positions: set[tuple[int, int]] = set()
    for kw in sorted(keywords, key=len, reverse=True):  # Longest first
        kw_lower = kw.lower()
        if not keyword_in_prompt(kw_lower, prompt_lower):
            continue
        if _intent_covers_keyword(kw_lower, matched_intent_lowers):
            continue  # concept already scored via intent (+2); avoid +1 double-count
        pos = prompt_lower.find(kw_lower)
        if pos >= 0 and any(s <= pos < s + l for s, l in matched_positions):
            continue
        score += 1
        matched_dims.append(f"kw:{kw}")
        matched_positions.add((pos, len(kw_lower)))

    # 3. Paths (+2 each)
    skill_paths = _split_list_field(meta.get("paths", ""))
    if skill_paths and detected_paths:
        for sp in skill_paths:
            for dp in detected_paths:
                if _path_segment_match(sp, dp):
                    score += 2
                    matched_dims.append(f"path:{sp}")
                    break

    # 4. Patterns - check file contents (+1 each)
    patterns = _split_list_field(meta.get("patterns", ""))
    if patterns and detected_paths:
        for dp in detected_paths:
            if dp not in file_contents_cache:
                file_contents_cache[dp] = read_file_head(dp)
            content_lower = file_contents_cache[dp].lower()
            if content_lower:
                for pat in patterns:
                    if pat.lower() in content_lower:
                        score += 1
                        matched_dims.append(f"pat:{pat}")

    min_score = int(meta.get("min_score", "1"))
    return score >= min_score, score, matched_dims
