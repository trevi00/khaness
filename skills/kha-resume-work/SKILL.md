---
name: kha-resume-work
description: "Resume work from previous session with full context restoration"
allowed-tools:
  - Read
  - Bash
  - Write
  - AskUserQuestion
  - SlashCommand
category: lifecycle
mutates: yes
long-running: no
---
<objective>
Restore complete project context and resume work seamlessly from previous session.

Routes to the resume-project workflow which handles:

- STATE.md loading (or reconstruction if missing)
- Checkpoint detection (.continue-here files)
- Incomplete work detection (PLAN without SUMMARY)
- Status presentation
- Context-aware next action routing
  </objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/resume-project.md
</execution_context>

<process>
**Follow the resume-project workflow** from `@$HOME/.claude/get-shit-done/workflows/resume-project.md`.

The workflow handles all resumption logic including:

1. Project existence verification
2. STATE.md loading or reconstruction
3. Checkpoint and incomplete work detection
4. Visual status presentation
5. Context-aware option offering (checks CONTEXT.md before suggesting plan vs discuss)
6. Routing to appropriate next command
7. Session continuity updates
   </process>

## Output


- artifact: `.planning/STATE.md` — loaded or reconstructed session state, then updated with new session continuity
- artifact: `.planning/HANDOFF.json` — structured handoff source when present; consumed as the primary resume source
- artifact: `.planning/phases/*/.continue-here*.md` — mid-plan checkpoint source when present
- artifact: `stdout` — full status restoration plus routed next-action options or quick-resume action
- status: `resume_ready` | `quick_resumed` | `reconstructed_state` | `routed_new_project`

## Failure behavior


- missing `STATE.md` but project artifacts exist: reconstruct state from `PROJECT.md`, `ROADMAP.md`, summaries, todos, and checkpoints instead of aborting
- divergence between `HANDOFF.json` uncommitted-file list and live `git status`: surface the mismatch; do not overwrite or ignore it
- interrupted agent detected: surface the agent id and resume handle rather than silently discarding the agent state

## Gate summary


- preflight: `.planning/` exists or reconstructable project artifacts exist; handoff/checkpoint paths are readable when present
- success criteria: project state is restored, incomplete work is flagged, session continuity is updated, and the user receives the primary next action or immediate quick-resume execution
- abort triggers: no planning structure and no reconstructable project artifacts

