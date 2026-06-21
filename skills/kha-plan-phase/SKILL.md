---
name: kha-plan-phase
description: "Create detailed phase plan (PLAN.md) with verification loop"
argument-hint: "[phase] [--auto] [--research] [--skip-research] [--gaps] [--skip-verify] [--prd <file>] [--reviews] [--text]"
agent: kha-planner
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
  - Grep
  - Task
  - AskUserQuestion
  - WebFetch
  - mcp__context7__*
category: plan
mutates: yes
long-running: yes
---
<objective>
Create executable phase prompts (PLAN.md files) for a roadmap phase with integrated research and verification.

**Default flow:** Research (if needed) → Plan → Verify → Done

**Orchestrator role:** Parse arguments, validate phase, research domain (unless skipped), spawn kha-planner, verify with kha-plan-checker, iterate until pass or max iterations, present results.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/plan-phase.md
@$HOME/.claude/get-shit-done/references/ui-brand.md
</execution_context>

<runtime_note>
**Copilot (VS Code):** Use `vscode_askquestions` wherever this workflow calls `AskUserQuestion`. They are equivalent — `vscode_askquestions` is the VS Code Copilot implementation of the same interactive question API. Do not skip questioning steps because `AskUserQuestion` appears unavailable; use `vscode_askquestions` instead.
</runtime_note>

<context>
Phase number: $ARGUMENTS (optional — auto-detects next unplanned phase if omitted)

**Flags:**
- `--research` — Force re-research even if RESEARCH.md exists
- `--skip-research` — Skip research, go straight to planning
- `--gaps` — Gap closure mode (reads VERIFICATION.md, skips research)
- `--skip-verify` — Skip verification loop
- `--prd <file>` — Use a PRD/acceptance criteria file instead of discuss-phase. Parses requirements into CONTEXT.md automatically. Skips discuss-phase entirely.
- `--reviews` — Replan incorporating cross-AI review feedback from REVIEWS.md (produced by `/kha-review-plan-peer`)
- `--text` — Use plain-text numbered lists instead of TUI menus (required for `/rc` remote sessions)

Normalize phase input in step 2 before any directory lookups.
</context>

<process>
Execute the plan-phase workflow from @$HOME/.claude/get-shit-done/workflows/plan-phase.md end-to-end.
Preserve all workflow gates (validation, research, planning, verification loop, routing).

**Graph projection post-step (deterministic; P2 D1, debate-1780870185-827a94):**
After plans land and `.planning/STATE.md` is updated, refresh the typed-edge phase graph:
`python -m cli.phase_graph build --root .planning`
This is a DETERMINISTIC orchestrator post-step over the already-written ROADMAP/`*-PLAN.md` — it does NOT run inside the kha-planner LLM agent (single-responsibility). It emits `.planning/_graph/phase-graph.json` (in-scope path; never written to the Atlas note-vault). Best-effort: if `ROADMAP.md` is absent the step exits non-zero and is skipped. Downstream planning can query it, e.g. "which phases depend on phase-3":
`python -m cli.phase_graph query --root .planning --kind depends-on --node phase-3 --direction in`
</process>

## Output


- artifact: `${phase_dir}/${padded_phase}-CONTEXT.md` — generated only when `--prd <file>` is used
- artifact: `${phase_dir}/${padded_phase}-RESEARCH.md` — phase research output when research runs
- artifact: `${phase_dir}/${padded_phase}-VALIDATION.md` — validation strategy file when Nyquist validation is enabled and research supports it
- artifact: `${phase_dir}/*-PLAN.md` — executable plan files with waves, dependencies, and acceptance criteria
- artifact: `.planning/STATE.md` — updated to `planned-phase` / ready-to-execute state
- artifact: `.planning/_graph/phase-graph.json` — typed-edge phase graph (deterministic projection; refreshed by the post-step `python -m cli.phase_graph build --root .planning`)
- status: `planned` | `planned_with_override` | `routed_discuss_phase` | `aborted_invalid_phase` | `aborted_missing_prd` | `aborted_missing_reviews` | `abandoned`

## Failure behavior


- missing `CONTEXT.md` and user chooses context capture first: exit with `routed_discuss_phase`; do not create plans
- `--prd <file>` unreadable: abort before planning and do not generate `CONTEXT.md`
- `--reviews` without `REVIEWS.md`, or `--reviews` combined with `--gaps`: abort before planning
- research blocked/inconclusive: keep current `CONTEXT.md` and any existing `RESEARCH.md`; user must provide context, skip research, retry, or stop
- checker stall or max-iteration limit: preserve latest `*-PLAN.md` revisions and require an explicit proceed/retry/abandon decision; never auto-pass a failed check loop

## Gate summary


- preflight: `.planning/` and `ROADMAP.md` exist; target phase resolves; `--prd` file is readable when supplied; `REVIEWS.md` exists for `--reviews`; phase directory is writable
- success criteria: at least one `*-PLAN.md` exists, the requirements-coverage gate passes or is explicitly overridden, and `.planning/STATE.md` records the phase as ready to execute
- abort triggers: invalid phase; unreadable PRD; missing review prerequisite; user abandons after the revision/coverage gates

## Retry / Resume


- checkpoint: `${phase_dir}/`
- resume command: `/kha-plan-phase ${phase_number}`
- idempotent: no — reruns may regenerate research, validation, and plan files and can replace prior plan revisions
- stall detection: checker issue count does not decrease across revision iterations, or planner/checker returns no terminal marker and no new `*-PLAN.md` revision appears
