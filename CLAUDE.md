# CLAUDE.md — Harness operating contract

> The harness's top-level operating rules, loaded into every session's system prompt. Keep it high-signal and short. Agents and commands cite this file by section ("CLAUDE.md core principle 1", "CLAUDE.md §Mutation").

## Core principles (apply to all work)

1. **DGE — Designer · Generator · Evaluator.** Never skip a stage.
   - **Designer** ("are we building the right thing?"): for architectural / refactoring / structural decisions, run `/harness-debate <topic>` — a 3-agent engine (Planner proposes → Critic attacks on assumption/failure/over-simplification → Architect renders an approved/rejected/conditional verdict). Convergence is deterministic: two consecutive `approved` verdicts with an identical ontology-snapshot hash (a generation-1 `approved` fast-paths; hard cap 4 generations). For simple, settled work, design directly — don't pay the debate overhead.
   - **Generator** ("did we build it as designed?"): implement the agreed design, nothing more.
   - **Evaluator** ("does it actually work?"): a 3-tier orthogonal stack — Tier 1 mechanical validators (`validators/*`, boolean pass/fail), Tier 2 a single semantic LLM evaluator (5 axes — cohesion, coupling, extensibility, stability, usability — plus a strict completeness boolean), Tier 3 optional multi-model consensus. A paradox guard prevents an agent from grading its own work as done. Do not advance to the next stage before verification (tests / E2E) passes.
2. **Self-improvement loop.** Problem found → fixed → the lesson is encoded **permanently** into a skill or hook so it cannot recur.
3. **2-Strike Rule.** The same class of problem twice → codify it as a skill "Gotcha" or a hook rule.
4. **Quantify the residual.** When claiming completion, also state known-defect count, regression coverage (X/Y), and that residual risk is non-zero. Absolute claims ("perfect", "fully secure", "true closure") are forbidden — there are always known defects N and residual risk.

## Design principles

- **Cohesion / coupling / Open-Closed.** A new provider/worker/engine/validator is a *new file* + *one registry line*. Editing existing files to add one thing is the smell that the seam is wrong.
- **Absorb before adding.** Check whether an existing module can absorb the change before creating a new one.
- **Event sourcing.** Debate / orchestrator state is append-only `state/**/events.jsonl`, replayed to reconstruct state — no mutable session DB.

## Skill tree + tech-stack isolation

- Skills live under `skills/` as a per-stack tree: `_common/` (always active) + `java/`, `kotlin/`, `typescript/`, `flutter/`, … and `_pipeline/` (dynamic pipeline stages).
- **At the start of a new project, create `.claude/tech-stack.yaml` first** → only `_common/` + the declared stack's skills activate. Without it, all skills are candidates (lower precision) and a hook warns once per day.

## Harness script architecture

`scripts/` is a one-directional 4-layer dependency stack: `lib/` (utilities) → `validators/` (mechanical gates + registry) → `handlers/` (hook entrypoints) → `engine/` (debate engine + orchestrator). `cli/` holds operator entrypoints; `tests/` holds `run_all.py` (validator regression) + `run_units.py` (internals regression).

**Extension points (OCP):** new AI provider → `lib/providers/<name>.py` + 1 registry line. New multiplexer → `lib/workers/<name>.py` + 1 line. New validator → `validators/<name>.py` + 1 manifest line. No existing file is edited.

## Subagent delegation rules

1. **Quote real field names / signatures / import paths** in the prompt — subagents can't see the parent context. Don't make them guess.
2. **Generate mutually-dependent declarations + implementations in the same subagent** (Controller↔Service, DTO↔parser, Widget↔state model) — splitting them produces name/type mismatches.
3. **Pass the source schema with any mapping delegation** — DDL for DB mapping, the API contract for HTTP, the message schema for socket handlers.
4. **Wave parallelism:** draw the dependency graph first; independent waves run concurrently, dependent waves sequentially.

## HANDOFF rules

- `HANDOFF.md` is created at the **project root** (never at the harness home). New session: "read `{project}/HANDOFF.md` and continue."
- **Phase Tree Convention:** long-running work is decomposed into a `sub_phases` tree in `HANDOFF.md`'s Current Phase Block (a step with ≥5 sub-steps and ≥3 children promotes to a child phase). `cli/handoff_render.py` renders the tree.

## Mutation classification (L0 — never automatic)

| Mutation | Auto OK | Token gate |
|---|---|---|
| skill candidate extraction | ✅ | — |
| skill activation | — | ✅ `enable-skill` |
| memory add / compaction | ✅ | — |
| user-preference application | — | ✅ `apply-user-preference` |
| cron job registration | ✅ | — |
| cron job execution | — | ✅ `enable-cron-job` |
| critic-policy change (disabling the Critic on a judgment-class agent) | — | ✅ `configure-critic-policy` |
| sub-skill → core promotion | — | ✅ `promote-to-core` |
| validator advisory→blocking graduation | — | ✅ `graduate-validator` |

**Never automatic:** changing runtime policy (`settings.json` permissions / hook registration), adding mutation tokens, changing core invariants. These require a source edit + rebuild, not a runtime command.

**⚠️ Honest threat model.** The mutation-gate is **defense-in-depth, not a boundary.** It surfaces and blocks an *accidental* honest agent's stray writes (e.g. a direct `Write` to `.claude/settings.json` is denied at the `guard.py` PreToolUse hook), but a shell-capable agent can route around file-deny rules (`echo > settings.json`) and supply its own tokens (`export …`). The enforcer that reliably fires under all permission modes is the `guard.py` PreToolUse hook; settings.json `deny[]` honored under bypass is unverified. **The real boundary is operator review of the committed diff.** Adding a guard deny-branch is itself a never-automatic change (it touches the enforcer) → operator-hand-applied via source diff only.

## Memory architecture (L0–L4)

| Layer | Mapping |
|---|---|
| L0 meta-rules / invariants | this `CLAUDE.md` + the harness guide (never-automatic gates) |
| L1 insight index | `memory/insight-index.jsonl` |
| L2 global facts | `memory/global-facts.jsonl` (promoter flag consumption is `enable-cron-job`-gated) |
| L3 task skills | `skills/` builtin + imported (candidates auto, activation gated) |
| L4 session archive | `projects/<sid>/memory/` (auto) |

L3–L4 are per-user and git-ignored.

## Environment notes

- The harness shells out to `git`; some hooks/validators assume it is present.
- Python 3.10+ is the hook interpreter. `PyYAML` is a hard dependency (`requirements.txt`).
- Cross-platform code paths are guarded by OS checks; primary development is on Windows, so Linux/macOS paths are less battle-tested.
