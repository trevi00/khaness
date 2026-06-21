---
name: kha-project-stats
description: "Display project statistics — phases, plans, requirements, git metrics, and timeline"
allowed-tools:
  - Read
  - Bash
category: meta
mutates: no
long-running: no
---
<objective>
Display comprehensive project statistics including phase progress, plan execution metrics, requirements completion, git history stats, and project timeline.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/stats.md
</execution_context>

<process>
Execute the stats workflow from @$HOME/.claude/get-shit-done/workflows/stats.md end-to-end.
</process>

## Output


- artifacts: inline project statistics view derived from `gsd-tools stats json`; no file writes.
- status: `stats_emitted` | `aborted_no_project`.

## Failure behavior


- preflight: if `.planning/` context is absent, abort with the instruction to initialize a project first.
- execution: if one metric source is missing, surface partial stats instead of inventing values.
- partial: none beyond explicitly reported unavailable metrics.

## Gate summary


- preflight: stats JSON can be produced from current project state.
- success: milestone, phase, plan, requirement, git, and timeline summaries were formatted for display.
- boundary: read-only project telemetry only; it never edits state or documentation.
