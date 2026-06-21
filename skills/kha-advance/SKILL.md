---
name: kha-advance
description: "Automatically advance to the next logical step in the GSD workflow"
allowed-tools:
  - Read
  - Bash
  - Grep
  - Glob
  - SlashCommand
category: status
mutates: yes
long-running: no
---
<objective>
Detect the current project state and automatically invoke the next logical GSD workflow step.
No arguments needed — reads STATE.md, ROADMAP.md, and phase directories to determine what comes next.

Designed for rapid multi-project workflows where remembering which phase/step you're on is overhead.

Supports `--force` flag to bypass safety gates (checkpoint, error state, verification failures).
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/next.md
</execution_context>

<process>
Execute the next workflow from @$HOME/.claude/get-shit-done/workflows/next.md end-to-end.
</process>

## Output


- artifact: `.planning/.next-call-count` — consecutive-call guard counter for repeated `/kha-advance` use
- artifact: `stdout` — status banner plus the immediately invoked next command
- status: `executed_next_command` | `forced_route` | `aborted_checkpoint` | `aborted_error_state` | `aborted_verification_failures` | `aborted_no_project`

## Failure behavior


- unresolved `.planning/.continue-here.md`: hard-stop before routing unless `--force`
- `STATE.md` in `error` or `failed` state: hard-stop before routing unless `--force`
- current-phase verification has unresolved FAIL items: hard-stop before routing unless `--force`
- after six consecutive `/kha-advance` calls, require explicit user confirmation before invoking the next command

## Gate summary


- preflight: `.planning/` exists; state snapshot and roadmap are readable; if `--force` is absent, all safety gates pass
- success criteria: exactly one next action is determined from the routing rules and is invoked immediately after the status banner
- abort triggers: no GSD project; unresolved checkpoint; error state; unresolved verification failures; user declines the consecutive-call guard
