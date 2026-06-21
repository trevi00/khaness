---
name: kha-remediate-code-review
description: "Auto-fix issues found by code review in REVIEW.md. Spawns fixer agent, commits each fix atomically, produces REVIEW-FIX.md summary."
argument-hint: "<phase-number> [--all] [--auto]"
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
  - Write
  - Edit
  - Task
category: remediate
mutates: yes
long-running: yes
---
<objective>
Auto-fix issues found by code review. Reads REVIEW.md from the specified phase, spawns kha-code-fixer agent to apply fixes, and produces REVIEW-FIX.md summary.

Arguments:
- Phase number (required) — which phase's REVIEW.md to fix (e.g., "2" or "02")
- `--all` (optional) — include Info findings in fix scope (default: Critical + Warning only)
- `--auto` (optional) — enable fix + re-review iteration loop, capped at 3 iterations

Output: {padded_phase}-REVIEW-FIX.md in phase directory + inline summary of fixes applied
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/code-review-fix.md
</execution_context>

<context>
Phase: $ARGUMENTS (first positional argument is phase number)

Optional flags parsed from $ARGUMENTS:
- `--all` — Include Info findings in fix scope. Default behavior fixes Critical + Warning only.
- `--auto` — Enable fix + re-review iteration loop. After applying fixes, re-run code-review at same depth. If new issues found, iterate. Cap at 3 iterations total. Without this flag, single fix pass only.

Context files (CLAUDE.md, REVIEW.md, phase state) are resolved inside the workflow via `gsd-tools init phase-op` and delegated to agent via config blocks.
</context>

<process>
This command is a thin dispatch layer. It parses arguments and delegates to the workflow.

Execute the code-review-fix workflow from @$HOME/.claude/get-shit-done/workflows/code-review-fix.md end-to-end.

The workflow (not this command) enforces these gates:
- Phase validation (before config gate)
- Config gate check (workflow.code_review)
- REVIEW.md existence check (error if missing)
- REVIEW.md status check (skip if clean/skipped)
- Agent spawning (kha-code-fixer)
- Iteration loop (if --auto, capped at 3 iterations)
- Result presentation (inline summary + next steps)
</process>

## Output


- inspection phase consumes existing `REVIEW.md` and emits a dry-run fix plan scoped to selected findings; mutation phase applies per-finding fix commits and produces `{NN}-REVIEW-FIX.md` with `all_fixed | partial | none_fixed`, counts, iteration, skipped findings, and rollback handles.

## Failure behavior


- missing `REVIEW.md` or `REVIEW.md` status `clean/skipped` aborts with no writes; fixer failure stops the run and reports whether any fix commits already landed; malformed fix report blocks the final docs commit.

## Gate summary


- review-consume and fix-apply are hard-separated; mandatory safety flow is dry-run -> snapshot (`HEAD` + targeted files) -> explicit confirm -> fix/test/commit; `--auto` may iterate only after the first confirmed pass; rollback is by reverting the recorded fix commits back to the pre-fix snapshot.

## Retry / Resume


- resume from `{NN}-REVIEW-FIX.md` and the recorded snapshot/commit list; reruns are not strictly idempotent because prior fix commits may already exist.
