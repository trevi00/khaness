---
name: kha-clarify-phase
description: "Gather phase context through adaptive questioning before planning. Use --auto to skip interactive questions (Claude picks recommended defaults). Use --chain for interactive discuss followed by automatic plan+execute. Use --power for bulk question generation into a file-based UI (answer at your own pace)."
argument-hint: "<phase> [--auto] [--chain] [--batch] [--analyze] [--text] [--power]"
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
  - Task
  - mcp__context7__resolve-library-id
  - mcp__context7__query-docs
category: plan
mutates: yes
long-running: yes
---
<objective>
Extract implementation decisions that downstream agents need — researcher and planner will use CONTEXT.md to know what to investigate and what choices are locked.

**How it works:**
1. Load prior context (PROJECT.md, REQUIREMENTS.md, STATE.md, prior CONTEXT.md files)
2. Scout codebase for reusable assets and patterns
3. Analyze phase — skip gray areas already decided in prior phases
4. Present remaining gray areas — user selects which to discuss
5. Deep-dive each selected area until satisfied
6. Create CONTEXT.md with decisions that guide research and planning

**Output:** `{phase_num}-CONTEXT.md` — decisions clear enough that downstream agents can act without asking the user again
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/discuss-phase.md
@$HOME/.claude/get-shit-done/workflows/discuss-phase-assumptions.md
@$HOME/.claude/get-shit-done/workflows/discuss-phase-power.md
@$HOME/.claude/get-shit-done/templates/context.md
</execution_context>

<runtime_note>
**Copilot (VS Code):** Use `vscode_askquestions` wherever this workflow calls `AskUserQuestion`. They are equivalent — `vscode_askquestions` is the VS Code Copilot implementation of the same interactive question API.
</runtime_note>

<context>
Phase number: $ARGUMENTS (required)

Context files are resolved in-workflow using `init phase-op` and roadmap/state tool calls.
</context>

<process>
**Mode routing:**
```bash
DISCUSS_MODE=$(node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" config-get workflow.discuss_mode 2>/dev/null || echo "discuss")
```

If `DISCUSS_MODE` is `"assumptions"`: Read and execute @$HOME/.claude/get-shit-done/workflows/discuss-phase-assumptions.md end-to-end.

If `DISCUSS_MODE` is `"discuss"` (or unset, or any other value): Read and execute @$HOME/.claude/get-shit-done/workflows/discuss-phase.md end-to-end.

**MANDATORY:** The execution_context files listed above ARE the instructions. Read the workflow file BEFORE taking any action. The objective and success_criteria sections in this command file are summaries — the workflow file contains the complete step-by-step process with all required behaviors, config checks, and interaction patterns. Do not improvise from the summary.
</process>

<success_criteria>
- Prior context loaded and applied (no re-asking decided questions)
- Gray areas identified through intelligent analysis
- User chose which areas to discuss
- Each selected area explored until satisfied
- Scope creep redirected to deferred ideas
- CONTEXT.md captures decisions, not vague vision
- User knows next steps
</success_criteria>

## Output


- artifact: `${phase_dir}/${padded_phase}-CONTEXT.md` — canonical decision record for downstream research/planning
- artifact: `${phase_dir}/${padded_phase}-DISCUSSION-LOG.md` — audit log of options presented and user choices
- artifact: `${phase_dir}/${padded_phase}-DISCUSS-CHECKPOINT.json` — incremental checkpoint while discussion is in progress; deleted after successful context write
- artifact: `${phase_dir}/${padded_phase}-QUESTIONS.json` — power-mode question state file when `--power` is used
- artifact: `${phase_dir}/${padded_phase}-QUESTIONS.html` — self-contained power-mode UI when `--power` is used
- artifact: `.planning/STATE.md` — updated resume/session pointer after context capture
- status: `context_captured` | `power_mode_waiting` | `planning_complete` | `phase_complete` | `skipped_existing_context` | `aborted_invalid_phase`

## Failure behavior


- existing `CONTEXT.md` or existing plans force an explicit update/view/skip or continue-and-replan decision; the skill never silently overwrites context
- interrupted discussion resumes from `${padded_phase}-DISCUSS-CHECKPOINT.json` instead of discarding completed areas
- empty AskUserQuestion reply: retry once, then fall back to plain-text numbered choices
- power-mode finalize with low answer coverage still writes `CONTEXT.md`, but unanswered questions are preserved as deferred items and the user is warned

## Gate summary


- preflight: phase resolves; `.planning/` exists; blocking anti-patterns from `.continue-here.md` are understood; phase directory is writable
- success criteria: `CONTEXT.md` and `DISCUSSION-LOG.md` are committed, or power mode writes `QUESTIONS.json`/`QUESTIONS.html`; `canonical_refs` is present; checkpoint file is removed after successful context write; `.planning/STATE.md` is updated
- abort triggers: invalid phase; user cancels after existing-context/existing-plan gates; blocking anti-pattern cannot be understood from the handoff

## Retry / Resume


- checkpoint: `${phase_dir}/${padded_phase}-DISCUSS-CHECKPOINT.json` or `${phase_dir}/${padded_phase}-QUESTIONS.json` in `--power` mode
- resume command: `/kha-clarify-phase ${phase_number}` (`--power` if using the file-based question UI)
- idempotent: no — repeated runs can revise prior decisions and overwrite `CONTEXT.md` / `DISCUSSION-LOG.md`
- stall detection: completed-area count stops advancing in the checkpoint, or power-mode `refresh` leaves `answered` unchanged while `remaining > 0`
