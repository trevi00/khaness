#!/usr/bin/env python3
"""Tests for validators.harness_bridge_state_block (Wave 15).

Per debate-1779314852-338b28 4-LOCK D5+D5a, this validator enforces the
``## Harness Bridge`` subsection inside ``.planning/STATE.md`` is
append-only. Test budget:

  (a) PASS when no .planning/STATE.md (non-GSD project)
  (b) PASS when STATE.md exists without ## Harness Bridge section
  (c) PASS when section exists with valid append-only bullets
  (d) FAIL on bullet format violation
  (e) FAIL on non-monotonic timestamps
  (f) FAIL on duplicate (phase, plan, sid) triple
  (g) FAIL when history shows historical bullet removed (append-only violated)
  (h) PASS scope-to-section: OTHER STATE.md sections can be mutated in-place
      (kha-executor's gsd-tools.cjs path) without validator complaint
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _reset_modules() -> None:
    for m in list(sys.modules):
        if m.startswith(("lib.paths", "validators.harness_bridge_state_block")):
            del sys.modules[m]


def _init_git(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "T"], check=True)


def _git_commit(root: Path, msg: str, file_rel: str, content: str) -> str:
    fp = root / file_rel
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", file_rel], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", msg], check=True)
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _run_validator_in(root: Path) -> str:
    saved = os.getcwd()
    os.chdir(root)
    try:
        _reset_modules()
        from validators.harness_bridge_state_block import main as v_main
        buf = io.StringIO()
        with redirect_stdout(buf):
            v_main()
        return buf.getvalue()
    finally:
        os.chdir(saved)


def _with_temp_home(fn):
    """Decorator: set CLAUDE_HOME to a fresh tmp dir for validator cache isolation."""
    def wrapper():
        with tempfile.TemporaryDirectory() as state_td:
            saved_home = os.environ.get("CLAUDE_HOME")
            os.environ["CLAUDE_HOME"] = state_td
            try:
                fn()
            finally:
                if saved_home is None:
                    os.environ.pop("CLAUDE_HOME", None)
                else:
                    os.environ["CLAUDE_HOME"] = saved_home
                # CRITICAL leak fix (2026-06-17): _run_validator_in() calls
                # _reset_modules() which DELETES lib.paths from sys.modules and
                # re-imports it while CLAUDE_HOME is the temp dir above — pinning
                # lib.paths.SCRIPTS_DIR to that (now-deleted) temp. Restoring the
                # env alone does NOT recompute the already-imported module global,
                # so any module imported later that does `from lib.paths import
                # SCRIPTS_DIR` (e.g. validators.{doc_code_drift,self_model_drift}
                # when graduated → run_all) binds the dead temp and its
                # _ref_resolves() fails. Re-reset here, AFTER the real CLAUDE_HOME
                # is restored, so the next import recomputes against the real home.
                _reset_modules()
    wrapper.__name__ = fn.__name__
    return wrapper


@_with_temp_home
def test_pass_no_state_md():
    with tempfile.TemporaryDirectory() as td:
        out = _run_validator_in(Path(td))
        assert "[PASS]" in out
        assert "non-GSD project" in out


@_with_temp_home
def test_pass_state_md_without_bridge_section():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".planning").mkdir()
        (root / ".planning" / "STATE.md").write_text(
            "# State\n\n## Current Plan\n\n1.0\n", encoding="utf-8"
        )
        out = _run_validator_in(root)
        assert "[PASS]" in out
        assert "no `## Harness Bridge` section" in out


@_with_temp_home
def test_pass_valid_append_only_bullets():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _init_git(root)
        (root / ".planning").mkdir()
        content = (
            "# State\n\n"
            "## Current Plan\n\n1.0\n\n"
            "## Harness Bridge\n\n"
            "- 2026-05-21T07:00:00Z | phase=8.3 | plan=01-foo | autopilot_sid=debate-1\n"
            "- 2026-05-21T07:05:00Z | phase=8.3 | plan=02-bar | autopilot_sid=debate-1\n"
        )
        (root / ".planning" / "STATE.md").write_text(content, encoding="utf-8")
        _git_commit(root, "init", ".planning/STATE.md", content)
        out = _run_validator_in(root)
        assert "[PASS]" in out, f"expected PASS, got: {out}"
        assert "2 bullets" in out


@_with_temp_home
def test_fail_bullet_format_violation():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _init_git(root)
        (root / ".planning").mkdir()
        # Missing autopilot_sid field
        content = (
            "## Harness Bridge\n\n"
            "- 2026-05-21T07:00:00Z | phase=8.3 | plan=01-foo\n"
        )
        (root / ".planning" / "STATE.md").write_text(content, encoding="utf-8")
        _git_commit(root, "init", ".planning/STATE.md", content)
        out = _run_validator_in(root)
        assert "[FAIL]" in out
        assert "format" in out


@_with_temp_home
def test_fail_non_monotonic_timestamps():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _init_git(root)
        (root / ".planning").mkdir()
        content = (
            "## Harness Bridge\n\n"
            "- 2026-05-21T07:10:00Z | phase=8.3 | plan=01-foo | autopilot_sid=s1\n"
            "- 2026-05-21T07:05:00Z | phase=8.3 | plan=02-bar | autopilot_sid=s1\n"
        )
        (root / ".planning" / "STATE.md").write_text(content, encoding="utf-8")
        _git_commit(root, "init", ".planning/STATE.md", content)
        out = _run_validator_in(root)
        assert "[FAIL]" in out
        assert "monotonic" in out


@_with_temp_home
def test_fail_duplicate_phase_plan_sid():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _init_git(root)
        (root / ".planning").mkdir()
        content = (
            "## Harness Bridge\n\n"
            "- 2026-05-21T07:00:00Z | phase=8.3 | plan=01-foo | autopilot_sid=s1\n"
            "- 2026-05-21T07:05:00Z | phase=8.3 | plan=01-foo | autopilot_sid=s1\n"
        )
        (root / ".planning" / "STATE.md").write_text(content, encoding="utf-8")
        _git_commit(root, "init", ".planning/STATE.md", content)
        out = _run_validator_in(root)
        assert "[FAIL]" in out
        assert "dedup" in out


@_with_temp_home
def test_fail_history_removed_bullet():
    """Historical bullet absent in current section = append-only violation."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _init_git(root)
        (root / ".planning").mkdir()
        # commit 1: 2 bullets
        v1 = (
            "## Harness Bridge\n\n"
            "- 2026-05-21T07:00:00Z | phase=8.3 | plan=01-foo | autopilot_sid=s1\n"
            "- 2026-05-21T07:05:00Z | phase=8.3 | plan=02-bar | autopilot_sid=s1\n"
        )
        (root / ".planning" / "STATE.md").write_text(v1, encoding="utf-8")
        _git_commit(root, "init", ".planning/STATE.md", v1)
        # commit 2: REMOVE bullet 1 (violation)
        v2 = (
            "## Harness Bridge\n\n"
            "- 2026-05-21T07:05:00Z | phase=8.3 | plan=02-bar | autopilot_sid=s1\n"
        )
        (root / ".planning" / "STATE.md").write_text(v2, encoding="utf-8")
        _git_commit(root, "mutate", ".planning/STATE.md", v2)

        out = _run_validator_in(root)
        assert "[FAIL]" in out
        assert "append-only" in out


@_with_temp_home
def test_pass_other_sections_can_mutate():
    """D8 split: kha-executor mutating Current Plan / Progress is OK.

    This is the critical scope-to-section invariant (gen-3 condition B2):
    the validator ENFORCES append-only ONLY on the ## Harness Bridge
    subsection. Other STATE.md sections (managed by gsd-tools.cjs state
    advance-plan/update-progress per kha-executor.md:461-507) freely mutate.
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _init_git(root)
        (root / ".planning").mkdir()
        # commit 1
        v1 = (
            "# State\n\n"
            "## Current Plan\n\n8.3-01\n\n"
            "## Progress\n\n2/5 plans complete\n\n"
            "## Harness Bridge\n\n"
            "- 2026-05-21T07:00:00Z | phase=8.3 | plan=01-foo | autopilot_sid=s1\n"
        )
        (root / ".planning" / "STATE.md").write_text(v1, encoding="utf-8")
        _git_commit(root, "init", ".planning/STATE.md", v1)
        # commit 2: kha-executor mutates Current Plan + Progress (in-place);
        # Harness Bridge section UNCHANGED (still has the same one bullet)
        v2 = (
            "# State\n\n"
            "## Current Plan\n\n8.3-02\n\n"
            "## Progress\n\n3/5 plans complete\n\n"
            "## Harness Bridge\n\n"
            "- 2026-05-21T07:00:00Z | phase=8.3 | plan=01-foo | autopilot_sid=s1\n"
        )
        (root / ".planning" / "STATE.md").write_text(v2, encoding="utf-8")
        _git_commit(root, "advance", ".planning/STATE.md", v2)

        out = _run_validator_in(root)
        assert "[PASS]" in out, f"expected PASS (other sections mutable), got: {out}"
        assert "1 bullets" in out


TESTS = [
    test_pass_no_state_md,
    test_pass_state_md_without_bridge_section,
    test_pass_valid_append_only_bullets,
    test_fail_bullet_format_violation,
    test_fail_non_monotonic_timestamps,
    test_fail_duplicate_phase_plan_sid,
    test_fail_history_removed_bullet,
    test_pass_other_sections_can_mutate,
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
