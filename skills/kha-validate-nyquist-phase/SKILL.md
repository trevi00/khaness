---
name: kha-validate-nyquist-phase
description: "Retroactively audit and fill Nyquist validation gaps for a completed phase"
argument-hint: "[phase number]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Task
  - AskUserQuestion
category: validate
mutates: yes
long-running: yes
---
<objective>
Audit Nyquist validation coverage for a completed phase. Three states:
- (A) VALIDATION.md exists — audit and fill gaps
- (B) No VALIDATION.md, SUMMARY.md exists — reconstruct from artifacts
- (C) Phase not executed — exit with guidance

Output: updated VALIDATION.md + generated test files.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/validate-phase.md
</execution_context>

<context>
Phase: $ARGUMENTS — optional, defaults to last completed phase.
</context>

<process>
Execute @$HOME/.claude/get-shit-done/workflows/validate-phase.md.
Preserve all workflow gates.
</process>

## Output


- inspection phase returns coverage gaps over requirements/tasks/tests, classifying each item `COVERED | PARTIAL | MISSING`; mutation phase creates or updates `{NN}-VALIDATION.md` and, when confirmed, generates/commits test files with evidence and Manual-Only carryovers.

## Failure behavior


- disabled validation exits cleanly; unexecuted phase aborts with guidance; auditor `ESCALATE` or failing test generation moves unresolved items to Manual-Only and does not edit implementation files.

## Gate summary


- coverage audit and test generation are separate; PLAN/SUMMARY and test infrastructure must be read first; AskUser gate decides fix-all/skip/cancel; if no gaps exist, short-circuit to compliant output and update the validation record only.

## Retry / Resume


- rerun after infra or implementation changes; not strictly idempotent once new tests have been committed.
