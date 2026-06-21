---
name: kha-scan-codebase
description: "Rapid codebase assessment — lightweight alternative to /kha-map-codebase"
allowed-tools:
  - Read
  - Write
  - Bash
  - Grep
  - Glob
  - Agent
  - AskUserQuestion
category: meta
mutates: no
long-running: yes
---
<objective>
Run a focused codebase scan for a single area, producing targeted documents in `.planning/codebase/`.
Accepts an optional `--focus` flag: `tech`, `arch`, `quality`, `concerns`, or `tech+arch` (default).

Lightweight alternative to `/kha-map-codebase` — spawns one mapper agent instead of four parallel ones.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/scan.md
</execution_context>

<process>
Execute the scan workflow from @$HOME/.claude/get-shit-done/workflows/scan.md end-to-end.
</process>

## Output


- artifacts: targeted `.planning/codebase/` docs for the chosen focus: `tech` -> `STACK.md`,`INTEGRATIONS.md`; `arch` -> `ARCHITECTURE.md`,`STRUCTURE.md`; `quality` -> `CONVENTIONS.md`,`TESTING.md`; `concerns` -> `CONCERNS.md`; `tech+arch` -> the four tech+arch docs.
- status: `scan_completed` | `scan_invalid_focus` | `scan_cancelled_existing_docs`.

## Failure behavior


- preflight: reject unknown focus before any write; if target docs already exist and the user refuses overwrite, abort with no mutation.
- execution: if the single mapper fails, preserve any pre-existing docs and report whether any target docs were partially replaced.
- partial: if the mapper wrote only some target docs, keep them and list the missing docs explicitly.

## Gate summary


- preflight: focus resolved from args, output directory exists or can be created, and overwrite consent is obtained for any existing target docs.
- success: exactly the focus-mapped doc set was written and summarized with line counts.
- boundary: own short shallow focused scans only; `kha-map-codebase` owns the full long-form 7-doc narrative pass; `kha-intel-index` owns incremental intel storage, not targeted narrative docs.

## Retry / Resume


- checkpoint: selected focus area and its target doc list are the resume state; any already-written target docs stay on disk.
- resume: rerun `kha-scan-codebase --focus <same-focus>` after addressing the failure; idempotent after overwrite confirmation.
