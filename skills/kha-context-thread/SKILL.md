---
name: kha-context-thread
description: "Manage persistent context threads for cross-session work"
argument-hint: "[name | description]"
allowed-tools:
  - Read
  - Write
  - Bash
category: workflow
mutates: yes
long-running: no
---
<objective>
Create, list, or resume persistent context threads. Threads are lightweight
cross-session knowledge stores for work that spans multiple sessions but
doesn't belong to any specific phase.
</objective>

<process>

**Parse $ARGUMENTS to determine mode:**

<mode_list>
**If no arguments or $ARGUMENTS is empty:**

List all threads:
```bash
ls .planning/threads/*.md 2>/dev/null
```

For each thread, read the first few lines to show title and status:
```
## Active Threads

| Thread | Status | Last Updated |
|--------|--------|-------------|
| fix-deploy-key-auth | OPEN | 2026-03-15 |
| pasta-tcp-timeout | RESOLVED | 2026-03-12 |
| perf-investigation | IN PROGRESS | 2026-03-17 |
```

If no threads exist, show:
```
No threads found. Create one with: /kha-context-thread <description>
```
</mode_list>

<mode_resume>
**If $ARGUMENTS matches an existing thread name (file exists):**

Resume the thread — load its context into the current session:
```bash
cat ".planning/threads/${THREAD_NAME}.md"
```

Display the thread content and ask what the user wants to work on next.
Update the thread's status to `IN PROGRESS` if it was `OPEN`.
</mode_resume>

<mode_create>
**If $ARGUMENTS is a new description (no matching thread file):**

Create a new thread:

1. Generate slug from description:
   ```bash
   SLUG=$(node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" generate-slug "$ARGUMENTS" --raw)
   ```

2. Create the threads directory if needed:
   ```bash
   mkdir -p .planning/threads
   ```

3. Write the thread file:
   ```bash
   cat > ".planning/threads/${SLUG}.md" << 'EOF'
   # Thread: {description}

   ## Status: OPEN

   ## Goal

   {description}

   ## Context

   *Created from conversation on {today's date}.*

   ## References

   - *(add links, file paths, or issue numbers)*

   ## Next Steps

   - *(what the next session should do first)*
   EOF
   ```

4. If there's relevant context in the current conversation (code snippets,
   error messages, investigation results), extract and add it to the Context
   section.

5. Commit:
   ```bash
   node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" commit "docs: create thread — ${ARGUMENTS}" --files ".planning/threads/${SLUG}.md"
   ```

6. Report:
   ```
   ## 🧵 Thread Created

   Thread: {slug}
   File: .planning/threads/{slug}.md

   Resume anytime with: /kha-context-thread {slug}
   ```
</mode_create>

</process>

<notes>
- Threads are NOT phase-scoped — they exist independently of the roadmap
- Lighter weight than /kha-pause-work — no phase state, no plan context
- The value is in Context and Next Steps — a cold-start session can pick up immediately
- Threads can be promoted to phases or backlog items when they mature:
  /kha-add-phase or /kha-capture-backlog with context from the thread
- Thread files live in .planning/threads/ — no collision with phases or other GSD structures
</notes>

## Output


- artifact: create writes `.planning/threads/{slug}.md`; resume loads that file and may update `## Status` from `OPEN` to `IN PROGRESS`; list is read-only and only renders discovered thread metadata.
- status: `no_threads` | `threads_listed` | `thread_created` | `thread_resumed`

## Failure behavior


- preflight failure: list mode with no thread files is a clean no-op, and create mode stops with no write if the description cannot be turned into a thread.
- execution failure: if thread creation writes the file but commit/reporting fails, keep the thread file and report its path; resume-mode status edits are not considered complete unless the file update succeeded.

## Gate summary


- preflight: mode resolves cleanly from `$ARGUMENTS`, `.planning/threads/` is readable or creatable, and a resume target matches an existing thread file when requested.
- success criteria: list shows existing threads, create produces a reusable thread file with Goal/Context/References/Next Steps, and resume loads the saved context and upgrades status to `IN PROGRESS` when appropriate.
