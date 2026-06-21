---
name: kha-import-plan
description: "Ingest external plans with conflict detection against project decisions before writing anything."
argument-hint: "--from <filepath>"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
  - Task
category: workflow
mutates: yes
long-running: yes
---
<objective>
Import external plan files into the GSD planning system with conflict detection against PROJECT.md decisions.

- **--from**: Import an external plan file, detect conflicts, write as GSD PLAN.md, validate via kha-plan-checker.

Future: `--prd` mode for PRD extraction is planned for a follow-up PR.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/import.md
@$HOME/.claude/get-shit-done/references/ui-brand.md
@$HOME/.claude/get-shit-done/references/gate-prompts.md
</execution_context>

<context>
$ARGUMENTS
</context>

<process>
Execute the import workflow end-to-end.
</process>

## Output


- artifact: `.planning/phases/{NN}-{slug}/{NN}-{MM}-PLAN.md`, updated `.planning/ROADMAP.md`, and optional `.planning/STATE.md` adjustments; if validation finds issues after write, the written PLAN file remains for manual correction.
- status: `import_blocked` | `import_cancelled` | `plan_imported` | `plan_written_needs_validation_fix`

## Failure behavior


- preflight failure: invalid usage, path traversal, missing source file, or any `[BLOCKER]` in conflict detection exits with no PLAN write.
- execution failure: once the PLAN file is written, checker errors or finalize/commit failures do not delete it; report the target plan path as the recovery handle and treat the run as partial rather than rolled back.

## Gate summary


- preflight: `--from <filepath>` parses cleanly, the file exists, project context loads, and conflict detection yields no blockers.
- success criteria: the imported content is converted to `{NN}-{MM}-PLAN.md`, the checker runs, roadmap/state updates are applied when appropriate, and the import summary identifies the written plan and validation result.

## Retry / Resume


- checkpoint: the written target PLAN file in `.planning/phases/{NN}-{slug}/{NN}-{MM}-PLAN.md`; before that point there is nothing to resume because blocker exits are read-only.
- resume command: rerun `/kha-import-plan --from <filepath>` after fixing blockers; if the PLAN file already exists but checker failed, resume from that written file and re-run the plan checker after edits.
- idempotent: no once a target plan number/file has been allocated and written.
