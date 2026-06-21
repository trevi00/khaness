---
name: kha-submit-pr
description: "Create PR, run review, and prepare for merge after verification passes"
argument-hint: "[phase number or milestone, e.g., '4' or 'v1.0']"
allowed-tools:
  - Read
  - Bash
  - Grep
  - Glob
  - Write
  - AskUserQuestion
category: workflow
mutates: yes
long-running: yes
---
<objective>
Bridge local completion → merged PR. After /kha-verify-uat passes, ship the work: push branch, create PR with auto-generated body, optionally trigger review, and track the merge.

Closes the plan → execute → verify → ship loop.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/ship.md
</execution_context>

Execute the ship workflow from @$HOME/.claude/get-shit-done/workflows/ship.md end-to-end.

## Preflight

- working tree clean: `git status --porcelain` empty (or only intended files)
- branch up-to-date with origin: `git fetch && git rev-parse origin/main`
- review reports present: `.planning/<phase>/REVIEW.md` exists and ends with `verdict: pass`
- tests pass on the current commit: `<test-runner>` exit 0

## Dry-run

- `--dry-run` shows: PR title, body, base/head branches, which checks would
  be enforced, list of commits in PR. NO `gh pr create` invocation.
- `--apply` actually creates the PR.

## Output


- artifact: a preflight snapshot surfaced before mutation, covering verification state, clean/dirty tree, current branch, base branch, remote presence, `gh` auth status, current HEAD, and commits ahead.
- artifact: a dry-run PR preview surfaced before `push`/`gh pr create`, covering the proposed title, base/head branches, verification summary, and generated PR body content.
- artifact: after approval, the remote branch `origin/{CURRENT_BRANCH}`, the created PR URL/number, and optional `.planning/STATE.md` shipping update commit.
- status: `preflight_blocked` | `dry_run_ready` | `pr_created` | `pr_created_state_update_failed`
- artifact: `.planning/<phase>/PR-<number>.md` with PR URL, base/head SHAs, review checklist status.
- on success: `[OK] PR #<n> created at <url>`
- on preflight fail: `[FAIL] preflight: <which check> — fix and retry`

## Failure behavior


- preflight failure: unacceptable verification without override, dirty working tree, unsuitable branch, missing remote, or missing/unauthenticated `gh` aborts before push or PR creation.
- execution failure: if push succeeds but PR creation or state update fails, keep the pushed branch and the generated title/body snapshot as the resume handle; never auto-delete a pushed branch or auto-close a created PR.
- partial success: reviewer assignment or `STATE.md` commit can fail after the PR already exists; report that as partial completion, not rollback.
- `gh` not authenticated: surface `gh auth login` hint, abort.
- branch behind origin: refuse, suggest `git pull --rebase`.
- tests failing: refuse, point to test output.
- existing open PR for the same branch: warn, ask if to update existing PR body/title, do not create duplicate.

## Gate summary


- preflight: verification is `passed` or an explicitly accepted `human_needed`, working tree is clean, branch/base/remote state is valid, and `gh` is authenticated.
- success criteria: the snapshot and dry-run preview are shown before mutation, the branch is pushed, the PR URL is reported, and shipping state is recorded when `commit_docs` is enabled.

## Retry / Resume


- checkpoint: the current branch name, HEAD hash, generated PR title/body preview, and whether the branch has already been pushed.
- resume command: rerun `/kha-submit-pr <phase-or-milestone>` on the same branch after fixing auth, remote, or state-update issues.
- idempotent: partially; re-pushing the same branch is safe, but PR creation is not guaranteed idempotent once a PR already exists.
