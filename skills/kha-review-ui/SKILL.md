---
name: kha-review-ui
description: "Retroactive 6-pillar visual audit of implemented frontend code"
argument-hint: "[phase]"
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
  - Grep
  - Task
  - AskUserQuestion
category: review
mutates: no
long-running: yes
---
<objective>
Conduct a retroactive 6-pillar visual audit. Produces UI-REVIEW.md with
graded assessment (1-4 per pillar). Works on any project.
Output: {phase_num}-UI-REVIEW.md
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/ui-review.md
@$HOME/.claude/get-shit-done/references/ui-brand.md
</execution_context>

<context>
Phase: $ARGUMENTS — optional, defaults to last completed phase.
</context>

<process>
Execute @$HOME/.claude/get-shit-done/workflows/ui-review.md end-to-end.
Preserve all workflow gates.
</process>

## Output


- review artifact `{NN}-UI-REVIEW.md` and inline finding list, including overall score, per-pillar scores, top fixes, and any `needs_human_review` markers from automated UI verification.

## Failure behavior


- unexecuted phase aborts; auditor failure produces no final score masquerading as complete; missing UI-SPEC downgrades the baseline to a generic 6-pillar review instead of blocking the review.

## Gate summary


- SUMMARY artifacts must exist; existing UI-REVIEW requires explicit `view | re-audit` choice before overwrite; review remains non-mutating against implementation.

## Retry / Resume


- rerun anytime to refresh the audit against the current implementation; safe review rerun, though scores can change as code changes.
