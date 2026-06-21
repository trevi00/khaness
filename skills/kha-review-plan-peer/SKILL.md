---
name: kha-review-plan-peer
description: "Request cross-AI peer review of phase plans from external AI CLIs"
argument-hint: "--phase N [--gemini] [--claude] [--codex] [--opencode] [--all]"
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
  - Grep
category: review
mutates: no
long-running: yes
---
<objective>
Invoke external AI CLIs (Gemini, Claude, Codex, OpenCode) to independently review phase plans.
Produces a structured REVIEWS.md with per-reviewer feedback that can be fed back into
planning via /kha-plan-phase --reviews.

**Flow:** Detect CLIs → Build review prompt → Invoke each CLI → Collect responses → Write REVIEWS.md
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/review.md
</execution_context>

<context>
Phase number: extracted from $ARGUMENTS (required)

**Flags:**
- `--gemini` — Include Gemini CLI review
- `--claude` — Include Claude CLI review (uses separate session)
- `--codex` — Include Codex CLI review
- `--opencode` — Include OpenCode review (uses model from user's OpenCode config)
- `--all` — Include all available CLIs
</context>

<process>
Execute the review workflow from @$HOME/.claude/get-shit-done/workflows/review.md end-to-end.
</process>

## Output


- peer feedback bundle in `{NN}-REVIEWS.md` plus inline consensus summary, preserving per-reviewer output, agreed strengths, agreed concerns, divergent views, and reviewer provenance.

## Failure behavior


- no external CLI available aborts with installation guidance; individual reviewer failures are recorded and the run continues with the remaining reviewers; if only the current runtime’s own CLI is available, abort because independence is not met.

## Gate summary


- at least one reviewer must be external to the current runtime; all reviewers receive the same prompt context; synthesis happens only after raw reviewer outputs are captured.

## Retry / Resume


- rerun after installing or enabling more CLIs; not strictly idempotent because reviewer outputs vary across time and models.
