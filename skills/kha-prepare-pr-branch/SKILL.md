---
name: kha-prepare-pr-branch
description: "Create a clean PR branch by filtering out .planning/ commits — ready for code review"
argument-hint: "[target branch, default: main]"
allowed-tools:
  - Bash
  - Read
  - AskUserQuestion
category: workflow
mutates: yes
long-running: no
---
<objective>
Create a clean branch suitable for pull requests by filtering out .planning/ commits
from the current branch. Reviewers see only code changes, not GSD planning artifacts.

This solves the problem of PR diffs being cluttered with PLAN.md, SUMMARY.md, STATE.md
changes that are irrelevant to code review.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/pr-branch.md
</execution_context>

<process>
Execute the pr-branch workflow from @$HOME/.claude/get-shit-done/workflows/pr-branch.md end-to-end.
</process>

## Output


- artifact: a filtered git branch `${CURRENT_BRANCH}-pr` rebuilt from `${TARGET}` with planning-only commits excluded and mixed commits scrubbed of `.planning/` paths.
- status: `pr_branch_created` | `nothing_to_filter` | `aborted`

## Failure behavior


- preflight failure: being on the target branch or having zero commits ahead of target stops before branch creation.
- execution failure: if cherry-pick/filtering fails mid-run, keep the partially built PR branch visible for manual cleanup and do not claim verification passed.

## Gate summary


- preflight: current branch is a feature branch, target resolves, and there are commits ahead of target to classify.
- success criteria: the PR branch exists, included commit messages are preserved, and `git diff ${TARGET}..${PR_BRANCH}` contains zero `.planning/` paths.
