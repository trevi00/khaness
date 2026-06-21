---
name: kha-sync-docs
description: "Generate or update project documentation verified against the codebase"
argument-hint: "[--force] [--verify-only]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Task
  - AskUserQuestion
category: meta
mutates: yes
long-running: no
---
<objective>
Generate and update up to 9 documentation files for the current project. Each doc type is written by a kha-doc-writer subagent that explores the codebase directly — no hallucinated paths, phantom endpoints, or stale signatures.

Flag handling rule:
- The optional flags documented below are available behaviors, not implied active behaviors
- A flag is active only when its literal token appears in `$ARGUMENTS`
- If a documented flag is absent from `$ARGUMENTS`, treat it as inactive
- `--force`: skip preservation prompts, regenerate all docs regardless of existing content or GSD markers
- `--verify-only`: check existing docs for accuracy against codebase, no generation (full verification requires Phase 4 verifier)
- If `--force` and `--verify-only` both appear in `$ARGUMENTS`, `--force` takes precedence
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/docs-update.md
</execution_context>

<context>
Arguments: $ARGUMENTS

**Available optional flags (documentation only — not automatically active):**
- `--force` — Regenerate all docs. Overwrites hand-written and GSD docs alike. No preservation prompts.
- `--verify-only` — Check existing docs for accuracy against the codebase. No files are written. Reports VERIFY marker count. Full codebase fact-checking requires the kha-doc-verifier agent (Phase 4).

**Active flags must be derived from `$ARGUMENTS`:**
- `--force` is active only if the literal `--force` token is present in `$ARGUMENTS`
- `--verify-only` is active only if the literal `--verify-only` token is present in `$ARGUMENTS`
- If neither token appears, run the standard full-phase generation flow
- Do not infer that a flag is active just because it is documented in this prompt
</context>

<process>
Execute the docs-update workflow from @$HOME/.claude/get-shit-done/workflows/docs-update.md end-to-end.
Preserve all workflow gates (preservation_check, flag handling, wave execution, monorepo dispatch, commit, reporting).
</process>

## Output


- artifacts: resolved canonical project docs (`README`, `ARCHITECTURE`, `GETTING-STARTED`, `DEVELOPMENT`, `TESTING`, `CONFIGURATION`, conditional `API`, `CONTRIBUTING`, `DEPLOYMENT`), optional per-package READMEs, `.planning/tmp/docs-work-manifest.json`, `.planning/tmp/verify-*.json`, and final verification report; `--verify-only` emits audit output without generation.
- status: `docs_generated_and_verified` | `verify_only_report_emitted` | `docs_generated_with_manual_followup` | `docs_aborted_by_user`.

## Failure behavior


- preflight: if queue assembly is aborted, preservation choices reject generation, or required project context cannot be initialized, stop before writes.
- execution: writer/verifier failures must be recorded in the manifest; fix loop stops after 2 iterations or any regression; secret-scan alert blocks commit until the user chooses whether to proceed.
- partial: keep successfully generated docs and per-doc verification results even when some docs fail or remain manually actionable.

## Gate summary


- preflight: docs-init JSON loaded, project type classified, queue assembled, mode resolution table shown, and preservation decisions applied before any write.
- success: dry-run included queue/mode/path preview; snapshot persisted to `.planning/tmp/docs-work-manifest.json` and verification JSONs; explicit `Proceed` confirmation occurred before generation; post-generation verify/fix/secret gates completed before any commit.
- boundary: own project documentation generation and fact-checking; it does not update the GSD toolchain, milestone state machine, or model/profile configuration.
