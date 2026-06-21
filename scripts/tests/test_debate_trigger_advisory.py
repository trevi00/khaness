#!/usr/bin/env python3
"""Unit tests for handlers/prompt/debate_trigger.py D3 round-robin advisory.

Tests the helpers + advisory state machine without invoking the hook
subprocess. Round-robin alternation, ack TTL decay, ack token detection,
and slot mutual exclusion.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _redirect_state_dir(tmp: Path):
    from lib import paths as P
    P.STATE_DIR = tmp / "state"
    P.STATE_DIR.mkdir(parents=True, exist_ok=True)


# ---- _select_advisory_slot ----

def test_slot_select_alternates_when_both_want():
    from handlers.prompt.debate_trigger import _select_advisory_slot
    # last=debate → this turn writeback
    assert _select_advisory_slot(
        want_debate=True, want_writeback=True, last_slot="debate"
    ) == "writeback"
    # last=writeback → this turn debate
    assert _select_advisory_slot(
        want_debate=True, want_writeback=True, last_slot="writeback"
    ) == "debate"
    # last="" → defaults to debate (alternate-from-empty)
    assert _select_advisory_slot(
        want_debate=True, want_writeback=True, last_slot=""
    ) == "debate"


def test_slot_select_single_want():
    from handlers.prompt.debate_trigger import _select_advisory_slot
    assert _select_advisory_slot(
        want_debate=True, want_writeback=False, last_slot="anything"
    ) == "debate"
    assert _select_advisory_slot(
        want_debate=False, want_writeback=True, last_slot="anything"
    ) == "writeback"


def test_slot_select_neither_want():
    from handlers.prompt.debate_trigger import _select_advisory_slot
    assert _select_advisory_slot(
        want_debate=False, want_writeback=False, last_slot="anything"
    ) == ""


# ---- _detect_ack_tokens ----

def test_detect_ack_debate_only():
    from handlers.prompt.debate_trigger import _detect_ack_tokens
    d, w = _detect_ack_tokens("이 제안 넘기자 /ack-debate 잠깐 보류")
    assert d is True
    assert w is False


def test_detect_ack_writeback_only():
    from handlers.prompt.debate_trigger import _detect_ack_tokens
    d, w = _detect_ack_tokens("/ack-writeback")
    assert d is False
    assert w is True


def test_detect_ack_both_in_one_prompt():
    from handlers.prompt.debate_trigger import _detect_ack_tokens
    d, w = _detect_ack_tokens("/ack-debate /ack-writeback both")
    assert d is True
    assert w is True


def test_detect_ack_neither():
    from handlers.prompt.debate_trigger import _detect_ack_tokens
    d, w = _detect_ack_tokens("just regular prompt")
    assert d is False
    assert w is False


# ---- advisory state load/save ----

def test_load_advisory_state_defaults_when_missing():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from handlers.prompt.debate_trigger import _load_advisory_state
        state = _load_advisory_state()
        assert state["turn_ordinal"] == 0
        assert state["last_emitted_slot"] == ""
        assert state["ack_remaining_debate"] == 0
        assert state["ack_remaining_writeback"] == 0


def test_save_then_load_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from handlers.prompt.debate_trigger import (
            _load_advisory_state, _save_advisory_state,
        )
        s = {
            "turn_ordinal": 5,
            "last_emitted_slot": "writeback",
            "ack_remaining_debate": 2,
            "ack_remaining_writeback": 0,
        }
        _save_advisory_state(s)
        loaded = _load_advisory_state()
        assert loaded == s


def test_load_advisory_state_handles_corrupt_json():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from handlers.prompt.debate_trigger import (
            _load_advisory_state, _advisory_state_path,
        )
        # Corrupt the state file directly
        path = _advisory_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json {{", encoding="utf-8")
        state = _load_advisory_state()
        # Defaults should kick in
        assert state["turn_ordinal"] == 0


# ---- _list_pending_writeback ----

def test_list_pending_returns_empty_when_no_store():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from handlers.prompt.debate_trigger import _list_pending_writeback
        # No proposals yet
        assert _list_pending_writeback() == []


def test_list_pending_returns_registered_proposals():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_store import ProposalRecord, register_proposal
        from handlers.prompt.debate_trigger import _list_pending_writeback

        register_proposal(ProposalRecord(
            id="p1", fingerprint="abc", target_skill_path="skills/_common/x.md",
            sha1_of_diff="0" * 40,
        ))
        pending = _list_pending_writeback()
        assert len(pending) == 1
        assert pending[0]["id"] == "p1"


# ---- _build_writeback_advisory ----

def test_build_writeback_advisory_includes_targets():
    from handlers.prompt.debate_trigger import _build_writeback_advisory
    pending = [
        {"id": "p1", "fingerprint": "abc12345xx", "target_skill_path": "skills/_common/a.md"},
        {"id": "p2", "fingerprint": "def67890yy", "target_skill_path": "skills/_common/b.md"},
    ]
    out = _build_writeback_advisory(pending)
    assert "harness-writeback-advisory" in out
    assert "skills/_common/a.md" in out
    assert "skills/_common/b.md" in out
    assert "/ack-writeback" in out


def test_build_writeback_advisory_caps_at_two():
    from handlers.prompt.debate_trigger import _build_writeback_advisory
    pending = [
        {"id": f"p{i}", "fingerprint": "fp" * 4, "target_skill_path": f"skills/_common/{i}.md"}
        for i in range(5)
    ]
    out = _build_writeback_advisory(pending)
    # Architect quota: max 2 proposals shown per turn
    assert "skills/_common/0.md" in out
    assert "skills/_common/1.md" in out
    assert "skills/_common/2.md" not in out


TESTS = [
    test_slot_select_alternates_when_both_want,
    test_slot_select_single_want,
    test_slot_select_neither_want,
    test_detect_ack_debate_only,
    test_detect_ack_writeback_only,
    test_detect_ack_both_in_one_prompt,
    test_detect_ack_neither,
    test_load_advisory_state_defaults_when_missing,
    test_save_then_load_roundtrip,
    test_load_advisory_state_handles_corrupt_json,
    test_list_pending_returns_empty_when_no_store,
    test_list_pending_returns_registered_proposals,
    test_build_writeback_advisory_includes_targets,
    test_build_writeback_advisory_caps_at_two,
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
