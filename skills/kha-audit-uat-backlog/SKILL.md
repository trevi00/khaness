---
name: kha-audit-uat-backlog
description: "Cross-phase audit of all outstanding UAT and verification items"
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
category: audit
mutates: no
long-running: yes
---
<objective>
Scan all phases for pending, skipped, blocked, and human_needed UAT items. Cross-reference against codebase to detect stale documentation. Produce prioritized human test plan.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/audit-uat.md
</execution_context>

<context>
Core planning files are loaded in-workflow via CLI.

**Scope:**
Glob: .planning/phases/*/*-UAT.md
Glob: .planning/phases/*/*-VERIFICATION.md
</context>

## Output


- read-only backlog gap report and priority-ordered human test plan, grouping items into `testable_now`, `needs_prerequisites`, and `stale`, and labeling each current item `active | stale | needs_update`.

## Failure behavior


- if no UAT/VERIFICATION artifacts exist, return `all_clear` or `no_artifacts` explicitly; if codebase cross-check is inconclusive, keep the item open and mark evidence missing instead of closing it.

## Gate summary


- scan all `*-UAT.md` and `*-VERIFICATION.md` first, then perform stale-doc detection only where referenced code/artifacts are actually readable; no file or code mutation.

## Retry / Resume


- rerun anytime; fully idempotent read-only audit of the current backlog.
