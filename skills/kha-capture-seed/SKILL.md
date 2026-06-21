---
name: kha-capture-seed
description: "Capture a forward-looking idea with trigger conditions — surfaces automatically at the right milestone"
argument-hint: "[idea summary]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - AskUserQuestion
category: capture
mutates: yes
long-running: no
---
<objective>
Capture an idea that's too big for now but should surface automatically when the right
milestone arrives. Seeds solve context rot: instead of a one-liner in Deferred that nobody
reads, a seed preserves the full WHY, WHEN to surface, and breadcrumbs to details.

Creates: .planning/seeds/SEED-NNN-slug.md
Consumed by: /kha-new-milestone (scans seeds and presents matches)
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/plant-seed.md
</execution_context>

<process>
Execute the plant-seed workflow from @$HOME/.claude/get-shit-done/workflows/plant-seed.md end-to-end.
</process>

## Output


- artifact: a triggered future idea in `.planning/seeds/SEED-{NNN}-{slug}.md`; this is not actionable now like a todo and is meant to resurface later during new-milestone scanning.
- status: `seed_planted` | `aborted`

## Failure behavior


- preflight failure: if the idea, trigger, why, or scope is not captured, stop before writing the seed file.
- execution failure: if the seed file is written but commit/reporting fails, keep the seed file as the recovery handle and report its full path.

## Gate summary


- preflight: an idea summary exists, trigger/why/scope prompts are answered, and `.planning/seeds/` is creatable.
- success criteria: the seed file exists with id, status, planted date, trigger, scope, and breadcrumbs, and the user sees the trigger conditions that will resurface it.
