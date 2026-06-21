---
description: 큰 작업을 독립 슬라이스로 쪼개 한꺼번에 실행하고 싶을 때. 의존성 그래프로 wave를 분리 → 각 wave 안의 일은 동시 발화. 검증 루프 없이 throughput 최우선. 결과 검증/재시도 필요하면 /harness-ralph, 다관점 검토는 /harness-team, 설계+구현+검증 전 자동화는 /harness-autopilot.
user-invocable: true
argument-hint: "<task with parallel work items>"
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent, TaskCreate, TaskUpdate
category: run
mutates: yes
long-running: yes
external-deps: none
---

You are orchestrating **harness-ultrawork** — parallel throughput, not persistence. For verify/fix loops use `/harness-ralph`. For full autonomy use `/harness-autopilot`.

## Inputs
- `task`: one-liner describing the goal. Internally decomposed into independent sub-items.

If `task` names only one atomic change, redirect to a direct executor call and stop.

## Protocol

1. **Intent grounding**: classify the task as one of: implement, investigate, evaluate, research. Do not code before this is explicit.

2. **Context gathering (parallel)**:
   - Direct tools for quick reads (Grep, Glob, Read).
   - `Agent(subagent_type=harness-explore, thoroughness="medium")` for broad unknowns.
   - Run all gathering calls in one tool-use block.
   - **Audit log (A2 wiring, commit 7aff8b7, 2026-05-10; E1 origin tag 2026-05-10)**: after each Agent returns, call `lib.subagent_invocation_log.record_invocation(ultrawork_sid, agent_name="harness-explore", tools=lib.agent_tool_audit.expected_tools("harness-explore"), generation=0, role="ultrawork-explore", extra={"thoroughness": "medium", "origin": lib.subagent_invocation_log.ORIGIN_DIRECTIVE})`. The PostToolUse hook records the same invocation as a safety net.

3. **Decompose + dependency matrix**:
   - List sub-items. For each: acceptance criteria + verification step.
   - Build a dependency matrix: which items are independent, which have prerequisites.
   - Split into **Waves**: W1 = independent, W2 = depends on W1, etc.
   - **Persist the plan (resume seam — closes "re-run produces a different graph / not
     resumable")**: mint `ultrawork_sid` and save the wave/slice decomposition:
     ```python
     from lib.ultrawork_plan import save_plan, pending_slices
     save_plan(ultrawork_sid, [["w1-slice-a","w1-slice-b"], ["w2-slice-c"]])
     ```
     On a RE-RUN of the same `--resume <sid>`: `pending_slices(sid)` returns only the
     not-done slices, so you re-decompose NOTHING — fire just the remaining work.

4. **Route by complexity** (per sub-item):
   - Use `lib.model_router.classify_complexity` to pick tier.
   - `haiku` for lookups/one-liners, `sonnet` for standard implementation, `opus` for complex analysis or >5-file refactor.

5. **Fire wave-by-wave**:
   - Within a wave: all Agent calls in a SINGLE tool-use block (true parallel).
   - Between waves: wait for prior wave to complete, then fire next.
   - Long operations (build, install, test suite): `run_in_background: true`.
   - **Mark each slice's outcome (for resume)**: after a slice completes, call
     `lib.ultrawork_plan.mark_slice(ultrawork_sid, "<slice_id>", "done"|"failed"|"skipped")`
     so a later `--resume` skips the done ones and re-runs only failed/pending.
     `render_progress(sid)` shows done/total at any time.
   - **Audit log (A2 wiring, commit 7aff8b7, 2026-05-10; E1 origin tag 2026-05-10)**: per-slice, after each wave Agent returns, call `lib.subagent_invocation_log.record_invocation(ultrawork_sid, "general-purpose", tools=[<tools claimed at dispatch>], generation=<wave_num>, role="ultrawork-slice", extra={"slice_id": "<id>", "owner": "<file or area>", "origin": lib.subagent_invocation_log.ORIGIN_DIRECTIVE})`. PostToolUse hook records this automatically too.

6. **Light verification**:
   - Build/typecheck passes.
   - Affected tests pass.
   - Manual QA for user-visible behavior.
   - No new errors introduced.

7. **Report**:
   - Per-item: files touched, verification status, blockers.
   - One-line summary, then bullet evidence.

## Non-Goals
- No persistence across invocations (use ralph for that).
- No PRD or acceptance-criteria JSON file (validators come from `/harness-ralph`).
- No sign-off by external reviewer (use harness-debate for that).

## Error handling
- One Agent in a wave fails → continue the wave; collect failure in report; do not auto-retry.
- Dependency cycle detected → abort, surface the cycle, ask user to restructure.

## Output

- per-wave summary inline to user: sub-item count, dependency graph, wave assignment.
- per-sub-item artifacts: agent commits / file writes per slice owner.
- final aggregation: per-wave pass/fail + total committed slices + any leftover work items.
- status: `all_complete` | `partial` (some slices failed, others ok) | `aborted_atomic` (work isn't decomposable to ≥2 independent slices) | `aborted_dep_cycle`.

## Failure behavior

- **task is atomic** (cannot decompose into ≥2 independent slices): redirect user to a single-purpose command (`kha-run-trivial` for inline, `kha-run-adhoc` for one-step quality, `harness-autopilot` for goal-driven). Abort with `aborted_atomic`.
- **dependency cycle in slice graph**: abort with `aborted_dep_cycle` + the cycle itself. No waves spawn.
- **agent error within a wave**: that slice is marked `failed`, sibling slices in the same wave continue; subsequent waves with dependencies on the failed slice are SKIPPED (cascading skip), reported in final aggregation.
- **shared file conflict** (two slices in the same wave write to the same path): preflight catches via `write_set` declaration; abort if not resolvable. If detected mid-execution: last-writer-wins, log the conflict warning.
- **NO validator loop**: ultrawork does not re-verify. Wrap with `/harness-ralph` if validator pass-required.

## Gate summary

- preflight: task decomposes into ≥2 independent slices; each slice has a single `owner`; `read_set`/`write_set` declared; no dependency cycle.
- success criteria: every wave completes with all expected commits applied; cascading-skip count = 0.
- abort triggers: atomic task; dependency cycle; preflight write-set conflict.

## Retry / Resume

- checkpoint: per-wave commit hashes form natural recovery points. Each wave is a transactional batch (all-or-skip-cascading-deps).
- resume command: not first-class — re-run with the SAME task. ultrawork will re-decompose and may produce a different graph. To preserve prior work: cherry-pick already-committed slice diffs, then re-run with reduced scope.
- idempotent: NO — slice decomposition is LLM-generated, not deterministic across runs.
- stall detection: per-wave wall-clock + progress on each slice's owner; user-visible advisory if any slice is silent for >2 min beyond expected.

## Boundary with other commands

- vs `harness-team`: ultrawork uses INTERNAL Agent tool subagents in dependency-graphed waves; team uses EXTERNAL CLI workers (claude/codex) with no dependency awareness.
- vs `harness-ralph`: ultrawork is one-shot fan-out (no validator re-run); ralph is verify→fix→re-verify persistence loop.
- vs `harness-autopilot`: autopilot handles a SINGLE goal end-to-end (debate→execute→verify→fix); ultrawork handles MANY independent slices in parallel waves.
- vs `kha-execute-phase`: kha-execute-phase reads roadmap PLAN.md and executes its plans; ultrawork takes ad-hoc task description and synthesizes the slice graph itself.
