#!/usr/bin/env python3
"""git_flow validator — branch name + commit message lint per skills/_common/git-flow.md.

Per harness git-flow integration (option C):
- Detects current branch name + recent 10 commit messages via subprocess.
- Validates against general git-flow patterns by default.
- Auto-detects company override at <cwd>/.claude/git-flow-overrides.md;
  switches to company prefix set (예: [f/d]/[f/r]/[f/m]/[fix]/[etc]) when present.
  회사별 구체 prefix 정의는 user-private 트리에 (예: flutter/example_app/git-flow-company.md).

Caller contract (validators/__init__.py L14-19 표준):
- main() -> None, no args
- reads os.getcwd() (must be inside a git repo)
- prints `[PASS]` / `[FAIL]` / `[WARN]` lines to stdout
- never raises; failures via stdout

Exit semantics: silent skip if cwd is not a git repo (e.g., running from
~/.claude harness root which is not git-tracked).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.logging import log_stderr, log_telemetry  # noqa: E402


# General (Conventional Commits) + harness-domain extensions:
# - `state`: state-store mutations (advisory acks, state/* files, telemetry resets)
#   that aren't fit for `chore` (mundane) or `data` (non-canonical). Used by
#   wave 7 후속 advisory cleanup (commit 2dfbd3a). Equivalent severity to chore.
# - `docs\+test`: compound prefix for commits that intentionally bundle
#   docstring + test additions (e.g., caller-side accessor guide + L4 anti-
#   regression assertions added together — invariant requires same-commit
#   coupling to prevent doc/test drift). Used by continuation cycle (f661cdb).
GENERAL_COMMIT_RE = re.compile(
    r"^(feat|fix|refactor|docs|test|chore|perf|build|ci|style|revert|state|docs\+test)(\([^)]+\))?(!)?:\s+.+",
    re.IGNORECASE,
)
GENERAL_BRANCH_RE = re.compile(
    r"^(main|master|develop|feature|release|hotfix|bugfix|chore)(/[\w./\-가-힣]+)?$"
)

# Company override prefixes (구체 prefix는 user-private 트리에 분리 보관)
COMPANY_COMMIT_PREFIXES = ("[f/d]", "[f/r]", "[f/m]", "[fix]", "[etc]")
COMPANY_BRANCH_RE = re.compile(
    r"^(main|master|develop|feature/[\w./\-가-힣]+|release-[\w.\-]+|hotfix-[\w.\-]+)$"
)

# Special branches that don't require feature prefix
PROTECTED_BRANCHES = {"main", "master", "develop"}


def _git(args: list[str], cwd: str) -> tuple[int, str]:
    try:
        r = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True,
            timeout=5, encoding="utf-8", errors="replace",
        )
        return r.returncode, r.stdout.strip()
    except Exception:
        return 1, ""


def _detect_override(cwd: str) -> bool:
    """Return True if <cwd>/.claude/git-flow-overrides.md declares company mode.

    Was previously a file-existence check (`override: company` was implicit).
    Now content-aware via lib.git_flow_override so the same file can carry
    other workflow declarations (e.g., `mode: solo` for personal repos)
    without falsely switching commit linting to company prefixes.
    """
    from lib.git_flow_override import is_company_mode
    return is_company_mode(cwd)


def _check_commit_message(msg: str, company_mode: bool) -> str | None:
    """Return None if OK, otherwise a short reason."""
    if not msg.strip():
        return "empty message"
    # Skip auto-merge commits
    if msg.startswith("Merge ") or msg.startswith("Revert "):
        return None
    if company_mode:
        if not any(msg.startswith(p) for p in COMPANY_COMMIT_PREFIXES):
            return f"missing company prefix (one of {COMPANY_COMMIT_PREFIXES})"
        return None
    # General: Conventional Commits
    if not GENERAL_COMMIT_RE.match(msg):
        return "missing Conventional Commits prefix (feat:/fix:/refactor:/etc.)"
    return None


def _check_branch_name(branch: str, company_mode: bool) -> str | None:
    """Return None if OK, otherwise a short reason."""
    pattern = COMPANY_BRANCH_RE if company_mode else GENERAL_BRANCH_RE
    if not pattern.match(branch):
        mode = "company" if company_mode else "general"
        return f"branch '{branch}' does not match {mode} pattern"
    return None


def main() -> None:
    cwd = os.getcwd()

    # Skip if not a git repo
    rc, _ = _git(["rev-parse", "--is-inside-work-tree"], cwd)
    if rc != 0:
        print("[PASS] not a git repo (skip)")
        return

    company_mode = _detect_override(cwd)
    mode_label = "company (override)" if company_mode else "general (Conventional Commits)"

    # 1. Current branch
    rc_b, branch = _git(["branch", "--show-current"], cwd)
    if rc_b != 0 or not branch:
        print("[WARN] could not determine current branch (detached HEAD?)")
        return

    branch_failures: list[str] = []
    reason = _check_branch_name(branch, company_mode)
    if reason:
        branch_failures.append(reason)
        try:
            log_telemetry("git-flow-violations", {
                "kind": "branch", "branch": branch, "mode": mode_label, "reason": reason,
            })
        except Exception as e:
            log_stderr(f"[git_flow] telemetry failed: {e}")

    # 2. Last 10 commit messages
    rc_l, log_out = _git(["log", "-10", "--pretty=format:%s"], cwd)
    commit_messages = log_out.splitlines() if rc_l == 0 else []

    commit_failures: list[tuple[str, str]] = []
    for msg in commit_messages:
        reason = _check_commit_message(msg, company_mode)
        if reason:
            commit_failures.append((msg[:80], reason))
            try:
                log_telemetry("git-flow-violations", {
                    "kind": "commit", "msg": msg[:120], "mode": mode_label, "reason": reason,
                })
            except Exception as e:
                log_stderr(f"[git_flow] telemetry failed: {e}")

    # Output
    if branch_failures:
        for r in branch_failures:
            print(f"[FAIL] branch: {r}")
    else:
        print(f"[PASS] branch '{branch}' matches {mode_label}")

    if commit_failures:
        print(f"[FAIL] {len(commit_failures)}/{len(commit_messages)} recent commit messages violate {mode_label}:")
        for short, reason in commit_failures[:5]:
            print(f"  - {short!r}: {reason}")
        if len(commit_failures) > 5:
            print(f"  ... and {len(commit_failures) - 5} more")
    else:
        if commit_messages:
            print(f"[PASS] last {len(commit_messages)} commits match {mode_label}")


if __name__ == "__main__":
    main()
