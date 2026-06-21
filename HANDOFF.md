# HANDOFF.md — session continuity & phase tree

> A per-project work-state document. The harness reads it at session start ("read `HANDOFF.md` and continue") and renders the phase tree from the yaml block below via `python -m cli.handoff_render`.
>
> This is a **template** — replace the example block with your project's real phase tree. Your live `HANDOFF.md` is git-ignored by default (it's working state, not shipped code).

## Phase Tree Convention

Long-running work is decomposed into a tree of phases. Each phase is either:
- a **leaf** with a flat `steps` map (`step_name: status-or-description`), or
- a **parent** with a `sub_phases` list of child phases.

**Promotion rule:** when a phase reaches ≥5 steps and at least one step is itself nested (≥3 sub-steps), promote it to a child phase. **Status propagation:** a parent is `in_progress` while any child is; `done` only when all children are. The *current* node is the deepest `in_progress` phase.

## Current Phase Block

```yaml
name: example-milestone
status: in_progress
sub_phases:
  - name: foundation
    status: done
    steps:
      step_1_scaffold: done
      step_2_ci: done
  - name: core-feature
    status: in_progress
    steps:
      step_1_design: done
      step_2_implement: in_progress
      step_3_tests: todo
  - name: hardening
    status: todo
    steps:
      step_1_edge_cases: todo
```

## Known platform residuals

Acknowledged here rather than silently claimed as closed (per the "quantify the residual" principle):

- **Subagent isolation contract.** Spawned subagents do not inherit the parent session's full context or permissions. The harness compensates by surfacing real field names, signatures, and source paths *into* delegation prompts (see "Subagent delegation rules" in `CLAUDE.md`) rather than relying on inheritance — but this is a platform-level residual, not an eliminated one.

## Notes

- Keep one `Current Phase Block` with a single top-level yaml document.
- `cli/handoff_render.py --check` verifies the rendered tree matches any anchored ASCII tree; `--in-place` updates it.
