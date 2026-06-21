---
name: kha-verify-uat
description: "Validate built features through conversational UAT"
argument-hint: "[phase number, e.g., '4']"
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
  - Edit
  - Write
  - Task
category: verify
mutates: no
long-running: yes
---
<objective>
Validate built features through conversational testing with persistent state.

Purpose: Confirm what Claude built actually works from user's perspective. One test at a time, plain text responses, no interrogation. When issues are found, automatically diagnose, plan fixes, and prepare for execution.

Output: {phase_num}-UAT.md tracking all test results. If issues found: diagnosed gaps, verified fix plans ready for /kha-execute-phase
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/verify-work.md
@$HOME/.claude/get-shit-done/templates/UAT.md
</execution_context>

<context>
Phase: $ARGUMENTS (optional)
- If provided: Test specific phase (e.g., "4")
- If not provided: Check for active sessions or prompt for phase

Context files are resolved inside the workflow (`init verify-work`) and delegated via `<files_to_read>` blocks.
</context>

<process>
Execute the verify-work workflow from @$HOME/.claude/get-shit-done/workflows/verify-work.md end-to-end.
Preserve all workflow gates (session management, test presentation, diagnosis, fix planning, routing).
</process>

## Output


- pass/fail evidence in `{NN}-UAT.md` plus inline checkpoint presentation, with session status `testing | partial | complete`, passed/issues/skipped counts, blocked reasons, and structured gap entries for failed expectations.

## Failure behavior


- no phase and no active session prompts once then aborts; missing SUMMARY artifacts mean no generated tests and no fabricated checkpoints; interrupted sessions preserve the last checkpoint and resume from the first pending test.

## Gate summary


- verify-only boundary is enforced; tests are presented one observable expectation at a time, severity is inferred from user text, and this skill never applies implementation fixes directly; failed expectations route into diagnosis/planning follow-up instead of code mutation.

## Retry / Resume


- resume from the existing `*-UAT.md`; checkpointed sessions survive `/clear` and continue from the first pending test.
