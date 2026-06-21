---
name: kha-self-update
description: "Update GSD to latest version with changelog display"
allowed-tools:
  - Bash
  - AskUserQuestion
category: meta
mutates: yes
long-running: no
---
<objective>
Check for GSD updates, install if available, and display what changed.

Routes to the update workflow which handles:
- Version detection (local vs global installation)
- npm version checking
- Changelog fetching and display
- User confirmation with clean install warning
- Update execution and cache clearing
- Restart reminder
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/update.md
</execution_context>

<process>
**Follow the update workflow** from `@$HOME/.claude/get-shit-done/workflows/update.md`.

The workflow handles all logic including:
1. Installed version detection (local/global)
2. Latest version checking via npm
3. Version comparison
4. Changelog fetching and extraction
5. Clean install warning display
6. User confirmation
7. Update execution
8. Cache clearing
</process>

## Output


- artifacts: detected install scope/runtime, installed-vs-latest comparison, changelog preview, updated GSD runtime files, cleared `cache/gsd-update-check.json`, and optional local patch backup metadata under `gsd-local-patches/`.
- status: `already_current` | `update_completed` | `update_cancelled` | `manual_update_required`.

## Failure behavior


- preflight: if npm/latest-version check is unavailable, abort before mutation and show the manual install command.
- execution: if install fails, preserve the existing installation and surface the failing runtime/scope; if local patches were backed up, report the backup location.
- partial: if install succeeds but cache clearing or patch-status reporting fails, keep the updated install and report the follow-up action instead of rolling back.

## Gate summary


- preflight: installed version/runtime/scope resolved, latest version checked, and changelog range fetched when an update exists.
- success: dry-run preview showed install target plus changelog; snapshot captured the detected runtime/scope and any `gsd-local-patches/` backup; explicit user confirmation occurred before install; completion message includes restart guidance.
- boundary: this command updates the GSD toolchain itself, not project docs, workspace state, or model/profile preferences.
