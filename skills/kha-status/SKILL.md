---
name: kha-status
description: "Check project progress, show context, and route to next action (execute or plan)"
allowed-tools:
  - Read
  - Bash
  - Grep
  - Glob
  - SlashCommand
category: status
mutates: no
long-running: no
---
<objective>
Check project progress, summarize recent work and what's ahead, then intelligently route to the next action - either executing an existing plan or creating the next one.

Provides situational awareness before continuing work.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/progress.md
</execution_context>

<process>
Execute the progress workflow from @$HOME/.claude/get-shit-done/workflows/progress.md end-to-end.
Preserve all routing logic (Routes A through F) and edge case handling.
</process>

## Output


- artifact: `stdout` — progress report with recent work, current position, blockers, todos, verification debt warning, and a single recommended route
- status: `routed_execute_phase` | `routed_plan_phase` | `routed_gap_planning` | `routed_verify_work` | `routed_complete_milestone` | `routed_new_milestone` | `aborted_no_planning`

## Failure behavior


- no `.planning/` structure: stop and route to `/kha-new-project`
- `PROJECT.md` exists but `ROADMAP.md` is missing: treat as between-milestones state and route to `/kha-new-milestone`, not as corruption
- cross-phase verification debt is advisory only: show it in the report but do not override the primary route unless the current phase has partial or diagnosed UAT

## Gate summary


- preflight: progress init succeeds and at least one of `.planning/PROJECT.md` or `.planning/ROADMAP.md` is available
- success criteria: recent work/current position/next objective are shown and exactly one route A-F is selected for the user
- abort triggers: no planning structure at all; missing both project and roadmap context
