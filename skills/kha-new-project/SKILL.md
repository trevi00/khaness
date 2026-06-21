---
name: kha-new-project
description: "Initialize a new project with deep context gathering and PROJECT.md"
argument-hint: "[--auto]"
allowed-tools:
  - Read
  - Bash
  - Write
  - Task
  - AskUserQuestion
category: lifecycle
mutates: yes
long-running: yes
---
<runtime_note>
**Copilot (VS Code):** Use `vscode_askquestions` wherever this workflow calls `AskUserQuestion`. They are equivalent — `vscode_askquestions` is the VS Code Copilot implementation of the same interactive question API.
</runtime_note>

<context>
**Flags:**
- `--auto` — Automatic mode. After config questions, runs research → requirements → roadmap without further interaction. Expects idea document via @ reference.
</context>

<objective>
Initialize a new project through unified flow: questioning → research (optional) → requirements → roadmap.

**Creates:**
- `.planning/PROJECT.md` — project context
- `.planning/config.json` — workflow preferences
- `.planning/research/` — domain research (optional)
- `.planning/REQUIREMENTS.md` — scoped requirements
- `.planning/ROADMAP.md` — phase structure
- `.planning/STATE.md` — project memory

**After this command:** Run `/kha-plan-phase 1` to start execution.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/new-project.md
@$HOME/.claude/get-shit-done/references/questioning.md
@$HOME/.claude/get-shit-done/references/ui-brand.md
@$HOME/.claude/get-shit-done/templates/project.md
@$HOME/.claude/get-shit-done/templates/requirements.md
</execution_context>

<process>
Execute the new-project workflow from @$HOME/.claude/get-shit-done/workflows/new-project.md end-to-end.
Preserve all workflow gates (validation, approvals, commits, routing).
</process>

## Output


- artifact: `.planning/PROJECT.md` — initialized project context from questioning or `--auto` idea-doc synthesis
- artifact: `.planning/config.json` — workflow mode, model profile, research/plan-check/verifier preferences
- artifact: `.planning/research/SUMMARY.md` — synthesized project research summary when research is selected
- artifact: `.planning/REQUIREMENTS.md` — scoped v1 requirements with REQ-IDs
- artifact: `.planning/ROADMAP.md` — committed phase roadmap with requirement traceability
- artifact: `.planning/STATE.md` — initialized execution state after roadmap creation
- artifact: `AGENTS.md` or `CLAUDE.md` — generated project instruction file for the current runtime
- status: `initialized` | `routed_map_codebase` | `aborted_existing_project` | `aborted_missing_auto_doc` | `blocked_roadmap`

## Failure behavior


- existing project already initialized: abort before `.planning/` mutation and route to `/kha-status`
- `--auto` without an attached/pasted idea document: abort before questioning/research with usage guidance
- brownfield mapping selected: exit cleanly with `routed_map_codebase`; no planning artifacts beyond any preflight git init
- roadmapper blocked after earlier stages committed: keep committed `.planning/PROJECT.md`, `.planning/config.json`, optional `.planning/research/`, and `.planning/REQUIREMENTS.md`; do not roll back; resume from `/kha-resume-work`

## Gate summary


- preflight: no existing initialized project; working directory is writable; git is present or can be initialized; `--auto` includes idea-document content
- success criteria: `.planning/ROADMAP.md` and `.planning/STATE.md` exist, `.planning/REQUIREMENTS.md` traceability is filled, and the runtime instruction file is generated
- abort triggers: project already initialized; missing `--auto` document; unresolved roadmapper blocker

## Retry / Resume


- checkpoint: `.planning/PROJECT.md`
- resume command: `/kha-resume-work`
- idempotent: no — rerunning after initialization hits the existing-project guard and earlier atomic commits are preserved
- stall detection: no new durable artifact appears at the expected stage boundary (`PROJECT.md` -> `config.json` -> `research/SUMMARY.md` -> `REQUIREMENTS.md` -> `ROADMAP.md`/`STATE.md`), or the roadmapper returns `## ROADMAP BLOCKED`
