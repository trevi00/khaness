---
name: kha-dispatch
description: "Route freeform text to the right GSD command automatically"
argument-hint: "<description of what you want to do>"
allowed-tools:
  - Read
  - Bash
  - AskUserQuestion
category: run
mutates: yes
long-running: no
---
<objective>
Analyze freeform natural language input and dispatch to the most appropriate GSD command.

Acts as a smart dispatcher — never does the work itself. Matches intent to the best GSD command using routing rules, confirms the match, then hands off.

Use when you know what you want but don't know which `/gsd-*` command to run.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/do.md
@$HOME/.claude/get-shit-done/references/ui-brand.md
</execution_context>

<context>
$ARGUMENTS
</context>

<process>
Execute the do workflow from @$HOME/.claude/get-shit-done/workflows/do.md end-to-end.
Route user intent to the best GSD command and invoke it.
</process>

## Output


- artifact: no direct file artifact; the concrete output is the routing decision shown to the user plus the downstream command invocation, and any mutations belong to that routed command.
- status: `dispatched` | `awaiting_input` | `awaiting_disambiguation` | `project_init_required`

## Failure behavior


- preflight failure: empty input pauses for a user description instead of guessing, and a route that requires `.planning/` stops with a project-initialization suggestion rather than dispatching blindly.
- execution failure: ambiguous intent does not mutate anything; it stays at the routing gate until the user chooses among candidate commands.

## Gate summary


- preflight: user intent text exists, project presence is checked when relevant, and routing rules narrow to one command or a bounded ambiguity set.
- success criteria: exactly one command is selected, the reason is displayed, and the dispatcher itself performs no substantive work.

