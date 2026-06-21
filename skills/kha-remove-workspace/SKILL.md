---
name: kha-remove-workspace
description: "Remove a GSD workspace and clean up worktrees"
argument-hint: "<workspace-name>"
allowed-tools:
  - Bash
  - Read
  - AskUserQuestion
category: meta
mutates: yes
long-running: no
---
<context>
**Arguments:**
- `<workspace-name>` (required) — Name of the workspace to remove
</context>

<objective>
Remove a workspace directory after confirmation. For worktree strategy, runs `git worktree remove` for each member repo first. Refuses if any repo has uncommitted changes.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/remove-workspace.md
@$HOME/.claude/get-shit-done/references/ui-brand.md
</execution_context>

<process>
Execute the remove-workspace workflow from @$HOME/.claude/get-shit-done/workflows/remove-workspace.md end-to-end.
</process>

## Output


- artifacts: init summary of target workspace, optional worktree cleanup warnings, and final removal report naming deleted workspace path and repo count.
- status: `workspace_removed` | `workspace_cancelled` | `workspace_blocked_dirty_repos`.

## Failure behavior


- preflight: if no workspace name is provided, resolve it interactively first; if dirty repos are present, abort before any deletion or worktree cleanup.
- execution: failed `git worktree remove` calls warn and continue; failed directory deletion must report the exact remaining path/state.
- partial: if some worktrees are removed but workspace deletion fails, surface what was cleaned and what remains for manual recovery.

## Gate summary


- preflight: workspace init resolved path, strategy, repo list, and dirty-repo state.
- success: dry-run preview showed workspace path/strategy/repo count; snapshot is the init manifest of repos and cleanup targets; destructive delete requires typed-name confirmation before any removal.
- boundary: own deletion of `~/gsd-workspaces/<name>` only; it is separate from workstream archival inside a project repo.
