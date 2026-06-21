---
name: kha-insert-phase
description: "Insert urgent work as decimal phase (e.g., 72.1) between existing phases"
argument-hint: "<after> <description>"
allowed-tools:
  - Read
  - Write
  - Bash
category: phase-mutation
mutates: yes
long-running: no
---
<objective>
Insert a decimal phase for urgent work discovered mid-milestone that must be completed between existing integer phases.

Uses decimal numbering (72.1, 72.2, etc.) to preserve the logical sequence of planned phases while accommodating urgent insertions.

Purpose: Handle urgent work discovered during execution without renumbering entire roadmap.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/insert-phase.md
</execution_context>

<context>
Arguments: $ARGUMENTS (format: <after-phase-number> <description>)

Roadmap and state are resolved in-workflow via `init phase-op` and targeted tool calls.
</context>

<process>
Execute the insert-phase workflow from @$HOME/.claude/get-shit-done/workflows/insert-phase.md end-to-end.
Preserve all validation gates (argument parsing, phase verification, decimal calculation, roadmap updates).
</process>

## Output


- artifact: `.planning/phases/${phase_number}-${slug}/` — newly created decimal phase directory
- artifact: `.planning/ROADMAP.md` — inserted decimal phase entry with `(INSERTED)` marker after the target phase
- artifact: `.planning/STATE.md` — roadmap-evolution note for the urgent insertion
- status: `inserted` | `aborted_missing_arguments` | `aborted_invalid_after_phase` | `aborted_no_roadmap`

## Failure behavior


- missing `after` phase or description, or non-integer `after` value: abort before mutation
- target phase missing from roadmap: abort before directory creation
- CLI insert failure: keep existing numbering untouched and do not attempt manual decimal renumbering

## Gate summary


- preflight: `.planning/ROADMAP.md` exists; `after_phase` parses as an integer; target phase exists; state file is writable
- success criteria: decimal phase directory exists, roadmap entry is inserted immediately after the target phase with `(INSERTED)`, and `STATE.md` records the urgent insertion
- abort triggers: malformed arguments; missing target phase; missing roadmap
