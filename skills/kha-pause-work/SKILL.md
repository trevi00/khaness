---
name: kha-pause-work
description: "Create context handoff when pausing work mid-phase"
allowed-tools:
  - Read
  - Write
  - Bash
category: lifecycle
mutates: yes
long-running: no
---
<objective>
Create `.continue-here.md` handoff file to preserve complete work state across sessions.

Routes to the pause-work workflow which handles:
- Current phase detection from recent files
- Complete state gathering (position, completed work, remaining work, decisions, blockers)
- Handoff file creation with all context sections
- Git commit as WIP
- Resume instructions
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/pause-work.md
</execution_context>

<context>
State and phase progress are gathered in-workflow with targeted reads.
</context>

<process>
**Follow the pause-work workflow** from `@$HOME/.claude/get-shit-done/workflows/pause-work.md`.

The workflow handles all logic including:
1. Phase directory detection
2. State gathering with user clarifications
3. Handoff file writing with timestamp
4. Git commit
5. Confirmation with resume instructions
</process>

## Output


- artifact: `.planning/HANDOFF.json` — structured machine-readable resume state
- artifact: `[detected handoff path]` — human-readable `.continue-here.md` at the detected phase/spike/deliberation/research/default target
- artifact: `git commit "wip: [context-name] paused at [X]/[Y]"` — WIP snapshot after handoff files are written
- status: `paused` | `paused_with_blockers` | `aborted_unwritable_handoff`

## Failure behavior


- no clear active context: fall back to `.planning/.continue-here.md` and record the ambiguity in `<current_state>` instead of guessing a phase path
- placeholder/TBD content found in prior summaries: treat those items as incomplete work and include them in the handoff
- commit failure after handoff write: keep `.planning/HANDOFF.json` and the `.continue-here.md` file on disk for manual recovery; do not delete the handoff artifacts

## Gate summary


- preflight: `.planning/` exists; a writable handoff destination can be selected; timestamp generation works; minimum current-state data can be gathered
- success criteria: `HANDOFF.json` and the human-readable handoff exist, required reading / anti-pattern / infra sections are filled, and a WIP commit is created
- abort triggers: no writable handoff target; handoff cannot capture enough state to resume safely

