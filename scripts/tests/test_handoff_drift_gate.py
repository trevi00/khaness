#!/usr/bin/env python3
"""Unit + subprocess smoke tests for handlers/pre_tool/handoff_drift_gate.py.

Coverage:
  - is_git_commit_command: positive (git commit, git -C path commit, etc.)
                           and negative (git status, git commit-tree, etc.)
  - subprocess gate behavior:
      non-Bash tool             -> exit 0, no output
      non-git-commit Bash       -> exit 0, no output
      git commit + no HANDOFF   -> exit 0, no output
      git commit + drift        -> exit 0, advisory in stdout JSON
      git commit + in-sync      -> exit 0, no advisory
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from handlers.pre_tool.handoff_drift_gate import is_git_commit_command  # noqa: E402
from lib.handoff_drift import (  # noqa: E402
    ANCHOR_BEGIN,
    ANCHOR_END,
    render_from_handoff,
)


_GATE_PATH = _SCRIPTS / "handlers" / "pre_tool" / "handoff_drift_gate.py"


# ---------- is_git_commit_command unit tests ----------

def test_is_git_commit_recognizes_plain_form():
    assert is_git_commit_command("git commit") is True
    assert is_git_commit_command("git commit -m \"msg\"") is True
    assert is_git_commit_command("git commit --amend") is True


def test_is_git_commit_recognizes_C_path_form():
    assert is_git_commit_command("git -C /repo commit -m x") is True


def test_is_git_commit_recognizes_inline_config_form():
    assert is_git_commit_command(
        'git -c user.name=x -c user.email=y commit -m "msg"'
    ) is True


def test_is_git_commit_excludes_non_commit_subcommands():
    assert is_git_commit_command("git status") is False
    assert is_git_commit_command("git push origin master") is False
    assert is_git_commit_command("git log --oneline") is False
    # Plumbing — different command despite shared prefix
    assert is_git_commit_command("git commit-tree HEAD") is False


def test_is_git_commit_handles_non_string():
    assert is_git_commit_command(None) is False
    assert is_git_commit_command(123) is False


def test_is_git_commit_excludes_non_git_commands():
    assert is_git_commit_command("docker commit container_id") is False
    assert is_git_commit_command("svn commit -m x") is False


# ---------- subprocess gate tests ----------

def _run_gate(stdin_payload: dict) -> tuple[int, str]:
    """Run the gate as subprocess with given stdin JSON, return (rc, stdout)."""
    proc = subprocess.run(
        [sys.executable, str(_GATE_PATH)],
        input=json.dumps(stdin_payload),
        capture_output=True,
        text=True,
        timeout=10,
        encoding="utf-8",
    )
    return proc.returncode, proc.stdout


def _write_handoff_with_anchor(path: Path, tree: str) -> None:
    text = (
        "# H\n\n"
        "## Current Phase Block (machine-readable)\n\n"
        "```yaml\n"
        "phase_id: root-x\n"
        "status: in_progress\n"
        "```\n\n"
        f"{ANCHOR_BEGIN}\n```\n{tree}\n```\n{ANCHOR_END}\n"
    )
    path.write_text(text, encoding="utf-8")


def test_gate_silent_on_non_bash_tool():
    rc, out = _run_gate({
        "tool_name": "Edit",
        "tool_input": {"file_path": "/x.md"},
        "cwd": "/tmp",
    })
    assert rc == 0
    assert out.strip() == ""


def test_gate_silent_on_non_git_commit_bash():
    rc, out = _run_gate({
        "tool_name": "Bash",
        "tool_input": {"command": "git status"},
        "cwd": "/tmp",
    })
    assert rc == 0
    assert out.strip() == ""


def test_gate_silent_when_no_handoff_in_cwd():
    with tempfile.TemporaryDirectory() as td:
        rc, out = _run_gate({
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m x"},
            "cwd": td,  # empty tmpdir, no HANDOFF.md
        })
        assert rc == 0
        assert out.strip() == ""


def test_gate_silent_when_handoff_in_sync():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "HANDOFF.md"
        canon = render_from_handoff(
            "## Current Phase Block (machine-readable)\n\n"
            "```yaml\nphase_id: root-x\nstatus: in_progress\n```\n"
        )
        _write_handoff_with_anchor(path, canon)

        rc, out = _run_gate({
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m x"},
            "cwd": td,
        })
        assert rc == 0
        assert out.strip() == ""


def test_gate_emits_advisory_when_handoff_drifts():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "HANDOFF.md"
        _write_handoff_with_anchor(path, "stale-tree-content")

        rc, out = _run_gate({
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m x"},
            "cwd": td,
        })
        assert rc == 0
        assert out.strip() != ""

        payload = json.loads(out)
        ctx = payload["hookSpecificOutput"]["additionalContext"]
        assert "phase-tree-drift-precommit" in ctx
        assert "drift" in ctx.lower()
        assert "handoff_render" in ctx  # fix hint cites the CLI
        # NON-blocking: NO 'decision: block' anywhere
        assert "decision" not in payload or payload.get("decision") != "block"


TESTS = [
    test_is_git_commit_recognizes_plain_form,
    test_is_git_commit_recognizes_C_path_form,
    test_is_git_commit_recognizes_inline_config_form,
    test_is_git_commit_excludes_non_commit_subcommands,
    test_is_git_commit_handles_non_string,
    test_is_git_commit_excludes_non_git_commands,
    test_gate_silent_on_non_bash_tool,
    test_gate_silent_on_non_git_commit_bash,
    test_gate_silent_when_no_handoff_in_cwd,
    test_gate_silent_when_handoff_in_sync,
    test_gate_emits_advisory_when_handoff_drifts,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"  [OK] {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  [test-failed] {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"  [test-errored] {fn.__name__}: {type(e).__name__}")
    if failed:
        print(f"\n{failed}/{len(TESTS)} tests failed")
        return 1
    print(f"\n[OK] {len(TESTS)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
