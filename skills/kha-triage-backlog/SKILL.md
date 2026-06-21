---
name: kha-triage-backlog
description: "Review and promote backlog items to active milestone"
allowed-tools:
  - Read
  - Write
  - Bash
  - AskUserQuestion
category: triage
mutates: yes
long-running: no
---
<objective>
Review all 999.x backlog items and optionally promote them into the active
milestone sequence or remove stale entries.
</objective>

<process>

1. **List backlog items:**
   ```bash
   ls -d .planning/phases/999* 2>/dev/null || echo "No backlog items found"
   ```

2. **Read ROADMAP.md** and extract all 999.x phase entries:
   ```bash
   cat .planning/ROADMAP.md
   ```
   Show each backlog item with its description, any accumulated context (CONTEXT.md, RESEARCH.md), and creation date.

3. **Present the list to the user** via AskUserQuestion:
   - For each backlog item, show: phase number, description, accumulated artifacts
   - Options per item: **Promote** (move to active), **Keep** (leave in backlog), **Remove** (delete)

4. **For items to PROMOTE:**
   - Find the next sequential phase number in the active milestone
   - Rename the directory from `999.x-slug` to `{new_num}-slug`:
     ```bash
     NEW_NUM=$(node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" phase add "${DESCRIPTION}" --raw)
     ```
   - Move accumulated artifacts to the new phase directory
   - Update ROADMAP.md: move the entry from `## Backlog` section to the active phase list
   - Remove `(BACKLOG)` marker
   - Add appropriate `**Depends on:**` field

5. **For items to REMOVE:**
   - Delete the phase directory
   - Remove the entry from ROADMAP.md `## Backlog` section

6. **Commit changes:**
   ```bash
   node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" commit "docs: review backlog — promoted N, removed M" --files .planning/ROADMAP.md
   ```

7. **Report summary:**
   ```
   ## 📋 Backlog Review Complete

   Promoted: {list of promoted items with new phase numbers}
   Kept: {list of items remaining in backlog}
   Removed: {list of deleted items}
   ```

</process>

## Stability (triage destructive)

### dry-run mode
- `--dry-run` shows planned promotions (item -> milestone) and planned
  removals (item id list). No state mutation.
- `--apply` required for actual mutation.

### snapshot before mutation
- `.planning/snapshots/triage-backlog-<ts>.json` containing:
  - full BACKLOG.md content pre-mutation
  - planned promote/remove operations
  - target milestone state (current ROADMAP entries)
- Restore = revert this snapshot.

### no checkpoint
- Triage is small enough to be atomic. No multi-step resume needed.

### no lock
- Multiple triage sessions can run; conflicts resolved by git (merge or
  refuse on backlog content overlap).

## Output


- artifact: before every `Promote` or `Remove`, the command must surface a dry-run preview and a snapshot of the current roadmap entry plus affected phase directory/artifacts; after approval it mutates `.planning/ROADMAP.md` and renames or deletes `.planning/phases/999.x-*`.
- status: `no_backlog_items` | `backlog_review_complete` | `review_cancelled`

## Failure behavior


- preflight failure: if no `999*` backlog dirs or no readable backlog entries exist, stop with no writes.
- execution failure: stop on the first failed promote/remove, keep already-applied approved mutations, and report the last dry-run/snapshot handles for the item that failed; unprocessed backlog items remain untouched.

## Gate summary


- preflight: backlog items are discoverable from `.planning/phases/999*` and `.planning/ROADMAP.md`.
- success criteria: every mutating action was preceded by an explicit dry-run plus snapshot, promoted items received a new active phase number and roadmap placement, removed items disappeared from both the backlog section and filesystem, and the final promoted/kept/removed summary is shown.
