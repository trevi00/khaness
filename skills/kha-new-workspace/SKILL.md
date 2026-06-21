---
name: kha-new-workspace
description: "Create an isolated workspace with repo copies and independent .planning/"
argument-hint: "--name <name> [--repos repo1,repo2] [--path /target] [--strategy worktree|clone] [--branch name] [--auto]"
allowed-tools:
  - Read
  - Bash
  - Write
  - AskUserQuestion
category: lifecycle
mutates: yes
long-running: yes
---
<context>
**Flags:**
- `--name` (required) — Workspace name
- `--repos` — Comma-separated repo paths or names. If omitted, interactive selection from child git repos in cwd
- `--path` — Target directory. Defaults to `~/gsd-workspaces/<name>`
- `--strategy` — `worktree` (default, lightweight) or `clone` (fully independent)
- `--branch` — Branch to checkout. Defaults to `workspace/<name>`
- `--auto` — Skip interactive questions, use defaults
</context>

<objective>
Create a physical workspace directory containing copies of specified git repos (as worktrees or clones) with an independent `.planning/` directory for isolated GSD sessions.

**Use cases:**
- Multi-repo orchestration: work on a subset of repos in parallel with isolated GSD state
- Feature branch isolation: create a worktree of the current repo with its own `.planning/`

**Creates:**
- `<path>/WORKSPACE.md` — workspace manifest
- `<path>/.planning/` — independent planning directory
- `<path>/<repo>/` — git worktree or clone for each specified repo

**After this command:** `cd` into the workspace and run `/kha-new-project` to initialize GSD.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/new-workspace.md
@$HOME/.claude/get-shit-done/references/ui-brand.md
</execution_context>

<process>
Execute the new-workspace workflow from @$HOME/.claude/get-shit-done/workflows/new-workspace.md end-to-end.
Preserve all workflow gates (validation, approvals, commits, routing).
</process>

## Output


- artifact: `${TARGET_PATH}/WORKSPACE.md` — manifest of member repos, source paths, branch names, and strategy
- artifact: `${TARGET_PATH}/.planning/` — isolated planning root for the new workspace
- artifact: `${TARGET_PATH}/${REPO_NAME}/` — worktree or clone for each selected repo
- status: `created` | `partial` | `aborted_invalid_target` | `aborted_no_repos`

## Failure behavior


- missing `--name`, invalid target path, or invalid strategy: abort before repo creation
- `--auto` without `--repos`: abort before creating `${TARGET_PATH}`
- per-repo creation failure: keep successful repo copies, record failures in `WORKSPACE.md`, and finish with `partial`
- branch collision during worktree creation: retry with a timestamped branch before marking the repo failed

## Gate summary


- preflight: workspace name resolved; target path is empty or absent; each source repo exists and has `.git`; strategy is `worktree` or `clone`; `worktree` mode requires git availability
- success criteria: `${TARGET_PATH}` exists, `WORKSPACE.md` is written, `.planning/` exists, and at least one repo copy succeeds
- abort triggers: no repos discovered or selected; target path already populated; all source repos invalid

## Retry / Resume


- checkpoint: `${TARGET_PATH}/WORKSPACE.md`
- resume command: `/kha-new-workspace --name ${WORKSPACE_NAME} --repos ${REPO_LIST} --path ${TARGET_PATH} --strategy ${STRATEGY} --branch ${BRANCH_NAME}`
- idempotent: no — rerunning against a non-empty target path aborts and partial workspaces must be reused or cleaned up explicitly
- stall detection: repo creation stops producing new manifest rows or `${TARGET_PATH}/.planning/` is missing after at least one repo copy succeeded
