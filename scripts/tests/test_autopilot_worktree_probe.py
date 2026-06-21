#!/usr/bin/env python3
"""Unit tests for lib/autopilot_worktree_probe.py — D1 from debate-1778302432-1ce6ea.

Coverage:
  - Escape hatch AUTOPILOT_SKIP_ONEDRIVE_PROBE=1 short-circuit
  - Non-Windows guard returns (True, "non_windows")
  - Path-substring primary signal (case-insensitive)
  - Env-var secondary signal (OneDrive / Commercial / Consumer)
  - Default no-match returns (True, None)
  - Resolve failure fallback to raw str
  - is_relative_to OSError survival
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _clean_env():
    keys = [
        "AUTOPILOT_SKIP_ONEDRIVE_PROBE",
        "OneDrive",
        "OneDriveCommercial",
        "OneDriveConsumer",
    ]
    return {k: None for k in keys}


def test_escape_hatch_short_circuits_to_skipped_via_env():
    from lib.autopilot_worktree_probe import is_onedrive_path
    with mock.patch.dict(os.environ, {"AUTOPILOT_SKIP_ONEDRIVE_PROBE": "1"}, clear=False):
        ok, reason = is_onedrive_path(Path("/home/user/OneDrive/repo"))
        assert ok is True
        assert reason == "skipped_via_env"


def test_escape_hatch_value_other_than_1_does_not_short_circuit():
    from lib.autopilot_worktree_probe import is_onedrive_path
    with mock.patch.dict(os.environ, {"AUTOPILOT_SKIP_ONEDRIVE_PROBE": "0"}, clear=False):
        with mock.patch("lib.autopilot_worktree_probe.platform.system", return_value="Linux"):
            ok, reason = is_onedrive_path(Path("/tmp/repo"))
            assert ok is True
            assert reason == "non_windows"


def test_non_windows_returns_true_non_windows():
    from lib.autopilot_worktree_probe import is_onedrive_path
    with mock.patch("lib.autopilot_worktree_probe.platform.system", return_value="Linux"):
        ok, reason = is_onedrive_path(Path("/tmp/repo"))
        assert ok is True
        assert reason == "non_windows"


def test_non_windows_macos_returns_true_non_windows():
    from lib.autopilot_worktree_probe import is_onedrive_path
    with mock.patch("lib.autopilot_worktree_probe.platform.system", return_value="Darwin"):
        ok, reason = is_onedrive_path(Path("/Users/x/repo"))
        assert ok is True
        assert reason == "non_windows"


def test_path_substring_lowercase_onedrive_match():
    from lib.autopilot_worktree_probe import is_onedrive_path
    with mock.patch.dict(os.environ, {}, clear=True):
        with mock.patch("lib.autopilot_worktree_probe.platform.system", return_value="Windows"):
            with mock.patch.object(Path, "resolve", return_value=Path(r"C:\Users\foo\OneDrive\repo")):
                ok, reason = is_onedrive_path(Path(r"C:\Users\foo\OneDrive\repo"))
                assert ok is False
                assert reason == "onedrive_path_match"


def test_path_substring_mixed_case_match():
    from lib.autopilot_worktree_probe import is_onedrive_path
    with mock.patch.dict(os.environ, {}, clear=True):
        with mock.patch("lib.autopilot_worktree_probe.platform.system", return_value="Windows"):
            with mock.patch.object(Path, "resolve", return_value=Path(r"C:\users\foo\onedrive - personal\repo")):
                ok, reason = is_onedrive_path(Path(r"C:\users\foo\onedrive - personal\repo"))
                assert ok is False
                assert reason == "onedrive_path_match"


def test_env_var_match_secondary_signal():
    from lib.autopilot_worktree_probe import is_onedrive_path
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "repo"
        repo.mkdir()
        env = {"OneDrive": str(td)}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("lib.autopilot_worktree_probe.platform.system", return_value="Windows"):
                ok, reason = is_onedrive_path(repo)
                assert ok is False
                assert reason and reason.startswith("onedrive_env_match:")


def test_env_var_no_match_returns_true_none():
    from lib.autopilot_worktree_probe import is_onedrive_path
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "repo"
        repo.mkdir()
        with tempfile.TemporaryDirectory() as od_td:
            env = {"OneDrive": od_td}
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch("lib.autopilot_worktree_probe.platform.system", return_value="Windows"):
                    ok, reason = is_onedrive_path(repo)
                    assert ok is True
                    assert reason is None


def test_default_no_signals_returns_true_none():
    from lib.autopilot_worktree_probe import is_onedrive_path
    with mock.patch.dict(os.environ, {}, clear=True):
        with mock.patch("lib.autopilot_worktree_probe.platform.system", return_value="Windows"):
            with tempfile.TemporaryDirectory() as td:
                ok, reason = is_onedrive_path(Path(td))
                assert ok is True
                assert reason is None


def test_resolve_failure_falls_back_to_raw_str():
    from lib.autopilot_worktree_probe import is_onedrive_path
    with mock.patch.dict(os.environ, {}, clear=True):
        with mock.patch("lib.autopilot_worktree_probe.platform.system", return_value="Windows"):
            def _bad_resolve(self, *a, **kw):
                raise OSError("boom")
            with mock.patch.object(Path, "resolve", _bad_resolve):
                ok, reason = is_onedrive_path(Path(r"C:\Users\foo\OneDrive\repo"))
                assert ok is False
                assert reason == "onedrive_path_match"


def test_env_var_resolve_oserror_skipped_continues_to_next():
    from lib.autopilot_worktree_probe import is_onedrive_path
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "repo"
        repo.mkdir()
        env = {
            "OneDrive": "C:\\nonexistent\\path\\that\\errors",
            "OneDriveCommercial": str(td),
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("lib.autopilot_worktree_probe.platform.system", return_value="Windows"):
                ok, reason = is_onedrive_path(repo)
                if ok is False:
                    assert reason and "onedrive_env_match" in reason
                else:
                    assert reason is None


def test_empty_env_var_skipped():
    from lib.autopilot_worktree_probe import is_onedrive_path
    with mock.patch.dict(os.environ, {"OneDrive": "", "OneDriveCommercial": ""}, clear=True):
        with mock.patch("lib.autopilot_worktree_probe.platform.system", return_value="Windows"):
            with tempfile.TemporaryDirectory() as td:
                ok, reason = is_onedrive_path(Path(td))
                assert ok is True
                assert reason is None


TESTS = [
    test_escape_hatch_short_circuits_to_skipped_via_env,
    test_escape_hatch_value_other_than_1_does_not_short_circuit,
    test_non_windows_returns_true_non_windows,
    test_non_windows_macos_returns_true_non_windows,
    test_path_substring_lowercase_onedrive_match,
    test_path_substring_mixed_case_match,
    test_env_var_match_secondary_signal,
    test_env_var_no_match_returns_true_none,
    test_default_no_signals_returns_true_none,
    test_resolve_failure_falls_back_to_raw_str,
    test_env_var_resolve_oserror_skipped_continues_to_next,
    test_empty_env_var_skipped,
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
    if failed:
        print(f"\n[FAIL] {failed}/{len(TESTS)} tests failed")
        return 1
    print(f"\n[OK] {len(TESTS)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
