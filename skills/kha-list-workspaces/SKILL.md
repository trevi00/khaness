---
name: kha-list-workspaces
description: "List active GSD workspaces and their status"
allowed-tools:
  - Bash
  - Read
category: meta
mutates: no
long-running: no
---
<objective>
Scan `~/gsd-workspaces/` for workspace directories containing `WORKSPACE.md` manifests. Display a summary table with name, path, repo count, strategy, and GSD project status.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/list-workspaces.md
@$HOME/.claude/get-shit-done/references/ui-brand.md
</execution_context>

<process>
Execute the list-workspaces workflow from @$HOME/.claude/get-shit-done/workflows/list-workspaces.md end-to-end.
</process>

## Output


- artifacts: inline table of workspaces from `~/gsd-workspaces/` with name, repo count, strategy, and GSD-project presence; no file writes.
- status: `workspaces_listed` | `no_workspaces_found`.

## Failure behavior


- preflight: if workspace inventory init fails, abort without mutating anything.
- execution: a missing workspace base should resolve to the empty-state message, not an errorful delete/create path.
- partial: not applicable.

## Gate summary


- preflight: list-workspaces init JSON is readable.
- success: all discovered workspaces are displayed or the explicit empty-state message is shown.
- boundary: read-only inventory only; it does not remove workspaces or manage workstreams/phases.
