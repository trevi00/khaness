# Architecture

A map of how the harness is put together. For the *why*, see the README's [What it is](README.md#what-it-is).

## Layers

`scripts/` is a strict one-directional dependency stack — each layer may import from layers above it, never below:

```
lib/         pure-ish utilities. No knowledge of hooks or the engine.
  ↑
validators/  mechanical pass/fail gates. Import lib/. Registered in the VALIDATOR_NAMES tuple (validators/__init__.py).
  ↑
handlers/    hook entrypoints. Import lib/ (and may run validators). Fail-open.
  ↑
engine/      the debate engine + orchestrator. The top of the stack.
```

`cli/` holds operator-facing entrypoints; `tests/` holds the two regression runners.

A layer-adjacency validator (`validators/commit_layer_adjacency.py`) enforces this direction in CI.

## The debate engine (`engine/` + `agents/harness-*`)

Design decisions run through three subagents:

- **Planner** proposes a single concrete design as structured JSON (decisions, rationale, alternatives, research citations).
- **Critic** attacks it on three axes — assumptions, failure modes, over-simplification — and assesses citation integrity.
- **Architect** renders a verdict (approved / rejected / conditional) plus an ontology snapshot.

**Convergence is deterministic**, not a judgment call: two consecutive `approved` verdicts with an identical ontology-snapshot hash (a generation-1 `approved` fast-paths). Hard cap at 4 generations.

**Event sourcing**: every step appends to `state/debates/<sid>/events.jsonl`. State (last generation, last verdict, convergence) is *reconstructed by replaying* the log — there is no mutable session DB, so a debate is resumable and auditable. The replay path distinguishes a benign torn final line from mid-log corruption (which it surfaces via telemetry rather than silently dropping).

## Evaluation: three orthogonal tiers

1. **Mechanical** — `validators/*`, boolean pass/fail, run as the `run_all` regression. Catches drift automatically.
2. **Semantic** — a single LLM evaluator scores 5 axes (cohesion, coupling, extensibility, stability, usability) plus a strict completeness boolean. A "paradox guard" prevents an agent from grading its own work as done.
3. **Consensus** (opt-in) — multiple models vote; a quorum is required to pass.

## Hooks (`scripts/handlers/`)

Hook entrypoints fire on Claude Code lifecycle events (UserPromptSubmit, PreToolUse, PostToolUse, Stop, SessionStart). They are **fail-open**: any exception exits cleanly so a hook bug can never wedge the user's tools. The deny mechanism is an explicit JSON decision (`{"decision":"block"}`) on a clean exit — a *crash* is non-blocking, by design.

Key guards: destructive-command denial, sensitive-file protection (credentials + the runtime-policy `settings.json`), and branch/PR conventions.

## The mutation-gate (and its honest threat model)

Certain changes are classified "never automatic" — editing runtime policy (`settings.json`, hook registration), adding mutation tokens, changing core invariants. The gate **surfaces and blocks accidental** attempts (e.g. a direct `Write` to `.claude/settings.json` is denied at the PreToolUse hook).

It is **defense-in-depth, not a boundary.** An agent with shell access can route around file-deny rules (`echo > settings.json`) and supply its own tokens. The enforcer that reliably fires is the `guard.py` PreToolUse hook; the real boundary is **operator review of the committed diff.** The harness documents this rather than pretending the gate is airtight.

## Skill tree (`skills/`) + memory (L0–L4)

- `skills/_common/` is always active; per-stack subtrees (`java/`, `kotlin/`, `typescript/`, `flutter/`, …) activate via a project's `.claude/tech-stack.yaml`.
- Memory is layered: **L0** meta-rules (invariants) → **L1** insight index → **L2** global facts → **L3** task skills → **L4** session archive. L3–L4 are per-user and git-ignored.

## Extending (Open/Closed)

| To add a… | Do this | Touch existing files? |
|---|---|---|
| AI provider | `lib/providers/<name>.py` + 1 registry line | No |
| Worker/multiplexer | `lib/workers/<name>.py` + 1 registry line | No |
| Validator | `validators/<name>.py` + one line in the `VALIDATOR_NAMES` tuple (`validators/__init__.py`) | No |

If adding one capability forces edits across many files, the seam is wrong — that's the signal to refactor toward a registry.
