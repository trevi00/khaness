---
name: kha-milestone-summary
description: "Generate a comprehensive project summary from milestone artifacts for team onboarding and review"
argument-hint: "[version]"
allowed-tools:
  - Read
  - Write
  - Bash
  - Grep
  - Glob
category: meta
mutates: no
long-running: yes
---
<objective>
Generate a structured milestone summary for team onboarding and project review. Reads completed milestone artifacts (ROADMAP, REQUIREMENTS, CONTEXT, SUMMARY, VERIFICATION files) and produces a human-friendly overview of what was built, how, and why.

Purpose: Enable new team members to understand a completed project by reading one document and asking follow-up questions.
Output: MILESTONE_SUMMARY written to `.planning/reports/`, presented inline, optional interactive Q&A.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/milestone-summary.md
</execution_context>

<context>
**Project files:**
- `.planning/ROADMAP.md`
- `.planning/PROJECT.md`
- `.planning/STATE.md`
- `.planning/RETROSPECTIVE.md`
- `.planning/milestones/v{version}-ROADMAP.md` (if archived)
- `.planning/milestones/v{version}-REQUIREMENTS.md` (if archived)
- `.planning/phases/*-*/` (SUMMARY.md, VERIFICATION.md, CONTEXT.md, RESEARCH.md)

**User input:**
- Version: $ARGUMENTS (optional — defaults to current/latest milestone)
</context>

<process>
Read and execute the milestone-summary workflow from @$HOME/.claude/get-shit-done/workflows/milestone-summary.md end-to-end.
</process>

<success_criteria>
- Milestone version resolved (from args, STATE.md, or archive scan)
- All available artifacts read (ROADMAP, REQUIREMENTS, CONTEXT, SUMMARY, VERIFICATION, RESEARCH, RETROSPECTIVE)
- Summary document written to `.planning/reports/MILESTONE_SUMMARY-v{version}.md`
- All 7 sections generated (Overview, Architecture, Phases, Decisions, Requirements, Tech Debt, Getting Started)
- Summary presented inline to user
- Interactive Q&A offered
- STATE.md updated
</success_criteria>

## Output


- artifacts: `.planning/reports/MILESTONE_SUMMARY-v{version}.md`, inline full summary, optional interactive Q&A context, commit of the summary file, and `STATE.md` session record pointing at the summary.
- status: `summary_generated` | `summary_viewed_existing` | `summary_aborted_no_milestone`.

## Failure behavior


- preflight: if version cannot be resolved from args, `STATE.md`, archives, or current roadmap state, abort with no write.
- execution: missing milestone artifacts are tolerated and should degrade the summary, not abort it; git-stat collection failure should omit Stats only.
- partial: if the summary file is written but commit or `STATE.md` session-record update fails, keep the report and surface the unfinished follow-up.

## Gate summary


- preflight: version resolved; archived-vs-current artifact paths determined; overwrite/view guard resolved when a summary already exists.
- success: source artifacts were discovered, the 7-section summary was written, displayed, committed, and recorded as the new resume file.
- boundary: own post-milestone onboarding summary only; it does not orchestrate phase execution like `kha-milestone-manager`.

## Retry / Resume


- checkpoint: resolved milestone version and discovered artifact set are the resume handle; an existing summary file becomes the overwrite/view gate on rerun.
- resume: rerun `kha-milestone-summary [version]`; idempotent at `.planning/reports/MILESTONE_SUMMARY-v{version}.md`.
