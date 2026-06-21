---
name: kha-execute-phase
description: "Execute all plans in a phase with wave-based parallelization"
argument-hint: "<phase-number> [--wave N] [--gaps-only] [--interactive]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
  - Task
  - TodoWrite
  - AskUserQuestion
category: run
mutates: yes
long-running: yes
---
<objective>
Execute all plans in a phase using wave-based parallel execution.

Orchestrator stays lean: discover plans, analyze dependencies, group into waves, spawn subagents, collect results. Each subagent loads the full execute-plan context and handles its own plan.

Optional wave filter:
- `--wave N` executes only Wave `N` for pacing, quota management, or staged rollout
- phase verification/completion still only happens when no incomplete plans remain after the selected wave finishes

Flag handling rule:
- The optional flags documented below are available behaviors, not implied active behaviors
- A flag is active only when its literal token appears in `$ARGUMENTS`
- If a documented flag is absent from `$ARGUMENTS`, treat it as inactive

Context budget: ~15% orchestrator, 100% fresh per subagent.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-phase.md
@$HOME/.claude/get-shit-done/references/ui-brand.md
</execution_context>

<runtime_note>
**Copilot (VS Code):** Use `vscode_askquestions` wherever this workflow calls `AskUserQuestion`. They are equivalent — `vscode_askquestions` is the VS Code Copilot implementation of the same interactive question API.
</runtime_note>

<context>
Phase: $ARGUMENTS

**Available optional flags (documentation only — not automatically active):**
- `--wave N` — Execute only Wave `N` in the phase. Use when you want to pace execution or stay inside usage limits.
- `--gaps-only` — Execute only gap closure plans (plans with `gap_closure: true` in frontmatter). Use after verify-work creates fix plans.
- `--interactive` — Execute plans sequentially inline (no subagents) with user checkpoints between tasks. Lower token usage, pair-programming style. Best for small phases, bug fixes, and verification gaps.

**Active flags must be derived from `$ARGUMENTS`:**
- `--wave N` is active only if the literal `--wave` token is present in `$ARGUMENTS`
- `--gaps-only` is active only if the literal `--gaps-only` token is present in `$ARGUMENTS`
- `--interactive` is active only if the literal `--interactive` token is present in `$ARGUMENTS`
- If none of these tokens appear, run the standard full-phase execution flow with no flag-specific filtering
- Do not infer that a flag is active just because it is documented in this prompt

Context files are resolved inside the workflow via `gsd-tools init execute-phase` and per-subagent `<files_to_read>` blocks.
</context>

<process>
Execute the execute-phase workflow from @$HOME/.claude/get-shit-done/workflows/execute-phase.md end-to-end.
Preserve all workflow gates (wave execution, checkpoint handling, verification, state updates, routing).
</process>

## Retry / Resume

### checkpoint per wave
- Each wave completion writes `.planning/checkpoints/execute-phase-<phase-id>.json`
  with: { wave_index, completed_plans: [...], failed_plans: [...], started_at, ended_at }.
- Re-running on same phase reads the checkpoint and skips completed plans.

### lock per phase
- Acquire `.planning/.locks/execute-phase-<phase-id>.lock` at start. Refuse
  to start another execute-phase on the same phase while lock is held.
- Lock is released on completion (DONE) or on hard-cap timeout.

### resume after interrupt
- On interrupt mid-wave, the in-flight plan's atomic commit may be partial.
  Resume scans `git status` first; if dirty, halts with "manual cleanup needed"
  message rather than auto-rolling-back.

### idempotency
- Plans are atomic-committed individually; resume picks up at the next
  un-committed plan in the wave order.

## Output


- artifact: `${phase_dir}/*-SUMMARY.md` — one summary per completed plan, used as the wave/plan completion checkpoint
- artifact: `${phase_dir}/*-VERIFICATION.md` — phase verification result with `status: passed|human_needed|gaps_found`
- artifact: `${phase_dir}/*-HUMAN-UAT.md` — persisted human-verification checklist when verifier returns `human_needed`
- artifact: `${phase_dir}/*-REVIEW.md` — code-review result when review is enabled
- artifact: `.planning/ROADMAP.md` — phase completion and progress updates
- artifact: `.planning/STATE.md` — current wave/phase progress and post-phase position
- artifact: `.planning/REQUIREMENTS.md` — updated requirement traceability after successful completion
- artifact: `.planning/PROJECT.md` — evolved project snapshot after phase completion
- status: `phase_complete` | `human_needed` | `gaps_found` | `partial_wave_complete` | `blocked_schema_drift` | `aborted_invalid_phase` | `aborted_no_plans`

## Failure behavior


- missing agent completion signal but `*-SUMMARY.md` plus expected commits exist: treat the plan as successful via spot-check fallback and continue
- wave failure preserves completed `*-SUMMARY.md` files and stops dependent work; user chooses retry, skip, or abort instead of silent replay
- schema drift after execution is a hard verification block until the push command runs or the user explicitly overrides the gate
- wave checkpoint rule: a wave is complete only when every targeted plan in that wave has its `*-SUMMARY.md`; phase verification never runs after a filtered wave while earlier matching work remains incomplete
- lock convention: worktree-creating Task dispatches are serialized one at a time to avoid `.git/config.lock` contention; never fan out same-wave worktree creation in a single burst

## Gate summary


- preflight: phase exists; at least one plan exists after any `--wave` / `--gaps-only` filtering; earlier waves are complete when `--wave N` is used; blocking anti-patterns in `.continue-here.md` are acknowledged
- success criteria: all targeted plans produce `*-SUMMARY.md`, verifier writes a terminal `status:` to `*-VERIFICATION.md`, and successful completion updates `ROADMAP.md`, `STATE.md`, and requirements traceability
- abort triggers: invalid phase; no plans after filtering; unresolved blocking anti-pattern; schema-drift block not overridden; user abort after systemic execution failure
