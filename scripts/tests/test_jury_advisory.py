#!/usr/bin/env python3
"""Tests for engine/jury_advisory.py — opt-in cross-vendor jury second-opinion.

Contract under test: ADVISORY ONLY. Default off; fail-soft (never raises into the
debate loop); never emits convergence-affecting keys.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _verdict(consensus, *, mode="panel", members=("codex/gpt",), votes=None,
            agreement=1.0, failures=()):
    return SimpleNamespace(
        consensus_verdict=consensus, mode=mode, members=tuple(members),
        votes=votes or {"approved": 1, "rejected": 0, "conditional": 0},
        agreement=agreement, failures=tuple(failures),
    )


def _boom(*a, **k):
    raise AssertionError("ask_fn must NOT be called")


# ---- opt-in gate ----

def test_is_enabled_env():
    from engine.jury_advisory import is_enabled
    assert is_enabled({"DEBATE_EXT_JURY": "1"}) is True
    assert is_enabled({"DEBATE_EXT_JURY": "0"}) is False
    assert is_enabled({}) is False


def test_disabled_by_default_does_not_call_jury():
    from engine.jury_advisory import jury_advisory
    out = jury_advisory("architect prompt", env={}, ask_fn=_boom, members_fn=lambda: [object()])
    assert out["enabled"] is False
    assert out["skipped"] is True
    assert out["skipped_reason"] == "opt_out"


def test_enabled_but_no_members_skips_cleanly():
    from engine.jury_advisory import jury_advisory
    out = jury_advisory("p", enabled=True, members_fn=lambda: [], ask_fn=_boom)
    assert out["enabled"] is True and out["skipped"] is True
    assert out["skipped_reason"] == "no_available_non_claude_members"


def test_empty_prompt_skips():
    from engine.jury_advisory import jury_advisory
    out = jury_advisory("", enabled=True, members=[object()], ask_fn=_boom)
    assert out["skipped"] is True and out["skipped_reason"] == "empty_prompt"


# ---- happy path + agreement comparison (the value) ----

def test_enabled_agreement_true():
    from engine.jury_advisory import jury_advisory
    out = jury_advisory(
        "p", enabled=True, members=[object()], architect_verdict="approved",
        ask_fn=lambda *a, **k: _verdict("approved"),
    )
    assert out["skipped"] is False
    assert out["consensus_verdict"] == "approved"
    assert out["agrees_with_architect"] is True
    assert out["disagreement"] is False
    assert out["advisory_only"] is True


def test_enabled_disagreement_surfaced():
    from engine.jury_advisory import jury_advisory
    out = jury_advisory(
        "p", enabled=True, members=[object()], architect_verdict="approved",
        ask_fn=lambda *a, **k: _verdict("conditional"),
    )
    assert out["consensus_verdict"] == "conditional"
    assert out["agrees_with_architect"] is False
    assert out["disagreement"] is True


def test_agreement_none_when_consensus_missing():
    from engine.jury_advisory import jury_advisory
    out = jury_advisory(
        "p", enabled=True, members=[object()], architect_verdict="approved",
        ask_fn=lambda *a, **k: _verdict(None),
    )
    assert out["consensus_verdict"] is None
    assert out["agrees_with_architect"] is None
    assert out["disagreement"] is None


# ---- fail-soft ----

def test_ask_raises_is_failsoft():
    from engine.jury_advisory import jury_advisory
    def _raise(*a, **k):
        raise RuntimeError("provider down")
    out = jury_advisory("p", enabled=True, members=[object()], ask_fn=_raise)
    assert out["enabled"] is True and out["skipped"] is True
    assert out["skipped_reason"] == "jury_error:RuntimeError"


# ---- the load-bearing guard: NEVER feeds convergence ----

def test_payload_has_no_convergence_keys():
    """A jury_advisory payload must NOT carry any key that could be mistaken for a
    convergence input (ontology_snapshot / sha / converged)."""
    from engine.jury_advisory import jury_advisory
    forbidden = {"ontology_snapshot", "sha", "this_sha", "prev_sha", "converged", "fields"}
    payloads = [
        jury_advisory("p", env={}, ask_fn=_boom),
        jury_advisory("p", enabled=True, members=[object()],
                      ask_fn=lambda *a, **k: _verdict("approved"), architect_verdict="approved"),
    ]
    for p in payloads:
        assert forbidden.isdisjoint(p.keys()), f"convergence key leaked: {p.keys()}"


def main() -> int:
    tests = [
        test_is_enabled_env,
        test_disabled_by_default_does_not_call_jury,
        test_enabled_but_no_members_skips_cleanly,
        test_empty_prompt_skips,
        test_enabled_agreement_true,
        test_enabled_disagreement_surfaced,
        test_agreement_none_when_consensus_missing,
        test_ask_raises_is_failsoft,
        test_payload_has_no_convergence_keys,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            import traceback
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failed += 1
    if failed == 0:
        print(f"[OK] {len(tests)} tests passed")
        return 0
    print(f"[FAIL] {failed}/{len(tests)} tests failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
