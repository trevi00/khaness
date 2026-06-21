---
name: kha-review-code
description: "Review source files changed during a phase for bugs, security issues, and code quality problems"
argument-hint: "<phase-number> [--depth=quick|standard|deep] [--files file1,file2,...]"
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
  - Write
  - Task
category: review
mutates: no
long-running: yes
---
<objective>
Review source files changed during a phase for bugs, security vulnerabilities, and code quality problems.

Spawns the kha-code-reviewer agent to analyze code at the specified depth level. Produces REVIEW.md artifact in the phase directory with severity-classified findings.

Arguments:
- Phase number (required) — which phase's changes to review (e.g., "2" or "02")
- `--depth=quick|standard|deep` (optional) — review depth level, overrides workflow.code_review_depth config
  - quick: Pattern-matching only (~2 min)
  - standard: Per-file analysis with language-specific checks (~5-15 min, default)
  - deep: Cross-file analysis including import graphs and call chains (~15-30 min)
- `--files file1,file2,...` (optional) — explicit comma-separated file list, skips SUMMARY/git scoping (highest precedence for scoping)

Output: {padded_phase}-REVIEW.md in phase directory + inline summary of findings
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/code-review.md
</execution_context>

<context>
Phase: $ARGUMENTS (first positional argument is phase number)

Optional flags parsed from $ARGUMENTS:
- `--depth=VALUE` — Depth override (quick|standard|deep). If provided, overrides workflow.code_review_depth config.
- `--files=file1,file2,...` — Explicit file list override. Has highest precedence for file scoping per D-08. When provided, workflow skips SUMMARY.md extraction and git diff fallback entirely.

Context files (CLAUDE.md, SUMMARY.md, phase state) are resolved inside the workflow via `gsd-tools init phase-op` and delegated to agent via `<files_to_read>` blocks.
</context>

<process>
This command is a thin dispatch layer. It parses arguments and delegates to the workflow.

Execute the code-review workflow from @$HOME/.claude/get-shit-done/workflows/code-review.md end-to-end.

The workflow (not this command) enforces these gates:
- Phase validation (before config gate)
- Config gate check (workflow.code_review)
- File scoping (--files override > SUMMARY.md > git diff fallback)
- Empty scope check (skip if no files)
- Agent spawning (kha-code-reviewer)
- Result presentation (inline summary + next steps)
</process>

## Output


- finding list for the resolved phase scope, with depth, files reviewed, severity counts, top findings, and next-step hints; primary output is inline review feedback, with optional persisted `{NN}-REVIEW.md` when docs persistence is enabled.

## Failure behavior


- invalid phase aborts before config checks; config-disabled returns explicit skip; empty or unreliable scope returns skip/guidance instead of a fabricated review; reviewer failure produces no partial REVIEW artifact.

## Gate summary


- phase validation runs before config gating; scope precedence is `--files` > `SUMMARY.md` > git diff; deleted/planning files are filtered; review remains read-only against implementation.

## Retry / Resume


- rerun the same phase with the same depth/scope, or narrow with `--files`; safe to rerun, but findings are non-deterministic and the latest persisted report replaces the old one.
