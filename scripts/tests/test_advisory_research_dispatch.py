#!/usr/bin/env python3
"""Tests for lib/advisory_research_dispatch.py — advisory-HIGH as 2nd dispatch source
+ cross-session blocklist (research-subsystem debate D2/D4)."""
from __future__ import annotations

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


def test_fingerprint_deterministic_and_namespaced():
    from lib.advisory_research_dispatch import advisory_fingerprint
    a = advisory_fingerprint("falsy_zero", "lib/x.py:42 numeric or time.time")
    b = advisory_fingerprint("falsy_zero", "lib/x.py:42  numeric   or time.time")  # ws-normalized
    assert a == b, "whitespace-normalized keys must map to the same fingerprint"
    assert a.startswith("adv:") and len(a) == 4 + 12
    # different validator/key -> different fingerprint
    assert advisory_fingerprint("spec_bundle", "lib/x.py:42") != a


def test_high_dispatches_first_occurrence():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.advisory_research_dispatch import should_dispatch_advisory
        ok, fp = should_dispatch_advisory("falsy_zero", "k1", "orch-1", severity="HIGH")
        assert ok is True and fp.startswith("adv:")


def test_med_low_never_dispatch():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.advisory_research_dispatch import should_dispatch_advisory
        assert should_dispatch_advisory("v", "k", "orch-1", severity="MEDIUM")[0] is False
        assert should_dispatch_advisory("v", "k", "orch-1", severity="LOW")[0] is False


def test_blocklist_suppresses_cross_session():
    """The core D4 guarantee: once closed as unfixable, the SAME finding does not
    re-dispatch in a FRESH session (new sid, empty per-sid quota)."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.advisory_research_dispatch import (
            should_dispatch_advisory, blocklist_close, advisory_fingerprint, is_blocklisted)
        fp = advisory_fingerprint("falsy_zero", "k1")
        # session 1: dispatches
        assert should_dispatch_advisory("falsy_zero", "k1", "orch-1", severity="HIGH")[0] is True
        # researcher gives up -> close
        blocklist_close(fp)
        assert is_blocklisted(fp) is True
        # session 2 (fresh sid): suppressed despite empty per-sid quota
        assert should_dispatch_advisory("falsy_zero", "k1", "orch-2-FRESH", severity="HIGH")[0] is False


def test_blocklist_failsoft_on_corrupt():
    """on_corrupt='empty' — a corrupt blocklist store reads empty (dispatch proceeds),
    never raising into the dispatch path (fail-soft, opposite of strike_dispatcher)."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.advisory_research_dispatch import _BLOCKLIST, _GLOBAL_SID, is_blocklisted
        p = _BLOCKLIST.path(_GLOBAL_SID)
        p.write_text("{ this is not valid json", encoding="utf-8")
        # fail-soft: corrupt -> treated as empty -> not blocklisted, no exception
        assert is_blocklisted("adv:deadbeef0000") is False


def test_per_fingerprint_quota_still_bounds_in_session():
    """Advisory dispatch reuses the strike per-(sid,fingerprint) quota so in-session
    recursion is bounded identically to N-strike."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.advisory_research_dispatch import (
            should_dispatch_advisory, record_advisory_dispatch, advisory_fingerprint)
        from lib.strike_dispatcher import PER_FINGERPRINT_DISPATCH_LIMIT
        fp = advisory_fingerprint("v", "k")
        for _ in range(PER_FINGERPRINT_DISPATCH_LIMIT):
            assert should_dispatch_advisory("v", "k", "orch-1", severity="HIGH")[0] is True
            record_advisory_dispatch(fp, "orch-1")
        # quota exhausted in this sid
        assert should_dispatch_advisory("v", "k", "orch-1", severity="HIGH")[0] is False


def main() -> int:
    tests = [
        test_fingerprint_deterministic_and_namespaced,
        test_high_dispatches_first_occurrence,
        test_med_low_never_dispatch,
        test_blocklist_suppresses_cross_session,
        test_blocklist_failsoft_on_corrupt,
        test_per_fingerprint_quota_still_bounds_in_session,
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
