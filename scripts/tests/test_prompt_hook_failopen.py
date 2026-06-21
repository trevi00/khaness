#!/usr/bin/env python3
"""Fuzz: registered prompt/agent hooks fail-OPEN (rc==0) on a non-string prompt.

deep-audit pass-2 rank 3: mode_detector / debate_trigger / agent_invocation_audit
crashed to exit 1 (uncaught AttributeError) when fed a truthy non-string prompt
(e.g. {"prompt":123}) — a hook crash must NEVER block the user. Each hook now
wraps main() in try/except sys.exit(0); lib.prompt_origin is isinstance-guarded.
This runs each hook exactly as registered (subprocess, hostile stdin) and asserts
rc==0 (fail-soft), the on_notification-class invariant.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent

_CASES = [
    ("handlers/prompt/mode_detector.py", '{"prompt":123}'),
    ("handlers/prompt/debate_trigger.py", '{"prompt":123}'),
    ("handlers/post_tool/agent_invocation_audit.py", '{"tool_name":"Agent","prompt":123,"tool_input":{"prompt":123}}'),
    # also the genuinely-malformed shapes
    ("handlers/prompt/mode_detector.py", '{"prompt":["a","b"]}'),
    ("handlers/prompt/debate_trigger.py", 'not json at all'),
]


def _run(rel: str, payload: str) -> int:
    r = subprocess.run(
        [sys.executable, str(_SCRIPTS / rel)],
        input=payload, capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    return r.returncode


def test_prompt_hooks_failopen_on_non_string():
    failed = []
    for rel, payload in _CASES:
        rc = _run(rel, payload)
        if rc != 0:
            failed.append(f"{rel} <- {payload[:40]} : rc={rc}")
    assert not failed, "hooks must fail-OPEN (rc==0) on hostile input:\n" + "\n".join(failed)


def test_prompt_origin_isinstance_guard():
    sys.path.insert(0, str(_SCRIPTS))
    from lib.prompt_origin import is_system_reinvocation
    assert is_system_reinvocation(123) is False
    assert is_system_reinvocation(None) is False
    assert is_system_reinvocation(["x"]) is False
    assert is_system_reinvocation("normal prompt") is False


TESTS = [test_prompt_hooks_failopen_on_non_string, test_prompt_origin_isinstance_guard]


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
