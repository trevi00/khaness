---
name: kha-plan-gap-phases
description: "Create phases to close all gaps identified by milestone audit"
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
category: plan
mutates: yes
long-running: yes
---
<objective>
Create all phases necessary to close gaps identified by `/kha-audit-milestone`.

Reads MILESTONE-AUDIT.md, groups gaps into logical phases, creates phase entries in ROADMAP.md, and offers to plan each phase.

One command creates all fix phases — no manual `/kha-add-phase` per gap.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/plan-milestone-gaps.md
</execution_context>

<context>
**Audit results:**
Glob: .planning/v*-MILESTONE-AUDIT.md (use most recent)

Original intent and current planning state are loaded on demand inside the workflow.
</context>

<process>
Execute the plan-milestone-gaps workflow from @$HOME/.claude/get-shit-done/workflows/plan-milestone-gaps.md end-to-end.
Preserve all workflow gates (audit loading, prioritization, phase grouping, user confirmation, roadmap updates).
</process>

## Output


- gap-closure phase plan plus confirmed updates to `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`, and new phase directories, reporting created phases, REQ reassignments, reset checkboxes, and deferred optional gaps.

## Failure behavior


- no `v*-MILESTONE-AUDIT.md` with gaps aborts; declined confirmation leaves planning untouched; inconsistent REQUIREMENTS traceability stops before any roadmap write and reports the blocking rows.

## Gate summary


- structured milestone-audit gaps are required; prioritization (`must | should | nice`) and phase grouping happen before the proposal; explicit user confirmation is required before roadmap, requirements, or directory mutation.

## Retry / Resume


- rerun after a fresh audit or after manual roadmap edits; not idempotent once phases already exist, so duplicate detection must happen before new phase creation.
