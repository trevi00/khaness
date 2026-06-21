#!/usr/bin/env python3
"""Unit tests for lib/skill_score.py — matching helpers + 4-dim scoring."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import skill_score as ss  # noqa: E402


def test_is_ascii_pure_ascii():
    assert ss.is_ascii("hello world") is True
    assert ss.is_ascii("ABCxyz_123") is True


def test_is_ascii_mixed_korean():
    assert ss.is_ascii("hello 안녕") is False
    assert ss.is_ascii("안녕") is False


def test_is_ascii_empty():
    assert ss.is_ascii("") is True


def test_keyword_in_prompt_ascii_word_boundary():
    assert ss.keyword_in_prompt("api", "use the api here") is True
    # word-boundary should reject substring inside larger word
    assert ss.keyword_in_prompt("api", "rapidly") is False


def test_keyword_in_prompt_ascii_punctuation_boundary():
    assert ss.keyword_in_prompt("api", "api.endpoint") is True
    assert ss.keyword_in_prompt("api", "(api)") is True


def test_keyword_in_prompt_korean_substring():
    assert ss.keyword_in_prompt("스킬", "스킬을 추가") is True
    assert ss.keyword_in_prompt("스킬", "다른 단어") is False


def test_intent_in_prompt_korean_stem_dropped():
    """Last syllable is dropped before substring check.
    'API만들어' → stem '만들' should match '만들기' or '만들어'.
    """
    assert ss.intent_in_prompt("만들어", "API 만들기 시작") is True
    assert ss.intent_in_prompt("만들어", "API 만들어 줘") is True


def test_intent_in_prompt_handles_no_space_compound():
    """'API만들어' should match 'API 만들어' (space-stripped match)."""
    assert ss.intent_in_prompt("api만들어", "api 만들어") is True


def test_intent_in_prompt_ascii_word_boundary():
    assert ss.intent_in_prompt("review", "please review the diff") is True
    assert ss.intent_in_prompt("review", "previewing changes") is False


def test_read_file_head_existing_file():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "x.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("hello world")
        assert ss.read_file_head(path) == "hello world"


def test_read_file_head_max_chars_cap():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "x.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("a" * 5000)
        assert len(ss.read_file_head(path, max_chars=100)) == 100


def test_read_file_head_missing_returns_empty():
    assert ss.read_file_head("/no/such/file/here") == ""


def test_score_skill_keyword_match():
    meta = {"keywords": "test"}
    is_match, score, dims = ss.score_skill(meta, "running test cases", set(), {})
    assert is_match is True
    assert score == 1
    assert "kw:test" in dims


def test_score_skill_intent_doubles():
    """Intent is +2 per match."""
    meta = {"intent": "fix"}
    is_match, score, dims = ss.score_skill(meta, "fix the bug", set(), {})
    assert score == 2
    assert is_match is True
    assert "intent:fix" in dims


def test_score_skill_no_match_below_min_score():
    meta = {"keywords": "absent", "min_score": "1"}
    is_match, score, _ = ss.score_skill(meta, "totally unrelated", set(), {})
    assert is_match is False
    assert score == 0


def test_score_skill_min_score_threshold():
    """min_score=3 with 2 keywords matched → no match (score 2 < 3)."""
    meta = {"keywords": "api endpoint", "min_score": "3"}
    is_match, score, _ = ss.score_skill(meta, "use the api endpoint", set(), {})
    assert score == 2
    assert is_match is False


def test_score_skill_path_match_doubles():
    meta = {"paths": "src/main"}
    paths = {"my/src/main/Foo.java"}
    is_match, score, dims = ss.score_skill(meta, "irrelevant prompt", paths, {})
    assert score == 2
    assert is_match is True
    assert "path:src/main" in dims


def test_score_skill_path_segment_boundary():
    """Path match is segment-bounded (M5): `auth` must not score on `authorized`."""
    # false positive killed: 'auth' is a substring of 'authorized' but not a segment
    is_match, score, dims = ss.score_skill(
        {"paths": "auth"}, "irrelevant prompt", {"src/authorized/Login.java"}, {}
    )
    assert score == 0 and is_match is False and not dims
    # legit: 'auth' matches the `auth` segment
    _, score, dims = ss.score_skill(
        {"paths": "auth"}, "irrelevant prompt", {"src/auth/Token.java"}, {}
    )
    assert score == 2 and "path:auth" in dims
    # legit: 'auth' matches a file basename stem `auth.java`
    _, score, _ = ss.score_skill(
        {"paths": "auth"}, "irrelevant prompt", {"src/services/auth.java"}, {}
    )
    assert score == 2


def test_score_skill_pattern_in_file_contents():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "App.java").replace("\\", "/")
        with open(path, "w", encoding="utf-8") as f:
            f.write("import org.springframework.boot.SpringApplication;")
        meta = {"patterns": "springframework"}
        cache = {}
        is_match, score, dims = ss.score_skill(meta, "anything", {path}, cache)
        assert score == 1
        assert is_match is True
        assert "pat:springframework" in dims


def test_score_skill_no_overlap_double_count():
    """Longer keyword 'springboot' should suppress shorter 'spring' at same pos."""
    meta = {"keywords": "spring springboot"}
    is_match, score, dims = ss.score_skill(meta, "use springboot here", set(), {})
    # springboot matches first (longer), spring at same position is suppressed
    assert score == 1
    assert "kw:springboot" in dims
    assert "kw:spring" not in dims


def test_score_skill_combined_dimensions():
    """keyword(+1) + intent(+2) + path(+2) = 5."""
    meta = {
        "keywords": "auth",
        "intent": "review",
        "paths": "auth/",
        "min_score": "1",
    }
    paths = {"src/auth/Token.java"}
    is_match, score, dims = ss.score_skill(meta, "review auth code", paths, {})
    assert score == 5
    assert is_match is True
    assert "kw:auth" in dims
    assert "intent:review" in dims
    assert "path:auth/" in dims


def test_score_skill_empty_meta_yields_zero():
    is_match, score, dims = ss.score_skill({}, "anything", set(), {})
    assert score == 0
    assert dims == []
    assert is_match is False  # min_score default 1 > 0


# --- _split_list_field — handles both whitespace and YAML-list syntax ---

def test_split_list_field_yaml_list():
    """[a, b, c] syntax — strip brackets+commas+whitespace."""
    assert ss._split_list_field("[a, b, c]") == ["a", "b", "c"]


def test_split_list_field_yaml_no_spaces():
    assert ss._split_list_field("[a,b,c]") == ["a", "b", "c"]


def test_split_list_field_whitespace_legacy():
    """Legacy whitespace-separated convention preserved."""
    assert ss._split_list_field("a b c") == ["a", "b", "c"]


def test_split_list_field_empty():
    assert ss._split_list_field("") == []
    assert ss._split_list_field("[]") == []


def test_split_list_field_strips_outer_padding():
    assert ss._split_list_field("  [  a , b  ]  ") == ["a", "b"]


def test_score_skill_yaml_list_keywords_match():
    """Real bug fix: YAML-list keywords used to score 0.

    Before fix: `[verification, verify]` → tokens `['[verification,', 'verify]']`
    → no match. After fix: `['verification', 'verify']` → matches.
    """
    meta = {"keywords": "[verification, verify, evidence]", "min_score": "1"}
    is_match, score, dims = ss.score_skill(meta, "evidence verification", set(), {})
    assert score >= 1, f"YAML list keywords must score; got {score}"
    assert any("kw:verification" in d or "kw:evidence" in d for d in dims)


def test_score_skill_yaml_list_intent_match():
    meta = {"intent": "[verify, check-before-claim]", "min_score": "1"}
    is_match, score, dims = ss.score_skill(meta, "verify the result", set(), {})
    assert score >= 2  # intent +2
    assert any("intent:verify" in d for d in dims)


# --- same-token dedup (wave effort-2): a keyword that is merely the noun-root of
#     an already-counted intent verb must NOT add a second point (one concept). ---

def test_intent_covers_keyword_korean_stem():
    """kw '승인' is the stem of intent '승인해' → covered (one concept)."""
    assert ss._intent_covers_keyword("승인", ["승인해"]) is True


def test_intent_covers_keyword_korean_prefix():
    """kw is a >=2-char prefix of a compound Korean intent verb → covered."""
    assert ss._intent_covers_keyword("리뷰", ["리뷰해줘"]) is True


def test_intent_covers_keyword_ascii_exact():
    assert ss._intent_covers_keyword("review", ["review"]) is True


def test_intent_covers_keyword_ascii_token_membership():
    """kw 'target' is a delimited token of compound intent 'pin-target' → covered."""
    assert ss._intent_covers_keyword("target", ["pin-target"]) is True


def test_intent_covers_keyword_ascii_no_incidental_prefix():
    """ASCII uses token-membership NOT raw startswith — 'app' must NOT be covered
    by 'append' (different concept, no delimiter)."""
    assert ss._intent_covers_keyword("app", ["append"]) is False


def test_intent_covers_keyword_distinct_concept_not_covered():
    assert ss._intent_covers_keyword("auth", ["review"]) is False


def test_score_skill_dedups_same_token_korean():
    """The example_gateway polysemy: kw '승인' + intent '승인해' on '승인' → score 2, not 3."""
    meta = {"keywords": "승인", "intent": "승인해"}
    is_match, score, dims = ss.score_skill(meta, "이거 승인할게", set(), {})
    assert score == 2, f"expected 2 (intent only, kw deduped); got {score}"
    assert any("intent:승인해" in d for d in dims)
    assert not any(d == "kw:승인" for d in dims), "kw '승인' must be deduped"


def test_score_skill_dedups_ascii_compound_token():
    """kw 'target' + intent 'pin-target' → score 2 (intent only)."""
    meta = {"keywords": "target", "intent": "pin-target"}
    is_match, score, dims = ss.score_skill(meta, "pin-target the build", set(), {})
    assert score == 2, f"expected 2; got {score}"
    assert not any(d == "kw:target" for d in dims)


def test_score_skill_distinct_kw_and_intent_both_count():
    """Genuinely distinct concept: kw 'auth' + intent 'review' → 3 (no dedup)."""
    meta = {"keywords": "auth", "intent": "review", "min_score": "1"}
    is_match, score, dims = ss.score_skill(meta, "review auth code", set(), {})
    assert score == 3, f"expected 3 (1+2, distinct); got {score}"
    assert any("kw:auth" in d for d in dims)
    assert any("intent:review" in d for d in dims)


def test_score_skill_dedup_drops_below_min_score():
    """example_gateway scenario: only signal is one concept double-counted; with min_score 3
    the dedup pushes it to 2 < 3 → no match (the FP elimination)."""
    meta = {"keywords": "승인", "intent": "승인해", "min_score": "3"}
    is_match, score, _ = ss.score_skill(meta, "승인할게", set(), {})
    assert score == 2
    assert is_match is False, "deduped single-concept must fall below min_score 3"


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
