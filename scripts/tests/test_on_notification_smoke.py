#!/usr/bin/env python3
"""Smoke test: handlers/notification/on_notification.py runs as a SCRIPT (rc==0).

The Notification hook is registered in settings.json and invoked as a bare script
(no package context). A `from . import ...` relative import crashed it on EVERY
invocation (deep-audit rank 6). This test runs it exactly as registered — as a
subprocess fed a minimal payload — and asserts it exits 0 (the import resolves and
the no-channel config path silently exits).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
_HOOK = _SCRIPTS / "handlers" / "notification" / "on_notification.py"


def test_on_notification_runs_as_script_rc0():
    r = subprocess.run(
        [sys.executable, str(_HOOK)],
        input='{"notification_type":"test","message":"smoke"}',
        capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert r.returncode == 0, (
        f"on_notification.py exited {r.returncode} (relative-import regression?)\n"
        f"stderr:\n{r.stderr}"
    )
    # must not have leaked an ImportError/Traceback to stderr
    assert "ImportError" not in r.stderr and "Traceback" not in r.stderr, r.stderr


TESTS = [test_on_notification_runs_as_script_rc0]


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
