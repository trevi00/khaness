---
name: kha-remediate-audit-findings
description: "Autonomous audit-to-fix pipeline — find issues, classify, fix, test, commit"
argument-hint: "--source <audit-uat> [--severity <medium|high|all>] [--max N] [--dry-run]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Grep
  - Glob
  - Agent
  - AskUserQuestion
category: remediate
mutates: yes
long-running: yes
---
<objective>
Run an audit, classify findings as auto-fixable vs manual-only, then autonomously fix
auto-fixable issues with test verification and atomic commits.

Flags:
- `--max N` — maximum findings to fix (default: 5)
- `--severity high|medium|all` — minimum severity to process (default: medium)
- `--dry-run` — classify findings without fixing (shows classification table)
- `--source <audit>` — which audit to run (default: audit-uat)
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/audit-fix.md
</execution_context>

<process>
Execute the audit-fix workflow from @$HOME/.claude/get-shit-done/workflows/audit-fix.md end-to-end.

## Process (scope-narrowed)

### Step 1: acquire findings (read-only)
- Input: `.planning/<phase>/AUDIT.md` from a prior audit run.
- This skill does NOT itself run an audit — that's `/kha-audit-*` skills.
- Findings parsed into a list of (id, severity, file, suggested_fix).

### Step 2: dry-run plan
- Emit a plan: which findings will be fixed in this run (filter by
  severity, file path, max-N), which will be skipped (out of scope),
  which require manual review.
- `--dry-run` (default): just the plan.
- `--apply` required to proceed.

### Step 3: snapshot
- `.planning/snapshots/remediate-audit-<phase>-<ts>/` containing the AUDIT.md,
  the plan JSON, and a copy of every file to be modified.

### Step 4: explicit confirm
- Print plan summary (N findings, M files affected). Refuse to mutate
  without `--apply --confirm` (two-flag confirmation for destructive
  remediation that touches code).

### Step 5: per-finding fix loop
- Apply each finding's suggested_fix as a separate atomic commit.
- Run tests after each commit; rollback the commit if tests regress.
- Continue with next finding regardless of single-finding rollback.

### Step 6: rollback path
- On exit, if any rollback occurred, emit a summary of which findings
  were applied vs rolled-back. User can `git revert` the snapshot
  reference to undo the entire batch.
</process>

## Output


- inspection phase consumes existing findings only and emits a dry-run classification table (`auto-fixable | manual-only | skip`) plus ordered fix scope; mutation phase applies confirmed fix commits and returns a fix report with finding IDs, test evidence, skipped/manual-only residue, and rollback metadata.

## Failure behavior


- if no persisted findings exist for the selected source, abort and tell the user to run/provide the audit separately; ambiguous findings without clear file scope stay manual-only; first failed verification reverts the attempted change to the snapshot and halts remaining findings as `not_attempted`.

## Gate summary


- audit-consume and fix-apply are hard-separated; this skill must never re-run the audit; mandatory safety flow is dry-run -> snapshot -> explicit confirm -> sequential fix/test/commit; scope may not expand beyond supplied finding IDs/findings text.

## Retry / Resume


- rerun from the remaining findings listed in the fix report; dry-run is idempotent, but fix mode is not once commits have been created.
