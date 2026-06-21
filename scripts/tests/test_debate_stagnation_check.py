#!/usr/bin/env python3
"""Tests for cli.debate_stagnation_check — the deterministic early-hard-cap seam (M14).

Covers the NEW deterministic surface the debate loop relies on: exit-code contract,
the event-append side effects (forensic + the SOLE terminal convergence event),
per-gen idempotency, the approved self-skip, and the fail-CLOSED paths. The detector
itself (recommend_early_hard_cap) is covered by lib.debate_stagnation._self_check via
test_debate_stagnation.py, so here we patch the recommender to control fire/no-fire
and assert the SEAM behavior. Auto-discovered by run_units.py via main() -> int.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _fake_rec(recommend: bool, reasons=()):
    sig = lambda d: SimpleNamespace(detected=d)  # noqa: E731
    return SimpleNamespace(
        recommend=recommend,
        reasons=tuple(reasons),
        signals={"oscillation": sig(recommend), "stagnation": sig(False),
                 "blocker_plateau": sig(False)},
    )


def _convergence_early_caps(store) -> list:
    return [e for e in store.replay()
            if e.get("type") == "convergence"
            and (e.get("payload") or {}).get("status") == "early_hard_cap"]


def _recs(store) -> list:
    return [e for e in store.replay() if e.get("type") == "early_hard_cap_recommendation"]


def test_fire_appends_one_convergence_and_is_idempotent():
    import cli.debate_stagnation_check as cli
    from lib.event_store import EventStore
    with tempfile.TemporaryDirectory() as td:
        with mock.patch("lib.event_store.DEBATES_DIR", Path(td)):
            with mock.patch.object(cli, "recommend_early_hard_cap",
                                   return_value=_fake_rec(True, ["oscillation"])):
                sid = "debate-test-fire"
                store = EventStore(sid)
                store.append("verdict", 3, "harness-architect", {"verdict": "rejected"})

                result, code = cli.evaluate_for_session(sid, 3, "rejected")
                assert code == cli.EXIT_FIRE, code
                assert result["early_hard_cap"] is True
                assert _convergence_early_caps(store) and len(_convergence_early_caps(store)) == 1
                assert len(_recs(store)) == 1

                # idempotent re-run: still terminates (exit 3) but appends NOTHING new
                result2, code2 = cli.evaluate_for_session(sid, 3, "rejected")
                assert code2 == cli.EXIT_FIRE and result2["skipped"] is True
                assert len(_convergence_early_caps(store)) == 1, "no second convergence"
                assert len(_recs(store)) == 1, "no second recommendation"


def test_no_fire_logs_forensic_only_no_convergence():
    import cli.debate_stagnation_check as cli
    from lib.event_store import EventStore
    with tempfile.TemporaryDirectory() as td:
        with mock.patch("lib.event_store.DEBATES_DIR", Path(td)):
            with mock.patch.object(cli, "recommend_early_hard_cap",
                                   return_value=_fake_rec(False)):
                sid = "debate-test-nofire"
                store = EventStore(sid)
                store.append("verdict", 2, "harness-architect", {"verdict": "conditional"})
                result, code = cli.evaluate_for_session(sid, 2, "conditional")
                assert code == cli.EXIT_CLEAN and result["early_hard_cap"] is False
                assert _convergence_early_caps(store) == []          # no fire -> no convergence
                assert len(_recs(store)) == 1                        # forensic trail preserved
                assert _recs(store)[0]["payload"]["recommend"] is False


def test_approved_self_skips_no_append():
    import cli.debate_stagnation_check as cli
    from lib.event_store import EventStore
    with tempfile.TemporaryDirectory() as td:
        with mock.patch("lib.event_store.DEBATES_DIR", Path(td)):
            sid = "debate-test-approved"
            result, code = cli.evaluate_for_session(sid, 2, "approved")
            assert code == cli.EXIT_CLEAN and result["skipped"] is True
            assert EventStore(sid).replay() == []                    # nothing written


def test_missing_verdict_fails_closed():
    import cli.debate_stagnation_check as cli
    from lib.event_store import EventStore
    with tempfile.TemporaryDirectory() as td:
        with mock.patch("lib.event_store.DEBATES_DIR", Path(td)):
            sid = "debate-test-missing"
            result, code = cli.evaluate_for_session(sid, 2, None)
            assert code == cli.EXIT_ERROR, "missing verdict must fail-CLOSED, not silent-skip"
            assert result["error"] and "parse_failure" in result["error"]
            assert EventStore(sid).replay() == []


def test_main_internal_error_exits_4():
    import cli.debate_stagnation_check as cli
    with tempfile.TemporaryDirectory() as td:
        with mock.patch("lib.event_store.DEBATES_DIR", Path(td)):
            with mock.patch.object(cli, "recommend_early_hard_cap",
                                   side_effect=RuntimeError("boom")):
                rc = cli.main(["--session-id", "debate-test-err", "--gen", "3",
                               "--verdict", "rejected"])
                assert rc == cli.EXIT_ERROR, "internal error must map to fail-closed exit 4"


def test_main_argparse_usage_error_is_exit_2():
    import cli.debate_stagnation_check as cli
    try:
        cli.main(["--gen", "3"])  # missing required --session-id
    except SystemExit as e:
        assert e.code == 2, "argparse usage error must stay exit 2 (reserved, not a fire signal)"
    else:
        raise AssertionError("expected SystemExit(2) on missing required arg")


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
