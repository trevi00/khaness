---
name: kha-remove-phase
description: "Remove a future phase from roadmap and renumber subsequent phases"
argument-hint: "<phase-number>"
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
category: phase-mutation
mutates: yes
long-running: no
---
<objective>
Remove an unstarted future phase from the roadmap and renumber all subsequent phases to maintain a clean, linear sequence.

Purpose: Clean removal of work you've decided not to do, without polluting context with cancelled/deferred markers.
Output: Phase deleted, all subsequent phases renumbered, git commit as historical record.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/remove-phase.md
</execution_context>

<context>
Phase: $ARGUMENTS

Roadmap and state are resolved in-workflow via `init phase-op` and targeted reads.
</context>

<process>
Execute the remove-phase workflow from @$HOME/.claude/get-shit-done/workflows/remove-phase.md end-to-end.
Preserve all validation gates (future phase check, work check), renumbering logic, and commit.
</process>

## Stability (destructive renumber)

### dry-run mode
- `--dry-run` (default in interactive mode): emit the list of phases to be
  renumbered (old_id → new_id) plus all files affected (PLAN.md /
  STATE.md / ROADMAP.md links / cross-references in other phases).
- `--apply` required for actual mutation.

### snapshot before mutation
- `.planning/snapshots/remove-phase-<old_id>-<ts>/` containing:
  - copy of phase dir being removed
  - copy of every file that will have a phase reference rewritten
  - JSON manifest with planned diffs

### atomic apply
- All renumbering happens in one git commit. If any sub-step fails, the
  commit is not made (caller can `git restore` back to pre-mutation state).

### no resume
- Renumber is all-or-nothing. Resume of partial renumber = manual git restore.

## Output


- artifact: `.planning/ROADMAP.md` — roadmap with the target phase removed and subsequent references renumbered
- artifact: `.planning/STATE.md` — updated phase counts after removal
- artifact: `.planning/phases/` — target phase directory deleted and subsequent phase directories/files renumbered by `gsd-tools phase remove`
- artifact: `git commit "chore: remove phase {target} ({original-phase-name})"` — historical rollback handle after destructive change
- status: `removed` | `aborted_not_future_phase` | `aborted_has_executed_work` | `aborted_user_declined`

## Failure behavior


- current or completed phase selected: abort before any deletion; route the user to pause/continue current work instead
- dry-run is mandatory: before `phase remove`, show the delete target plus renumber set and require explicit confirmation; if the user declines, no writes occur
- backup is mandatory: capture a rollback handle in git before destructive removal and rely on the removal commit as the authoritative history record; never hand-renumber as a fallback
- phase has executed work (`SUMMARY.md` or equivalent): require explicit force-style user confirmation before removal; otherwise abort

## Gate summary


- preflight: target phase exists; target phase number is greater than the current phase from `STATE.md`; roadmap and state are writable; dry-run preview has been acknowledged
- success criteria: `gsd-tools phase remove` completes, subsequent dirs/files are renumbered consistently, and the removal commit is created
- abort triggers: target is current/past; user declines the dry-run confirmation; executed work exists without explicit destructive confirmation
