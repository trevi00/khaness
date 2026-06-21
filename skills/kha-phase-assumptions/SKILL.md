---
name: kha-phase-assumptions
description: "Surface Claude's assumptions about a phase approach before planning"
argument-hint: "[phase]"
allowed-tools:
  - Read
  - Bash
  - Grep
  - Glob
category: status
mutates: no
long-running: no
---
<objective>
Analyze a phase and present Claude's assumptions about technical approach, implementation order, scope boundaries, risk areas, and dependencies.

Purpose: Help users see what Claude thinks BEFORE planning begins - enabling course correction early when assumptions are wrong.
Output: Conversational output only (no file creation) - ends with "What do you think?" prompt
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/list-phase-assumptions.md
</execution_context>

<context>
Phase number: $ARGUMENTS (required)

Project state and roadmap are loaded in-workflow using targeted reads.
</context>

<process>
1. Validate phase number argument (error if missing or invalid)
2. Check if phase exists in roadmap
3. Follow list-phase-assumptions.md workflow:
   - Analyze roadmap description
   - Surface assumptions about: technical approach, implementation order, scope, risks, dependencies
   - Present assumptions clearly
   - Prompt "What do you think?"
4. Gather feedback and offer next steps
</process>

<success_criteria>

- Phase validated against roadmap
- Assumptions surfaced across five areas
- User prompted for feedback
- User knows next steps (discuss context, plan phase, or correct assumptions)
  </success_criteria>

## Output


- artifact: `stdout` — conversational assumption report across technical approach, implementation order, scope boundaries, risk areas, and dependencies
- status: `reported` | `corrected` | `aborted_missing_phase` | `aborted_phase_not_found`

## Failure behavior


- missing phase argument: abort with usage text; no file writes
- phase not found in roadmap: abort after listing available phases; no file writes
- user corrections remain conversational only; nothing is persisted until the user runs `/kha-clarify-phase` or `/kha-plan-phase`

## Gate summary


- preflight: phase argument is present and `.planning/ROADMAP.md` is readable
- success criteria: all five assumption areas are surfaced, confidence is called out where relevant, the user is prompted with “What do you think?”, and next-step options are offered
- abort triggers: missing phase argument; unknown phase in roadmap
