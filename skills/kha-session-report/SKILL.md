---
name: kha-session-report
description: "Generate a session report with token usage estimates, work summary, and outcomes"
allowed-tools:
  - Read
  - Bash
  - Write
category: meta
mutates: no
long-running: no
---
<objective>
Generate a structured SESSION_REPORT.md document capturing session outcomes, work performed, and estimated resource usage. Provides a shareable artifact for post-session review.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/session-report.md
</execution_context>

<process>
Execute the session-report workflow from @$HOME/.claude/get-shit-done/workflows/session-report.md end-to-end.
</process>

## Output


- artifacts: `.planning/reports/SESSION_REPORT.md` or a dated variant when previous reports exist, plus inline highlight summary of commits, files changed, phase progress, and plans executed.
- status: `session_report_written`.

## Failure behavior


- preflight: if session context files and git signals cannot be gathered sufficiently to build a report, abort before write and surface which sources were unavailable.
- execution: token/cost estimates are best-effort only; missing git diff or prior reports should degrade the content, not corrupt the report file.
- partial: if the report file is written but inline display fails, keep the file and surface its path.

## Gate summary


- preflight: project session inputs (`STATE.md`, roadmap context, recent git activity) are readable and report output path is writable.
- success: a report file was written under `.planning/reports/` and a concise inline summary was shown.
- boundary: own end-of-session reporting only; broader milestone onboarding belongs to `kha-milestone-summary`, and aggregate project stats belong to `kha-project-stats`.
