#!/usr/bin/env python3
"""Unit tests for lib/autopilot_phase1_merge.py — D3 from debate-1778302432-1ce6ea.

Coverage:
  - build_merge_dispatch_payload returns required dispatch keys
  - subagent_type fixed to harness-git-master
  - prompt_text references locked F4 protocol
  - prompt_text embeds JSON response schema
  - expected_keys matches RESPONSE_SCHEMA_HINT keys
  - Input validation: empty sid / branches / integration_branch / base_ref
  - Worker branch list rendered into prompt
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _valid_args():
    return dict(
        sid="orch-test-1234",
        worker_branches=["auto/orch-test-1234/D1", "auto/orch-test-1234/D3"],
        integration_branch="team-orch-test-1234/integration",
        base_ref="main",
    )


def test_returns_dict_with_required_top_level_keys():
    from lib.autopilot_phase1_merge import build_merge_dispatch_payload
    p = build_merge_dispatch_payload(**_valid_args())
    for k in ("subagent_type", "prompt_text", "response_schema_hint",
              "expected_keys", "sid", "worker_branches",
              "integration_branch", "base_ref"):
        assert k in p, f"missing key {k}"


def test_subagent_type_locked_to_harness_git_master():
    from lib.autopilot_phase1_merge import build_merge_dispatch_payload
    p = build_merge_dispatch_payload(**_valid_args())
    assert p["subagent_type"] == "harness-git-master"


def test_prompt_text_references_locked_f4_debate():
    from lib.autopilot_phase1_merge import build_merge_dispatch_payload
    p = build_merge_dispatch_payload(**_valid_args())
    assert "debate-1778161608-713bdc" in p["prompt_text"]
    assert "cherry_pick_sequential" in p["prompt_text"]


def test_prompt_text_embeds_halt_no_theirs_ours_invariant():
    from lib.autopilot_phase1_merge import build_merge_dispatch_payload
    p = build_merge_dispatch_payload(**_valid_args())
    text = p["prompt_text"].lower()
    assert "halt" in text
    assert "no -x theirs" in text or "no theirs" in text


def test_prompt_text_embeds_response_schema_request():
    from lib.autopilot_phase1_merge import build_merge_dispatch_payload
    p = build_merge_dispatch_payload(**_valid_args())
    assert "```json" in p["prompt_text"]
    for key in ("integration_branch", "head_sha", "merged_workers",
                "conflicted_worker", "conflicted_paths"):
        assert key in p["prompt_text"], f"schema key {key} missing in prompt"


def test_expected_keys_matches_schema_hint():
    from lib.autopilot_phase1_merge import (
        build_merge_dispatch_payload, EXPECTED_KEYS, RESPONSE_SCHEMA_HINT,
    )
    p = build_merge_dispatch_payload(**_valid_args())
    assert tuple(p["expected_keys"]) == EXPECTED_KEYS
    assert set(EXPECTED_KEYS) == set(RESPONSE_SCHEMA_HINT.keys())


def test_worker_branches_rendered_into_prompt():
    from lib.autopilot_phase1_merge import build_merge_dispatch_payload
    p = build_merge_dispatch_payload(**_valid_args())
    for b in _valid_args()["worker_branches"]:
        assert b in p["prompt_text"]


def test_sid_integration_base_rendered_into_prompt():
    from lib.autopilot_phase1_merge import build_merge_dispatch_payload
    args = _valid_args()
    p = build_merge_dispatch_payload(**args)
    assert args["sid"] in p["prompt_text"]
    assert args["integration_branch"] in p["prompt_text"]
    assert args["base_ref"] in p["prompt_text"]


def test_validation_rejects_empty_sid():
    from lib.autopilot_phase1_merge import build_merge_dispatch_payload
    args = _valid_args()
    args["sid"] = ""
    try:
        build_merge_dispatch_payload(**args)
    except ValueError:
        return
    raise AssertionError("expected ValueError on empty sid")


def test_validation_rejects_empty_worker_branches():
    from lib.autopilot_phase1_merge import build_merge_dispatch_payload
    args = _valid_args()
    args["worker_branches"] = []
    try:
        build_merge_dispatch_payload(**args)
    except ValueError:
        return
    raise AssertionError("expected ValueError on empty worker_branches")


def test_validation_rejects_non_string_worker_branch():
    from lib.autopilot_phase1_merge import build_merge_dispatch_payload
    args = _valid_args()
    args["worker_branches"] = ["good", ""]
    try:
        build_merge_dispatch_payload(**args)
    except ValueError:
        return
    raise AssertionError("expected ValueError on empty worker branch entry")


def test_validation_rejects_empty_integration_branch():
    from lib.autopilot_phase1_merge import build_merge_dispatch_payload
    args = _valid_args()
    args["integration_branch"] = ""
    try:
        build_merge_dispatch_payload(**args)
    except ValueError:
        return
    raise AssertionError("expected ValueError on empty integration_branch")


def test_validation_rejects_empty_base_ref():
    from lib.autopilot_phase1_merge import build_merge_dispatch_payload
    args = _valid_args()
    args["base_ref"] = ""
    try:
        build_merge_dispatch_payload(**args)
    except ValueError:
        return
    raise AssertionError("expected ValueError on empty base_ref")


def test_response_schema_hint_is_returned_copy_not_singleton():
    from lib.autopilot_phase1_merge import build_merge_dispatch_payload, RESPONSE_SCHEMA_HINT
    p = build_merge_dispatch_payload(**_valid_args())
    p["response_schema_hint"]["mutated"] = "yes"
    assert "mutated" not in RESPONSE_SCHEMA_HINT


# ---------- D3 wave (b) — parse_merge_response ----------

_CLEAN_BODY = (
    '{"integration_branch":"team-orch-x/integration",'
    '"head_sha":"abc123","merged_workers":["auto/x/D1","auto/x/D3"],'
    '"conflicted_worker":null,"conflicted_paths":[]}'
)
_CONFLICT_BODY = (
    '{"integration_branch":"team-orch-x/integration",'
    '"head_sha":"abc123","merged_workers":["auto/x/D1"],'
    '"conflicted_worker":"auto/x/D3","conflicted_paths":["a.py","b.py"]}'
)


def test_parse_clean_merge_fenced_json():
    from lib.autopilot_phase1_merge import parse_merge_response
    text = f"Done. Integration head computed.\n\n```json\n{_CLEAN_BODY}\n```\n"
    result = parse_merge_response(text)
    assert result["integration_branch"] == "team-orch-x/integration"
    assert result["head_sha"] == "abc123"
    assert result["merged_workers"] == ["auto/x/D1", "auto/x/D3"]
    assert result["conflicted_worker"] is None
    assert result["conflicted_paths"] == []


def test_parse_conflict_merge_with_paths():
    from lib.autopilot_phase1_merge import parse_merge_response
    text = f"```json\n{_CONFLICT_BODY}\n```"
    result = parse_merge_response(text)
    assert result["conflicted_worker"] == "auto/x/D3"
    assert result["conflicted_paths"] == ["a.py", "b.py"]
    assert result["merged_workers"] == ["auto/x/D1"]


def test_parse_fence_without_json_lang_tag():
    from lib.autopilot_phase1_merge import parse_merge_response
    text = f"```\n{_CLEAN_BODY}\n```"
    result = parse_merge_response(text)
    assert result["head_sha"] == "abc123"


def test_parse_picks_last_fenced_block():
    from lib.autopilot_phase1_merge import parse_merge_response
    bogus = '{"foo":"bar"}'
    text = f"```json\n{bogus}\n```\n\nrevised:\n\n```json\n{_CLEAN_BODY}\n```"
    result = parse_merge_response(text)
    assert result["head_sha"] == "abc123"


def test_parse_bare_json_no_fence():
    from lib.autopilot_phase1_merge import parse_merge_response
    result = parse_merge_response(_CLEAN_BODY)
    assert result["head_sha"] == "abc123"


def test_parse_bare_json_with_surrounding_whitespace():
    from lib.autopilot_phase1_merge import parse_merge_response
    result = parse_merge_response("\n\n  " + _CLEAN_BODY + "  \n\n")
    assert result["head_sha"] == "abc123"


def test_parse_empty_text_raises():
    from lib.autopilot_phase1_merge import parse_merge_response, MergeResponseError
    for bad in ("", "   ", "\n\n"):
        try:
            parse_merge_response(bad)
        except MergeResponseError:
            continue
        raise AssertionError(f"expected MergeResponseError on {bad!r}")


def test_parse_non_str_raises():
    from lib.autopilot_phase1_merge import parse_merge_response, MergeResponseError
    try:
        parse_merge_response(None)  # type: ignore[arg-type]
    except MergeResponseError:
        return
    raise AssertionError("expected MergeResponseError on None")


def test_parse_no_fence_no_bare_json_raises():
    from lib.autopilot_phase1_merge import parse_merge_response, MergeResponseError
    try:
        parse_merge_response("I cherry-picked 2 workers and got HEAD abc123.")
    except MergeResponseError as e:
        assert "no fenced" in str(e) or "no bare" in str(e)
        return
    raise AssertionError("expected MergeResponseError on prose-only response")


def test_parse_malformed_json_raises():
    from lib.autopilot_phase1_merge import parse_merge_response, MergeResponseError
    try:
        parse_merge_response("```json\n{not valid json\n```")
    except MergeResponseError as e:
        assert "invalid JSON" in str(e)
        return
    raise AssertionError("expected MergeResponseError on malformed JSON")


def test_parse_missing_key_raises():
    from lib.autopilot_phase1_merge import parse_merge_response, MergeResponseError
    text = '```json\n{"integration_branch":"x","head_sha":"y","merged_workers":[]}\n```'
    try:
        parse_merge_response(text)
    except MergeResponseError as e:
        assert "missing required keys" in str(e)
        return
    raise AssertionError("expected MergeResponseError on missing keys")


def test_parse_merged_workers_wrong_type_raises():
    from lib.autopilot_phase1_merge import parse_merge_response, MergeResponseError
    bad = (
        '{"integration_branch":"x","head_sha":"y","merged_workers":"oops",'
        '"conflicted_worker":null,"conflicted_paths":[]}'
    )
    try:
        parse_merge_response(f"```json\n{bad}\n```")
    except MergeResponseError as e:
        assert "merged_workers" in str(e)
        return
    raise AssertionError("expected MergeResponseError on non-list merged_workers")


def test_parse_empty_integration_branch_raises():
    from lib.autopilot_phase1_merge import parse_merge_response, MergeResponseError
    bad = (
        '{"integration_branch":"","head_sha":"y","merged_workers":[],'
        '"conflicted_worker":null,"conflicted_paths":[]}'
    )
    try:
        parse_merge_response(f"```json\n{bad}\n```")
    except MergeResponseError as e:
        assert "integration_branch" in str(e)
        return
    raise AssertionError("expected MergeResponseError on empty integration_branch")


def test_parse_conflicted_paths_nonempty_with_null_worker_raises():
    from lib.autopilot_phase1_merge import parse_merge_response, MergeResponseError
    bad = (
        '{"integration_branch":"x","head_sha":"y","merged_workers":[],'
        '"conflicted_worker":null,"conflicted_paths":["a.py"]}'
    )
    try:
        parse_merge_response(f"```json\n{bad}\n```")
    except MergeResponseError as e:
        assert "conflicted_paths must be empty" in str(e)
        return
    raise AssertionError("expected MergeResponseError on inconsistent null/paths")


def test_parse_conflicted_worker_wrong_type_raises():
    from lib.autopilot_phase1_merge import parse_merge_response, MergeResponseError
    bad = (
        '{"integration_branch":"x","head_sha":"y","merged_workers":[],'
        '"conflicted_worker":42,"conflicted_paths":[]}'
    )
    try:
        parse_merge_response(f"```json\n{bad}\n```")
    except MergeResponseError as e:
        assert "conflicted_worker" in str(e)
        return
    raise AssertionError("expected MergeResponseError on non-str conflicted_worker")


def test_parse_top_level_array_raises():
    from lib.autopilot_phase1_merge import parse_merge_response, MergeResponseError
    try:
        parse_merge_response('```json\n[1,2,3]\n```')
    except MergeResponseError as e:
        assert "expected JSON object" in str(e)
        return
    raise AssertionError("expected MergeResponseError on top-level array")


def test_is_clean_merge_true_when_no_conflict():
    from lib.autopilot_phase1_merge import parse_merge_response, is_clean_merge
    result = parse_merge_response(_CLEAN_BODY)
    assert is_clean_merge(result) is True


def test_is_clean_merge_false_when_conflict():
    from lib.autopilot_phase1_merge import parse_merge_response, is_clean_merge
    result = parse_merge_response(_CONFLICT_BODY)
    assert is_clean_merge(result) is False


def test_merge_response_error_carries_diagnostic_and_raw():
    from lib.autopilot_phase1_merge import parse_merge_response, MergeResponseError
    raw_text = "```json\n{not json\n```"
    try:
        parse_merge_response(raw_text)
    except MergeResponseError as e:
        assert e.diagnostic and "invalid JSON" in e.diagnostic
        assert e.raw is not None
        return
    raise AssertionError("expected MergeResponseError")


def test_d4_invariant_comment_present_in_source():
    """D4 (debate-1778307906-23b7b3) lock: ralph re-entry happens in parent
    Agent context, never in worker subprocess. The invariant is documented
    via a one-line comment in the lib source — this test enforces its
    presence so a future PR cannot silently drop the contract.
    """
    src = (_SCRIPTS / "lib" / "autopilot_phase1_merge.py").read_text(encoding="utf-8")
    assert "INVARIANT: ralph re-entry happens in parent Agent context" in src, (
        "D4 invariant comment removed from lib/autopilot_phase1_merge.py — "
        "any change to the ralph re-entry contract must go through a new "
        "harness-debate citing debate-1778307906-23b7b3 D4"
    )
    assert "debate-1778307906-23b7b3" in src, (
        "D4 invariant must cite the locking debate sid for traceability"
    )


TESTS = [
    test_returns_dict_with_required_top_level_keys,
    test_subagent_type_locked_to_harness_git_master,
    test_prompt_text_references_locked_f4_debate,
    test_prompt_text_embeds_halt_no_theirs_ours_invariant,
    test_prompt_text_embeds_response_schema_request,
    test_expected_keys_matches_schema_hint,
    test_worker_branches_rendered_into_prompt,
    test_sid_integration_base_rendered_into_prompt,
    test_validation_rejects_empty_sid,
    test_validation_rejects_empty_worker_branches,
    test_validation_rejects_non_string_worker_branch,
    test_validation_rejects_empty_integration_branch,
    test_validation_rejects_empty_base_ref,
    test_response_schema_hint_is_returned_copy_not_singleton,
    test_parse_clean_merge_fenced_json,
    test_parse_conflict_merge_with_paths,
    test_parse_fence_without_json_lang_tag,
    test_parse_picks_last_fenced_block,
    test_parse_bare_json_no_fence,
    test_parse_bare_json_with_surrounding_whitespace,
    test_parse_empty_text_raises,
    test_parse_non_str_raises,
    test_parse_no_fence_no_bare_json_raises,
    test_parse_malformed_json_raises,
    test_parse_missing_key_raises,
    test_parse_merged_workers_wrong_type_raises,
    test_parse_empty_integration_branch_raises,
    test_parse_conflicted_paths_nonempty_with_null_worker_raises,
    test_parse_conflicted_worker_wrong_type_raises,
    test_parse_top_level_array_raises,
    test_is_clean_merge_true_when_no_conflict,
    test_is_clean_merge_false_when_conflict,
    test_merge_response_error_carries_diagnostic_and_raw,
    test_d4_invariant_comment_present_in_source,
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
