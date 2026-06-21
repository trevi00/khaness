---
name: kha-milestone-manager
description: "Interactive command center for managing multiple phases from one terminal"
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
  - Skill
  - Task
category: meta
mutates: yes
long-running: no
---
<objective>
Single-terminal command center for managing a milestone. Shows a dashboard of all phases with visual status indicators, recommends optimal next actions, and dispatches work — discuss runs inline, plan/execute run as background agents.

Designed for power users who want to parallelize work across phases from one terminal: discuss a phase while another plans or executes in the background.

**Creates/Updates:**
- No files created directly — dispatches to existing GSD commands via Skill() and background Task agents.
- Reads `.planning/STATE.md`, `.planning/ROADMAP.md`, phase directories for status.

**After:** User exits when done managing, or all phases complete and milestone lifecycle is suggested.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/manager.md
@$HOME/.claude/get-shit-done/references/ui-brand.md
</execution_context>

<context>
No arguments required. Requires an active milestone with ROADMAP.md and STATE.md.

Project context, phase list, dependencies, and recommendations are resolved inside the workflow using `gsd-tools.cjs init manager`. No upfront context loading needed.
</context>

<process>
Execute the manager workflow from @$HOME/.claude/get-shit-done/workflows/manager.md end-to-end.
Maintain the dashboard refresh loop until the user exits or all phases complete.
</process>

## Output


- artifacts: live dashboard view from `init manager`, background plan/execute task dispatches, inline discuss routing, completion notifications, and final session-end status block.
- status: `dashboard_refreshed` | `action_dispatched` | `manager_exited` | `milestone_complete`.

## Failure behavior


- preflight: if manager init fails or no active milestone state can be loaded, abort before entering the dashboard loop.
- execution: background agent errors must surface as retry/run-inline/skip choices; inline discuss/plan/execute failures stay owned by the delegated skill and are reported back through the manager.
- partial: the manager itself should not roll back phase mutations; it only reports which delegated action succeeded, failed, or is still running.

## Gate summary


- preflight: active milestone state is readable; dashboard shows current phase statuses and recommended actions before anything is dispatched.
- success: dry-run/snapshot/confirm are enforced by rendering the current dashboard as before-state, enumerating every compound action before dispatch, and requiring an explicit action selection before any background mutation starts.
- boundary: own interactive multi-phase orchestration within the current milestone; `kha-list-workspaces` only lists external workspaces read-only; `kha-workstream-manager` owns parallel workstream lifecycle rather than per-phase milestone control.
