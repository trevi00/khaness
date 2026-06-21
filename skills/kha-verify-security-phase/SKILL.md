---
name: kha-verify-security-phase
description: "Retroactively verify threat mitigations for a completed phase"
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
Verify threat mitigations for a completed phase. Three states:
- (A) SECURITY.md exists — audit and verify mitigations
- (B) No SECURITY.md, PLAN.md with threat model exists — run from artifacts
- (C) Phase not executed — exit with guidance

Output: updated SECURITY.md.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/secure-phase.md
</execution_context>

<context>
Phase: $ARGUMENTS — optional, defaults to last completed phase.
</context>

<process>
Execute @$HOME/.claude/get-shit-done/workflows/secure-phase.md.
Preserve all workflow gates.
</process>

## Output


- inspection phase returns threat verification evidence, with open/closed counts, per-threat status, and blocker list; mutation phase creates or updates `{NN}-SECURITY.md` with the threat register, accepted-risk decisions, audit trail, and `threats_open` summary.

## Failure behavior


- disabled security enforcement exits cleanly; unexecuted phase or missing SUMMARY artifacts abort with guidance; auditor `ESCALATE` records open threats and blocks advancement without touching implementation files.

## Gate summary


- verify and SECURITY.md update are separate; PLAN threat model and SUMMARY threat flags must be read before any user decision; AskUser gate decides verify/accept/cancel; if `threats_open > 0`, stop with a security block and emit no next-phase routing.

## Retry / Resume


- rerun after mitigations land or accepted risks are documented; logically idempotent on unchanged implementation, with only the audit trail extending.
