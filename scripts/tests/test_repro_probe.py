#!/usr/bin/env python3
"""Tests for lib.repro_probe — the M18 deterministic-vs-transient reproduction probe.

Auto-discovered by run_units.py via main() -> int.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.repro_probe import build_probe, is_transient, Probe  # noqa: E402

_FP = "a" * 16


def test_deterministic_signature_builds_probe():
    p = build_probe(_FP, "Bash", "fatal: schema mismatch in <X> at column <X>")
    assert isinstance(p, Probe) and p.passed() is True
    assert p.fingerprint == _FP and p.tool_name == "Bash"


def test_transient_403_cloudflare_returns_none():
    # 403 may be <X>-normalized, so classification is on the WORD, not the number.
    assert build_probe(_FP, "WebFetch", "HTTP <X> Forbidden — cloudflare challenge") is None


def test_transient_timeout_and_lock_return_none():
    assert build_probe(_FP, "Bash", "operation timed out after <X>s") is None
    assert build_probe(_FP, "Write", "the file is locked by another process") is None
    assert build_probe(_FP, "Bash", "connection refused") is None


def test_placeholder_only_excerpt_returns_none():
    # <X>-normalization erased the discriminating tokens -> over-escalation bias.
    assert build_probe(_FP, "Bash", "<X> <X> <X>") is None
    assert build_probe(_FP, "Bash", "") is None
    assert build_probe(_FP, "Bash", "   ") is None


def test_missing_inputs_return_none():
    assert build_probe("", "Bash", "real error here") is None
    assert build_probe(_FP, "", "real error here") is None
    assert build_probe(_FP, "Bash", None) is None  # type: ignore[arg-type]


def test_is_transient_helper():
    assert is_transient("rate limit exceeded") is True
    assert is_transient("service unavailable") is True
    assert is_transient("undefined symbol foo in module bar") is False


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
