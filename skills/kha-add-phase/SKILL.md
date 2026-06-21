---
name: kha-add-phase
description: "Add phase to end of current milestone in roadmap"
argument-hint: "<description>"
allowed-tools:
  - Read
  - Write
  - Bash
category: phase-mutation
mutates: yes
long-running: no
---
<objective>
Add a new integer phase to the end of the current milestone in the roadmap.

Routes to the add-phase workflow which handles:
- Phase number calculation (next sequential integer)
- Directory creation with slug generation
- Roadmap structure updates
- STATE.md roadmap evolution tracking
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/add-phase.md
</execution_context>

<context>
Arguments: $ARGUMENTS (phase description)

Roadmap and state are resolved in-workflow via `init phase-op` and targeted tool calls.
</context>

<process>
**Follow the add-phase workflow** from `@$HOME/.claude/get-shit-done/workflows/add-phase.md`.

The workflow handles all logic including:
1. Argument parsing and validation
2. Roadmap existence checking
3. Current milestone identification
4. Next phase number calculation (ignoring decimals)
5. Slug generation from description
6. Phase directory creation
7. Roadmap entry insertion
8. STATE.md updates
</process>

## Output


- artifact: `.planning/phases/${padded}-${slug}/` — newly created phase directory
- artifact: `.planning/ROADMAP.md` — appended integer phase entry at the end of the current milestone
- artifact: `.planning/STATE.md` — roadmap-evolution note for the added phase
- status: `added` | `aborted_no_description` | `aborted_no_roadmap`

## Failure behavior


- missing description: abort before any directory or roadmap mutation
- missing `.planning/ROADMAP.md`: abort and route to project initialization
- CLI add failure: do not hand-edit roadmap numbering; preserve current files and surface the CLI error for retry

## Gate summary


- preflight: description text is non-empty; `.planning/ROADMAP.md` exists; `.planning/STATE.md` is writable
- success criteria: `gsd-tools phase add` returns a new phase number and directory, `ROADMAP.md` contains the new entry, and `STATE.md` records the roadmap-evolution note
- abort triggers: missing description; missing roadmap; failed `phase add` delegation
