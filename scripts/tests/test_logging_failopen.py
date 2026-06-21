#!/usr/bin/env python3
"""Contract test for lib.logging.log_telemetry fail-open behavior.

When jsonl_append raises (disk full, permission error, etc.), log_telemetry MUST:
- Return None (not raise).
- Emit zero failure-token markers ([FAIL]/[ERROR]/Traceback) to stdout, so that
  run_all.py's D5 regex on captured stdout does not misread telemetry failure
  as test failure.
- May write any diagnostic message to stderr via log_stderr (sanctioned escape).

Run:
    cd ~/.claude/scripts && python -m tests.test_logging_failopen
"""
from __future__ import annotations

import contextlib
import io
import re
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import logging as L  # noqa: E402

_FAILURE_TOKEN_RE = re.compile(r"\[FAIL\]|\[ERROR\]|^Traceback", re.MULTILINE)


def _ioerror_jsonl_append(*_args, **_kwargs):
    raise IOError("simulated disk full")


def test_log_telemetry_returns_none_on_ioerror():
    saved = L.jsonl_append
    L.jsonl_append = _ioerror_jsonl_append
    try:
        result = L.log_telemetry("contract-test", {"k": 1})
        assert result is None, f"expected None, got {result!r}"
    finally:
        L.jsonl_append = saved


def test_log_telemetry_no_stdout_failure_tokens():
    saved = L.jsonl_append
    L.jsonl_append = _ioerror_jsonl_append
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            L.log_telemetry("contract-test", {"k": 2})
    finally:
        L.jsonl_append = saved
    captured = buf.getvalue()
    assert _FAILURE_TOKEN_RE.search(captured) is None, (
        f"stdout contains failure-token marker: {captured!r}"
    )


def test_log_telemetry_does_not_raise_on_arbitrary_exception():
    def raise_runtime(*_a, **_kw):
        raise RuntimeError("boom")

    saved = L.jsonl_append
    L.jsonl_append = raise_runtime
    try:
        L.log_telemetry("contract-test", {"k": 3})
    finally:
        L.jsonl_append = saved


TESTS = [
    test_log_telemetry_returns_none_on_ioerror,
    test_log_telemetry_no_stdout_failure_tokens,
    test_log_telemetry_does_not_raise_on_arbitrary_exception,
]


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
    total = len(TESTS)
    if failed:
        print(f"\n[FAIL] {failed}/{total} tests failed")
        return 1
    print(f"\n[OK] {total} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
