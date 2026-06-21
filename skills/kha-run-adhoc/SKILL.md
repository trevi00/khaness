---
name: kha-run-adhoc
description: "Execute a quick task with GSD guarantees (atomic commits, state tracking) but skip optional agents"
argument-hint: "[--full] [--validate] [--discuss] [--research] [--scratch]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
  - Task
  - AskUserQuestion
category: run
mutates: yes
long-running: yes
---
<objective>
Execute small, ad-hoc tasks with GSD guarantees (atomic commits, STATE.md tracking).

Quick mode is the same system with a shorter path:
- Spawns kha-planner (quick mode) + kha-executor(s)
- Quick tasks live in `.planning/quick/` separate from planned phases
- Updates STATE.md "Quick Tasks Completed" table (NOT ROADMAP.md)

**Default:** Skips research, discussion, plan-checker, verifier. Use when you know exactly what to do.

**`--discuss` flag:** Lightweight discussion phase before planning. Surfaces assumptions, clarifies gray areas, captures decisions in CONTEXT.md. Use when the task has ambiguity worth resolving upfront.

**`--full` flag:** Enables the complete quality pipeline — discussion + research + plan-checking + verification. One flag for everything.

**`--validate` flag:** Enables plan-checking (max 2 iterations) and post-execution verification only. Use when you want quality guarantees without discussion or research.

**`--research` flag:** Spawns a focused research agent before planning. Investigates implementation approaches, library options, and pitfalls for the task. Use when you're unsure of the best approach.

**`--scratch` flag (throwaway / no-commit, P3 absorption — debate-1780911873-da8277):** Disposable experiment or mockup that leaves NO permanent artifact. Writes under `.planning/scratch/` instead of `.planning/quick/`, requires no ROADMAP.md, and SKIPS all commits + the STATE.md quick-task row — the output stays uncommitted and deletable. This is the home for gsd-core `spike` (experimental code: `/kha-run-adhoc --scratch <experiment>`, add `--research` when the approach is unknown) and `sketch` (throwaway UI mockup: `/kha-run-adhoc --scratch 'emit a single self-contained throwaway HTML mockup'`). For production-grade UI use the harness-designer agent instead.

Granular flags are composable: `--discuss --research --validate` gives the same result as `--full`.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/quick.md
</execution_context>

<context>
$ARGUMENTS

Context files are resolved inside the workflow (`init quick`) and delegated via `<files_to_read>` blocks.
</context>

<process>
Execute the quick workflow from @$HOME/.claude/get-shit-done/workflows/quick.md end-to-end.
Preserve all workflow gates (validation, task description, planning, execution, state updates, commits).
</process>

## Output


- artifact: `.planning/quick/{quick_id}-{slug}/` keyed by a real task description, with mandatory `{quick_id}-PLAN.md` and `{quick_id}-SUMMARY.md`, optional `-CONTEXT.md`, `-RESEARCH.md`, `-VERIFICATION.md`, and a `STATE.md` quick-task row. **Under `--scratch`: artifact lives at `.planning/scratch/{quick_id}-{slug}/` instead, with NO STATE.md row and NO commit (uncommitted + deletable).**
- status: `quick_complete` | `quick_complete_validated` | `quick_complete_needs_review` | `quick_gaps_found` | `blocked_no_project` | `scratch_complete`

## Failure behavior


- preflight failure: flags alone are not a valid invocation; if no non-flag task description remains after parsing, ask until one exists and do not allocate a quick dir yet; missing `ROADMAP.md` aborts before any quick-task artifact is created — **except under `--scratch`, which requires no ROADMAP.md and runs in any directory**.
- execution failure: once the quick dir exists, preserve whatever artifacts were already produced by discussion, research, planning, execution, or verification, and report the exact stage reached instead of cleaning them up.

## Gate summary


- preflight: at least one non-flag task-description token is present, `init quick` succeeds, and the project has an active `ROADMAP.md` (the ROADMAP requirement is waived under `--scratch`).
- success criteria: the quick dir exists, the planner writes `PLAN.md`, the executor writes `SUMMARY.md`, optional research/discussion/verification files appear when their flags are enabled, `STATE.md` records the task, and the artifact commit completes.

## Retry / Resume


- checkpoint: `.planning/quick/{quick_id}-{slug}/` and any artifacts already written there.
- resume command: none stable; rerunning `/kha-run-adhoc ...` creates a new quick task, so the existing quick dir is the handoff surface for manual continuation or for seeding a fresh rerun.
- idempotent: no.
