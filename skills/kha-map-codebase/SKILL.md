---
name: kha-map-codebase
description: "Analyze codebase with parallel mapper agents to produce .planning/codebase/ documents"
argument-hint: "[optional: specific area to map, e.g., 'api' or 'auth']"
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
  - Write
  - Task
category: meta
mutates: no
long-running: yes
---
<objective>
Analyze existing codebase using parallel kha-codebase-mapper agents to produce structured codebase documents.

Each mapper agent explores a focus area and **writes documents directly** to `.planning/codebase/`. The orchestrator only receives confirmations, keeping context usage minimal.

Output: .planning/codebase/ folder with 7 structured documents about the codebase state.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/map-codebase.md
</execution_context>

<context>
Focus area: $ARGUMENTS (optional - if provided, tells agents to focus on specific subsystem)

**Load project state if exists:**
Check for .planning/STATE.md - loads context if project already initialized

**This command can run:**
- Before /kha-new-project (brownfield codebases) - creates codebase map first
- After /kha-new-project (greenfield codebases) - updates codebase map as code evolves
- Anytime to refresh codebase understanding
</context>

<when_to_use>
**Use map-codebase for:**
- Brownfield projects before initialization (understand existing code first)
- Refreshing codebase map after significant changes
- Onboarding to an unfamiliar codebase
- Before major refactoring (understand current state)
- When STATE.md references outdated codebase info

**Skip map-codebase for:**
- Greenfield projects with no code yet (nothing to map)
- Trivial codebases (<5 files)
</when_to_use>

<process>
1. Check if .planning/codebase/ already exists (offer to refresh or skip)
2. Create .planning/codebase/ directory structure
3. Spawn 4 parallel kha-codebase-mapper agents:
   - Agent 1: tech focus → writes STACK.md, INTEGRATIONS.md
   - Agent 2: arch focus → writes ARCHITECTURE.md, STRUCTURE.md
   - Agent 3: quality focus → writes CONVENTIONS.md, TESTING.md
   - Agent 4: concerns focus → writes CONCERNS.md
4. Wait for agents to complete, collect confirmations (NOT document contents)
5. Verify all 7 documents exist with line counts
6. Commit codebase map
7. Offer next steps (typically: /kha-new-project or /kha-plan-phase)
</process>

<success_criteria>
- [ ] .planning/codebase/ directory created
- [ ] All 7 codebase documents written by mapper agents
- [ ] Documents follow template structure
- [ ] Parallel agents completed without errors
- [ ] User knows next steps
</success_criteria>

## Output


- artifacts: `.planning/codebase/STACK.md`, `INTEGRATIONS.md`, `ARCHITECTURE.md`, `STRUCTURE.md`, `CONVENTIONS.md`, `TESTING.md`, `CONCERNS.md`; line-count summary; commit of generated codebase docs after secret scan.
- status: `codebase_map_created` | `codebase_map_updated` | `codebase_map_skipped` | `codebase_map_created_with_manual_review`.

## Failure behavior


- preflight: if an existing map is present and the user chooses `Skip`, abort with no write.
- execution: if one or more mapper passes fail, keep completed docs, report missing/empty docs, and block commit if secret scan finds potential leaks.
- partial: do not discard successfully written docs when one mapper fails; report the surviving set and the missing set separately.

## Gate summary


- preflight: project root readable; existing `.planning/codebase/` state resolved; runtime capability decides parallel agents vs sequential inline mapping.
- success: all 7 docs exist, each is non-empty, secret scan passed or was explicitly overridden, and the completion summary names the produced files.
- boundary: own the full deep narrative codebase map; `kha-scan-codebase` handles a lighter focused subset; `kha-intel-index` owns incremental machine-readable intel, not these 7 narrative docs.

## Retry / Resume


- checkpoint: `.planning/codebase/` plus the current line-count summary is the resume state; existing-map refresh/update choice determines whether prior docs are preserved or replaced.
- resume: rerun `kha-map-codebase` with the same refresh/update intent after fixing the failed mapper or secret issue; idempotent at the document-set level.
