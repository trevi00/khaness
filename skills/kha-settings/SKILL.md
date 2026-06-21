---
name: kha-settings
description: "Configure GSD workflow toggles and model profile"
allowed-tools:
  - Read
  - Write
  - Bash
  - AskUserQuestion
category: meta
mutates: yes
long-running: no
---
<objective>
Interactive configuration of GSD workflow agents and model profile via multi-question prompt.

Routes to the settings workflow which handles:
- Config existence ensuring
- Current settings reading and parsing
- Interactive 5-question prompt (model, research, plan_check, verifier, branching)
- Config merging and writing
- Confirmation display with quick command references
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/settings.md
</execution_context>

<process>
**Follow the settings workflow** from `@$HOME/.claude/get-shit-done/workflows/settings.md`.

The workflow handles all logic including:
1. Config file creation with defaults if missing
2. Current config reading
3. Interactive settings presentation with pre-selection
4. Answer parsing and config merging
5. File writing
6. Confirmation display
</process>

## Output


- artifacts: `.planning/config.json` updated with workflow toggles; optional `~/.gsd/defaults.json` written when the user chooses global defaults; inline confirmation table of effective settings.
- status: `settings_updated` | `settings_updated_with_defaults` | `viewed_current_settings_only`.

## Failure behavior


- preflight: if project config cannot be ensured or parsed, abort before questioning and surface the blocking path/error.
- execution: if project config write fails, do not claim success; if defaults write fails after project config succeeds, keep the project config change and report the defaults failure separately.
- partial: declining global defaults is not a failure; report project-only application explicitly.

## Gate summary


- preflight: workflow context readable; project root has a usable `.planning/` area; current config can be loaded or created.
- success: current values were shown, the user answered the settings prompt, `.planning/config.json` was written, and the defaults decision was resolved.
- boundary: own full interactive workflow configuration only; one-off routing profile flips belong to `kha-set-model-profile`; behavioral personalization and `USER-PROFILE.md` belong to `kha-user-profile`; runtime alias or per-session `/model` ownership is out of scope.
