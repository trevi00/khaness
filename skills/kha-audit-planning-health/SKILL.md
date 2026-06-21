---
name: kha-audit-planning-health
description: "Diagnose planning directory health in read-only audit mode by default, or repair audited issues only with --mode repair --confirm after a recent audit report."
argument-hint: "[--mode audit|repair] [--confirm]"
allowed-tools:
  - Read
  - Bash
  - Write
  - AskUserQuestion
category: audit
mutates: yes
long-running: yes
---
<objective>
Validate `.planning/` directory integrity and report actionable issues. Checks for missing files, invalid configurations, inconsistent state, and orphaned plans.
</objective>

## Modes (audit vs repair, explicit)

This skill has TWO distinct modes; you MUST pick one.

### `--mode audit` (default, read-only)
- Diagnoses planning directory health: orphan phase dirs, broken links in
  ROADMAP.md, STATE.md drift, malformed PLAN.md, etc.
- Output: `.planning/audit/health-<ts>.md` listing findings + severity.
- Side effects: NONE on planning state.

### `--mode repair` (mutation)
- Reads the most-recent audit report, applies repairs:
  - removes orphan dirs (with snapshot)
  - rewrites broken ROADMAP.md links
  - regenerates STATE.md from current state
  - flags malformed PLAN.md for manual fix (does not auto-edit)
- Requires the audit step to have run first; refuses to repair without
  a recent (`<24h`) audit report.
- Snapshot: `.planning/snapshots/audit-repair-<ts>/` of all touched files.
- Confirm: `--mode repair --confirm` required for actual mutation.

### Why split

- Audit is safe to run anywhere/anytime; repair is destructive and needs
  evidence (the audit report) before acting.
- Two-step pattern enables CI use of audit (always read-only) without
  accidental mutation.

<execution_context>
@$HOME/.claude/get-shit-done/workflows/health.md
</execution_context>

<process>
Execute the health workflow from @$HOME/.claude/get-shit-done/workflows/health.md with explicit mode handling.

## 1. Parse Mode and Flags

- Default to `--mode audit` when no mode is supplied.
- Accept only `--mode audit` or `--mode repair`.
- Accept `--confirm` only with `--mode repair`.
- Reject legacy `--repair`; instruct the caller to use `--mode repair --confirm`.

## 2. Audit Mode (`--mode audit`)

- Run the planning-health workflow in read-only mode.
- Diagnose orphan phase dirs, broken ROADMAP.md links, STATE.md drift, malformed PLAN.md, missing files, invalid config, and other planning integrity issues.
- Write `.planning/audit/health-<ts>.md` with findings, severity, evidence, and repairability.
- Exit after the report is written; do not mutate planning state.

## 3. Repair Mode Preflight (`--mode repair`)

- Locate the most recent `.planning/audit/health-*.md` report.
- If no audit report exists, exit early with `repair_blocked_no_recent_audit`.
- If the newest report is older than 24 hours, exit early with `repair_blocked_stale_audit`.
- Parse the report and derive the repair plan from its findings.
- If there are no repairable findings, exit with `nothing_to_repair`.
- If `--confirm` is absent, show the planned repairs and exit with `repair_confirmation_required`.

## 4. Repair Mode Execution (`--mode repair --confirm`)

- Create `.planning/snapshots/audit-repair-<ts>/` containing every file or directory that may be touched.
- Apply only repairs justified by the most recent audit report:
  - remove orphan dirs after snapshot
  - rewrite broken ROADMAP.md links
  - regenerate STATE.md from current state
  - flag malformed PLAN.md for manual fix without auto-editing it
- Re-run the audit after repair and write a follow-up health report.

## 5. Early-Exit Rule

If `--mode repair` is invoked without a recent audit report, stop before any mutation and return the blocking reason plus the exact audit command to run next.
</process>

## Output

- `--mode audit` writes `.planning/audit/health-<ts>.md` listing findings, severity, evidence, and repairability; no planning mutation occurs
- `--mode repair` returns the audit report used, the snapshot path, repairs applied, post-repair audit status, and any findings still requiring manual action

## Failure behavior

- missing `.planning/` or unavailable validator aborts with the exact blocking path or tool detail
- `--mode repair` without a recent (`<24h`) audit report exits early with no mutation
- malformed validator output returns the raw failure instead of guessed health
- malformed PLAN.md is flagged for manual repair and is never auto-edited
- repair failure preserves the snapshot and reports what changed versus what did not

## Gate summary

- audit and repair are explicitly separate modes
- default mode is `--mode audit` and is read-only
- repair requires a recent audit report, explicit `--mode repair`, and `--confirm`
- snapshot creation is mandatory before any repair mutation
- repair uses the audit report as the authority for what may be changed

## Retry / Resume

- rerun `--mode audit` anytime
- rerun `--mode repair` only against the most recent audit report after reviewing its findings
- if repair is interrupted, restore from `.planning/snapshots/audit-repair-<ts>/` before retrying
