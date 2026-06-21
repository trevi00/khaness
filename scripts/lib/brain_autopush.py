"""brain_autopush — auto-commit + push brain/ to a dedicated ORPHAN branch
(M-brain-handoff D1, full durability automation).

The brain auto-save writes brain/ FILES into the operator's working tree, but the git
commit + push that makes them survive machine death is manual (brain_store C5). This
closes the file→remote hop WITHOUT touching the default-branch push hard gate: it
commits the just-saved brain/ to a dedicated **orphan** branch `brain-snapshots`
(brain/ ONLY, no code) via an EPHEMERAL fixed-path git worktree, and pushes it. The
operator's HEAD / master / working tree are never touched (worktree isolation).

Design converged via two adversarial DGE passes (brain-subsystem survey + D1 gen-1/2
Critic):
  - ORPHAN, brain-only: no code is exposed on the snapshot branch; restore reads only
    brain/*.jsonl (the data-mirror's code would be inert anyway — orphan is cleaner).
  - FIXED-path worktree + prune + remove-on-entry: bounds leakage to one dir, survives
    a mid-run crash (next run reclaims it) — unlike ephemeral mkdtemp which leaks.
  - GIT_TERMINAL_PROMPT=0 / GCM_INTERACTIVE=never: a credential-less push FAILS FAST
    instead of hanging the scheduler pass-lock to its 600s timeout.
  - FF-only push (never --force): on a non-fast-forward (another machine pushed ahead)
    it returns reason='non-ff' and does NOT force — the E1 content-diff advisory
    (lib.brain_git_status) keeps nudging, so the divergence is surfaced, not silent.
  - Coherent with E1: E1 measures live brain/ vs origin/brain-snapshots (content), so a
    successful autopush silences it and a non-ff keeps it nudging.

Authorization: the caller (cron.run_brain_push) asserts the enable-cron-job token; this
module performs the push only when invoked from that gated path. Pushing to a NON-default
branch is not the default-branch NEVER-auto gate. Fail-soft throughout (any git error →
{pushed:False, reason}, never raises into the cron/hook chain).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

BRANCH = "brain-snapshots"
_WT_NAME = "claude-brain-snapshots-wt"   # fixed path under the system temp dir
_COMMIT_USER = ["-c", "user.name=harness-cron", "-c", "user.email=cron@harness.local"]


def _env() -> dict:
    """Non-interactive git env — fail fast on missing credentials, never prompt/hang."""
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never",
            "PYTHONIOENCODING": "utf-8"}


def _git(home: Path, args: list[str], *, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(home), *args],
        capture_output=True, text=True, timeout=120,
        encoding="utf-8", errors="replace", env=_env(), check=check,
    )


def _ok(cp: subprocess.CompletedProcess) -> bool:
    return cp.returncode == 0


def _wt_path(home: Path) -> Path:
    """Deterministic worktree path scoped to `home`.

    Still FIXED (so a mid-run crash is reclaimable on the next run for the same
    home — the design intent), but now UNIQUE per repo via a short stable digest
    of the resolved home path. The old global path
    (``<tmp>/claude-brain-snapshots-wt``) was shared across every repo + every
    process on the machine, so two autopush() calls on DIFFERENT homes (parallel
    tests, multiple checkouts) collided: one process's worktree add / rmtree
    stomped the other's, surfacing as ``git worktree add`` rc=128. Scoping the
    path to home isolates them while preserving crash-reclaim for the real
    single-home brain repo.
    """
    import hashlib
    key = hashlib.sha1(str(home.resolve()).encode("utf-8")).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"{_WT_NAME}-{key}"


def _remote_branch_exists(home: Path) -> bool:
    cp = _git(home, ["ls-remote", "--exit-code", "--heads", "origin", BRANCH])
    return _ok(cp)


def _cleanup_worktree(home: Path, wt: Path) -> None:
    # Reclaim a leaked/previous worktree (fixed path → at most one).
    _git(home, ["worktree", "remove", "--force", str(wt)])
    _git(home, ["worktree", "prune"])
    if wt.exists():
        shutil.rmtree(wt, ignore_errors=True)


def _add_worktree_existing(home: Path, wt: Path) -> bool:
    """Check out the LATEST origin/brain-snapshots into the worktree (orphan-shaped:
    brain/ only). Fetch first so the commit is based on the current remote tip — the
    push then fast-forwards and the union (below) means no machine's insights are lost."""
    if not _ok(_git(home, ["fetch", "-q", "origin", BRANCH])):
        return False
    return _ok(_git(home, ["worktree", "add", "-q", "-B", BRANCH, str(wt), f"origin/{BRANCH}"]))


def _union_brain_into_worktree(home: Path, wt: Path) -> None:
    """UNION the live brain/ (this machine) into the worktree's brain/ (the remote tip),
    rather than overwriting — so a brain insight only on the remote (another machine) is
    NOT lost when this machine commits. Reuses brain_store's per-layer union-by-id (the
    same dedup the cross-machine model relies on). L1/L2 JSONL layers union by their key;
    graduation (a tiny streak blob, re-validated on restore) takes this machine's copy."""
    from lib import brain_store as bs
    wt_brain = wt / "brain"
    for _live, brain_path, key in bs._jsonl_layers():
        rel = brain_path.relative_to(bs._brain_dir())          # e.g. l1/insight-index.jsonl
        remote_file = wt_brain / rel                            # the worktree's (remote tip) copy
        local_file = home / "brain" / rel                      # this machine's live copy
        remote_recs = bs._read_jsonl_pinned(remote_file) if remote_file.exists() else []
        local_recs = bs._read_jsonl_pinned(local_file) if local_file.exists() else []
        unioned = bs._union_by_key(remote_recs, local_recs, key)   # local overlays remote on id collision
        (wt_brain / rel).parent.mkdir(parents=True, exist_ok=True)
        bs._write_jsonl_sorted(wt_brain / rel, unioned, key)
    # graduation json: take this machine's copy (re-validated on restore; not id-unioned)
    grad_live, _grad_brain = bs._graduation_paths()
    grad_rel = Path("graduation") / "graduation-state.json"
    src_grad = home / "brain" / grad_rel
    if src_grad.is_file():
        (wt_brain / grad_rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_grad, wt_brain / grad_rel)


def _add_worktree_orphan(home: Path, wt: Path) -> bool:
    """First-ever run: create the orphan branch with brain/ ONLY. `git worktree add`
    cannot make an orphan directly, so we detach into the worktree, then
    `checkout --orphan` + clear the index — the committed tree ends up brain/-only."""
    if not _ok(_git(home, ["worktree", "add", "-q", "--detach", str(wt), "HEAD"])):
        return False
    if not _ok(_git(wt, ["checkout", "-q", "--orphan", BRANCH])):
        return False
    # Empty the index (working-tree files remain untracked; only brain/ will be added).
    _git(wt, ["rm", "-rf", "--cached", "-q", "."])
    return True


def autopush(home: str | Path | None = None) -> dict:
    """Commit the live brain/ to the orphan `brain-snapshots` branch and push it.
    Returns {pushed, committed, reason}. Fail-soft (never raises)."""
    if home is None:
        from .paths import CLAUDE_HOME
        home = CLAUDE_HOME
    home = Path(home)
    brain_src = home / "brain"
    if not brain_src.is_dir():
        return {"pushed": False, "committed": False, "reason": "no brain/ dir"}

    wt = _wt_path(home)
    try:
        _git(home, ["worktree", "prune"])
        _cleanup_worktree(home, wt)

        if _remote_branch_exists(home):
            if not _add_worktree_existing(home, wt):
                return {"pushed": False, "committed": False, "reason": "worktree add (existing) failed"}
        else:
            if not _add_worktree_orphan(home, wt):
                return {"pushed": False, "committed": False, "reason": "worktree add (orphan) failed"}

        # UNION the live brain/ into the worktree's (remote-tip) brain/ — never lose
        # another machine's insights (the cross-machine union-by-id model).
        _union_brain_into_worktree(home, wt)

        _git(wt, ["add", "--", "brain/"])
        if _ok(_git(wt, ["diff", "--cached", "--quiet"])):
            return {"pushed": True, "committed": False, "reason": "no change (already current)"}

        cm = _git(wt, [*_COMMIT_USER, "commit", "-q", "-m", "brain: auto-snapshot"])
        if not _ok(cm):
            return {"pushed": False, "committed": False, "reason": f"commit failed: {cm.stderr.strip()[:120]}"}

        push = _git(wt, ["push", "origin", f"HEAD:{BRANCH}"])
        if not _ok(push):
            err = (push.stderr or "").lower()
            reason = "non-ff" if ("non-fast-forward" in err or "rejected" in err or "fetch first" in err) \
                else f"push failed: {push.stderr.strip()[:120]}"
            return {"pushed": False, "committed": True, "reason": reason}
        return {"pushed": True, "committed": True, "reason": "ok"}
    except Exception as e:  # noqa: BLE001 — fail-soft: a cron/hook must never break here
        return {"pushed": False, "committed": False, "reason": f"{type(e).__name__}: {e}"}
    finally:
        _cleanup_worktree(home, wt)
