---
name: kha-capture-note
description: "Zero-friction idea capture. Append, list, or promote notes to todos."
argument-hint: "<text> | list | promote <N> [--global]"
allowed-tools:
  - Read
  - Write
  - Glob
  - Grep
category: capture
mutates: yes
long-running: no
---
<objective>
Zero-friction idea capture — one Write call, one confirmation line.

Three subcommands:
- **append** (default): Save a timestamped note file. No questions, no formatting.
- **list**: Show all notes from project and global scopes.
- **promote**: Convert a note into a structured todo.

Runs inline — no Task, no AskUserQuestion, no Bash.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/note.md
@$HOME/.claude/get-shit-done/references/ui-brand.md
</execution_context>

<context>
$ARGUMENTS
</context>

<process>
Execute the note workflow from @$HOME/.claude/get-shit-done/workflows/note.md end-to-end.
Capture the note, list notes, or promote to todo — depending on arguments.
</process>

## Output


- artifact: append writes a raw inbox note to `.planning/notes/{YYYY-MM-DD}-{slug}.md` or `$HOME/.claude/notes/{YYYY-MM-DD}-{slug}.md`; promote creates an actionable todo at `.planning/todos/pending/{NNN}-{slug}.md` and marks the source note `promoted: true`; list is read-only.
- status: `note_added_project` | `note_added_global` | `notes_listed` | `note_promoted` | `promote_requires_project` | `invalid_note_selection`

## Failure behavior


- preflight failure: invalid `promote <N>`, an already-promoted note, or missing `.planning/` for promote stops with no destination todo write.
- execution failure: if promote creates the todo but fails before marking the source note as promoted, keep the new todo file and report both paths so the note can be reconciled manually; append/list never ask follow-up questions.

## Gate summary


- preflight: subcommand is parsed exactly after stripping `--global`, and promote resolves to a valid active note index.
- success criteria: append captures verbatim text in the correct scope, list shows both scopes with active numbering, and promote creates the todo plus flips the source note to `promoted: true`.
