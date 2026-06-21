<div align="center">

# khaness

### Design it. Build it. Verify it.

**A self-improving operations layer for [Claude Code](https://claude.ai/code)** — it wraps the agent in a senior engineering process so non-trivial work is *designed before it's built* and *verified before it's called done*.

English · [한국어](README.ko.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg?style=for-the-badge&logo=python&logoColor=white)](requirements.txt)
[![CI](https://img.shields.io/badge/CI-run__all%20%2B%20run__units-brightgreen.svg?style=for-the-badge)](.github/workflows/ci.yml)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-orange.svg?style=for-the-badge)](CONTRIBUTING.md)
[![Status: experimental](https://img.shields.io/badge/status-v0.1%20experimental-lightgrey.svg?style=for-the-badge)](#status)

</div>

* * *

## What it is

Claude Code is already a capable agent. **khaness** adds the discipline of a senior engineering process on top of it — structure, gates, and memory — so that the agent designs before it builds and verifies before it claims done.

It is a *meta-layer*: you keep using Claude Code as normal, and khaness wraps each substantial task in a **DGE loop**:

- **Designer** — *"are we building the right thing?"* For architectural decisions, a 3-agent debate (Planner → Critic → Architect) converges on a design, deterministically.
- **Generator** — *"did we build it as designed?"* Implement the agreed design, nothing more.
- **Evaluator** — *"does it actually work?"* A 3-tier stack: mechanical validators → a semantic LLM evaluator → optional multi-model consensus. Verification gates the next step.

> *Claude Code is powerful. khaness makes it disciplined.*

* * *

## How it works

1. **You state a goal.** A prompt hook detects design-class work and surfaces the debate engine.
2. **Design converges.** `/harness-debate` spins up Planner / Critic / Architect subagents. The Critic attacks the proposal on assumption, failure, and over-simplification axes; the Architect renders a verdict. Convergence is deterministic — two consecutive approvals with an identical ontology-snapshot hash — and every step is appended to an event log so the decision is replayable.
3. **Generation proceeds** against the locked design, with lifecycle hooks enforcing guardrails (destructive-command denial, sensitive-file protection, branch/PR conventions).
4. **Evaluation gates done.** ~40 mechanical validators run as a regression suite; a semantic evaluator scores 5 axes plus a strict completeness boolean; a paradox guard stops an agent from grading its own work as finished.
5. **The harness improves itself.** A repeated failure becomes a permanent skill or hook rule (the 2-Strike Rule), so the same mistake can't recur.

* * *

## Quickstart

```bash
git clone https://github.com/trevi00/khaness ~/.claude
cd ~/.claude
bash install.sh
```

`install.sh` generates a portable `settings.json` from the template (interpolating your clone location into the hook paths), installs Python deps, and runs the regression suite to prove the install is sound. Then open a new Claude Code session in that directory.

A few commands to try:

```
/harness-debate <a design decision>     # 3-agent design convergence
/harness-autopilot                       # drive a task through the DGE phases
/harness-audit                           # 6-axis harness self-check
```

> **First thing in any project:** create `.claude/tech-stack.yaml` declaring your stack, so the skill tree filters to what's relevant.

* * *

## What's inside

| | |
|---|---|
| **42** subagents | Planner / Critic / Architect debate roles, evaluators, researchers, and project-workflow agents |
| **17** `harness-*` commands | debate, autopilot, audit, interview, team, ultrawork, … |
| **69** `kha-*` workflow skills | spec → plan → execute → verify project lifecycle |
| **~40** validators | mechanical pass/fail gates run as a regression suite |
| **254** skills | `_common/` (always-on) + per-stack trees (java, kotlin, typescript, flutter, …) |

The `scripts/` codebase is a one-directional 4-layer stack — `lib/` → `validators/` → `handlers/` → `engine/` — and is **Open/Closed by design**: a new provider, worker, or validator is a *new file + one registry line*, never an edit to existing code.

📖 **Documentation:** [ARCHITECTURE.md](ARCHITECTURE.md) (the full map) · [CONTRIBUTING.md](CONTRIBUTING.md) (get started) · [CLAUDE.md](CLAUDE.md) (the operating contract loaded each session)

* * *

## Status

**v0.1 / experimental.** It works and its regression suite is green (`run_all` + `run_units`, verified from a fresh clone), but it is opinionated, developed primarily on Windows (cross-platform paths are guarded but less battle-tested), and APIs may shift.

Runtime data — `state/`, `memory/`, `brain/`, `atlas/`, your live `HANDOFF.md` — is per-user and git-ignored; the repo ships templates and machinery, not session state.

## Honesty about guarantees

This harness was built by an engineer who distrusts absolute claims, and the design reflects it:

- **The mutation-gate is defense-in-depth, not a security boundary.** It surfaces and blocks *accidental* writes to runtime-policy files (a direct `Write` to `.claude/settings.json` is denied), but a shell-capable agent can bypass token gates. The real boundary is **operator review of committed diffs**.
- **Hooks fail open.** A crashing hook exits cleanly rather than blocking your tools — availability over enforcement.
- **Completeness is quantified, not asserted.** "Done" is reported with known-defect count and coverage; words like "perfect" are avoided on purpose.

If you find a claim stronger than the code that backs it, that's a bug — please [open an issue](https://github.com/trevi00/khaness/issues).

* * *

## License

[MIT](LICENSE).

<div align="center">

*Design it. Build it. Verify it.*

</div>
