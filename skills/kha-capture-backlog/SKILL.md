---
name: kha-capture-backlog
description: "Add an idea to the backlog parking lot (999.x numbering)"
argument-hint: "<description>"
allowed-tools:
  - Read
  - Write
  - Bash
category: capture
mutates: yes
long-running: no
---
<objective>
Add a backlog item to the roadmap using 999.x numbering. Backlog items are
unsequenced ideas that aren't ready for active planning — they live outside
the normal phase sequence and accumulate context over time.
</objective>

<process>

1. **Read ROADMAP.md** to find existing backlog entries:
   ```bash
   cat .planning/ROADMAP.md
   ```

2. **Find next backlog number:**
   ```bash
   NEXT=$(node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" phase next-decimal 999 --raw)
   ```
   If no 999.x phases exist, start at 999.1.

3. **Create the phase directory:**
   ```bash
   SLUG=$(node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" generate-slug "$ARGUMENTS" --raw)
   mkdir -p ".planning/phases/${NEXT}-${SLUG}"
   touch ".planning/phases/${NEXT}-${SLUG}/.gitkeep"
   ```

4. **Add to ROADMAP.md** under a `## Backlog` section. If the section doesn't exist, create it at the end:

   ```markdown
   ## Backlog

   ### Phase {NEXT}: {description} (BACKLOG)

   **Goal:** [Captured for future planning]
   **Requirements:** TBD
   **Plans:** 0 plans

   Plans:
   - [ ] TBD (promote with /kha-triage-backlog when ready)
   ```

5. **Commit:**
   ```bash
   node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" commit "docs: add backlog item ${NEXT} — ${ARGUMENTS}" --files .planning/ROADMAP.md ".planning/phases/${NEXT}-${SLUG}/.gitkeep"
   ```

6. **Report:**
   ```
   ## 📋 Backlog Item Added

   Phase {NEXT}: {description}
   Directory: .planning/phases/{NEXT}-{slug}/

   This item lives in the backlog parking lot.
   Use /kha-clarify-phase {NEXT} to explore it further.
   Use /kha-triage-backlog to promote items to active milestone.
   ```

</process>

<notes>
- 999.x numbering keeps backlog items out of the active phase sequence
- Phase directories are created immediately, so /kha-clarify-phase and /kha-plan-phase work on them
- No `Depends on:` field — backlog items are unsequenced by definition
- Sparse numbering is fine (999.1, 999.3) — always uses next-decimal
</notes>

## Output


- artifact: `.planning/phases/{NEXT}-{slug}/.gitkeep` and a matching `## Backlog` entry in `.planning/ROADMAP.md`; this contract is intentionally narrow: backlog is a phase-shaped future candidate, not an active sequenced phase, todo, or triggerable seed.
- status: `backlog_added` | `aborted`

## Failure behavior


- preflight failure: if the description is empty, `ROADMAP.md` is unreadable, or the next `999.x` number cannot be resolved, stop with no writes.
- execution failure: if the phase dir or roadmap entry was written before commit/reporting fails, leave both in place and report `{NEXT}` plus `.planning/phases/{NEXT}-{slug}/` as the recovery handle; do not silently downgrade it into an active phase.

## Gate summary


- preflight: non-empty capture text, readable `.planning/ROADMAP.md`, and a resolvable next backlog number via `phase next-decimal 999`.
- success criteria: a new `999.x` directory exists and the roadmap has a `## Backlog` entry for the same phase number and description.
