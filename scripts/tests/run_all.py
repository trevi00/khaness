#!/usr/bin/env python3
"""Validator test runner — discovers tests/test_<name>.py for each registered validator.

Per harness-perfection debate D2 (Gen3+Gen4 converged):
- Walks `validators.VALIDATOR_NAMES` from validators/__init__.py.
- For each validator name, attempts `importlib.import_module(f'tests.test_<name>')`.
- If module exists and has a callable `main()`, run it (with cwd save/restore).
- If validator main() exits via sys.exit() during import, fall back to subprocess.
- Missing test module → [SKIP] with telemetry. Missing main() in validator → [FAIL].
- Sequential execution. cwd is saved before each test and restored in finally.

Usage:
    cd ~/.claude/scripts && python -m tests.run_all
    cd ~/.claude/scripts && python tests/run_all.py

Exit code: 0 if all passed or skipped; 1 if any test failed.
"""
from __future__ import annotations

import contextlib
import importlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.logging import log_telemetry  # noqa: E402
from validators import VALIDATOR_NAMES  # noqa: E402

# D5 (F1, fixplan-meta debate Gen4): silent-failure regex applied ONLY to
# captured per-test child stdout (proc.stdout for subprocess; redirect_stdout
# buffer for in-process). Never applied to run_all.py's own meta-output —
# that would self-pollute on any failed sub-test.
_FAILURE_TOKEN_RE = re.compile(r"\[FAIL\]|\[ERROR\]|^Traceback", re.MULTILINE)


def _has_failure_token(stdout: str) -> bool:
    return bool(_FAILURE_TOKEN_RE.search(stdout))


def _import_test_module(validator_name: str):
    """Try importing tests.test_<name>. Return module on success, None if missing.

    SystemExit during import → fall back to subprocess invocation (return sentinel
    'subprocess_required' so caller can re-run as subprocess).
    """
    module_name = f"tests.test_{validator_name}"
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        # L41 narrowing (worker-3 H5, fixplan-meta debate Gen4):
        # only treat as missing-test-module if the failed import IS the test
        # module itself. A transitive import error inside the test module
        # (e.g. typo in `from validators.X import Y`) must be re-raised so
        # it surfaces as a real [FAIL], not a silent SKIP.
        if e.name == module_name:
            return None
        raise
    except SystemExit:
        return "subprocess_required"


def _run_test_in_subprocess(validator_name: str) -> tuple[int, str]:
    """Run tests/test_<name>.py as subprocess for sys.exit isolation.

    D5 hardening (fixplan-meta debate Gen4):
    - subprocess.run already enforces timeout=60 (line below); on TimeoutExpired
      we return rc=124 + tail of captured output, loop continues to next test.
    - F1 silent-failure detection: if rc==0 but captured stdout matches
      _FAILURE_TOKEN_RE, coerce to rc=1 (regex never sees stderr).
    """
    test_path = _SCRIPTS / "tests" / f"test_{validator_name}.py"
    if not test_path.is_file():
        return 1, f"test file not found: {test_path}"
    try:
        proc = subprocess.run(
            [sys.executable, str(test_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as te:
        out = (te.stdout or "") if isinstance(te.stdout, str) else (te.stdout or b"").decode("utf-8", "replace")
        err = (te.stderr or "") if isinstance(te.stderr, str) else (te.stderr or b"").decode("utf-8", "replace")
        tail = (out + err)[-500:]
        return 124, f"timeout after 60s\n{tail}"
    rc = proc.returncode
    if rc == 0 and _has_failure_token(proc.stdout):
        return 1, f"silent-failure: stdout contains failure marker\n{proc.stdout[-500:]}"
    return rc, proc.stdout + proc.stderr


def _validator_has_main(validator_name: str) -> bool:
    """Check that validators.<name>.main exists and is callable."""
    try:
        mod = importlib.import_module(f"validators.{validator_name}")
    except Exception:
        return False
    main = getattr(mod, "main", None)
    return callable(main)


def _run_validators() -> int:
    saved_cwd = os.getcwd()
    skipped: list[str] = []
    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    print(f"=== validator test run ({len(VALIDATOR_NAMES)} validators) ===")

    for name in VALIDATOR_NAMES:
        # Pre-check: validator itself must have main() (caller contract)
        if not _validator_has_main(name):
            failed.append((name, "validator missing main() — caller contract violation"))
            print(f"  [FAIL] validators.{name}: no main()")
            continue

        # Try test module
        test_mod = _import_test_module(name)

        if test_mod is None:
            skipped.append(name)
            print(f"  [SKIP] tests.test_{name}: module missing")
            try:
                log_telemetry("test-coverage-gaps", {"validator": name, "reason": "no_test_module"})
            except Exception:
                pass
            continue

        if test_mod == "subprocess_required":
            rc, out = _run_test_in_subprocess(name)
            if rc == 0:
                passed.append(name)
                print(f"  [OK]   tests.test_{name} (subprocess)")
            else:
                failed.append((name, f"subprocess rc={rc}\n{out[:500]}"))
                print(f"  [FAIL] tests.test_{name} (subprocess rc={rc})")
            continue

        # In-process execution
        test_main = getattr(test_mod, "main", None)
        if not callable(test_main):
            failed.append((name, "test module has no callable main()"))
            print(f"  [FAIL] tests.test_{name}: no main()")
            continue

        try:
            os.chdir(saved_cwd)  # ensure clean cwd before each test
            # F1 (fixplan-meta Gen4): capture per-test stdout so the silent-failure
            # regex can be applied ONLY to child output. F5: write captured back to
            # real stdout with explicit flush to preserve CI log ordering.
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = test_main()
            captured = buf.getvalue()
            sys.stdout.write(captured)
            sys.stdout.flush()
            if rc == 0 and _has_failure_token(captured):
                failed.append((name, "silent-failure: stdout contains failure marker (rc=0)"))
                print(f"  [FAIL] tests.test_{name}: silent-failure (rc=0 with failure-token in stdout)")
            elif rc == 0:
                passed.append(name)
                print(f"  [OK]   tests.test_{name}")
            else:
                failed.append((name, f"test main() returned {rc}"))
                print(f"  [FAIL] tests.test_{name}: main returned {rc}")
        except SystemExit as e:
            # Late-stage sys.exit — retry as subprocess
            rc, out = _run_test_in_subprocess(name)
            if rc == 0:
                passed.append(name)
                print(f"  [OK]   tests.test_{name} (sys.exit caught, subprocess fallback)")
            else:
                failed.append((name, f"sys.exit + subprocess rc={rc}\n{out[:500]}"))
                print(f"  [FAIL] tests.test_{name}: SystemExit({e.code}) + subprocess fallback")
        except Exception as e:
            failed.append((name, f"{type(e).__name__}: {e}"))
            print(f"  [FAIL] tests.test_{name}: {type(e).__name__}: {e}")
        finally:
            os.chdir(saved_cwd)

    # Summary
    total = len(VALIDATOR_NAMES)
    print(f"\n=== summary: {len(passed)}/{total} passed, {len(skipped)} skipped, {len(failed)} failed ===")
    if skipped:
        print(f"  skipped: {', '.join(skipped)}")
    if failed:
        print("  failures:")
        for name, msg in failed:
            print(f"    - {name}: {msg.splitlines()[0]}")

    return 0 if not failed else 1


def main() -> int:
    """Wrap the validator run in telemetry isolation so the regression cannot
    pollute production ~/.claude/telemetry/ (harness-advancement #2).

    Smoking gun (assessment): validator gap-telemetry (hashline-violations,
    skill-frontmatter-gaps, ...) AND run_all's own test-coverage-gaps were landing
    in real telemetry/ during a run. log_telemetry reads lib.logging.TELEMETRY_DIR
    at CALL time, so swapping that one module global redirects ALL telemetry
    writes — including in-process validator-test writes — to a throwaway dir.
    Read paths (SCRIPTS_DIR/ATLAS_DIR/...) stay real so validators still scan the
    live tree; no execution-model change (vs a full subprocess refactor)."""
    from lib import logging as _logging
    iso = Path(tempfile.mkdtemp(prefix="run-all-telemetry-iso-"))
    saved_tel = _logging.TELEMETRY_DIR
    _logging.TELEMETRY_DIR = iso / "telemetry"
    try:
        return _run_validators()
    finally:
        _logging.TELEMETRY_DIR = saved_tel
        shutil.rmtree(iso, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
