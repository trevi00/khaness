---
name: kha-set-model-profile
description: "Switch model profile for GSD agents (quality/balanced/budget/inherit)"
argument-hint: "<profile (quality|balanced|budget|inherit)>"
allowed-tools:
  - Bash
category: meta
mutates: yes
long-running: no
---
Show the following output to the user verbatim, with no extra commentary:

!`node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" config-set-model-profile $ARGUMENTS --raw`

## Output


- artifacts: `.planning/config.json` ensured if missing, `model_profile` updated, and an agent-to-model routing table emitted from `config-set-model-profile`.
- status: `profile_updated` | `profile_unchanged`.

## Failure behavior


- preflight: reject missing or invalid profile argument before any write.
- execution: if config ensure or write fails, leave the prior profile intact and surface the exact config error.
- partial: none; this command is single-target and should be all-or-nothing.

## Gate summary


- preflight: a valid profile token is present and project config is writable.
- success: the CLI returns the effective profile, previous profile, and agent routing table.
- boundary: own model routing profile only; workflow toggles remain with `kha-settings`; developer behavior profiling remains with `kha-user-profile`.
