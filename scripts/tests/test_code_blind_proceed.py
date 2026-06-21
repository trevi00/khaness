#!/usr/bin/env python3
"""Tests for the code_blind_proceed validator + lib.handoff_drift.code_blind_readiness (M16).

Un-skips the validator in run_all (a validator stays skipped until a dedicated test exists,
per the M3 atlas precedent). Auto-discovered via main()->int.
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.handoff_drift import code_blind_readiness  # noqa: E402
import validators.code_blind_proceed as vmod  # noqa: E402

_PARSEABLE = """# HANDOFF

## Current Phase Block
```yaml
phase_id: root
phase_goal: ship M16
status: in_progress
steps:
  step_1: DONE wrote validator
  step_2: pending hook up tests
```
"""

# The documented gotcha: a `이름: 설명` colon inside a step VALUE breaks yaml parsing.
_BROKEN = """# HANDOFF

## Current Phase Block
```yaml
phase_id: root
phase_goal: ship M16
status: in_progress
steps:
  step_1: 검증: 설명에 콜론이 있어서 yaml 파싱 실패
```
"""

_NO_BLOCK = "# HANDOFF\n\nSome notes, no phase block.\n"


def test_readiness_parseable():
    ok, reason = code_blind_readiness(_PARSEABLE)
    assert ok is True and "parseable" in reason


def test_readiness_broken_colon_fails():
    ok, reason = code_blind_readiness(_BROKEN)
    assert ok is False and "unparseable" in reason and "code-blind" in reason


def test_readiness_no_block_opts_out():
    ok, reason = code_blind_readiness(_NO_BLOCK)
    assert ok is True and "opt-out" in reason


def _run_validator_in(handoff_text: str | None) -> str:
    with tempfile.TemporaryDirectory() as td:
        if handoff_text is not None:
            (Path(td) / "HANDOFF.md").write_text(handoff_text, encoding="utf-8")
        buf = io.StringIO()
        with mock.patch.object(os, "getcwd", lambda: td), redirect_stdout(buf):
            vmod.main()
        return buf.getvalue()


def test_validator_pass_on_parseable():
    out = _run_validator_in(_PARSEABLE)
    assert "[PASS]" in out and "[FAIL]" not in out


def test_validator_fail_on_broken():
    out = _run_validator_in(_BROKEN)
    assert "[FAIL]" in out and "code_blind_proceed" in out


def test_validator_skip_when_no_handoff():
    out = _run_validator_in(None)
    assert "[PASS]" in out and "skip" in out


def test_validator_registered_in_builtin():
    from validators import _BUILTIN
    assert "code_blind_proceed" in _BUILTIN


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
