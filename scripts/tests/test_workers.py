#!/usr/bin/env python3
"""Regression for lib/workers/ — the multiplexer registry + fallback chain.

Closes a coverage gap (harness review 2026-06-20, lane E): lib/workers/ is the
OCP extension point that spawns every /harness-team + /harness-ultrawork pane
("new multiplexer = new file + one registry line"), yet had ZERO tests. This
pins the registry resolution (get_multiplexer / detect_best / _REGISTRY_ORDER),
the missing-export and all-unavailable error paths, and a real spawn/list/kill
round-trip on the always-available subprocess_fallback backend.

Run: cd ~/.claude/scripts && python tests/test_workers.py
"""
from __future__ import annotations

import sys
import types
import uuid
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import workers as W  # noqa: E402
from lib.workers.base import (  # noqa: E402
    MultiplexerBase,
    WorkerHandle,
    WorkerUnavailableError,
)

_PASS = 0
_FAIL = 0


def _ok(msg: str) -> None:
    global _PASS
    _PASS += 1
    print(f"  [OK]   {msg}")


def _fail(msg: str) -> None:
    global _FAIL
    _FAIL += 1
    print(f"  [FAIL] {msg}")


def _check(cond: bool, msg: str) -> None:
    _ok(msg) if cond else _fail(msg)


class _FakeMux(MultiplexerBase):
    """Minimal concrete MultiplexerBase for registry-resolution tests."""

    def __init__(self, available: bool, name: str = "fake") -> None:
        self._avail = available
        self.name = name

    def is_available(self) -> bool:
        return self._avail

    def spawn(self, command, *, session, worker_id, cwd=None, env=None):  # noqa: ANN001
        raise NotImplementedError

    def list_workers(self, session):  # noqa: ANN001
        return []

    def kill(self, handle):  # noqa: ANN001
        return False

    def kill_session(self, session):  # noqa: ANN001
        return 0


def test_registry_resolves_subprocess_fallback() -> None:
    print("test_registry_resolves_subprocess_fallback")
    mux = W.get_multiplexer("subprocess_fallback")
    _check(isinstance(mux, MultiplexerBase), "get_multiplexer returns a MultiplexerBase")
    _check(mux.is_available() is True, "subprocess_fallback is always available (stdlib only)")
    _check(mux.name == "subprocess", "name == 'subprocess'")
    _check("subprocess_fallback" in W._REGISTRY_ORDER, "subprocess_fallback is in _REGISTRY_ORDER")


def test_get_multiplexer_missing_export_raises() -> None:
    print("test_get_multiplexer_missing_export_raises")
    fake_mod = types.ModuleType("lib.workers._fake_no_export")  # no MULTIPLEXER attr
    orig = W.import_module
    W.import_module = lambda name: fake_mod  # type: ignore[assignment]
    try:
        try:
            W.get_multiplexer("_fake_no_export")
            _fail("module without MULTIPLEXER export should raise RuntimeError")
        except RuntimeError as e:
            _check("MULTIPLEXER" in str(e), "missing MULTIPLEXER export -> RuntimeError naming it")
    finally:
        W.import_module = orig  # type: ignore[assignment]


def test_get_multiplexer_unknown_module_raises() -> None:
    print("test_get_multiplexer_unknown_module_raises")
    try:
        W.get_multiplexer("definitely_not_a_real_adapter")
        _fail("unknown adapter name should raise")
    except (ModuleNotFoundError, ImportError):
        _ok("unknown adapter name -> ImportError/ModuleNotFoundError")


def test_detect_best_picks_first_available() -> None:
    print("test_detect_best_picks_first_available (fallback chain order)")
    # First registered (psmux_adapter) unavailable, fallback available -> fallback wins.
    fakes = {
        "psmux_adapter": _FakeMux(False, "psmux"),
        "subprocess_fallback": _FakeMux(True, "sub"),
    }
    orig = W.get_multiplexer
    W.get_multiplexer = lambda name: fakes[name]  # type: ignore[assignment]
    try:
        chosen = W.detect_best()
        _check(chosen.name == "sub", "detect_best skips unavailable, returns first available")
    finally:
        W.get_multiplexer = orig  # type: ignore[assignment]


def test_detect_best_raises_when_none_available() -> None:
    print("test_detect_best_raises_when_none_available")
    fakes = {name: _FakeMux(False, name) for name in W._REGISTRY_ORDER}
    orig = W.get_multiplexer
    W.get_multiplexer = lambda name: fakes[name]  # type: ignore[assignment]
    try:
        try:
            W.detect_best()
            _fail("all-unavailable should raise WorkerUnavailableError")
        except WorkerUnavailableError:
            _ok("all backends unavailable -> WorkerUnavailableError")
    finally:
        W.get_multiplexer = orig  # type: ignore[assignment]


def test_subprocess_spawn_list_kill_roundtrip() -> None:
    print("test_subprocess_spawn_list_kill_roundtrip (real Popen on the always-available backend)")
    mux = W.get_multiplexer("subprocess_fallback")
    session = f"wtest-{uuid.uuid4().hex[:8]}"
    try:
        h = mux.spawn(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            session=session, worker_id="w1",
        )
        _check(isinstance(h, WorkerHandle) and h.backend == "subprocess", "spawn returns a subprocess WorkerHandle")
        running = mux.list_workers(session)
        _check(any(x.worker_id == "w1" for x in running), "list_workers shows the running worker")
        # spawning the same (session, worker_id) again while running is refused
        try:
            mux.spawn([sys.executable, "-c", "pass"], session=session, worker_id="w1")
            _fail("duplicate live worker_id should be refused")
        except WorkerUnavailableError:
            _ok("duplicate live worker_id -> WorkerUnavailableError (no clobber)")
        _check(mux.kill(h) is True, "kill terminates the running worker")
        _check(all(x.worker_id != "w1" for x in mux.list_workers(session)), "killed worker no longer listed")
    finally:
        mux.kill_session(session)


def main() -> int:
    tests = [
        test_registry_resolves_subprocess_fallback,
        test_get_multiplexer_missing_export_raises,
        test_get_multiplexer_unknown_module_raises,
        test_detect_best_picks_first_available,
        test_detect_best_raises_when_none_available,
        test_subprocess_spawn_list_kill_roundtrip,
    ]
    for t in tests:
        try:
            t()
        except Exception as e:  # noqa: BLE001
            _fail(f"{t.__name__} raised {type(e).__name__}: {e}")
    print(f"\n{_PASS} passed, {_FAIL} failed")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
