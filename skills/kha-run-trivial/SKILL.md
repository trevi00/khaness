---
name: kha-run-trivial
description: "Execute a trivial task inline — no subagents, no planning overhead"
argument-hint: "[task description]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Grep
  - Glob
category: run
mutates: yes
long-running: no
---
<objective>
Execute a trivial task directly in the current context without spawning subagents
or generating PLAN.md files. For tasks too small to justify planning overhead:
typo fixes, config changes, small refactors, forgotten commits, simple additions.

This is NOT a replacement for /kha-run-adhoc — use /kha-run-adhoc for anything that
needs research, multi-step planning, or verification. /kha-run-trivial is for tasks
you could describe in one sentence and execute in under 2 minutes.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/fast.md
</execution_context>

<process>
Execute the fast workflow from @$HOME/.claude/get-shit-done/workflows/fast.md end-to-end.
</process>

## Output


- artifact: the requested small source/config/doc edits plus an atomic git commit; `.planning/STATE.md` gets a quick-task row only if that table already exists.
- status: `trivial_task_complete` | `redirected_non_trivial` | `aborted`

## Failure behavior


- preflight failure: if the task is empty or not truly trivial, stop before edits and redirect to the quick/ad-hoc workflow instead.
- execution failure: if edits were made but verification or commit failed, keep the working-tree changes visible and do not claim the quick-task state row or atomic commit succeeded.

## Gate summary


- preflight: the task is describable in one sentence, fits within about 3 file edits, needs no research, and can be done inline.
- success criteria: the work is completed without subagents or plan files, verification/sanity check runs, an atomic conventional commit exists, and `STATE.md` is updated only when its quick-task table already exists.

