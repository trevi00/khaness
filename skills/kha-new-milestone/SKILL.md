---
name: kha-new-milestone
description: "Start a new milestone cycle — update PROJECT.md and route to requirements"
argument-hint: "[milestone name, e.g., 'v1.1 Notifications']"
allowed-tools:
  - Read
  - Write
  - Bash
  - Task
  - AskUserQuestion
category: lifecycle
mutates: yes
long-running: yes
---
<objective>
Start a new milestone: questioning → research (optional) → requirements → roadmap.

Brownfield equivalent of new-project. Project exists, PROJECT.md has history. Gathers "what's next", updates PROJECT.md, then runs requirements → roadmap cycle.

**Creates/Updates:**
- `.planning/PROJECT.md` — updated with new milestone goals
- `.planning/research/` — domain research (optional, NEW features only)
- `.planning/REQUIREMENTS.md` — scoped requirements for this milestone
- `.planning/ROADMAP.md` — phase structure (continues numbering)
- `.planning/STATE.md` — reset for new milestone

**After:** `/kha-plan-phase [N]` to start execution.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/new-milestone.md
@$HOME/.claude/get-shit-done/references/questioning.md
@$HOME/.claude/get-shit-done/references/ui-brand.md
@$HOME/.claude/get-shit-done/templates/project.md
@$HOME/.claude/get-shit-done/templates/requirements.md
</execution_context>

<context>
Milestone name: $ARGUMENTS (optional - will prompt if not provided)

Project and milestone context files are resolved inside the workflow (`init new-milestone`) and delegated via `<files_to_read>` blocks where subagents are used.
</context>

<process>
Execute the new-milestone workflow from @$HOME/.claude/get-shit-done/workflows/new-milestone.md end-to-end.
Preserve all workflow gates (validation, questioning, research, requirements, roadmap approval, commits).
</process>

## Output


- artifact: `.planning/PROJECT.md` — updated with current milestone name, goal, and target features
- artifact: `.planning/STATE.md` — reset to milestone-start position before planning
- artifact: `.planning/research/SUMMARY.md` — synthesized milestone research summary when research is selected
- artifact: `.planning/REQUIREMENTS.md` — milestone-scoped requirements with continued REQ-ID numbering
- artifact: `.planning/ROADMAP.md` — new milestone roadmap with continued or reset phase numbering
- status: `initialized` | `blocked_reset_phase_numbers` | `blocked_roadmap` | `aborted_missing_project_context`

## Failure behavior


- missing project context (`PROJECT.md`/`STATE.md`/milestone history): abort before milestone rewrite and route back to project initialization or repair
- `--reset-phase-numbers` without a valid `phase_archive_path`: abort before roadmap generation; do not clear existing phase directories
- research or roadmapper blocked after milestone start commit: keep updated `.planning/PROJECT.md`, `.planning/STATE.md`, and any research/requirements already written; resume from `/kha-resume-work`
- old phase directories present during reset-numbering mode: archive or clear them first; never allow new `01-*` directories to collide with stale milestone phase dirs

## Gate summary


- preflight: existing project files are readable; `.planning/` is writable; if `--reset-phase-numbers` is set and phase dirs exist, `phase_archive_path` is available
- success criteria: `.planning/PROJECT.md` and `.planning/STATE.md` reflect the new milestone, `.planning/REQUIREMENTS.md` and `.planning/ROADMAP.md` are written, and the selected numbering mode is honored
- abort triggers: missing brownfield project context; unsafe reset-numbering archive state; unresolved roadmapper blocker

## Retry / Resume


- checkpoint: `.planning/STATE.md`
- resume command: `/kha-resume-work`
- idempotent: no — milestone versioning, phase clearing/archive, and requirement numbering are stateful transitions
- stall detection: no new durable artifact appears after the milestone-start commit, or the roadmapper returns a blocking result without producing `ROADMAP.md`
