---
name: kha-audit-milestone
description: "Audit milestone completion against original intent before archiving"
argument-hint: "[version]"
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
  - Task
  - Write
category: audit
mutates: no
long-running: yes
---
<objective>
Verify milestone achieved its definition of done. Check requirements coverage, cross-phase integration, and end-to-end flows.

**This command IS the orchestrator.** Reads existing VERIFICATION.md files (phases already verified during execute-phase), aggregates tech debt and deferred gaps, then spawns integration checker for cross-phase wiring.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/audit-milestone.md
</execution_context>

<context>
Version: $ARGUMENTS (optional — defaults to current milestone)

Core planning files are resolved in-workflow (`init milestone-op`) and loaded only as needed.

**Completed Work:**
Glob: .planning/phases/*/*-SUMMARY.md
Glob: .planning/phases/*/*-VERIFICATION.md
</context>

<process>
Execute the audit-milestone workflow from @$HOME/.claude/get-shit-done/workflows/audit-milestone.md end-to-end.
Preserve all workflow gates (scope determination, verification reading, integration check, requirements coverage, routing).
</process>

## Output


- gap report and priority list in `.planning/v*-MILESTONE-AUDIT.md`, with milestone status `passed | gaps_found | tech_debt`, REQ coverage matrix, integration/flow gaps, Nyquist coverage summary, and prioritized next actions.

## Failure behavior


- missing phase `VERIFICATION.md` files are treated as blockers inside the audit, not silently skipped; missing traceability or SUMMARY evidence marks requirements `partial/unsatisfied`; integration-checker failure degrades to a partial audit with an explicit incomplete-integration section.

## Gate summary


- milestone scope, VERIFICATION evidence, REQUIREMENTS traceability, and SUMMARY frontmatter must be cross-checked; any unsatisfied or orphaned requirement forces `gaps_found`; audit remains read-only.

## Retry / Resume


- safe to rerun after new verification or validation artifacts exist; the latest audit replaces the prior audit file for the same milestone window.
