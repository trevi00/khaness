#!/usr/bin/env python3
"""pr_squash_guard.py - PreToolUse hook for stale-base squash detection.

Triggers WARN when the model is about to:
  - `gh pr merge .* --squash` and the PR branch is behind its base by ≥1 commit
  - `gh pr create .* --base <X>` from a branch behind origin/<X> by ≥1 commit

Why:
  Squash merging a stale branch silently overwrites commits made on the base
  between the PR branch's divergence point and current base tip. Files only
  changed on the base side (no conflict) are reverted to the PR's older
  version. Caused EXAMPLE_APP PR #12 to revert PR #11's endpoint fix in 2026-05.

Output:
  WARN via additionalContext (not DENY — sometimes intentional, e.g. cherry-pick).

Spec aligned with handlers/pre_tool/guard.py emit_warn().
"""

import sys
import json
import os
import re
import subprocess
from pathlib import Path

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

try:
    from lib.logging import timed
except ImportError:
    def timed(_name):
        def deco(f):
            return f
        return deco


# Match `gh pr merge <num> ... --squash` (or --squash before <num>).
_GH_MERGE_SQUASH = re.compile(
    r"\bgh\s+pr\s+merge\b[^|;&]*\b--squash\b",
    re.IGNORECASE,
)

# Match `gh pr create ... --base <branch>`.
_GH_CREATE_BASE = re.compile(
    r"\bgh\s+pr\s+create\b[^|;&]*\b--base\s+(\S+)",
    re.IGNORECASE,
)


def _git(args, cwd):
    """Run git, return stripped stdout or None on failure."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _detect_pr_base(cwd, pr_num):
    """Try to resolve PR base branch via gh CLI. Returns base branch name or None."""
    try:
        result = subprocess.run(
            ["gh", "pr", "view", str(pr_num), "--json", "baseRefName,headRefName"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            return None, None
        data = json.loads(result.stdout)
        return data.get("baseRefName"), data.get("headRefName")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, json.JSONDecodeError):
        return None, None


def _stale_count(cwd, base_ref, head_ref):
    """Count commits on origin/<base> not yet in <head>'s history.

    Returns int (≥0) or None if git unavailable.
    """
    # Make sure remote tracking is current — best effort, don't fail if no network.
    _git(["fetch", "origin", base_ref, "--quiet"], cwd)

    # merge-base between head branch and remote base.
    mb = _git(["merge-base", head_ref, f"origin/{base_ref}"], cwd)
    if not mb:
        return None

    count_str = _git(["rev-list", f"{mb}..origin/{base_ref}", "--count"], cwd)
    if count_str is None:
        return None
    try:
        return int(count_str)
    except ValueError:
        return None


def _emit_warn(text):
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                f"<pre-tool-warning>\n"
                f"[Squash stale-base 경고]\n{text}\n"
                f"</pre-tool-warning>"
            ),
        }
    }
    print(json.dumps(output, ensure_ascii=False))


def _check_merge_squash(command, cwd):
    """Detect `gh pr merge <num> --squash` and check stale-base."""
    if not _GH_MERGE_SQUASH.search(command):
        return None

    # Extract PR number (first int after `gh pr merge`).
    m = re.search(r"\bgh\s+pr\s+merge\s+(\d+)", command, re.IGNORECASE)
    if not m:
        # `gh pr merge` without explicit number = current branch's PR; skip
        # heuristic — we'd need extra calls and false-positive risk is moderate.
        return None
    pr_num = m.group(1)

    base, head = _detect_pr_base(cwd, pr_num)
    if not base or not head:
        return None  # Can't determine; stay silent

    count = _stale_count(cwd, base, head)
    if count is None or count < 1:
        return None

    return (
        f"PR #{pr_num} ({head}) is behind origin/{base} by {count} commit(s).\n"
        f"Squash merge will NOT preserve those {count} commit(s) — files changed\n"
        f"only on the base side will be silently overwritten with the PR's older\n"
        f"version (no conflict, no warning from GitHub).\n"
        f"\n"
        f"Recommended: run on the PR branch first ↓\n"
        f"  git fetch origin {base} && git rebase origin/{base} && git push --force-with-lease\n"
        f"Or use GitHub UI 'Update branch' button, then re-run merge.\n"
        f"\n"
        f"If this overwrite is intentional (e.g. you reviewed the diff), proceed."
    )


def _check_create_base(command, cwd):
    """Detect `gh pr create --base <X>` and check current branch staleness."""
    m = _GH_CREATE_BASE.search(command)
    if not m:
        return None

    base = m.group(1)
    head = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    if not head or head in ("HEAD", base):
        return None

    count = _stale_count(cwd, base, head)
    if count is None or count < 1:
        return None

    return (
        f"Current branch '{head}' is behind origin/{base} by {count} commit(s).\n"
        f"If you intend a squash merge later, those {count} commit(s) will NOT\n"
        f"be preserved — base-only changes get silently reverted to the PR's\n"
        f"older version.\n"
        f"\n"
        f"Recommended before opening PR:\n"
        f"  git fetch origin {base} && git rebase origin/{base} && git push --force-with-lease\n"
        f"\n"
        f"Cherry-pick or non-squash merges are unaffected — if that's your plan, proceed."
    )


@timed("pre_tool.pr_squash_guard")
def main():
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    if input_data.get("tool_name") != "Bash":
        sys.exit(0)

    command = input_data.get("tool_input", {}).get("command", "")
    if not command or "gh pr" not in command.lower():
        sys.exit(0)

    cwd = input_data.get("cwd") or os.getcwd()

    warn_text = _check_merge_squash(command, cwd) or _check_create_base(command, cwd)
    if warn_text:
        _emit_warn(warn_text)

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never crash the hook chain — silent on any unexpected failure.
        sys.exit(0)
