<purpose>
Execute small, ad-hoc tasks with GSD guarantees (atomic commits, STATE.md tracking). Quick mode spawns kha-planner (quick mode) + kha-executor(s), tracks tasks in `.planning/quick/`, and updates STATE.md's "Quick Tasks Completed" table.

With `--full` flag: enables the complete quality pipeline — discussion + research + plan-checking + verification. One flag for everything.

With `--validate` flag: enables plan-checking (max 2 iterations) and post-execution verification only. Use when you want quality guarantees without discussion or research.

With `--discuss` flag: lightweight discussion phase before planning. Surfaces assumptions, clarifies gray areas, captures decisions in CONTEXT.md so the planner treats them as locked.

With `--research` flag: spawns a focused research agent before planning. Investigates implementation approaches, library options, and pitfalls. Use when you're unsure how to approach a task.

Granular flags are composable: `--discuss --research --validate` gives the same result as `--full`.
</purpose>

<required_reading>
Read all files referenced by the invoking prompt's execution_context before starting.
</required_reading>

<available_agent_types>
Valid GSD subagent types (use exact names — do not fall back to 'general-purpose'):
- kha-phase-researcher — Researches technical approaches for a phase
- kha-planner — Creates detailed plans from phase scope
- kha-plan-checker — Reviews plan quality before execution
- kha-executor — Executes plan tasks, commits, creates SUMMARY.md
- kha-verifier — Verifies phase completion, checks quality gates
- kha-code-reviewer — Reviews source files for bugs, security issues, and code quality
</available_agent_types>

<process>
**Step 1: Parse arguments and get task description**

Parse `$ARGUMENTS` for:
- `--full` flag → store `$FULL_MODE=true`, `$DISCUSS_MODE=true`, `$RESEARCH_MODE=true`, `$VALIDATE_MODE=true`
- `--validate` flag → store `$VALIDATE_MODE=true`
- `--discuss` flag → store `$DISCUSS_MODE=true`
- `--research` flag → store `$RESEARCH_MODE=true`
- `--scratch` flag → store `$SCRATCH_MODE=true` (throwaway / no-commit mode)
- Remaining text → use as `$DESCRIPTION` if non-empty

**Scratch mode (`--scratch`, P3 absorption — debate-1780911873-da8277):** a disposable experiment/mockup that leaves NO permanent artifact. When `$SCRATCH_MODE=true`, this workflow MUST: (1) NOT require ROADMAP.md (skip the Step 2 abort); (2) write under `.planning/scratch/` instead of `.planning/quick/` and NOT create the init `task_dir` (Step 3); (3) NOT commit code atomically (Step 6 executor); (4) NOT update STATE.md (Step 7); (5) NOT run the final docs commit (Step 8); (6) NOT use worktree isolation — force `$USE_WORKTREES=false` (Step 2). A no-commit throwaway run has no commits to isolate or merge back, so a worktree is pure overhead that also breaks delivery: `git worktree add` does not inherit the untracked `PLAN.md` (which scratch forbids committing), so a worktree-isolated executor cannot read its plan, and the worktree's removal would discard the scratch artifact. Running in-place keeps the throwaway files uncommitted and deletable in the main tree, as intended. The artifact stays uncommitted and deletable. This is the home for gsd-core `spike` (experimental code) and `sketch` (`/kha-run-adhoc --scratch 'emit a single self-contained throwaway HTML mockup'`).

If `$DESCRIPTION` is empty after parsing, prompt user interactively:

```
AskUserQuestion(
  header: "Quick Task",
  question: "What do you want to do?",
  followUp: null
)
```

Store response as `$DESCRIPTION`.

If still empty, re-prompt: "Please provide a task description."

Display banner based on active flags:

If `$FULL_MODE` (all phases enabled — `--full` or all granular flags):
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 GSD ► QUICK TASK (FULL)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ Discussion + research + plan checking + verification enabled
```

If `$DISCUSS_MODE` and `$RESEARCH_MODE` and `$VALIDATE_MODE` (no `$FULL_MODE` — composed granularly):
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 GSD ► QUICK TASK (DISCUSS + RESEARCH + VALIDATE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ Discussion + research + plan checking + verification enabled
```

If `$DISCUSS_MODE` and `$VALIDATE_MODE` (no research):
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 GSD ► QUICK TASK (DISCUSS + VALIDATE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ Discussion + plan checking + verification enabled
```

If `$DISCUSS_MODE` and `$RESEARCH_MODE` (no validate):
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 GSD ► QUICK TASK (DISCUSS + RESEARCH)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ Discussion + research enabled
```

If `$RESEARCH_MODE` and `$VALIDATE_MODE` (no discuss):
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 GSD ► QUICK TASK (RESEARCH + VALIDATE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ Research + plan checking + verification enabled
```

If `$DISCUSS_MODE` only:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 GSD ► QUICK TASK (DISCUSS)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ Discussion phase enabled — surfacing gray areas before planning
```

If `$RESEARCH_MODE` only:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 GSD ► QUICK TASK (RESEARCH)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ Research phase enabled — investigating approaches before planning
```

If `$VALIDATE_MODE` only:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 GSD ► QUICK TASK (VALIDATE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ Plan checking + verification enabled
```

---

**Step 2: Initialize**

```bash
INIT=$(node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" init quick "$DESCRIPTION")
if [[ "$INIT" == @file:* ]]; then INIT=$(cat "${INIT#@file:}"); fi
AGENT_SKILLS_PLANNER=$(node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" agent-skills kha-planner 2>/dev/null)
AGENT_SKILLS_EXECUTOR=$(node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" agent-skills kha-executor 2>/dev/null)
AGENT_SKILLS_CHECKER=$(node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" agent-skills kha-plan-checker 2>/dev/null)
AGENT_SKILLS_VERIFIER=$(node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" agent-skills kha-verifier 2>/dev/null)
```

Parse JSON for: `planner_model`, `executor_model`, `checker_model`, `verifier_model`, `commit_docs`, `branch_name`, `quick_id`, `slug`, `date`, `timestamp`, `quick_dir`, `task_dir`, `roadmap_exists`, `planning_exists`.

```bash
USE_WORKTREES=$(node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" config-get workflow.use_worktrees 2>/dev/null || echo "true")
# Scratch mode forces no worktree: a no-commit throwaway run has nothing to isolate/merge,
# and a worktree cannot receive the untracked PLAN.md (scratch forbids committing it).
if [ "${SCRATCH_MODE}" = "true" ]; then USE_WORKTREES="false"; fi
# commit_docs=false forces no worktree: worktree plan-delivery (Step 6) must commit the untracked
# PLAN.md to reach the isolated worktree, which would violate the deliberate no-.planning-commit
# invariant (#1783). Run in-place instead so the PLAN stays reachable uncommitted.
COMMIT_DOCS=$(node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" config-get commit_docs 2>/dev/null || echo "true")
if [ "${COMMIT_DOCS}" = "false" ]; then USE_WORKTREES="false"; fi
```

**If `roadmap_exists` is false:** Error — Quick mode requires an active project with ROADMAP.md. Run `/kha-new-project` first. **(Skip this abort entirely when `$SCRATCH_MODE=true` — a throwaway scratch run needs no governing project.)**

Quick tasks can run mid-phase - validation only checks ROADMAP.md exists, not phase status.

---

**Step 2.5: Handle quick-task branching**

**If `branch_name` is empty/null:** Skip and continue on the current branch.

**If `branch_name` is set:** Check out the quick-task branch before any planning commits:

```bash
git checkout -b "$branch_name" 2>/dev/null || git checkout "$branch_name"
```

All quick-task commits for this run stay on that branch. User handles merge/rebase afterward.

---

**Step 3: Create task directory**

```bash
mkdir -p "${task_dir}"
```

**If `$SCRATCH_MODE=true`:** SKIP this `mkdir` — `task_dir` is the init-computed `.planning/quick/...` path, which a throwaway run must not create (Step 4 makes the `.planning/scratch/` dir instead). Skipping here prevents an orphan empty `.planning/quick/<id>/` dir from leaking per scratch run.

---

**Step 4: Create quick task directory**

Create the directory for this quick task:

```bash
QUICK_DIR=".planning/quick/${quick_id}-${slug}"
# Scratch mode: throwaway artifacts live under .planning/scratch/ (deletable, never committed)
if [ "${SCRATCH_MODE}" = "true" ]; then QUICK_DIR=".planning/scratch/${quick_id}-${slug}"; fi
mkdir -p "$QUICK_DIR"
```

Report to user:
```
Creating quick task ${quick_id}: ${DESCRIPTION}
Directory: ${QUICK_DIR}
```

Store `$QUICK_DIR` for use in orchestration.

---

**Step 4.5: Discussion phase (only when `$DISCUSS_MODE`)**

Skip this step entirely if NOT `$DISCUSS_MODE`.

Display banner:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 GSD ► DISCUSSING QUICK TASK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ Surfacing gray areas for: ${DESCRIPTION}
```

**4.5a. Identify gray areas**

Analyze `$DESCRIPTION` to identify 2-4 gray areas — implementation decisions that would change the outcome and that the user should weigh in on.

Use the domain-aware heuristic to generate phase-specific (not generic) gray areas:
- Something users **SEE** → layout, density, interactions, states
- Something users **CALL** → responses, errors, auth, versioning
- Something users **RUN** → output format, flags, modes, error handling
- Something users **READ** → structure, tone, depth, flow
- Something being **ORGANIZED** → criteria, grouping, naming, exceptions

Each gray area should be a concrete decision point, not a vague category. Example: "Loading behavior" not "UX".

**4.5b. Present gray areas**

```
AskUserQuestion(
  header: "Gray Areas",
  question: "Which areas need clarification before planning?",
  options: [
    { label: "${area_1}", description: "${why_it_matters_1}" },
    { label: "${area_2}", description: "${why_it_matters_2}" },
    { label: "${area_3}", description: "${why_it_matters_3}" },
    { label: "All clear", description: "Skip discussion — I know what I want" }
  ],
  multiSelect: true
)
```

If user selects "All clear" → skip to Step 5 (no CONTEXT.md written).

**4.5c. Discuss selected areas**

For each selected area, ask 1-2 focused questions via AskUserQuestion:

```
AskUserQuestion(
  header: "${area_name}",
  question: "${specific_question_about_this_area}",
  options: [
    { label: "${concrete_choice_1}", description: "${what_this_means}" },
    { label: "${concrete_choice_2}", description: "${what_this_means}" },
    { label: "${concrete_choice_3}", description: "${what_this_means}" },
    { label: "You decide", description: "Claude's discretion" }
  ],
  multiSelect: false
)
```

Rules:
- Options must be concrete choices, not abstract categories
- Highlight recommended choice where you have a clear opinion
- If user selects "Other" with freeform text, switch to plain text follow-up (per questioning.md freeform rule)
- If user selects "You decide", capture as Claude's Discretion in CONTEXT.md
- Max 2 questions per area — this is lightweight, not a deep dive

Collect all decisions into `$DECISIONS`.

**4.5d. Write CONTEXT.md**

Write `${QUICK_DIR}/${quick_id}-CONTEXT.md` using the standard context template structure:

```markdown
# Quick Task ${quick_id}: ${DESCRIPTION} - Context

**Gathered:** ${date}
**Status:** Ready for planning

<domain>
## Task Boundary

${DESCRIPTION}

</domain>

<decisions>
## Implementation Decisions

### ${area_1_name}
- ${decision_from_discussion}

### ${area_2_name}
- ${decision_from_discussion}

### Claude's Discretion
${areas_where_user_said_you_decide_or_areas_not_discussed}

</decisions>

<specifics>
## Specific Ideas

${any_specific_references_or_examples_from_discussion}

[If none: "No specific requirements — open to standard approaches"]

</specifics>

<canonical_refs>
## Canonical References

${any_specs_adrs_or_docs_referenced_during_discussion}

[If none: "No external specs — requirements fully captured in decisions above"]

</canonical_refs>
```

Note: Quick task CONTEXT.md omits `<code_context>` and `<deferred>` sections (no codebase scouting, no phase scope to defer to). Keep it lean. The `<canonical_refs>` section is included when external docs were referenced — omit it only if no external docs apply.

Report: `Context captured: ${QUICK_DIR}/${quick_id}-CONTEXT.md`

---

**Step 4.75: Research phase (only when `$RESEARCH_MODE`)**

Skip this step entirely if NOT `$RESEARCH_MODE`.

Display banner:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 GSD ► RESEARCHING QUICK TASK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ Investigating approaches for: ${DESCRIPTION}
```

Spawn a single focused researcher (not 4 parallel researchers like full phases — quick tasks need targeted research, not broad domain surveys):

```
Task(
  prompt="
<research_context>

**Mode:** quick-task
**Task:** ${DESCRIPTION}
**Output:** ${QUICK_DIR}/${quick_id}-RESEARCH.md

<files_to_read>
- .planning/STATE.md (Project state — what's already built)
- .planning/PROJECT.md (Project context)
- ./CLAUDE.md (if exists — project-specific guidelines)
${DISCUSS_MODE ? '- ' + QUICK_DIR + '/' + quick_id + '-CONTEXT.md (User decisions — research should align with these)' : ''}
</files_to_read>

${AGENT_SKILLS_PLANNER}

</research_context>

<focus>
This is a quick task, not a full phase. Research should be concise and targeted:
1. Best libraries/patterns for this specific task
2. Common pitfalls and how to avoid them
3. Integration points with existing codebase
4. Any constraints or gotchas worth knowing before planning

Do NOT produce a full domain survey. Target 1-2 pages of actionable findings.
</focus>

<output>
Write research to: ${QUICK_DIR}/${quick_id}-RESEARCH.md
Use standard research format but keep it lean — skip sections that don't apply.
Return: ## RESEARCH COMPLETE with file path
</output>
",
  subagent_type="kha-phase-researcher",
  model="{planner_model}",
  description="Research: ${DESCRIPTION}"
)
```

After researcher returns:
1. Verify research exists at `${QUICK_DIR}/${quick_id}-RESEARCH.md`
2. Report: "Research complete: ${QUICK_DIR}/${quick_id}-RESEARCH.md"

If research file not found, warn but continue: "Research agent did not produce output — proceeding to planning without research."

---

**Step 5: Spawn planner (quick mode)**

**If `$VALIDATE_MODE`:** Use `quick-full` mode with stricter constraints.

**If NOT `$VALIDATE_MODE`:** Use standard `quick` mode.

```
Task(
  prompt="
<planning_context>

**Mode:** ${VALIDATE_MODE ? 'quick-full' : 'quick'}
**Directory:** ${QUICK_DIR}
**Description:** ${DESCRIPTION}

<files_to_read>
- .planning/STATE.md (Project State)
- ./CLAUDE.md (if exists — follow project-specific guidelines)
${DISCUSS_MODE ? '- ' + QUICK_DIR + '/' + quick_id + '-CONTEXT.md (User decisions — locked, do not revisit)' : ''}
${RESEARCH_MODE ? '- ' + QUICK_DIR + '/' + quick_id + '-RESEARCH.md (Research findings — use to inform implementation choices)' : ''}
</files_to_read>

${AGENT_SKILLS_PLANNER}

**Project skills:** Check .claude/skills/ or .agents/skills/ directory (if either exists) — read SKILL.md files, plans should account for project skill rules

</planning_context>

<constraints>
- Create a SINGLE plan with 1-3 focused tasks
- Quick tasks should be atomic and self-contained
${RESEARCH_MODE ? '- Research findings are available — use them to inform library/pattern choices' : '- No research phase'}
${VALIDATE_MODE ? '- Target ~40% context usage (structured for verification)' : '- Target ~30% context usage (simple, focused)'}
${VALIDATE_MODE ? '- MUST generate `must_haves` in plan frontmatter (truths, artifacts, key_links)' : ''}
${VALIDATE_MODE ? '- Each task MUST have `files`, `action`, `verify`, `done` fields' : ''}
</constraints>

<output>
Write plan to: ${QUICK_DIR}/${quick_id}-PLAN.md
Return: ## PLANNING COMPLETE with plan path
</output>
",
  subagent_type="kha-planner",
  model="{planner_model}",
  description="Quick plan: ${DESCRIPTION}"
)
```

After planner returns:
1. Verify plan exists at `${QUICK_DIR}/${quick_id}-PLAN.md`
2. Extract plan count (typically 1 for quick tasks)
3. Report: "Plan created: ${QUICK_DIR}/${quick_id}-PLAN.md"

If plan not found, error: "Planner failed to create ${quick_id}-PLAN.md"

---

**Step 5.5: Plan-checker loop (only when `$VALIDATE_MODE`)**

Skip this step entirely if NOT `$VALIDATE_MODE`.

Display banner:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 GSD ► CHECKING PLAN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ Spawning plan checker...
```

Checker prompt:

```markdown
<verification_context>
**Mode:** quick-full
**Task Description:** ${DESCRIPTION}

<files_to_read>
- ${QUICK_DIR}/${quick_id}-PLAN.md (Plan to verify)
</files_to_read>

${AGENT_SKILLS_CHECKER}

**Scope:** This is a quick task, not a full phase. Skip checks that require a ROADMAP phase goal.
</verification_context>

<check_dimensions>
- Requirement coverage: Does the plan address the task description?
- Task completeness: Do tasks have files, action, verify, done fields?
- Key links: Are referenced files real?
- Scope sanity: Is this appropriately sized for a quick task (1-3 tasks)?
- must_haves derivation: Are must_haves traceable to the task description?

Skip: cross-plan deps (single plan), ROADMAP alignment
${DISCUSS_MODE ? '- Context compliance: Does the plan honor locked decisions from CONTEXT.md?' : '- Skip: context compliance (no CONTEXT.md)'}
</check_dimensions>

<expected_output>
- ## VERIFICATION PASSED — all checks pass
- ## ISSUES FOUND — structured issue list
</expected_output>
```

```
Task(
  prompt=checker_prompt,
  subagent_type="kha-plan-checker",
  model="{checker_model}",
  description="Check quick plan: ${DESCRIPTION}"
)
```

**Handle checker return:**

- **`## VERIFICATION PASSED`:** Display confirmation, proceed to step 6.
- **`## ISSUES FOUND`:** Display issues, check iteration count, enter revision loop.

**Revision loop (max 2 iterations):**

Track `iteration_count` (starts at 1 after initial plan + check).

**If iteration_count < 2:**

Display: `Sending back to planner for revision... (iteration ${N}/2)`

Revision prompt:

```markdown
<revision_context>
**Mode:** quick-full (revision)

<files_to_read>
- ${QUICK_DIR}/${quick_id}-PLAN.md (Existing plan)
</files_to_read>

${AGENT_SKILLS_PLANNER}

**Checker issues:** ${structured_issues_from_checker}

</revision_context>

<instructions>
Make targeted updates to address checker issues.
Do NOT replan from scratch unless issues are fundamental.
Return what changed.
</instructions>
```

```
Task(
  prompt=revision_prompt,
  subagent_type="kha-planner",
  model="{planner_model}",
  description="Revise quick plan: ${DESCRIPTION}"
)
```

After planner returns → spawn checker again, increment iteration_count.

**If iteration_count >= 2:**

Display: `Max iterations reached. ${N} issues remain:` + issue list

Offer: 1) Force proceed, 2) Abort

---

**Step 6: Spawn executor**

**Worktree plan delivery (only when `$USE_WORKTREES` is not `false`):** the planner wrote `PLAN.md` as an *untracked* file in the main working tree, but `git worktree add` (used by `isolation="worktree"`) does NOT carry untracked files into the executor's worktree — a worktree-isolated executor would not find its plan. Commit the plan artifact now so the worktree (branched from the `EXPECTED_BASE` captured below) contains it. This is a no-op for in-place runs: when `$USE_WORKTREES=false` — normal in-place, scratch (Step 2 forces `false`), and `commit_docs=false` (Step 2 forces `false` so this commit never violates the no-`.planning`-commit invariant) — the plan is already reachable in the main tree. Step 8's `gsd-tools commit` handles the already-committed plan gracefully. (Because Fix E only runs when `commit_docs` is not `false`, it never creates an unwanted `.planning/` commit.)
```bash
if [ "${USE_WORKTREES}" != "false" ]; then
  git add "${QUICK_DIR}/${quick_id}-PLAN.md" 2>/dev/null || true
  git commit -q -m "docs(quick-${quick_id}): plan for ${DESCRIPTION}" 2>/dev/null || true
fi
```

Capture current HEAD before spawning (used for worktree branch check; includes the plan-delivery commit above when worktrees are enabled):
```bash
EXPECTED_BASE=$(git rev-parse HEAD)
```

Spawn kha-executor with plan reference:

```
Task(
  prompt="
Execute quick task ${quick_id}.

${USE_WORKTREES !== "false" ? `
<worktree_branch_check>
FIRST ACTION before any other work: verify this worktree branch is based on the correct commit.
Run: git merge-base HEAD ${EXPECTED_BASE}
If the result differs from ${EXPECTED_BASE}, run: git reset --soft ${EXPECTED_BASE}
This corrects a known issue on Windows where EnterWorktree creates branches from main instead of the feature branch HEAD.
</worktree_branch_check>
` : ''}

<files_to_read>
- ${QUICK_DIR}/${quick_id}-PLAN.md (Plan)
- .planning/STATE.md (Project state)
- ./CLAUDE.md (Project instructions, if exists)
- .claude/skills/ or .agents/skills/ (Project skills, if either exists — list skills, read SKILL.md for each, follow relevant rules during implementation)
</files_to_read>

${AGENT_SKILLS_EXECUTOR}

<constraints>
- Execute all tasks in the plan
- Commit each task atomically (code changes only) ${SCRATCH_MODE === "true" ? "— SKIP under scratch mode: do NOT commit anything; leave all changes uncommitted and deletable" : ""}
- Create summary at: ${QUICK_DIR}/${quick_id}-SUMMARY.md
- ${USE_WORKTREES !== "false" ? "Make the SUMMARY a FINAL separate commit (`git add ${QUICK_DIR}/${quick_id}-SUMMARY.md && git commit`) AFTER the atomic code commits — a worktree-isolated run is merged back by `gsd-tools quick-merge-back`, and `git worktree remove --force` would discard an UNcommitted SUMMARY. Commit ONLY the SUMMARY doc this way; do NOT commit STATE.md or ROADMAP.md (the orchestrator owns those)." : "Do NOT commit docs artifacts (SUMMARY.md, STATE.md, PLAN.md) — the orchestrator handles the docs commit in Step 8"}
- Do NOT update ROADMAP.md (quick tasks are separate from planned phases)
</constraints>
",
  subagent_type="kha-executor",
  model="{executor_model}",
  ${USE_WORKTREES !== "false" ? 'isolation="worktree",' : ''}
  description="Execute: ${DESCRIPTION}"
)
```

After executor returns:
1. **Worktree merge-back (only when `$USE_WORKTREES` is not `false`):** the executor ran isolated in a worktree (committing its code atomically + the SUMMARY as a final commit). Merge each worktree branch back into `main`, protect orchestrator-owned files (STATE/ROADMAP — main always wins, #1756), sweep resurrected `.planning/` artifacts, and clean up — all via the deterministic `quick-merge-back` subcommand. The git edge cases that made the former inline bash patch-resistant (fast-forward vs merge-commit, pre-merge-tip diffing not `HEAD~1`, fresh reconcile commit never `--amend`, QUICK_DIR-scoped resurrection, detached-HEAD by sha) are handled once in `bin/lib/merge-back.cjs` and regression-covered by `bin/lib/__tests__/merge-back.test.cjs`:
   ```bash
   if [ "${USE_WORKTREES}" != "false" ]; then
     MERGE_BACK=$(node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" quick-merge-back \
       --quick-id "${quick_id}" --quick-dir "${QUICK_DIR}" --expected-base "${EXPECTED_BASE}")
     echo "$MERGE_BACK"
   fi
   ```
   Parse the JSON in `$MERGE_BACK`:
   - `.merged == false` with a non-empty `.conflicts[]` → a worktree hit a merge conflict; the subcommand aborted that merge and **left the worktree in place**. Report each `.conflicts[].path` / `.message` and tell the user to resolve it manually. Do NOT proceed as if the task merged.
   - `.commit_hash` → the executor's CODE commit (NOT the SUMMARY/merge/reconcile commit). Use it as `commit_hash` for the STATE.md row (Step 7) — this supersedes "extract commit hash from executor output".
   - `.worktrees[].summary_present` / `.plan_present` confirm the artifacts are committed on `main`; `.worktrees[].resurrected_removed[]` lists any swept resurrections (informational).
   When `$USE_WORKTREES` is `false` (normal in-place, scratch which Step 2 forces to `false`, or `commit_docs=false` which Step 2 also forces to `false`), there is no worktree to merge — skip this block; the executor's code commits and the uncommitted SUMMARY are already in the main tree for Step 8.
2. Verify the summary exists at `${QUICK_DIR}/${quick_id}-SUMMARY.md` (committed on `main` in worktree mode per `.worktrees[].summary_present`; uncommitted in the main tree for in-place runs — Step 8 commits it).
3. `commit_hash`: from `$MERGE_BACK` `.commit_hash` in worktree mode; from the executor's atomic code commit for in-place runs.
4. Report completion status.

**Known Claude Code bug (classifyHandoffIfNeeded):** If executor reports "failed" with error `classifyHandoffIfNeeded is not defined`, this is a Claude Code runtime bug — not a real failure. Check if summary file exists and git log shows commits. If so, treat as successful.

If summary not found, error: "Executor failed to create ${quick_id}-SUMMARY.md"

Note: For quick tasks producing multiple plans (rare), spawn executors in parallel waves per execute-phase patterns.

---

**Step 6.25: Code review (auto)**

Skip this step entirely if `$FULL_MODE` is false.

**Config gate:**
```bash
CODE_REVIEW_ENABLED=$(node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" config-get workflow.code_review 2>/dev/null || echo "true")
```
If `"false"`, skip with message "Code review skipped (workflow.code_review=false)".

**Scope files from executor's commits:**
```bash
# Find the diff base: last commit before quick task started
# Use git log to find commits referencing the quick task id, then take the parent of the oldest
QUICK_COMMITS=$(git log --oneline --format="%H" --grep="${quick_id}" 2>/dev/null)
if [ -n "$QUICK_COMMITS" ]; then
  DIFF_BASE=$(echo "$QUICK_COMMITS" | tail -1)^
  # Verify parent exists (guard against first commit in repo)
  git rev-parse "${DIFF_BASE}" >/dev/null 2>&1 || DIFF_BASE=$(echo "$QUICK_COMMITS" | tail -1)
else
  # No commits found for this quick task — skip review
  DIFF_BASE=""
fi

if [ -n "$DIFF_BASE" ]; then
  CHANGED_FILES=$(git diff --name-only "${DIFF_BASE}..HEAD" -- . ':!.planning' 2>/dev/null | tr '\n' ' ')
else
  CHANGED_FILES=""
fi
```

If `CHANGED_FILES` is empty, skip with "No source files changed — skipping code review."

**Invoke review:**
```
Task(
  prompt="Review these files for bugs, security issues, and code quality.
  Files: ${CHANGED_FILES}
  Output: ${QUICK_DIR}/${quick_id}-REVIEW.md
  Depth: quick",
  subagent_type="kha-code-reviewer",
  model="{executor_model}"
)
```

If review produces findings, display advisory message. **Error handling:** Failures are non-blocking — catch and proceed.

---

**Step 6.5: Verification (only when `$VALIDATE_MODE`)**

Skip this step entirely if NOT `$VALIDATE_MODE`.

Display banner:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 GSD ► VERIFYING RESULTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ Spawning verifier...
```

```
Task(
  prompt="Verify quick task goal achievement.
Task directory: ${QUICK_DIR}
Task goal: ${DESCRIPTION}

<files_to_read>
- ${QUICK_DIR}/${quick_id}-PLAN.md (Plan)
</files_to_read>

${AGENT_SKILLS_VERIFIER}

Check must_haves against actual codebase. Create VERIFICATION.md at ${QUICK_DIR}/${quick_id}-VERIFICATION.md.",
  subagent_type="kha-verifier",
  model="{verifier_model}",
  description="Verify: ${DESCRIPTION}"
)
```

Read verification status:
```bash
grep "^status:" "${QUICK_DIR}/${quick_id}-VERIFICATION.md" | cut -d: -f2 | tr -d ' '
```

Store as `$VERIFICATION_STATUS`.

| Status | Action |
|--------|--------|
| `passed` | Store `$VERIFICATION_STATUS = "Verified"`, continue to step 7 |
| `human_needed` | Display items needing manual check, store `$VERIFICATION_STATUS = "Needs Review"`, continue |
| `gaps_found` | Display gap summary, offer: 1) Re-run executor to fix gaps, 2) Accept as-is. Store `$VERIFICATION_STATUS = "Gaps"` |

---

**Step 7: Update STATE.md**

**If `$SCRATCH_MODE=true`:** SKIP this entire step — a throwaway scratch run leaves no record in the tracked quick-task ledger. Proceed to Step 8.

Update STATE.md with quick task completion record.

**7a. Check if "Quick Tasks Completed" section exists:**

Read STATE.md and check for `### Quick Tasks Completed` section.

**7b. If section doesn't exist, create it:**

Insert after `### Blockers/Concerns` section:

**If `$VALIDATE_MODE`:**
```markdown
### Quick Tasks Completed

| # | Description | Date | Commit | Status | Directory |
|---|-------------|------|--------|--------|-----------|
```

**If NOT `$VALIDATE_MODE`:**
```markdown
### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
```

**Note:** If the table already exists, match its existing column format. If adding `--validate` (or `--full`) to a project that already has quick tasks without a Status column, add the Status column to the header and separator rows, and leave Status empty for the new row's predecessors.

**7c. Append new row to table:**

Use `date` from init:

**If `$VALIDATE_MODE` (or table has Status column):**
```markdown
| ${quick_id} | ${DESCRIPTION} | ${date} | ${commit_hash} | ${VERIFICATION_STATUS} | [${quick_id}-${slug}](./quick/${quick_id}-${slug}/) |
```

**If NOT `$VALIDATE_MODE` (and table has no Status column):**
```markdown
| ${quick_id} | ${DESCRIPTION} | ${date} | ${commit_hash} | [${quick_id}-${slug}](./quick/${quick_id}-${slug}/) |
```

**7d. Update "Last activity" line:**

Use `date` from init:
```
Last activity: ${date} - Completed quick task ${quick_id}: ${DESCRIPTION}
```

Use Edit tool to make these changes atomically

---

**Step 8: Final commit and completion**

**If `$SCRATCH_MODE=true`:** SKIP this entire step — do NOT stage or commit anything. Report the throwaway artifact path (`${QUICK_DIR}/...`) and tell the user it is uncommitted and deletable (`rm -rf ${QUICK_DIR}` when done). Then finish. The remainder of this step applies only to non-scratch runs.

Stage and commit quick task artifacts. This step MUST always run — even if the executor already committed some files (e.g. when running without worktree isolation). The `gsd-tools commit` command handles already-committed files gracefully.

Build file list:
- `${QUICK_DIR}/${quick_id}-PLAN.md`
- `${QUICK_DIR}/${quick_id}-SUMMARY.md`
- `.planning/STATE.md`
- If `$DISCUSS_MODE` and context file exists: `${QUICK_DIR}/${quick_id}-CONTEXT.md`
- If `$RESEARCH_MODE` and research file exists: `${QUICK_DIR}/${quick_id}-RESEARCH.md`
- If `$VALIDATE_MODE` and verification file exists: `${QUICK_DIR}/${quick_id}-VERIFICATION.md`
- If `$FULL_MODE` and review file exists (`[ -f "${QUICK_DIR}/${quick_id}-REVIEW.md" ]` — Step 6.25 produces it, but it is absent when code-review is skipped): `${QUICK_DIR}/${quick_id}-REVIEW.md`

```bash
# Explicitly stage all artifacts before commit — PLAN.md may be untracked
# if the executor ran without worktree isolation and committed docs early
# Filter .planning/ files from staging if commit_docs is disabled (#1783)
COMMIT_DOCS=$(node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" config-get commit_docs 2>/dev/null || echo "true")
if [ "$COMMIT_DOCS" = "false" ]; then
  file_list_filtered=$(echo "${file_list}" | tr ' ' '\n' | grep -v '^\.planning/' | tr '\n' ' ')
  git add ${file_list_filtered} 2>/dev/null
else
  git add ${file_list} 2>/dev/null
fi
node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" commit "docs(quick-${quick_id}): ${DESCRIPTION}" --files ${file_list}
```

Get final commit hash:
```bash
commit_hash=$(git rev-parse --short HEAD)
```

Display completion output:

**If `$VALIDATE_MODE`:**
```
---

GSD > QUICK TASK COMPLETE (VALIDATED)

Quick Task ${quick_id}: ${DESCRIPTION}

${RESEARCH_MODE ? 'Research: ' + QUICK_DIR + '/' + quick_id + '-RESEARCH.md' : ''}
Summary: ${QUICK_DIR}/${quick_id}-SUMMARY.md
Verification: ${QUICK_DIR}/${quick_id}-VERIFICATION.md (${VERIFICATION_STATUS})
Commit: ${commit_hash}

---

Ready for next task: /kha-run-adhoc ${GSD_WS}
```

**If NOT `$VALIDATE_MODE`:**
```
---

GSD > QUICK TASK COMPLETE

Quick Task ${quick_id}: ${DESCRIPTION}

${RESEARCH_MODE ? 'Research: ' + QUICK_DIR + '/' + quick_id + '-RESEARCH.md' : ''}
Summary: ${QUICK_DIR}/${quick_id}-SUMMARY.md
Commit: ${commit_hash}

---

Ready for next task: /kha-run-adhoc ${GSD_WS}
```

</process>

<success_criteria>
- [ ] ROADMAP.md validation passes
- [ ] User provides task description
- [ ] `--full`, `--validate`, `--discuss`, and `--research` flags parsed from arguments when present
- [ ] `--full` sets all booleans (`$FULL_MODE`, `$DISCUSS_MODE`, `$RESEARCH_MODE`, `$VALIDATE_MODE`)
- [ ] Slug generated (lowercase, hyphens, max 40 chars)
- [ ] Quick ID generated (YYMMDD-xxx format, 2s Base36 precision)
- [ ] Directory created at `.planning/quick/YYMMDD-xxx-slug/`
- [ ] (--discuss) Gray areas identified and presented, decisions captured in `${quick_id}-CONTEXT.md`
- [ ] (--research) Research agent spawned, `${quick_id}-RESEARCH.md` created
- [ ] `${quick_id}-PLAN.md` created by planner (honors CONTEXT.md decisions when --discuss, uses RESEARCH.md findings when --research)
- [ ] (--validate) Plan checker validates plan, revision loop capped at 2
- [ ] `${quick_id}-SUMMARY.md` created by executor
- [ ] (--validate) `${quick_id}-VERIFICATION.md` created by verifier
- [ ] STATE.md updated with quick task row (Status column when --validate)
- [ ] Artifacts committed
</success_criteria>
