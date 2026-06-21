#!/usr/bin/env python3
"""Tests for lib/quota_tracker.py — the shared per-(sid,key) dispatch counter (M10).

Covers BOTH corruption policies the two original call sites needed:
  - on_corrupt='raise' + value_mode='coerce'  (strike_dispatcher: fail-closed)
  - on_corrupt='empty' + value_mode='filter'  (evaluator_dispatcher: fail-soft)
plus the shared mechanics (cold start, atomic increment, remaining, reset, sid/key
validation). State is redirected to a temp dir by patching lib.paths.STATE_DIR.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _redirect_state(td: Path):
    import lib.paths as paths
    paths.STATE_DIR = td


def test_cold_start_returns_empty():
    from lib.quota_tracker import QuotaCounter
    with tempfile.TemporaryDirectory() as td:
        _redirect_state(Path(td))
        qc = QuotaCounter("orchestrator")
        assert qc.load("sid-cold") == {}
        assert qc.get("sid-cold", "k") == 0


def test_record_increments_and_persists():
    from lib.quota_tracker import QuotaCounter
    with tempfile.TemporaryDirectory() as td:
        _redirect_state(Path(td))
        qc = QuotaCounter("evaluator")
        assert qc.record("s", "a") == 1
        assert qc.record("s", "a") == 2
        assert qc.record("s", "b") == 1
        c = qc.load("s")
        assert c == {"a": 2, "b": 1}


def test_remaining_and_reset():
    from lib.quota_tracker import QuotaCounter
    with tempfile.TemporaryDirectory() as td:
        _redirect_state(Path(td))
        qc = QuotaCounter("orchestrator")
        assert qc.remaining("s", "a", 3) == 3
        qc.record("s", "a")
        assert qc.remaining("s", "a", 3) == 2
        assert qc.path("s").exists()
        qc.reset("s")
        assert not qc.path("s").exists()
        assert qc.load("s") == {}


def test_empty_sid_and_key_rejected():
    from lib.quota_tracker import QuotaCounter
    with tempfile.TemporaryDirectory() as td:
        _redirect_state(Path(td))
        qc = QuotaCounter("orchestrator")
        for bad in ("", None, 5):
            try:
                qc.path(bad)  # type: ignore[arg-type]
            except ValueError:
                pass
            else:
                raise AssertionError(f"expected ValueError on sid={bad!r}")
        try:
            qc.record("s", "")
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError on empty key")


def test_raise_policy_fail_closed_on_corrupt():
    """strike's policy: malformed JSON -> RuntimeError ('counter corrupt')."""
    from lib.quota_tracker import QuotaCounter
    with tempfile.TemporaryDirectory() as td:
        _redirect_state(Path(td))
        qc = QuotaCounter("orchestrator", on_corrupt="raise", value_mode="coerce",
                          label="strike_dispatcher")
        qc.path("s-corrupt").write_text("{not json", encoding="utf-8")
        try:
            qc.load("s-corrupt")
        except RuntimeError as e:
            assert "counter corrupt" in str(e)
        else:
            raise AssertionError("expected RuntimeError (fail-closed)")


def test_raise_policy_non_object_raises_json_object():
    from lib.quota_tracker import QuotaCounter
    with tempfile.TemporaryDirectory() as td:
        _redirect_state(Path(td))
        qc = QuotaCounter("orchestrator", on_corrupt="raise", value_mode="coerce",
                          label="strike_dispatcher")
        qc.path("s-list").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        try:
            qc.load("s-list")
        except RuntimeError as e:
            assert "JSON object" in str(e)
        else:
            raise AssertionError("expected RuntimeError on non-object")


def test_empty_policy_fail_soft_on_corrupt():
    """evaluator's policy: malformed/non-object -> {} (no raise)."""
    from lib.quota_tracker import QuotaCounter
    with tempfile.TemporaryDirectory() as td:
        _redirect_state(Path(td))
        qc = QuotaCounter("evaluator", on_corrupt="empty", value_mode="filter")
        qc.path("s1").write_text("{not json", encoding="utf-8")
        assert qc.load("s1") == {}            # malformed -> soft
        qc.path("s2").write_text(json.dumps([1, 2]), encoding="utf-8")
        assert qc.load("s2") == {}            # non-object -> soft


def test_filter_mode_drops_bad_values():
    """filter: keep only non-negative non-bool ints."""
    from lib.quota_tracker import QuotaCounter
    with tempfile.TemporaryDirectory() as td:
        _redirect_state(Path(td))
        qc = QuotaCounter("evaluator", on_corrupt="empty", value_mode="filter")
        qc.path("s").write_text(
            json.dumps({"ok": 3, "neg": -1, "boolt": True, "str": "x", "flo": 1.5}),
            encoding="utf-8")
        assert qc.load("s") == {"ok": 3}


def test_coerce_mode_coerces_values():
    """coerce: int(v) every value (int(True)==1), matching legacy strike."""
    from lib.quota_tracker import QuotaCounter
    with tempfile.TemporaryDirectory() as td:
        _redirect_state(Path(td))
        qc = QuotaCounter("orchestrator", on_corrupt="raise", value_mode="coerce")
        qc.path("s").write_text(json.dumps({"a": 2, "b": True, "c": 0}),
                                encoding="utf-8")
        assert qc.load("s") == {"a": 2, "b": 1, "c": 0}


def test_coerce_mode_non_numeric_under_raise_is_corrupt():
    from lib.quota_tracker import QuotaCounter
    with tempfile.TemporaryDirectory() as td:
        _redirect_state(Path(td))
        qc = QuotaCounter("orchestrator", on_corrupt="raise", value_mode="coerce")
        qc.path("s").write_text(json.dumps({"a": "not-a-number"}), encoding="utf-8")
        try:
            qc.load("s")
        except RuntimeError as e:
            assert "non-numeric" in str(e)
        else:
            raise AssertionError("expected RuntimeError on non-numeric value")


def test_constructor_validates_args():
    from lib.quota_tracker import QuotaCounter
    for kwargs in (
        {"subsystem": ""},
        {"subsystem": "x", "on_corrupt": "bogus"},
        {"subsystem": "x", "value_mode": "bogus"},
    ):
        try:
            QuotaCounter(**kwargs)  # type: ignore[arg-type]
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {kwargs}")


def test_separate_subsystems_isolated():
    """Two QuotaCounters on different subsystems do not share state."""
    from lib.quota_tracker import QuotaCounter
    with tempfile.TemporaryDirectory() as td:
        _redirect_state(Path(td))
        a = QuotaCounter("orchestrator")
        b = QuotaCounter("evaluator")
        a.record("s", "k")
        assert a.get("s", "k") == 1
        assert b.get("s", "k") == 0          # different subdir, isolated


def main() -> int:
    tests = [
        test_cold_start_returns_empty,
        test_record_increments_and_persists,
        test_remaining_and_reset,
        test_empty_sid_and_key_rejected,
        test_raise_policy_fail_closed_on_corrupt,
        test_raise_policy_non_object_raises_json_object,
        test_empty_policy_fail_soft_on_corrupt,
        test_filter_mode_drops_bad_values,
        test_coerce_mode_coerces_values,
        test_coerce_mode_non_numeric_under_raise_is_corrupt,
        test_constructor_validates_args,
        test_separate_subsystems_isolated,
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
