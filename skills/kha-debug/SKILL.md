---
name: kha-debug
description: "Systematic debugging with persistent state across context resets. Default to diagnose-only investigation; use --fix --hypothesis-id <id> for a single atomic fix attempt or --interactive to review hypotheses one at a time."
argument-hint: "[issue description] [--fix --hypothesis-id <id>] [--interactive]"
allowed-tools:
  - Read
  - Bash
  - Task
  - AskUserQuestion
category: remediate
mutates: yes
long-running: yes
---
<objective>
Debug issues using scientific method with subagent isolation.

**Orchestrator role:** Gather symptoms, spawn kha-debugger agent, handle checkpoints, and keep each diagnosis or fix attempt isolated.

**Why subagent:** Investigation burns context fast (reading files, forming hypotheses, testing). Fresh 200k context per investigation. Main context stays lean for user interaction.
</objective>

## Modes

### Default: diagnose-only (no mutation)
- Reads logs, traces, recent commits, runs read-only tools.
- Output: `.planning/debug/<session>/HYPOTHESIS.md` with prioritized
  hypotheses and the evidence for each.
- Side effects: NONE on user code. NONE on .planning state beyond the
  HYPOTHESIS.md write.

### Opt-in: --fix mode
- After diagnose-only run, user reviews HYPOTHESIS.md and explicitly
  invokes with `--fix --hypothesis-id <id>` to attempt the chosen fix.
- Single-hypothesis fix per invocation (no batch).
- Atomic commit per fix attempt; revertable.

### Opt-in: --interactive mode
- Walk through hypotheses one at a time, ask user to accept/reject each.
- Same single-fix-per-acceptance contract as --fix.

## Why default-diagnose-only

- Bug analysis benefits from human review before code changes
- Premature mutation may mask the actual root cause
- Atomic per-fix invocation gives clean git history for each attempt

## Stability

- `--fix` mode follows the standard atomic-commit-per-mutation contract and is rollback-friendly.

<available_agent_types>
Valid GSD subagent types (use exact names - do not fall back to 'general-purpose'):
- kha-debugger - Diagnoses issues and can apply a single hypothesis-scoped fix when explicitly instructed
</available_agent_types>

<context>
User's issue: $ARGUMENTS

Parse flags from $ARGUMENTS:
- Default to `mode=diagnose`.
- If `--fix` is present, require `--hypothesis-id <id>`, set `mode=fix`, and remove both from the issue description.
- If `--interactive` is present, set `mode=interactive` and remove the flag from the issue description.
- Reject `--fix` combined with `--interactive`.
- Reject `--hypothesis-id` unless `--fix` is present.

Check for active sessions:
```bash
ls .planning/debug/*/HYPOTHESIS.md 2>/dev/null | head -5
```
</context>

<process>

## 0. Initialize Context

```bash
INIT=$(node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" state load)
if [[ "$INIT" == @file:* ]]; then INIT=$(cat "${INIT#@file:}"); fi
```

Extract `commit_docs` from init JSON. Resolve debugger model:
```bash
debugger_model=$(node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" resolve-model kha-debugger --raw)
```

## 1. Check Active Sessions

If active sessions exist AND no issue description AND `mode=diagnose`:
- List sessions with status, top hypotheses, and next action
- User picks number to resume OR describes new issue

If `mode=fix` or `mode=interactive`:
- Resolve the target session from the issue description if supplied; otherwise use the most recent unresolved session and ask the user to confirm if multiple candidates exist
- Require `.planning/debug/{session}/HYPOTHESIS.md`
- Refuse to continue if no hypothesis report exists for the selected session

If issue description is provided OR user describes a new issue:
- Continue to symptom gathering for diagnose mode
- Continue to hypothesis review for fix or interactive mode

## 2. Gather Symptoms (diagnose mode only)

Use AskUserQuestion for each:

1. **Expected behavior** - What should happen?
2. **Actual behavior** - What happens instead?
3. **Error messages** - Any errors? (paste or describe)
4. **Timeline** - When did this start? Ever worked?
5. **Reproduction** - How do you trigger it?

After all gathered, confirm ready to investigate.

## 3. Spawn kha-debugger Agent

### Diagnose-only mode

Fill prompt and spawn:

```markdown
<objective>
Investigate issue: {session}

**Summary:** {trigger}
</objective>

<symptoms>
expected: {expected}
actual: {actual}
errors: {errors}
reproduction: {reproduction}
timeline: {timeline}
</symptoms>

<mode>
goal: find_root_causes_only
mutation: forbidden
</mode>

<debug_dir>
Create: .planning/debug/{session}/
Write: .planning/debug/{session}/HYPOTHESIS.md
</debug_dir>
```

```
Task(
  prompt=filled_prompt,
  subagent_type="kha-debugger",
  model="{debugger_model}",
  description="Diagnose {session}"
)
```

### Fix mode

Fill prompt and spawn:

```markdown
<objective>
Attempt a fix for debug session {session}.

**Chosen hypothesis:** {hypothesis_id}
</objective>

<prior_state>
<files_to_read>
- .planning/debug/{session}/HYPOTHESIS.md
</files_to_read>
</prior_state>

<mode>
goal: fix_single_hypothesis
hypothesis_id: {hypothesis_id}
mutation: allowed
commit_contract: atomic_one_commit
</mode>
```

```
Task(
  prompt=filled_prompt,
  subagent_type="kha-debugger",
  model="{debugger_model}",
  description="Fix {session} hypothesis {hypothesis_id}"
)
```

## 4. Handle Agent Return

**If `mode=diagnose` and `## ROOT CAUSE CANDIDATES`:**
- Display the prioritized hypotheses, evidence, confidence level, and the path to `.planning/debug/{session}/HYPOTHESIS.md`
- Stop after the diagnosis handoff
- Next actions are:
  - Re-run with `--fix --hypothesis-id <id>` to attempt one chosen fix
  - Re-run with `--interactive` to review hypotheses one at a time
  - Apply a manual fix outside this skill

**If `mode=fix` and `## DEBUG FIX COMPLETE`:**
- Display the chosen hypothesis, fix summary, verification result, commit id, and rollback note
- Mark the session as updated with the result of that single fix attempt

**If `mode=interactive`:**
- Read `.planning/debug/{session}/HYPOTHESIS.md`
- Present hypotheses in priority order and ask the user to accept or reject each one
- On acceptance, spawn the same single-hypothesis fix flow used by `--fix`
- Stop after one accepted hypothesis is attempted; do not batch multiple fixes in one invocation

**If `## CHECKPOINT REACHED` during fix mode:**
- Present checkpoint details to the user
- Get user response
- Continue only the same selected hypothesis; do not switch hypotheses mid-run
- Spawn a continuation agent if needed (see step 5)

**If `## INVESTIGATION INCONCLUSIVE`:**
- Show what was checked and eliminated
- Return the missing artifacts or evidence needed for the next diagnose-only pass

## 5. Spawn Continuation Agent (Fix Mode Checkpoints Only)

When a fix attempt hits a checkpoint and the user responds, spawn a fresh continuation agent:

```markdown
<objective>
Continue fix attempt for debug session {session}.
</objective>

<prior_state>
<files_to_read>
- .planning/debug/{session}/HYPOTHESIS.md
</files_to_read>
</prior_state>

<checkpoint_response>
**Type:** {checkpoint_type}
**Response:** {user_response}
</checkpoint_response>

<mode>
goal: fix_single_hypothesis
hypothesis_id: {hypothesis_id}
mutation: allowed
commit_contract: atomic_one_commit
</mode>
```

```
Task(
  prompt=continuation_prompt,
  subagent_type="kha-debugger",
  model="{debugger_model}",
  description="Continue fix {session} hypothesis {hypothesis_id}"
)
```

</process>

<success_criteria>
- [ ] Active sessions checked
- [ ] Symptoms gathered for new diagnose runs
- [ ] `.planning/debug/{session}/HYPOTHESIS.md` produced before any mutation
- [ ] `--fix` requires explicit `--hypothesis-id`
- [ ] Exactly one hypothesis is attempted per fix invocation
</success_criteria>

## Output

- default mode writes `.planning/debug/{session}/HYPOTHESIS.md` with prioritized hypotheses, evidence, confidence, and suggested next actions; no code mutation occurs
- `--fix` mode returns the selected hypothesis id, atomic commit id, verification notes, and rollback guidance for that single attempt
- `--interactive` returns the reviewed hypotheses plus the result of at most one accepted fix attempt

## Failure behavior

- empty symptom input asks once and then aborts with `aborted_no_symptom`
- `--fix` without `--hypothesis-id` aborts with `missing_hypothesis_id`
- `--fix` or `--interactive` without an existing hypothesis report aborts with `missing_hypothesis_report`
- inconclusive investigation returns `needs_data` or `investigation_inconclusive` with concrete artifacts to gather
- fix-mode failure stops at the current checkpoint and preserves the hypothesis report and rollback path

## Gate summary

- diagnose and fix modes are hard-separated
- default mode never changes code
- entering mutation requires explicit `--fix --hypothesis-id <id>` or one accepted hypothesis in `--interactive`
- active-session detection precedes any new debug session
- no same-invocation "diagnose then auto-fix" path is allowed

## Retry / Resume

- resume diagnosis from `.planning/debug/{session}/HYPOTHESIS.md`
- rerun `--fix` only for the chosen hypothesis id and only as a single atomic attempt
- if a fix attempt is interrupted, resume that same hypothesis or roll back the single commit before retrying
