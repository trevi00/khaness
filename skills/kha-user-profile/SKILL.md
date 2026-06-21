---
name: kha-user-profile
description: "Generate developer behavioral profile and create Claude-discoverable artifacts"
argument-hint: "[--questionnaire] [--refresh]"
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
  - Task
category: meta
mutates: yes
long-running: no
---
<objective>
Generate a developer behavioral profile from session analysis (or questionnaire) and produce artifacts (USER-PROFILE.md, /gsd-dev-preferences, CLAUDE.md section) that personalize Claude's responses.

Routes to the profile-user workflow which orchestrates the full flow: consent gate, session analysis or questionnaire fallback, profile generation, result display, and artifact selection.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/profile-user.md
@$HOME/.claude/get-shit-done/references/ui-brand.md
</execution_context>

<context>
Flags from $ARGUMENTS:
- `--questionnaire` -- Skip session analysis entirely, use questionnaire-only path
- `--refresh` -- Rebuild profile even when one exists, backup old profile, show dimension diff
</context>

<process>
Execute the profile-user workflow end-to-end.

The workflow handles all logic including:
1. Initialization and existing profile detection
2. Consent gate before session analysis
3. Session scanning and data sufficiency checks
4. Session analysis (profiler agent) or questionnaire fallback
5. Cross-project split resolution
6. Profile writing to USER-PROFILE.md
7. Result display with report card and highlights
8. Artifact selection (dev-preferences, CLAUDE.md sections)
9. Sequential artifact generation
10. Summary with refresh diff (if applicable)
</process>

## Output


- artifacts: `~/.claude/get-shit-done/USER-PROFILE.md`; optional `USER-PROFILE.backup.md` on `--refresh`; optional `~/.claude/commands/gsd/dev-preferences.md`; optional profile sections in project `CLAUDE.md` and global `~/.claude/CLAUDE.md`.
- status: `profile_generated` | `profile_refreshed` | `profile_viewed` | `questionnaire_completed` | `cancelled_no_change`.

## Failure behavior


- preflight: if the user declines consent or cancels an existing-profile prompt, abort with no writes.
- execution: if session sampling or analysis fails, fall back to questionnaire when available; if one artifact generation step fails, keep the written profile and offer retry/skip per artifact.
- partial: selected artifacts may succeed independently; report exactly which artifacts were generated and which were skipped or failed.

## Gate summary


- preflight: profiling references readable; existing-profile state checked; consent resolved unless `--questionnaire` was requested.
- success: profile analysis was produced, `USER-PROFILE.md` was written, optional artifact selection completed, and temp sampling files were cleaned up.
- boundary: own developer-behavior profiling only; workflow toggles belong to `kha-settings`; routing profile changes belong to `kha-set-model-profile`.
