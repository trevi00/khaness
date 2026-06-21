---
name: kha-generate-tests
description: "Generate tests for a completed phase based on UAT criteria and implementation"
argument-hint: "<phase> [additional instructions]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Task
  - AskUserQuestion
category: phase-mutation
mutates: yes
long-running: yes
---
<objective>
Generate unit and E2E tests for a completed phase, using its SUMMARY.md, CONTEXT.md, and VERIFICATION.md as specifications.

Analyzes implementation files, classifies them into TDD (unit), E2E (browser), or Skip categories, presents a test plan for user approval, then generates tests following RED-GREEN conventions.

Output: Test files committed with message `test(phase-{N}): add unit and E2E tests from add-tests command`
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/add-tests.md
</execution_context>

<context>
Phase: $ARGUMENTS

@.planning/STATE.md
@.planning/ROADMAP.md
</context>

<process>
Execute the add-tests workflow from @$HOME/.claude/get-shit-done/workflows/add-tests.md end-to-end.
Preserve all workflow gates (classification approval, test plan approval, RED-GREEN verification, gap reporting).
</process>

## Output


- artifact: created or modified unit/E2E test files following the project's discovered conventions, plus an inline results report with generated/passing/failing/blocked counts and any bugs found.
- status: `tests_committed` | `tests_generated_with_failures` | `tests_blocked` | `cancelled`

## Failure behavior


- preflight failure: missing phase arg, missing phase dir, or missing `SUMMARY.md` aborts with no test-file writes.
- execution failure: if classification approval, test-plan approval, runner errors, or blockers interrupt execution, preserve any test files already written and report which tests are passing, failing, or blocked; do not fix implementation bugs inside this command.

## Gate summary


- preflight: target phase resolves, required phase artifacts load, and the implementation files can be classified.
- success criteria: classification is user-approved, the test plan is user-approved, generated tests are actually executed, failures/blockers are surfaced honestly, and passing test files are committed when available.

## Retry / Resume


- checkpoint: any generated test files plus the phase artifacts already read from `.planning/phases/{phase}/`.
- resume command: rerun `/kha-generate-tests <phase> [additional instructions]` after fixing blockers or adjusting the plan; expect to review classification and test-plan gates again.
- idempotent: no; reruns must account for already-created test files and existing coverage.
