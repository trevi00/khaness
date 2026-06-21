---
name: kha-archive-completed-phases
description: "Archive accumulated phase directories from completed milestones"
allowed-tools:
  - Read
  - Write
  - Bash
  - AskUserQuestion
category: remediate
mutates: yes
long-running: yes
---
<objective>
Archive phase directories from completed milestones into `.planning/milestones/v{X.Y}-phases/`.

Use when `.planning/phases/` has accumulated directories from past milestones.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/cleanup.md
</execution_context>

<process>
Follow the cleanup workflow at @$HOME/.claude/get-shit-done/workflows/cleanup.md.
Identify completed milestones, show a dry-run summary, and archive on confirmation.
</process>

## Output


- mandatory dry-run archive plan first; after explicit confirm, emit archive report plus archive commit, including milestone-to-phase mapping, destination dirs, snapshot manifest, and moved-directory counts.

## Failure behavior


- missing `MILESTONES.md` or archived ROADMAP snapshots aborts before any move; if nothing remains to archive, return `nothing_to_do`; move failure mid-run stops immediately and reports what was moved vs pending from the snapshot manifest.

## Gate summary


- mandatory mutation safety flow is dry-run -> snapshot manifest of source/destination dirs -> explicit confirm -> move -> commit; this skill archives by move only and never deletes phase directories.

## Retry / Resume


- rerun from the snapshot manifest or from the remaining source dirs; rollback is reverse-move from the manifest before any new cleanup run.
