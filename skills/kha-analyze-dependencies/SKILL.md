---
name: kha-analyze-dependencies
description: "Analyze phase dependencies and suggest Depends on entries for ROADMAP.md"
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
category: validate
mutates: yes
long-running: yes
---
<objective>
Analyze the phase dependency graph for the current milestone. For each phase pair, determine if there is a dependency relationship based on:
- File overlap (phases that modify the same files must be ordered)
- Semantic dependencies (a phase that uses an API built by another phase)
- Data flow (a phase that consumes output from another phase)

Then suggest `Depends on` updates to ROADMAP.md.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/analyze-dependencies.md
</execution_context>

<context>
No arguments required. Requires an active milestone with ROADMAP.md.

Run this command BEFORE `/kha-milestone-manager` to fill in missing `Depends on` fields and prevent merge conflicts from unordered parallel execution.
</context>

<process>
Execute the analyze-dependencies workflow from @$HOME/.claude/get-shit-done/workflows/analyze-dependencies.md end-to-end.
Present dependency suggestions clearly and apply confirmed updates to ROADMAP.md.
</process>

## Output


- inspection phase returns a dependency gap report with per-phase suggestions and reasons (`file_overlap | semantic | data_flow`); mutation phase applies confirmed `Depends on:` updates to `ROADMAP.md` and reports the before/after diff summary.

## Failure behavior


- missing ROADMAP aborts; ambiguous dependencies stay as suggestions and are not auto-applied; write conflicts while editing ROADMAP stop the apply step and surface exact phase entries needing manual merge.

## Gate summary


- analysis and apply are separate; all phases are read first, heuristic inference is used only when explicit file lists are absent, and user choice (`yes | no | edit`) is required before ROADMAP mutation.

## Retry / Resume


- rerun after roadmap or phase-scope changes; idempotent once the same dependency set is already present.
