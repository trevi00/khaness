---
name: kha-triage-todos
description: "List pending todos and select one to work on"
argument-hint: "[area filter]"
allowed-tools:
  - Read
  - Write
  - Bash
  - AskUserQuestion
category: triage
mutates: yes
long-running: no
---
<objective>
List all pending todos, allow selection, load full context for the selected todo, and route to appropriate action.

Routes to the check-todos workflow which handles:
- Todo counting and listing with area filtering
- Interactive selection with full context loading
- Roadmap correlation checking
- Action routing (work now, add to phase, brainstorm, create phase)
- STATE.md updates and git commits
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/check-todos.md
</execution_context>

<context>
Arguments: $ARGUMENTS (optional area filter)

Todo state and roadmap correlation are loaded in-workflow using `init todos` and targeted reads.
</context>

<process>
**Follow the check-todos workflow** from `@$HOME/.claude/get-shit-done/workflows/check-todos.md`.

The workflow handles all logic including:
1. Todo existence checking
2. Area filtering
3. Interactive listing and selection
4. Full context loading with file summaries
5. Roadmap correlation checking
6. Action offering and execution
7. STATE.md updates
8. Git commits
</process>

## Output


- artifact: if the user chooses “Work on it now,” `.planning/todos/pending/[filename]` moves to `.planning/todos/completed/[filename]` and `.planning/STATE.md` is updated when present; all other actions keep the todo pending.
- status: `no_pending_todos` | `todo_started` | `todo_kept_pending` | `brainstorming` | `phase_creation_suggested`

## Failure behavior


- preflight failure: if there are no pending todos, exit cleanly with no writes.
- execution failure: if the selected todo is moved but state update or commit fails, keep the completed todo file in place and report its path; if the action was non-mutating, leave the todo pending and stop.

## Gate summary


- preflight: todo list loads from `init todos`, any area filter is applied, and a valid selection is made.
- success criteria: the chosen todo’s full context is loaded, roadmap correlation is checked, one action path is completed, and count-changing actions update `STATE.md` when present.
