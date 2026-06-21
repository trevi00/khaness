#!/usr/bin/env python3
"""Tests for lib.debate_convergence + cli.debate_converge_check (M24).

The deterministic convergence + severity-invalidate seam. Covers the pure rule
(evaluate_convergence) and the CLI's single-event-append + idempotency + exit codes.
Auto-discovered by run_units.py via main()->int.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.debate_convergence import evaluate_convergence, snapshot_sha1  # noqa: E402

_F = [{"id": "D1", "type": "api", "value": "x"}]
_G = [{"id": "D2", "type": "api", "value": "y"}]


def _v(gen, verdict, fields):
    return {"type": "verdict", "gen": gen, "payload": {"verdict": verdict, "ontology_snapshot": {"fields": fields}}}


# ---- pure rule ----

def test_snapshot_sha1_stable_and_order_invariant():
    a = snapshot_sha1([{"a": 1, "b": 2}])
    b = snapshot_sha1([{"b": 2, "a": 1}])  # key order normalized
    assert a == b and a is not None
    assert snapshot_sha1(None) is None and snapshot_sha1([]) is None


def test_gen1_approved_converges():
    assert evaluate_convergence([_v(1, "approved", _F)], 1).converged is True


def test_gen2_approved_matching_sha_converges():
    r = evaluate_convergence([_v(1, "approved", _F), _v(2, "approved", _F)], 2)
    assert r.converged is True and r.status == "converged" and r.this_sha == r.prev_sha


# ---- M10 D4: same-gen verdict conflict fail-closed (debate-1781937446-1281b5) ----

def test_same_gen_conflicting_verdict_fail_closed():
    # two gen-1 verdicts that DISAGREE on the verdict string -> ambiguous -> fail-closed
    r = evaluate_convergence([_v(1, "approved", _F), _v(1, "rejected", _F)], 1)
    assert r.converged is False and r.error == "verdict_ambiguous" and r.status == "rejected"


def test_same_gen_conflicting_sha_fail_closed():
    # same verdict but DIFFERENT snapshot fields -> sha mismatch -> ambiguous
    # (this is the gen-1 Critic blocker the verdict-only compare would have missed)
    r = evaluate_convergence([_v(1, "approved", _F), _v(1, "approved", _G)], 1)
    assert r.converged is False and r.error == "verdict_ambiguous"


def test_same_gen_idempotent_reappend_tolerated():
    # identical re-append (same verdict AND same fields) is NOT a conflict -> converges
    r = evaluate_convergence([_v(1, "approved", _F), _v(1, "approved", _F)], 1)
    assert r.converged is True and r.error is None


def test_conflict_marker_does_not_un_conflict_on_third_event():
    # once conflicted, a later matching event must NOT clear the conflict
    evs = [_v(1, "approved", _F), _v(1, "rejected", _G), _v(1, "approved", _F)]
    r = evaluate_convergence(evs, 1)
    assert r.converged is False and r.error == "verdict_ambiguous"


def test_conflicted_prev_gen_no_crash_no_spurious_converge():
    # gen-1 conflicted, gen-2 approved with different fields: gen-2 must not crash
    # and must not spuriously converge off the conflicted prev gen
    evs = [_v(1, "approved", _F), _v(1, "rejected", _G), _v(2, "approved", _F)]
    assert evaluate_convergence(evs, 1).error == "verdict_ambiguous"
    assert evaluate_convergence(evs, 2).converged is False


def test_conflicted_prev_gen_matching_last_fields_no_spurious_converge():
    # deep-audit rank 5 (reproduced hole): gen-2 approved matching the conflicted
    # prev gen's LAST-WRITTEN fields (_G) must NOT converge. The sibling test above
    # used different fields (_F) and missed this exact violating sequence — a
    # conflicted prev must yield prev_sha=None, not the last conflicting snapshot.
    evs = [_v(1, "approved", _F), _v(1, "rejected", _G), _v(2, "approved", _G)]
    r = evaluate_convergence(evs, 2)
    assert r.converged is False, "spurious converge against conflicted prev gen's last fields"
    assert r.prev_sha is None


def test_gen2_approved_different_sha_not_converged():
    r = evaluate_convergence([_v(1, "approved", _F), _v(2, "approved", _G)], 2)
    assert r.converged is False and r.this_sha != r.prev_sha


def test_conditional_continues():
    r = evaluate_convergence([_v(1, "conditional", _F)], 1)
    assert r.converged is False and r.status == "conditional"


def test_severity_invalidate_forces_rejected():
    events = [_v(1, "approved", _F), _v(2, "approved", _F),
              {"type": "verdict_invalidated_by_severity", "gen": 2, "payload": {}}]
    r = evaluate_convergence(events, 2)
    assert r.converged is False and r.effective_verdict == "rejected" and r.severity_invalidated
    assert "severity=invalidate" in r.reason


def test_missing_verdict_fail_closed():
    r = evaluate_convergence([], 3)
    assert r.error == "verdict_missing" and r.converged is False


# ---- CLI: event append + idempotency + exit codes ----

def test_cli_converged_appends_event_exit3():
    import cli.debate_converge_check as cli
    from lib.event_store import EventStore
    with tempfile.TemporaryDirectory() as td:
        with mock.patch("lib.event_store.DEBATES_DIR", Path(td)):
            sid = "debate-test-conv"
            store = EventStore(sid)
            store.append("verdict", 1, "harness-architect", {"verdict": "approved", "ontology_snapshot": {"fields": _F}})
            store.append("verdict", 2, "harness-architect", {"verdict": "approved", "ontology_snapshot": {"fields": _F}})
            result, code = cli.run(sid, 2)
            assert code == cli.EXIT_CONVERGED and result["converged"] is True
            convs = [e for e in store.replay() if e.get("type") == "convergence"
                     and (e.get("payload") or {}).get("status") == "converged"]
            assert len(convs) == 1
            # idempotent re-run: still exit 3, no second event
            result2, code2 = cli.run(sid, 2)
            assert code2 == cli.EXIT_CONVERGED and result2["skipped"] is True
            convs2 = [e for e in store.replay() if e.get("type") == "convergence"
                      and (e.get("payload") or {}).get("status") == "converged"]
            assert len(convs2) == 1


def test_cli_conditional_exit0():
    import cli.debate_converge_check as cli
    from lib.event_store import EventStore
    with tempfile.TemporaryDirectory() as td:
        with mock.patch("lib.event_store.DEBATES_DIR", Path(td)):
            sid = "debate-test-cond"
            EventStore(sid).append("verdict", 1, "harness-architect",
                                   {"verdict": "conditional", "ontology_snapshot": {"fields": _F}})
            result, code = cli.run(sid, 1)
            assert code == cli.EXIT_CONTINUE and result["status"] == "conditional"


def test_cli_missing_verdict_fail_closed_exit4():
    import cli.debate_converge_check as cli
    with tempfile.TemporaryDirectory() as td:
        with mock.patch("lib.event_store.DEBATES_DIR", Path(td)):
            result, code = cli.run("debate-test-empty", 1)
            assert code == cli.EXIT_ERROR and result["error"]


def test_cli_argparse_usage_exit2():
    import cli.debate_converge_check as cli
    try:
        cli.main(["--gen", "1"])  # missing --session-id
    except SystemExit as e:
        assert e.code == 2
    else:
        raise AssertionError("expected SystemExit(2)")


def main() -> int:
    failed = 0
    n = 0
    for name, obj in list(globals().items()):
        if not name.startswith("test_"):
            continue
        n += 1
        try:
            obj()
            print(f"  [OK] {name}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [ERR] {name}: {e!r}")
    if failed:
        print(f"\n{failed}/{n} failed")
        return 1
    print(f"\n[OK] {n} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
