#!/usr/bin/env python3
"""Unit-test runner for harness internals (Wave 19 closing).

Companion to `tests/run_all.py`:
  - run_all.py walks `validators.VALIDATOR_NAMES` (37 entries: 35 builtin + graduated) → validator regression
  - run_units.py walks every other `tests/test_*.py` → harness internals regression

Together they form the full regression suite. Existing `tests/test_<name>.py`
where `<name>` is in VALIDATOR_NAMES is delegated to run_all to avoid duplicate
runs. All remaining test files are auto-discovered here.

Usage:
    cd ~/.claude/scripts && python tests/run_units.py

Each unit test module is expected to define a top-level `main() -> int` that
returns 0 on success and prints `[OK]`/`[FAIL]`/`[ERROR]` per case. Modules
without `main()` are skipped with a [SKIP] notice. SystemExit during in-process
import or call falls back to subprocess invocation (60s timeout).

Exit code: 0 if all passed or skipped; 1 if any failed.
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

from validators import VALIDATOR_NAMES  # noqa: E402

_FAILURE_TOKEN_RE = re.compile(r"\[FAIL\]|\[ERROR\]|^Traceback", re.MULTILINE)


def _has_failure_token(stdout: str) -> bool:
    return bool(_FAILURE_TOKEN_RE.search(stdout))


def _discover_unit_tests() -> list[str]:
    """Find tests/test_*.py whose <name> is NOT a validator (covered by run_all).

    Returns sorted list of unit-test module suffixes (e.g. 'advisory_ack' for
    tests/test_advisory_ack.py). 'run_units' itself is excluded.
    """
    tests_dir = _SCRIPTS / "tests"
    validator_set = set(VALIDATOR_NAMES)
    found: list[str] = []
    for p in sorted(tests_dir.glob("test_*.py")):
        suffix = p.stem[len("test_") :]
        if suffix in validator_set:
            continue
        found.append(suffix)
    return found


def _run_subprocess(test_path: Path, claude_home: Path | None = None) -> tuple[int, str]:
    """Run a unit test as subprocess and return (rc, captured).

    On PASS (rc == 0 AND no failure token): captured = stdout only. stderr is
    suppressed because tests legitimately emit `[log_telemetry] ... append
    failed: ...` lines from negative-path coverage that pollute the runner's
    summary. On FAIL: captured = stdout + stderr so the diagnosis is visible.

    When `claude_home` is set, the test runs with CLAUDE_HOME pointed at the
    isolated temp home (write isolation, STEP 4).
    """
    if not test_path.is_file():
        return 1, f"test file not found: {test_path}"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if claude_home is not None:
        env["CLAUDE_HOME"] = str(claude_home)
    try:
        proc = subprocess.run(
            [sys.executable, str(test_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            env=env,
        )
    except subprocess.TimeoutExpired as te:
        out = (te.stdout or "") if isinstance(te.stdout, str) else (te.stdout or b"").decode("utf-8", "replace")
        err = (te.stderr or "") if isinstance(te.stderr, str) else (te.stderr or b"").decode("utf-8", "replace")
        tail = (out + err)[-500:]
        return 124, f"timeout after 60s\n{tail}"
    rc = proc.returncode
    if rc == 0 and _has_failure_token(proc.stdout):
        return 1, f"silent-failure: stdout contains failure marker\n{proc.stdout[-500:]}\n{proc.stderr}"
    if rc == 0:
        return 0, proc.stdout
    return rc, proc.stdout + proc.stderr


def _check_skip(suffix: str, claude_home: Path | None = None) -> bool:
    """Quickly determine if a test module lacks a callable main() (SKIP).

    Uses a separate subprocess so we don't pollute the runner's import state
    just to inspect the module — a unit test importing harness lib modules
    would otherwise mutate REGISTRY/STATE_DIR before tests even run. The probe
    runs under the isolated CLAUDE_HOME too, so import-time side effects also
    land in throwaway space (STEP 4).
    """
    test_path = _SCRIPTS / "tests" / f"test_{suffix}.py"
    env = {**os.environ}
    if claude_home is not None:
        env["CLAUDE_HOME"] = str(claude_home)
    try:
        proc = subprocess.run(
            [sys.executable, "-c",
             f"import importlib; m = importlib.import_module('tests.test_{suffix}'); "
             f"import sys; sys.exit(0 if callable(getattr(m, 'main', None)) else 3)"],
            cwd=str(_SCRIPTS),
            capture_output=True,
            timeout=10,
            env=env,
        )
        return proc.returncode == 3
    except Exception:
        return False


# ---- Per-test CLAUDE_HOME isolation (STEP 4, self-verifying-harness) ----
# Audit finding: unit tests that exercise handlers/lib write to PRODUCTION state
# (insight-index burst-pollution, telemetry FP) because every write root derives
# from CLAUDE_HOME. We redirect CLAUDE_HOME to a temp dir so all writes (state/
# telemetry/memory/skill-candidates/...) land in throwaway space, and junction
# the READ-ONLY asset dirs back to the real home so reads (atlas cards, scripts
# AST, skills tree) still resolve. Write dirs are reset before each test → fresh
# per-test state. CLAUDE_HOME resolution is lazy in lib.paths/insight_index, so
# the subprocess env injection is sufficient with no per-module changes.

# Read-only asset dirs to junction back to the real home. _REQUIRED are the ones
# the suite provably needs (probe 2026-06-04: doc_code_drift→atlas+scripts,
# kha_normalize/project_analyze→skills); the rest are junctioned defensively.
_ASSET_SUBDIRS: tuple[str, ...] = (
    "agents", "atlas", "commands", "docs", "get-shit-done", "hooks",
    "plugins", "scripts", "skill-bodies", "skills", "templates",
)
_REQUIRED_ASSETS: frozenset[str] = frozenset({"scripts", "skills", "atlas"})


def _real_home() -> Path:
    """The genuine ~/.claude — `_SCRIPTS` is <home>/scripts resolved from
    __file__, so this is correct regardless of any CLAUDE_HOME override."""
    return _SCRIPTS.parent


def _make_junction(link: Path, target: Path) -> bool:
    """Create a Windows directory junction link->target (no admin needed).
    Returns True iff the link now exists."""
    try:
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, text=True, timeout=10,
        )
        return proc.returncode == 0 and link.exists()
    except Exception:
        return False


def _remove_junction(link: Path) -> None:
    """Unlink a junction via `rmdir` — removes only the link, NEVER the target;
    on a real non-empty dir it fails safely (rmdir is non-recursive)."""
    try:
        subprocess.run(["cmd", "/c", "rmdir", str(link)], capture_output=True, timeout=10)
    except Exception:
        pass


def _build_isolated_home() -> tuple[Path | None, list[Path]]:
    """Return (temp_home, junctions) or (None, []) if a required asset junction
    cannot be created (caller then runs WITHOUT isolation — degraded, never
    broken)."""
    real = _real_home()
    home = Path(tempfile.mkdtemp(prefix="claude-units-"))
    junctions: list[Path] = []
    for name in _ASSET_SUBDIRS:
        target = real / name
        if not target.is_dir():
            continue
        link = home / name
        if _make_junction(link, target):
            junctions.append(link)
        elif name in _REQUIRED_ASSETS:
            _cleanup_isolated_home(home, junctions)
            return None, []
    return home, junctions


def _reset_writes(home: Path, junctions: list[Path]) -> None:
    """Delete every non-junction child of `home` so the next test starts with
    fresh write roots. Junctions are explicitly skipped — we NEVER recurse into
    them (that would delete real assets)."""
    jnames = {j.name for j in junctions}
    try:
        children = list(home.iterdir())
    except OSError:
        return
    for child in children:
        if child.name in jnames:
            continue
        try:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        except Exception:
            pass


def _cleanup_isolated_home(home: Path, junctions: list[Path]) -> None:
    """Remove junctions first, then rmtree the home — but ONLY if every junction
    is confirmed gone, so rmtree can never recurse through a live junction into
    real asset targets. A surviving junction → leak the temp home (harmless)."""
    for j in junctions:
        _remove_junction(j)
    if all(not j.exists() for j in junctions):
        shutil.rmtree(home, ignore_errors=True)


def main() -> int:
    saved_cwd = os.getcwd()
    suffixes = _discover_unit_tests()
    iso_home, iso_junctions = _build_isolated_home()
    iso_note = f"isolated CLAUDE_HOME={iso_home.name}" if iso_home else "NO isolation (junction unavailable)"
    print(f"=== unit test run ({len(suffixes)} modules, subprocess-isolated; {iso_note}) ===")

    passed: list[str] = []
    failed: list[tuple[str, str]] = []
    skipped: list[str] = []

    try:
        for suffix in suffixes:
            # Fresh write roots per test (junctions preserved) → true per-test
            # isolation. No-op when isolation is unavailable.
            if iso_home is not None:
                _reset_writes(iso_home, iso_junctions)

            if _check_skip(suffix, iso_home):
                skipped.append(suffix)
                print(f"  [SKIP] tests.test_{suffix}: no main()")
                continue

            test_path = _SCRIPTS / "tests" / f"test_{suffix}.py"
            try:
                os.chdir(saved_cwd)
                rc, out = _run_subprocess(test_path, iso_home)
            finally:
                os.chdir(saved_cwd)

            if rc == 0 and "[SKIP-SUITE]" in out:
                # A discovered module with main() that self-reported its meaningful
                # coverage was NOT exercised because an optional dependency is absent
                # (e.g. psmux/node). Count as SKIPPED — not passed — so an environment
                # missing the dependency cannot masquerade as full green. (The token
                # is emitted ONLY by the affected suites; failure tokens still win.)
                skipped.append(suffix)
                print(f"  [SKIP] tests.test_{suffix}: optional dependency absent (suite not exercised)")
            elif rc == 0:
                passed.append(suffix)
                print(f"  [OK]   tests.test_{suffix}")
            else:
                failed.append((suffix, out[:500] if out else ""))
                print(f"  [FAIL] tests.test_{suffix}: rc={rc}")
    finally:
        if iso_home is not None:
            _cleanup_isolated_home(iso_home, iso_junctions)

    total = len(suffixes)
    print(f"\n=== summary: {len(passed)}/{total} passed, {len(skipped)} skipped, {len(failed)} failed ===")
    if skipped:
        print(f"  skipped: {', '.join(skipped)}")
    if failed:
        print("  failures:")
        for name, msg in failed:
            print(f"    - {name}: {msg.splitlines()[0] if msg else 'no output'}")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
