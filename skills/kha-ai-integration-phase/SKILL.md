---
name: kha-ai-integration-phase
description: "Spec-driven AI/LLM integration phase — produces a governed AI-SPEC.md design contract (domain + framework + failure-mode taxonomy + eval-coverage manifest) upstream of /kha-plan-phase. Eval is wired to the harness's own E1 debate + Tier-1 validator, NOT a parallel eval-judge."
keywords: ai, llm, ai-integration, ai-spec, eval, eval-coverage, failure-mode, framework-selection, spec-driven, gsd
argument-hint: "[phase] [--spec-path <file>] [--skip-debate]"
agent: kha-ai-researcher
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
  - Grep
  - Task
  - AskUserQuestion
  - WebFetch
  - mcp__context7__*
category: plan
mutates: yes
long-running: yes
---

> **STAGING NOTE (kha AI-building track P1).** This skill is a STAGED CANDIDATE in
> `~/.claude/skill-candidates/`. It is NOT active. Promotion to live
> `~/.claude/skills/` is gated by the `enable-skill` mutation token (writing a
> SKILL.md into `~/.claude/skills/` is itself activation, per skill_match.py glob).
> Design lock: /harness-debate `debate-1780835868-980eb5` (converged gen-2, approved,
> ontology sha1 98c3bc8760e4b66686745dd7201190e6c5d03464).

<objective>
Run the **AI-integration pre-plan** for a phase whose core is an AI/LLM feature, and emit a single governed design contract `AI-SPEC.md` that `/kha-plan-phase` then consumes like `CONTEXT.md`. This absorbs gsd-core's AI-building methodology (domain + framework research, failure-mode taxonomy, eval coverage) while keeping ALL evaluation inside the harness's own governance:

- **eval STRATEGY** (the failure-mode taxonomy + framework selection) → decided at the **§4-6 E1 debate gate** (`/harness-debate`), the same Designer-evaluator channel the harness already uses.
- **eval COVERAGE** (does each declared failure mode have a corresponding test/fixture/rubric artifact) → checked by the deterministic Tier-1 validator `ai_spec_eval_coverage` (advisory).
- **product-level eval EXECUTION** (running the golden set, scoring the live model) → **out of scope** = the user's CI. Named explicitly in AI-SPEC §Descoped-Capabilities, never silently dropped.

**No eval-JUDGE agent is spawned.** The harness's `harness-evaluator` (E2) and `harness-architect` (E1) remain the only judges; this skill adds only generator-side researchers + a mechanical validator. (governance invariant `kha_ai_track_eval_is_governed_not_imported`.)
</objective>

<orchestration>
Resolve the phase + AI-SPEC path (default `.planning/phases/<XX>/AI-SPEC.md`). Then:

**Wave A — research (parallel, independent).** Spawn together:
- `kha-ai-researcher` → writes §2 Integration Architecture + §5 Eval Strategy draft + candidate failure-mode ids.
- `kha-domain-researcher` → writes §1 Domain Context + domain-driven candidate failure-mode ids + per-category error-cost asymmetry.
Pass each the phase CONTEXT.md (if any), CLAUDE.md, tech-stack.yaml in a `<files_to_read>` block.

**Wave B — framework options (after Wave A).** Spawn `kha-framework-selector` → writes §3 Framework Options as a NEUTRAL options+tradeoffs matrix (alphabetical order, comparable depth, NO selection). It consumes §1 + §2.

**Wave C — assemble draft.** Merge the Wave-A/B outputs into AI-SPEC.md §1-§5. Deduplicate the candidate failure-mode ids into a single §4 Failure-Mode Taxonomy DRAFT (slug ids, `^[a-z0-9][a-z0-9-]*$`). Carry the recommended `golden_set_size` / `acceptable_fail_rate` from §5.

**Wave D — E1 debate gate (the governed decision).** Unless `--skip-debate`, run `/harness-debate` on exactly two questions (and ONLY these — numeric thresholds are NOT debated, per the converged design):
  1. **Failure-mode taxonomy**: which §4 modes are in scope / correct / complete for this phase.
  2. **Framework selection**: choose among the §3 options.
Record the debate session id. Write the locked taxonomy into §4 and the chosen framework into §7 Framework Selection (with the debate sid). If `--skip-debate`, mark §4/§7 `STATUS: draft (debate skipped)` so downstream knows the lock is absent.

**Wave E — finalize the contract.**
- Write §6 Eval Coverage Manifest: for every LOCKED §4 failure-mode id, add a manifest entry mapping it → an `artifact_path` (a test / fixture / judge-rubric the user's repo will contain). Use the EXACT block grammar below.
- Write §Descoped-Capabilities (verbatim boilerplate below — names the lost gsd eval-auditor semantic-adequacy verdict).
- Run the coverage validator (advisory): `python -m validators.ai_spec_eval_coverage` from the project root. Surface its WARN lines; they do NOT block (advisory until `graduate-validator`).
- Set AI-SPEC `STATUS: locked` (or `draft` if `--skip-debate`).

**Downstream.** `/kha-plan-phase` reads AI-SPEC.md as an additional upstream input alongside CONTEXT.md/RESEARCH.md.
</orchestration>

<ai_spec_template>
The canonical `AI-SPEC.md` skeleton (agents own the sections noted; the orchestrator assembles):

```markdown
# AI-SPEC — <phase>
STATUS: draft | locked
DEBATE: <debate-sid or "none (skipped)">

## §1 Domain Context            (owner: kha-domain-researcher)
## §2 Integration Architecture  (owner: kha-ai-researcher)
## §3 Framework Options         (owner: kha-framework-selector — neutral, no selection)
## §4 Failure-Mode Taxonomy     (DRAFT from researchers → LOCKED by §4-6 debate)
## §5 Eval Strategy             (golden-set design + rubric approach; discretion scalars)
## §6 Eval Coverage Manifest    (machine-checkable; one entry per LOCKED §4 id)
## §7 Framework Selection        (DECIDED by §4-6 debate; records chosen + debate sid)
## §Descoped-Capabilities        (boilerplate — names the lost capability)
```

**§6 Eval Coverage Manifest — EXACT grammar** (the `ai_spec_eval_coverage` validator parses this byte-for-byte; do not rename keys or delimiters):

    <!-- eval-coverage-manifest -->
    ```yaml
    golden_set_size: 12            # int >= 1 (from §5)
    acceptable_fail_rate: 0.05     # float in [0.0, 1.0] (from §5)
    failure_modes:
      - id: tool-call-malformed    # slug ^[a-z0-9][a-z0-9-]*$, unique
        artifact_path: tests/evals/tool_call_malformed.py
      - id: confident-wrong-pricing
        artifact_path: tests/evals/confident_wrong_pricing.py
    ```
    <!-- /eval-coverage-manifest -->

Every `id` MUST be a locked §4 failure-mode. Every `artifact_path` is repo-relative and must point at a file that exists and is non-empty (the validator checks referential integrity only — see §Descoped-Capabilities).

**§Descoped-Capabilities — boilerplate (write verbatim):**

    ## §Descoped-Capabilities
    - **LOST: gsd eval-auditor per-dimension semantic-adequacy verdict** (COVERED /
      PARTIAL / MISSING per failure mode). This harness does NOT reproduce it.
      - Replacement: the failure-mode taxonomy is judged ONCE at the §4-6 E1 debate
        gate; ongoing per-output adequacy of the user's product LLM is **user-CI scope**.
      - The `ai_spec_eval_coverage` validator proves only that a NON-EMPTY artifact
        exists per failure mode (referential integrity). A 1-byte stub passes — so
        "manifest validates" must NEVER be read as "coverage is adequate".
</ai_spec_template>

<governance>
- This skill spawns only generator-side researchers + the existing /harness-debate engine. It introduces NO new judge agent (provider separation, paradox guard, mutation gates intact).
- Numeric discretion scalars (`golden_set_size`, `acceptable_fail_rate`) are range-checked by the validator, NEVER routed to the debate (avoids debate overhead — CLAUDE.md principle 1).
- The coverage validator is advisory; its advisory→blocking graduation is `graduate-validator`-token-gated and requires re-quantifying false-MISSING/COVERED blast radius first.
</governance>
