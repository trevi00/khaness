---
name: kha-complete-milestone
description: "Archive completed milestone and prepare for next version"
argument-hint: "<version>"
allowed-tools:
  - Read
  - Write
  - Bash
category: lifecycle
mutates: yes
long-running: yes
---
<objective>
Mark milestone {{version}} complete, archive to milestones/, and update ROADMAP.md and REQUIREMENTS.md.

Purpose: Create historical record of shipped version, archive milestone artifacts (roadmap + requirements), and prepare for next milestone.
Output: Milestone archived (roadmap + requirements), PROJECT.md evolved, git tagged.
</objective>

<execution_context>
**Load these files NOW (before proceeding):**

- @$HOME/.claude/get-shit-done/workflows/complete-milestone.md (main workflow)
- @$HOME/.claude/get-shit-done/templates/milestone-archive.md (archive template)
  </execution_context>

<context>
**Project files:**
- `.planning/ROADMAP.md`
- `.planning/REQUIREMENTS.md`
- `.planning/STATE.md`
- `.planning/PROJECT.md`

**User input:**

- Version: {{version}} (e.g., "1.0", "1.1", "2.0")
  </context>

<process>

**Follow complete-milestone.md workflow:**

0. **Check for audit:**

   - Look for `.planning/v{{version}}-MILESTONE-AUDIT.md`
   - If missing or stale: recommend `/kha-audit-milestone` first
   - If audit status is `gaps_found`: recommend `/kha-plan-gap-phases` first
   - If audit status is `passed`: proceed to step 1

   ```markdown
   ## Pre-flight Check

   {If no v{{version}}-MILESTONE-AUDIT.md:}
   ⚠ No milestone audit found. Run `/kha-audit-milestone` first to verify
   requirements coverage, cross-phase integration, and E2E flows.

   {If audit has gaps:}
   ⚠ Milestone audit found gaps. Run `/kha-plan-gap-phases` to create
   phases that close the gaps, or proceed anyway to accept as tech debt.

   {If audit passed:}
   ✓ Milestone audit passed. Proceeding with completion.
   ```

1. **Verify readiness:**

   - Check all phases in milestone have completed plans (SUMMARY.md exists)
   - Present milestone scope and stats
   - Wait for confirmation

2. **Gather stats:**

   - Count phases, plans, tasks
   - Calculate git range, file changes, LOC
   - Extract timeline from git log
   - Present summary, confirm

3. **Extract accomplishments:**

   - Read all phase SUMMARY.md files in milestone range
   - Extract 4-6 key accomplishments
   - Present for approval

4. **Archive milestone:**

   - Create `.planning/milestones/v{{version}}-ROADMAP.md`
   - Extract full phase details from ROADMAP.md
   - Fill milestone-archive.md template
   - Update ROADMAP.md to one-line summary with link

5. **Archive requirements:**

   - Create `.planning/milestones/v{{version}}-REQUIREMENTS.md`
   - Mark all v1 requirements as complete (checkboxes checked)
   - Note requirement outcomes (validated, adjusted, dropped)
   - Delete `.planning/REQUIREMENTS.md` (fresh one created for next milestone)

6. **Update PROJECT.md:**

   - Add "Current State" section with shipped version
   - Add "Next Milestone Goals" section
   - Archive previous content in `<details>` (if v1.1+)

7. **Commit and tag:**

   - Stage: MILESTONES.md, PROJECT.md, ROADMAP.md, STATE.md, archive files
   - Commit: `chore: archive v{{version}} milestone`
   - Tag: `git tag -a v{{version}} -m "[milestone summary]"`
   - Ask about pushing tag

8. **Offer next steps:**
   - `/kha-new-milestone` — start next milestone (questioning → research → requirements → roadmap)

</process>

<success_criteria>

- Milestone archived to `.planning/milestones/v{{version}}-ROADMAP.md`
- Requirements archived to `.planning/milestones/v{{version}}-REQUIREMENTS.md`
- `.planning/REQUIREMENTS.md` deleted (fresh for next milestone)
- ROADMAP.md collapsed to one-line entry
- PROJECT.md updated with current state
- Git tag v{{version}} created
- Commit successful
- User knows next steps (including need for fresh requirements)
  </success_criteria>

<critical_rules>

- **Load workflow first:** Read complete-milestone.md before executing
- **Verify completion:** All phases must have SUMMARY.md files
- **User confirmation:** Wait for approval at verification gates
- **Archive before deleting:** Always create archive files before updating/deleting originals
- **One-line summary:** Collapsed milestone in ROADMAP.md should be single line with link
- **Context efficiency:** Archive keeps ROADMAP.md and REQUIREMENTS.md constant size per milestone
- **Fresh requirements:** Next milestone starts with `/kha-new-milestone` which includes requirements definition
  </critical_rules>

## Stability (lifecycle destructive)

### dry-run mode
- Default mode emits `--dry-run` shows what would be deleted/tagged/committed
  without applying. Output: human-readable plan + machine-readable JSON manifest.
- Real mode requires `--apply` flag.

### snapshot before mutation
- Before any delete/tag/commit, create snapshot: `.planning/snapshots/milestone-<id>-<ts>/`
  - copy of state files (ROADMAP.md, STATE.md, current-milestone/)
  - JSON manifest: { sid, timestamp, files_to_delete, tags_to_create, commits_to_make }

### checkpoint
- Each step (delete-state / tag-version / commit-archive) writes a single-line
  checkpoint to `.planning/checkpoints/complete-milestone.json` so a resume
  can pick up at the next un-done step.

### lock
- Acquire `.planning/.locks/complete-milestone.lock` for the duration. Refuse
  if existing lock < 1h old (concurrent run protection).

## Output


- artifact: `.planning/milestones/v{{version}}-ROADMAP.md` — archived full roadmap snapshot for the shipped milestone
- artifact: `.planning/milestones/v{{version}}-REQUIREMENTS.md` — archived requirements with completion outcomes and traceability
- artifact: `.planning/MILESTONES.md` — appended shipped-milestone entry with accomplishments and known gaps when applicable
- artifact: `.planning/PROJECT.md` — full evolution review reflecting shipped state and next-milestone context
- artifact: `.planning/RETROSPECTIVE.md` — updated milestone retrospective and cross-milestone trends
- artifact: `git tag v{{version}}` — release tag created after archival and review complete
- status: `completed` | `completed_with_known_gaps` | `aborted_not_ready` | `aborted_audit_required` | `aborted_user_wait`

## Failure behavior


- missing audit, stale audit, or audit `gaps_found` with no explicit proceed-anyway decision: stop before archive/delete and route to `/kha-audit-milestone` or `/kha-plan-gap-phases`
- readiness/stats/accomplishments preview is the mandatory dry-run gate: if the user does not approve the scope/stats preview, no archive/delete/tag step runs
- archive-before-delete is the mandatory snapshot procedure: `.planning/milestones/v{{version}}-ROADMAP.md` and `.planning/milestones/v{{version}}-REQUIREMENTS.md` must exist and be verified before collapsing `ROADMAP.md` or deleting `.planning/REQUIREMENTS.md`
- tag/push/commit failure after archival: keep archive files, `PROJECT.md`, and milestone summary edits on disk; do not recreate deleted originals or roll back the archive

## Gate summary


- preflight: milestone phases analyze as complete; requirements traceability can be parsed; archive paths under `.planning/milestones/` are writable; the dry-run readiness preview is approved
- success criteria: archive files exist, `MILESTONES.md`/`PROJECT.md`/`RETROSPECTIVE.md` are updated, the original milestone requirements file is removed only after archive verification, and tag `v{{version}}` plus the milestone commit are created
- abort triggers: failed readiness gate; missing or blocking audit with no explicit override; archive verification failure; tag/commit failure that prevents completion

## Retry / Resume


- checkpoint: `.planning/milestones/v{{version}}-ROADMAP.md`
- resume command: `/kha-resume-work`
- idempotent: no — archive/delete/tag/commit transition the project into a new milestone state and cannot be replayed blindly
- stall detection: archive files exist but the milestone tag or completion commit does not, or the original `ROADMAP.md`/`REQUIREMENTS.md` still remain after the archive step should have closed
