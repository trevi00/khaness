---
name: kha-spec-ui-phase
description: "Generate UI design contract (UI-SPEC.md) for frontend phases"
argument-hint: "[phase]"
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
  - Grep
  - Task
  - WebFetch
  - AskUserQuestion
  - mcp__context7__*
category: validate
mutates: yes
long-running: yes
---
<objective>
Create a UI design contract (UI-SPEC.md) for a frontend phase.
Orchestrates kha-ui-researcher and kha-ui-checker.
Flow: Validate → Research UI → Verify UI-SPEC → Done
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/ui-phase.md
@$HOME/.claude/get-shit-done/references/ui-brand.md
</execution_context>

<context>
Phase number: $ARGUMENTS — optional, auto-detects next unplanned phase if omitted.
</context>

<process>
Execute @$HOME/.claude/get-shit-done/workflows/ui-phase.md end-to-end.
Preserve all workflow gates.
</process>

## Output


- inspection phase yields a UI contract gap list across the 6 dimensions plus research findings; mutation phase authors `{NN}-UI-SPEC.md`, then returns checker verdict `verified | blocked` and any non-blocking recommendations.

## Failure behavior


- disabled UI phase or missing planning root aborts with guidance; researcher `BLOCKED` stops before approval; checker failure after 2 revisions surfaces the remaining blockers and requires user choice to force-approve, edit manually, or abandon.

## Gate summary


- research, spec authoring, and verification are separate stages; missing CONTEXT/RESEARCH are warnings, not blockers; existing UI-SPEC requires explicit `view | update | skip` choice before any overwrite.

## Retry / Resume


- rerun with the existing UI-SPEC as the new baseline; the approved UI-SPEC is the canonical resume artifact.
