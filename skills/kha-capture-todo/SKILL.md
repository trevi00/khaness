---
name: kha-capture-todo
description: "Capture idea or task as todo from current conversation context"
argument-hint: "[optional description]"
allowed-tools:
  - Read
  - Write
  - Bash
  - AskUserQuestion
category: capture
mutates: yes
long-running: no
---
<objective>
Capture an idea, task, or issue that surfaces during a GSD session as a structured todo for later work.

Routes to the add-todo workflow which handles:
- Directory structure creation
- Content extraction from arguments or conversation
- Area inference from file paths
- Duplicate detection and resolution
- Todo file creation with frontmatter
- STATE.md updates
- Git commits
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/add-todo.md
</execution_context>

<context>
Arguments: $ARGUMENTS (optional todo description)

State is resolved in-workflow via `init todos` and targeted reads.
</context>

<process>
**Follow the add-todo workflow** from `@$HOME/.claude/get-shit-done/workflows/add-todo.md`.

The workflow handles all logic including:
1. Directory ensuring
2. Existing area checking
3. Content extraction (arguments or conversation)
4. Area inference
5. Duplicate checking
6. File creation with slug generation
7. STATE.md updates
8. Git commits
</process>

## Output


- artifact: an actionable todo in `.planning/todos/pending/{date}-{slug}.md`, or an existing pending todo updated in-place if the user chose duplicate replacement; `.planning/STATE.md` is updated when present.
- status: `todo_created` | `todo_replaced` | `duplicate_skipped` | `aborted`

## Failure behavior


- preflight failure: if todo init cannot load or the pending/completed directories cannot be ensured, stop with no file creation.
- execution failure: if the todo file is created or replaced but `STATE.md` update or commit fails, keep the todo file as the source of truth and report its path; partial completion is valid and must not be rolled back implicitly.

## Gate summary


- preflight: todo context from `init todos` loads, target directories are creatable, and duplicate handling is resolved before writing.
- success criteria: the pending todo file exists with valid frontmatter and Problem/Solution sections, duplicate resolution is honored, and `STATE.md` is updated when it exists.
