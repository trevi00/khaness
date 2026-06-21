---
name: kha-revert-work
description: "Safe git revert. Roll back phase or plan commits using the phase manifest with dependency checks."
argument-hint: "--last N | --phase NN | --plan NN-MM"
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
category: workflow
mutates: yes
long-running: yes
---
<objective>
Safe git revert — roll back GSD phase or plan commits using the phase manifest, with dependency checks and a confirmation gate before execution.

Three modes:
- **--last N**: Show recent GSD commits for interactive selection
- **--phase NN**: Revert all commits for a phase (manifest + git log fallback)
- **--plan NN-MM**: Revert all commits for a specific plan
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/undo.md
@$HOME/.claude/get-shit-done/references/ui-brand.md
@$HOME/.claude/get-shit-done/references/gate-prompts.md
</execution_context>

<context>
$ARGUMENTS
</context>

<process>
Execute the undo workflow from @$HOME/.claude/get-shit-done/workflows/undo.md end-to-end.
</process>

## Output


- artifact: a single revert commit on the current branch, created from one or more staged `git revert --no-commit` operations; the selected commit list and revert reason are part of the user-visible execution record.
- status: `nothing_to_revert` | `revert_cancelled` | `revert_complete` | `revert_blocked_dirty_tree` | `revert_conflict`

## Failure behavior


- preflight failure: invalid mode, no matching commits, dependency warning aborted by the user, or a dirty working tree stops before any revert staging.
- execution failure: if any `git revert --no-commit` step conflicts, abort/cleanup the entire pending revert sequence and restore a clean working tree; do not leave half-staged revert state behind.

## Gate summary


- preflight: a valid target mode resolves to a non-empty commit set, dependency warnings are acknowledged when present, and the tree is clean.
- success criteria: commits are reverted newest-first with `--no-commit`, exactly one final revert commit is created, and no destructive reset mode is used.

## Retry / Resume


- checkpoint: there is no persisted in-place checkpoint after failure because the workflow must clean staged/worktree revert state; the durable handle is the original command plus the selected target scope.
- resume command: rerun the same `/kha-revert-work --last N | --phase NN | --plan NN-MM` invocation after resolving dirty-tree or dependency issues.
- idempotent: no; after success, rerunning would revert additional history or effectively undo the revert.
