---
name: kha-run-milestone
description: "Run all remaining phases autonomously — discuss→plan→execute per phase"
argument-hint: "[--from N] [--to N] [--only N] [--interactive]"
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
  - Task
category: run
mutates: yes
long-running: yes
---
<objective>
Execute all remaining milestone phases autonomously. For each phase: discuss → plan → execute. Pauses only for user decisions (grey area acceptance, blockers, validation requests).

Uses ROADMAP.md phase discovery and Skill() flat invocations for each phase command. After all phases complete: milestone audit → complete → cleanup.

**Creates/Updates:**
- `.planning/STATE.md` — updated after each phase
- `.planning/ROADMAP.md` — progress updated after each phase
- Phase artifacts — CONTEXT.md, PLANs, SUMMARYs per phase

**After:** Milestone is complete and cleaned up.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/autonomous.md
@$HOME/.claude/get-shit-done/references/ui-brand.md
</execution_context>

<context>
Optional flags:
- `--from N` — start from phase N instead of the first incomplete phase.
- `--to N` — stop after phase N completes (halt instead of advancing to next phase).
- `--only N` — execute only phase N (single-phase mode).
- `--interactive` — run discuss inline with questions (not auto-answered), then dispatch plan→execute as background agents. Keeps the main context lean while preserving user input on decisions.

Project context, phase list, and state are resolved inside the workflow using init commands (`gsd-tools.cjs init milestone-op`, `gsd-tools.cjs roadmap analyze`). No upfront context loading needed.
</context>

<process>
Execute the autonomous workflow from @$HOME/.claude/get-shit-done/workflows/autonomous.md end-to-end.
Preserve all workflow gates (phase discovery, per-phase execution, blocker handling, progress display).
</process>

## Output


- artifact: `.planning/RUN-MILESTONE.json` — resume token recording current phase, completed/skipped phases, next phase, and active flag set
- artifact: `.planning/.run-milestone.lock` — single-run concurrency lock for autonomous milestone execution
- artifact: `.planning/STATE.md` — updated after each phase and each lifecycle step
- artifact: `.planning/ROADMAP.md` — re-read and updated after each phase to catch inserted work
- artifact: `.planning/phases/*/` — per-phase `CONTEXT.md`, `PLAN.md`, `SUMMARY.md`, `VERIFICATION.md`, and optional UI artifacts
- artifact: `.planning/milestones/v${milestone_version}-ROADMAP.md` — created only when a full milestone run reaches lifecycle completion
- status: `complete` | `partial_range_complete` | `single_phase_complete` | `stopped_blocker` | `stopped_user` | `aborted_no_roadmap` | `aborted_lock_held`

## Failure behavior


- concurrent autonomous run detected: if `.planning/.run-milestone.lock` already exists, abort before discovery and print the existing lock/resume-token owner instead of starting a second run
- resume token is mandatory: update `.planning/RUN-MILESTONE.json` after every completed, skipped, or blocked phase so the next run can restart from the exact next phase
- per-phase blocker: preserve all already-completed phases in the resume token and offer retry / skip / stop; never restart the whole milestone silently
- lifecycle failure after all phases complete: stop at the failing audit/complete/cleanup step, keep prior phase outputs, and leave the resume token pointing at the lifecycle stage instead of rerunning earlier phases

## Gate summary


- preflight: `.planning/ROADMAP.md` and `.planning/STATE.md` exist; `--from`/`--to`/`--only` filters parse cleanly; no active `.planning/.run-milestone.lock`; resume token, if present, matches the same milestone scope
- success criteria: selected phases are processed in numeric order, the resume token advances after each phase, and a full-run invocation completes the lifecycle chain audit -> complete -> cleanup
- abort triggers: missing roadmap/state; active lock; user chooses stop in blocker handling; lifecycle step fails to produce its required file/status

## Retry / Resume


- checkpoint: `.planning/RUN-MILESTONE.json`
- resume command: `/kha-run-milestone --from ${next_incomplete_phase}`
- idempotent: yes — each rerun re-analyzes the roadmap and skips phases already marked complete, while the lock prevents concurrent duplicate runs
- stall detection: the resume token does not advance after a phase attempt, or the current phase fails to produce its expected `CONTEXT.md` / `PLAN.md` / `VERIFICATION.md` terminal artifact before the next loop

### checkpoint per phase
- Before starting each phase, append to `.planning/checkpoints/run-milestone.jsonl`:
  `{phase_id, started_at, mode: discuss|plan|execute, attempt: N}`.
- On phase completion, append `{phase_id, completed_at, status: ok|failed}`.
- Resume reads the JSONL tail and skips phases marked completed.

### lock for the whole milestone
- Acquire `.planning/.locks/run-milestone.lock` at start. Single concurrent
  run-milestone per project. Lock TTL = max-runtime + 1h grace.

### deadline-aware
- Per-phase soft deadline = max-runtime / phases-remaining. On overrun,
  emit `phase_overrun` event but continue (do not auto-kill — user intervention).

### partial-failure handling
- On a single phase failure, halt the milestone (do not advance). Manual
  user review then explicit re-trigger of run-milestone resumes from the
  failed phase.

=== worker-1 lifecycle/phase 본문 fill 완료 ===
