#!/usr/bin/env python3
"""Unit tests for lib/graduation.py — validator advisory→blocking graduation
streak tracker + token-gated flip (Track 1 debate-1780722434-e5h19n gen-2).

Hermetic: graduation.STATE_DIR is redirected to a temp dir per test, and the
tick is driven by INJECTED scan_fn/watermark_fn (no real validator scan, no real
clock — `now` is passed explicitly). Covers D1a dedup / C9 mtime-watermark /
C10 exception-safety + STATE_DIR-lazy / D5 demote-asymmetry + circuit-breaker /
D2 GRADUATED_NAMES concat.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import graduation as g  # noqa: E402

W = g.DEDUP_WINDOW_SECONDS  # 43200
NAME = "doc_code_drift"


class _Tmp:
    """Redirect graduation state to a fresh temp dir (covers C10 — the module
    reads STATE_DIR from its global namespace at call time)."""
    def __enter__(self):
        self._td = tempfile.TemporaryDirectory()
        self._saved = g.STATE_DIR
        g.STATE_DIR = Path(self._td.name)
        return self

    def __exit__(self, *exc):
        g.STATE_DIR = self._saved
        self._td.cleanup()


def _const_drift(value):
    """scan_fn that always reports `value` drift (and records call count)."""
    calls = {"n": 0}
    def fn(name):
        calls["n"] += 1
        return value
    fn.calls = calls
    return fn


def test_tick_increment_on_clean():
    with _Tmp():
        st = g.load_state()
        a = g.tick_validator(st, NAME, now=1000.0, scan_fn=_const_drift(0),
                             watermark_fn=lambda: 5.0)
        assert a == "increment"
        assert st["validators"][NAME]["consecutive_clean"] == 1
        assert st["validators"][NAME]["last_total_drift"] == 0


def test_tick_reset_on_drift():
    with _Tmp():
        st = g.load_state()
        e = g._entry(st, NAME)
        e["consecutive_clean"] = 5
        e["last_scan_epoch"] = 0.0
        a = g.tick_validator(st, NAME, now=W + 1, scan_fn=_const_drift(3),
                             watermark_fn=lambda: 9.0)
        assert a == "reset"
        assert e["consecutive_clean"] == 0
        assert e["ready"] is False


def test_tick_dedup_skip_leaves_streak_untouched():
    with _Tmp():
        st = g.load_state()
        e = g._entry(st, NAME)
        e["consecutive_clean"] = 4
        e["last_scan_epoch"] = 1000.0
        scan = _const_drift(0)
        a = g.tick_validator(st, NAME, now=1000.0 + W - 1, scan_fn=scan,
                             watermark_fn=lambda: 1.0)
        assert a == "skip-dedup"
        assert e["consecutive_clean"] == 4, "dedup-skip must NOT touch the streak"
        assert scan.calls["n"] == 0, "dedup-skip must NOT run the expensive scan"


def test_mtime_watermark_shortcircuits_scan_but_still_advances():
    # C9: content unchanged since last clean scan (watermark not exceeded) →
    # reuse last_total_drift (0), advance the streak WITHOUT calling scan_fn.
    with _Tmp():
        st = g.load_state()
        e = g._entry(st, NAME)
        e["consecutive_clean"] = 2
        e["last_scan_epoch"] = 0.0
        e["last_total_drift"] = 0
        e["last_watermark"] = 100.0
        def boom(name):
            raise AssertionError("scan_fn must NOT be called when watermark unchanged")
        a = g.tick_validator(st, NAME, now=W + 1, scan_fn=boom,
                             watermark_fn=lambda: 100.0)  # <= prior watermark
        assert a == "increment"
        assert e["consecutive_clean"] == 3


def test_watermark_increase_forces_real_scan():
    with _Tmp():
        st = g.load_state()
        e = g._entry(st, NAME)
        e["last_total_drift"] = 0
        e["last_watermark"] = 100.0
        e["last_scan_epoch"] = 0.0
        scan = _const_drift(2)  # content changed → drift now present
        a = g.tick_validator(st, NAME, now=W + 1, scan_fn=scan,
                             watermark_fn=lambda: 200.0)  # > prior watermark
        assert scan.calls["n"] == 1, "watermark increase must trigger a real scan"
        assert a == "reset"


def test_streak_reaches_threshold_sets_ready():
    with _Tmp():
        st = g.load_state()
        for i in range(g.GRADUATION_THRESHOLD):
            g.tick_validator(st, NAME, now=(i + 1) * (W + 1),
                             scan_fn=_const_drift(0), watermark_fn=lambda: float(i + 1))
        e = st["validators"][NAME]
        assert e["consecutive_clean"] == g.GRADUATION_THRESHOLD
        assert e["ready"] is True


def test_exception_leaves_counter_unchanged():
    # C10: a raising scan must leave streak + epoch exactly as they were.
    with _Tmp():
        st = g.load_state()
        e = g._entry(st, NAME)
        e["consecutive_clean"] = 7
        e["last_scan_epoch"] = 0.0
        def boom(name):
            raise RuntimeError("disk flaked")
        a = g.tick_validator(st, NAME, now=W + 1, scan_fn=boom,
                             watermark_fn=lambda: 999.0)
        assert a == "error-untouched"
        assert e["consecutive_clean"] == 7, "exception must NOT reset the streak"
        assert e["last_scan_epoch"] == 0.0, "exception must NOT advance the epoch"


def test_graduate_requires_token():
    with _Tmp():
        st = g.load_state()
        g._entry(st, NAME)["ready"] = True
        g.save_state(st)
        try:
            g.graduate(NAME, token="")
            assert False, "empty token must be refused"
        except g.TokenError:
            pass
        try:
            g.graduate(NAME, token="enable-skill")
            assert False, "wrong token must be refused"
        except g.TokenError:
            pass


def test_graduate_requires_ready():
    with _Tmp():
        st = g.load_state()
        g._entry(st, NAME)["ready"] = False
        g.save_state(st)
        try:
            g.graduate(NAME, token=g.TOKEN_GRADUATE)
            assert False, "un-ready validator must be refused even with token"
        except g.TokenError as e:
            assert "not ready" in str(e)


def test_graduate_success_and_concat():
    with _Tmp():
        st = g.load_state()
        g._entry(st, NAME)["ready"] = True
        g.save_state(st)
        g.graduate(NAME, token=g.TOKEN_GRADUATE)
        assert g.graduated_names() == (NAME,)
        assert g.is_graduated(NAME) is True
        # D2/C3 concat formula: graduated name appends onto the builtin tuple.
        from validators import _BUILTIN
        combined = _BUILTIN + g.graduated_names()
        assert NAME in combined and combined.count(NAME) == 1


def test_demote_safe_token_only():
    with _Tmp():
        st = g.load_state()
        e = g._entry(st, NAME)
        e["ready"] = True
        e["graduated"] = True
        e["consecutive_clean"] = g.GRADUATION_THRESHOLD
        g.save_state(st)
        # wrong token refused
        try:
            g.demote(NAME, token="nonsense")
            assert False
        except g.TokenError:
            pass
        # safe-direction token (apply-user-preference) accepted, streak reset
        g.demote(NAME, token=g.TOKEN_DEMOTE)
        assert g.is_graduated(NAME) is False
        assert g.load_state()["validators"][NAME]["consecutive_clean"] == 0


def test_circuit_breaker_auto_demotes_fresh_graduate_on_drift():
    with _Tmp():
        st = g.load_state()
        e = g._entry(st, NAME)
        e["graduated"] = True
        e["runs_since_graduation"] = 0
        e["last_scan_epoch"] = 0.0
        a = g.tick_validator(st, NAME, now=W + 1, scan_fn=_const_drift(4),
                             watermark_fn=lambda: 5.0)
        assert a == "circuit-breaker-demote"
        assert e["graduated"] is False, "fresh graduate must auto-demote on first drift"


def test_circuit_breaker_demotes_through_boundary_run_k():
    """Verification (2026-06-17): the breaker fires THROUGH runs_since_graduation
    == K (the condition is `<= K`), not only on the very first post-grad run."""
    with _Tmp():
        st = g.load_state()
        e = g._entry(st, NAME)
        e["graduated"] = True
        e["runs_since_graduation"] = g.CIRCUIT_BREAKER_K - 1  # +1 in tick -> == K
        e["last_scan_epoch"] = 0.0
        a = g.tick_validator(st, NAME, now=W + 1, scan_fn=_const_drift(2),
                             watermark_fn=lambda: 5.0)
        assert a == "circuit-breaker-demote"
        assert e["runs_since_graduation"] == g.CIRCUIT_BREAKER_K
        assert e["graduated"] is False


def test_circuit_breaker_does_not_demote_after_k_stays_blocking():
    """Verification (2026-06-17): the breaker is a HONEYMOON-only safety net.
    After K post-graduation runs, drift does NOT auto-demote — the validator
    STAYS blocking (run_all [FAIL]) and the streak hard-resets. This is exactly
    the enforcing behavior graduation exists to provide; the breaker only guards
    the early-life window against a prematurely-graduated validator."""
    with _Tmp():
        st = g.load_state()
        e = g._entry(st, NAME)
        e["graduated"] = True
        e["runs_since_graduation"] = g.CIRCUIT_BREAKER_K + 1  # +1 in tick -> > K
        e["last_scan_epoch"] = 0.0
        e["consecutive_clean"] = 20
        a = g.tick_validator(st, NAME, now=W + 1, scan_fn=_const_drift(3),
                             watermark_fn=lambda: 5.0)
        assert a == "reset", a
        assert e["graduated"] is True, "a proven-stable validator must stay blocking on drift"
        assert e["consecutive_clean"] == 0


def test_circuit_breaker_writes_audit_history_record():
    """Verification (2026-06-17): a circuit-breaker demote appends a
    `circuit_breaker_demote` record to graduation-history.jsonl (M13-observable)."""
    import json
    with _Tmp():
        st = g.load_state()
        e = g._entry(st, NAME)
        e["graduated"] = True
        e["runs_since_graduation"] = 0
        e["last_scan_epoch"] = 0.0
        g.tick_validator(st, NAME, now=W + 1, scan_fn=_const_drift(7),
                         watermark_fn=lambda: 5.0)
        recs = [json.loads(ln) for ln in
                g._history_path().read_text(encoding="utf-8").splitlines() if ln.strip()]
        cb = [r for r in recs if r.get("action") == "circuit_breaker_demote"]
        assert cb, "circuit-breaker demote must append an audit record"
        assert cb[-1]["validator"] == NAME and cb[-1]["total_drift"] == 7


def test_run_tracked_scans_and_tick_circuit_breaker_demotes_end_to_end():
    """Verification (2026-06-17): the PRODUCTION entrypoint
    (SessionStart-amortized run_tracked_scans_and_tick) auto-demotes graduated
    validators on drift end-to-end — not only the low-level tick_validator."""
    with _Tmp():
        st = g.load_state()
        for n in g.TRACKED:
            ee = g._entry(st, n)
            ee["graduated"] = True
            ee["runs_since_graduation"] = 0
            ee["last_scan_epoch"] = 0.0
        g.save_state(st)
        actions = g.run_tracked_scans_and_tick(now=W + 1, scan_fn=_const_drift(1),
                                               watermark_fn=lambda: 9.0)
        assert all(v == "circuit-breaker-demote" for v in actions.values()), actions
        after = g.load_state()
        assert not any(after["validators"][n].get("graduated") for n in g.TRACKED)


def test_is_graduated_failsoft_on_garbled_state():
    with _Tmp():
        (g.STATE_DIR / "graduation-state.json").write_text("{ not json", encoding="utf-8")
        assert g.is_graduated(NAME) is False
        assert g.graduated_names() == ()


def test_run_tracked_scans_and_tick_isolates_failures():
    with _Tmp():
        def selective(name):
            if name == "self_model_drift":
                raise RuntimeError("one validator flaked")
            return 0
        actions = g.run_tracked_scans_and_tick(now=W + 1, scan_fn=selective,
                                               watermark_fn=lambda: 1.0)
        assert actions["doc_code_drift"] == "increment"
        assert actions["self_model_drift"] == "error-untouched"
        # the healthy validator's streak persisted; the flaky one's did not move
        st = g.load_state()
        assert st["validators"]["doc_code_drift"]["consecutive_clean"] == 1
        assert st["validators"]["self_model_drift"]["consecutive_clean"] == 0


def test_claim_verifier_not_tracked():
    # D3: claim_verifier is advisory-only, NOT graduation-eligible this gen.
    assert "claim_verifier" not in g.TRACKED


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            import traceback
            failed += 1
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
    if failed:
        print(f"[FAIL] {failed}/{len(tests)} failed")
        return 1
    print(f"[OK] {len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
