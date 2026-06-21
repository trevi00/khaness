#!/usr/bin/env python3
"""Tests for M15 external_jury retry+circuit-breaker wiring + CompositeBreaker thresholds.

Covers D2 (thresholds injection back-compat + jury short cap), D3 (classify-in-except,
permanent→record_success, circuit_open skip-fast, finally-safe single record), D4
(behavior-preserving legacy vs breaker, panel resilience, forensic strings).
Auto-discovered via main()->int.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.providers.base import AskResponse, ProviderUnavailableError  # noqa: E402
from lib.breakers.composite import CompositeBreaker, State  # noqa: E402
from lib.breakers.config import BreakerThresholds, resolve_thresholds  # noqa: E402
import engine.external_jury as ej  # noqa: E402
from engine.external_jury import ask_jury, JuryMember  # noqa: E402


class _Fake:
    def __init__(self, name, script):
        self.name = name
        self.script = list(script)
        self.i = 0

    def is_available(self):
        return True

    def ask(self, req):
        a = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        if isinstance(a, Exception):
            raise a
        return AskResponse(text=a, provider=self.name, model=req.model or "def")


def _v(verdict):
    return '{"verdict":"' + verdict + '"}'


# ---- D2: CompositeBreaker thresholds injection (additive, back-compat) ----

def test_breaker_thresholds_injection_backcompat():
    with tempfile.TemporaryDirectory() as td:
        # No thresholds → resolve_thresholds() (global), unchanged for existing callers.
        b = CompositeBreaker("x", "m", "p", base_dir=td)
        assert b._thresholds_or_global() == resolve_thresholds()
        # Injected short cap is used verbatim.
        short = BreakerThresholds(backoff_cap_sec=300)
        b2 = CompositeBreaker("x", "m", "p", base_dir=td, thresholds=short)
        assert b2._thresholds_or_global().backoff_cap_sec == 300


def test_jury_uses_short_cap():
    assert ej.JURY_THRESHOLDS.backoff_cap_sec == 300
    assert ej.JURY_THRESHOLDS.backoff_cap_sec < resolve_thresholds().backoff_cap_sec or \
        resolve_thresholds().backoff_cap_sec == 3600


# ---- D3: classify / breaker behavior ----

def test_classify_jury():
    assert ej._classify_jury(ProviderUnavailableError("x")) == "transient"
    assert ej._classify_jury(TimeoutError()) == "transient"
    assert ej._classify_jury(RuntimeError()) == "transient"   # UNKNOWN → transient
    assert ej._classify_jury(TypeError()) == "permanent"
    assert ej._classify_jury(KeyError()) == "permanent"


def test_permanent_after_acquire_records_success():
    with tempfile.TemporaryDirectory() as td:
        with mock.patch.object(ej, "get_provider", lambda n: _Fake(n, [TypeError("bug")])):
            try:
                ask_jury("p", [JuryMember("cx")], mode="single", retry_breaker=True,
                         sleep_fn=lambda s: None, breaker_base_dir=td)
            except ProviderUnavailableError as e:
                assert "TypeError" in str(e)
        snap = CompositeBreaker("cx", "jury_dispatch", "_external_jury", base_dir=td).snapshot()
        assert snap.state == State.CLOSED and snap.history == (True,)  # record_success, not failure


def test_transient_fail_records_failure_and_retry_exhausted():
    with tempfile.TemporaryDirectory() as td:
        with mock.patch.object(ej, "get_provider", lambda n: _Fake(n, [ProviderUnavailableError("down")])):
            try:
                ask_jury("p", [JuryMember("cx")], mode="single", retry_breaker=True,
                         sleep_fn=lambda s: None, max_attempts=2, breaker_base_dir=td)
                raise AssertionError("expected raise (all failed)")
            except ProviderUnavailableError as e:
                assert "retry_exhausted" in str(e)
        snap = CompositeBreaker("cx", "jury_dispatch", "_external_jury", base_dir=td).snapshot()
        assert snap.history == (False,)  # exactly one record_failure (retries invisible to breaker)


def test_circuit_opens_and_skips_fast():
    with tempfile.TemporaryDirectory() as td:
        with mock.patch.object(ej, "get_provider", lambda n: _Fake(n, [ProviderUnavailableError("down")])):
            for _ in range(3):  # default trip_per_mode=3
                try:
                    ask_jury("p", [JuryMember("flaky")], mode="single", retry_breaker=True,
                             sleep_fn=lambda s: None, max_attempts=1, breaker_base_dir=td)
                except ProviderUnavailableError:
                    pass
            assert CompositeBreaker("flaky", "jury_dispatch", "_external_jury", base_dir=td).snapshot().state == State.OPEN
            try:
                ask_jury("p", [JuryMember("flaky")], mode="single", retry_breaker=True,
                         sleep_fn=lambda s: None, max_attempts=1, breaker_base_dir=td)
            except ProviderUnavailableError as e:
                assert "circuit_open" in str(e)


# ---- D4: behavior-preservation + panel resilience ----

def test_behavior_preserving_legacy_vs_breaker_no_failure():
    with tempfile.TemporaryDirectory() as td:
        with mock.patch.object(ej, "get_provider", lambda n: _Fake(n, [_v("approved")])):
            leg = ask_jury("p", [JuryMember("claude")], mode="single", retry_breaker=False)
            brk = ask_jury("p", [JuryMember("claude")], mode="single", retry_breaker=True,
                           sleep_fn=lambda s: None, breaker_base_dir=td)
        assert leg.consensus_verdict == brk.consensus_verdict == "approved"
        assert leg.members == brk.members
        assert leg.votes == brk.votes


def test_panel_resilience_one_bad_one_good():
    with tempfile.TemporaryDirectory() as td:
        def gp(n):
            return _Fake(n, [ProviderUnavailableError("down")]) if n == "bad" else _Fake(n, [_v("rejected")])
        with mock.patch.object(ej, "get_provider", gp):
            v = ask_jury("p", [JuryMember("bad"), JuryMember("good")], mode="panel",
                         retry_breaker=True, sleep_fn=lambda s: None, max_attempts=1, breaker_base_dir=td)
        assert v.consensus_verdict == "rejected"
        assert any("retry_exhausted" in f for f in v.failures)


def test_probe_ttl_reclaims_orphaned_half_open_probe():
    """M15 follow-up: a half-open probe reserved then never resolved (holder hard-killed)
    must NOT wedge the key forever — a try_acquire after PROBE_TTL_SEC reclaims it."""
    import lib.breakers.composite as cb
    with tempfile.TemporaryDirectory() as td:
        clock = {"t": 1000.0}
        with mock.patch.object(cb, "_now", lambda: clock["t"]):
            b = cb.CompositeBreaker("p", "m", "proj", base_dir=td,
                                    thresholds=BreakerThresholds(backoff_base_sec=10, backoff_cap_sec=10))
            # Trip to OPEN (default trip_per_mode=3).
            for _ in range(3):
                b.record_failure()
            assert b.snapshot().state == State.OPEN
            # Advance past cool_off → try_acquire promotes HALF_OPEN + reserves the probe.
            clock["t"] += 100.0
            assert b.try_acquire() is True
            assert b.snapshot().state == State.HALF_OPEN
            # Holder "dies" — no record_*. A fresh try_acquire is refused (live probe).
            assert b.try_acquire() is False
            # After PROBE_TTL_SEC the orphaned probe is reclaimed (self-heal).
            clock["t"] += cb.PROBE_TTL_SEC + 1
            assert b.try_acquire() is True, "stale half-open probe must be reclaimable"


def test_unknown_provider_skips_without_breaker():
    with tempfile.TemporaryDirectory() as td:
        def gp(n):
            raise KeyError(n)
        with mock.patch.object(ej, "get_provider", gp):
            try:
                ask_jury("p", [JuryMember("nope")], mode="single", retry_breaker=True,
                         sleep_fn=lambda s: None, breaker_base_dir=td)
            except ProviderUnavailableError as e:
                assert "unknown" in str(e)
        # no breaker file created for an unknown provider (never acquired)
        assert not (Path(td) / "breakers" / "_external_jury" / "nope__jury_dispatch.json").exists()


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
