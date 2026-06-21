---
description: 목표만 던지고 사람 개입 없이 끝까지 가고 싶을 때. 설계(/harness-debate) → 구현(Executor) → 검증(validators) → 실패 시 수정(/harness-ralph) 자동 사이클. 수렴하거나 사용자가 멈출 때까지. `--resume <sid>`로 중단된 super-session 재개 (W19.1.1+). `--kha-phase X.Y`로 kha-executor 브릿지 라우팅 (W15+, debate-1779314852-338b28). 의사결정 없이 빠르게 시도가 더 맞으면 /harness-ultrawork.
user-invocable: true
argument-hint: "<goal> | --resume <sid> | --kha-phase X.Y <goal>"
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Skill, Agent, TaskCreate, TaskUpdate
category: run
mutates: yes
long-running: yes
external-deps: none
---

You are orchestrating the **harness-autopilot** skill — end-to-end automation from intent to verified code.

## Inputs
- `goal`: 2–5 line description of what to build or fix. **Mutually exclusive with `--resume`.**
- `--resume <sid>`: resume a paused super-session created by a prior invocation (W19.1.1+).
- `--kha-phase X.Y[.Z]`: route Phase 1 implementation through the kha↔harness bridge (W15+, debate-1779314852-338b28 4-LOCK D3). When set, autopilot dispatches via `kha-executor` against the named `.planning/phases/` plan instead of spawning generic agents per `accepted_decision`. **Disambiguation**: this `--kha-phase` is a *kha taxonomy* (GSD phase number naming `.planning/` subdir), distinct from `autopilot Phase 0/1/2/3` numerals (autopilot internal lifecycle stages) — they share digits but live in disjoint namespaces.

If `goal` is empty AND no `--resume` arg, OR the `goal` contains no concrete anchor (file path, function name, feature name), suggest `/harness-interview` first and stop.

If `--kha-phase X.Y` provided:
- Validate the value against `re.fullmatch(r"^[1-9]\d*\.(?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*))?$", value)` (rejects leading-zero forms `01.02`, `1.01`, `0.1` per gen-3 condition S4 — prevents octal-confusion and ambiguous sort).
- On regex fail: abort with `aborted_kha_phase_invalid_format` advisory; print expected shape and quit (do NOT fall back to inference).
- Set `KHA_PHASE = <X.Y[.Z]>`. Bridge routing takes effect at **Phase 1.a Bridge Routing** (below). Phase 0 design debate is *skipped* when `--kha-phase` is set (kha plans carry their own pre-authored intent via `.planning/phases/<phase>-<plan>/PLAN.md`; re-debating would duplicate kha-planner authorship per debate-1779314852-338b28 D3 alternatives_rejected).

If `--resume <sid>` provided:
- Call `engine.orchestrator.load_session(sid)` (per-debate-1778161608-713bdc F6 events.jsonl replay).
- If `None` returned (B5 cold-start FileNotFoundError): abort with `aborted_resume_unknown_sid` + suggest `python -m engine.orchestrator list-sessions`.
- If `RuntimeError` raised on corrupt `child_sids.json`: abort with `aborted_resume_corrupt_state` (B5 fail-closed) — manual inspection required, never silent reset.
- Else: extract `next_action` from `root_phase`, jump to the matching Phase below.

## Protocol

### Phase 0 — Design (harness-debate)
- Invoke the debate engine via `Skill("harness-debate", args=<goal>)` OR by driving the 3 subagents directly.
- Wait for convergence (Architect approved + stable `ontology_snapshot`) OR hard_cap (escalate to user).
- Output: `accepted_decisions` list.

### Phase 1 — Implementation
- **OneDrive guard (D1, debate-1778302432-1ce6ea)**: Before spawning any decision agents, call `engine.orchestrator.phase1_onedrive_check(sess, repo_root)` (orchestrator wrapper that delegates to `lib.autopilot_worktree_probe.is_onedrive_path` AND emits the `worktree_probe_failed` event automatically on positive detection). On `(False, reason)` (OneDrive detected), HALT — surface advisory: "OneDrive-hosted repo detected. Move repo outside `%OneDrive%` or set `AUTOPILOT_SKIP_ONEDRIVE_PROBE=1` to bypass." Do NOT auto-fall back to sequential mode (D5 Phase-2 territory). On `(True, *)`, proceed.
- **Parallel default**: opt-in via `AUTOPILOT_PARALLEL=1` env. Default = sequential (D5 follow-up debate decides flip). Sequential path: spawn decisions one at a time in the parent claude-code Agent context (current behavior). Parallel path: per-decision worktree + per-pane shard events + cherry-pick integration merge (steps below).
- For each `accepted_decision` (sequential path):
  - Classify complexity via `lib.model_router.classify_complexity`.
  - Spawn `Agent(subagent_type="general-purpose", model=<haiku|sonnet|opus>, prompt=<decision + project context>)`.
  - **Audit log (A2 wiring, commit 7aff8b7, 2026-05-10; E1 origin tag 2026-05-10)**: immediately after the Agent tool returns, call `lib.subagent_invocation_log.record_invocation(sess.sid, "general-purpose", tools=[<tier-appropriate tool list>], generation=<current iteration>, role="executor", extra={"decision_id": "<D_n>", "model_tier": "<haiku|sonnet|opus>", "origin": lib.subagent_invocation_log.ORIGIN_DIRECTIVE})`. Record-as-claimed: pass the tools the caller actually invoked the Agent with, not a frontmatter lookup (`general-purpose` is the platform default — no agent .md file).
  - Decisions without dependencies issue parallel tool calls (Wave pattern via single message with multiple Agent invocations — no worktree isolation).
- **Parallel path** (`AUTOPILOT_PARALLEL=1`, debate-1778302432-1ce6ea):
  - For each decision: `git worktree add .worktrees/auto-<sid>-<did> auto/<sid>/<did>` rooted at `HEAD`.
  - Emit `lib.autopilot_pane_events.emit_pane_started(sid_dir, pane_id=<did>, worktree_path=...)` per pane.
  - Spawn decision agents (parallel tool calls) with each agent's `cwd` set to its worktree.
  - **Audit log (A2 wiring, commit 7aff8b7, 2026-05-10; E1 origin tag 2026-05-10)**: per-decision, immediately after each Agent tool returns, call `lib.subagent_invocation_log.record_invocation(sess.sid, "general-purpose", tools=[...], generation=<iter>, role="executor", extra={"decision_id": "<D_n>", "worktree": "<path>", "branch": "auto/<sid>/<did>", "origin": lib.subagent_invocation_log.ORIGIN_DIRECTIVE})`. The shard event (`emit_pane_started`) already records pane-side lifecycle; this audit log records the dispatch surface for cross-session forensics.
  - On agent completion: `emit_pane_status(sid_dir, pane_id=<did>, status="exited"|"failed", exit_code=...)`.
  - After ALL panes complete, in orchestrator process: call `engine.orchestrator.merge_pane_shards(sid)` to fold per-pane shards into canonical `events.jsonl`.
  - Build cherry-pick payload: `payload = lib.autopilot_phase1_merge.build_merge_dispatch_payload(sid=sid, worker_branches=[...], integration_branch=f"team-{sid}/integration", base_ref=<HEAD-at-Phase1-start>)`.
  - Dispatch via Task tool: `result = Agent(subagent_type=payload["subagent_type"], prompt=payload["prompt_text"])`. After the Agent returns, call `lib.subagent_invocation_log.record_invocation(sess.sid, payload["subagent_type"], tools=lib.agent_tool_audit.expected_tools(payload["subagent_type"]), generation=<iter>, role="merge", extra={"integration_branch": payload["integration_branch"], "origin": lib.subagent_invocation_log.ORIGIN_DIRECTIVE})` (A2 wiring, commit 7aff8b7; E1 origin tag).
  - Parse: `parsed = lib.autopilot_phase1_merge.parse_merge_response(result)` (raises `MergeResponseError` on bad shape — surface advisory, do NOT cherry-pick).
  - `is_clean_merge(parsed)` True → integration_branch ready for Phase 2; False → emit `merge_conflict` event with `parsed["conflicted_worker"]` + `parsed["conflicted_paths"]`, escalate.
  - `git worktree remove --force .worktrees/auto-<sid>-<did>` for each pane on Phase 1 exit (success or escalate).

### Phase 1.a — kha bridge routing (W15+, debate-1779314852-338b28 4-LOCK)

Active only when `--kha-phase X.Y[.Z]` was supplied at invocation (D3 LOCK). Skipped otherwise — sequential / parallel paths above remain canonical for generic goals.

- **Dispatch shape**: instead of `Agent(subagent_type="general-purpose", ...)` per `accepted_decision`, route execution through `kha-executor` against the named plan(s) under `.planning/phases/<phase>-*/`. autopilot itself does NOT author `PLAN.md` — kha-planner is the sole author (D3 LOCK alternatives_rejected). If no matching phase dir exists, abort with `aborted_kha_phase_no_plan_dir` advisory + remediation (`run /kha-plan-phase first OR drop --kha-phase`).
- **Bridge dispatch emission (D4 dual-emit)**: for each plan about to dispatch, call:
  ```python
  from lib.autopilot_kha_bridge import emit_bridge_dispatch
  rec = emit_bridge_dispatch(
      orch_sid=sess.sid,
      gen=<current_iter>,
      phase=KHA_PHASE,
      plan=<plan_id parsed from .planning/phases/X-NAME/PLAN dir>,
      mode="wrapped",   # "bare" only when /kha-execute-phase is invoked directly without autopilot
  )
  ```
  This writes one `bridge.dispatch` event to canonical `state/debates/<orch_sid>/events.jsonl` AND one phase-lifecycle event (`status='started'`, `phase_id='kha-{phase}-{plan}'`) to sibling `state/orchestrator/<orch_sid>/phase_events.jsonl`. **Source-of-truth precedence** (gen-3 condition S1): `EventStore.append` is canonical for replay; `phase_events` is a derived projection — readers MUST treat EventStore as authoritative on stream disagreement.
- **kha-executor spawn**: `Agent(subagent_type="kha-executor", prompt=<plan path + project context + continuation table if any>)`. Continuation table (when resuming an in-flight plan) is built via `lib.autopilot_kha_bridge.build_completed_tasks_table(repo_root, phase, plan)` — output shape matches `agents/kha-executor.md:281-313` CHECKPOINT format so kha-executor's `<continuation_handling>` (lines 315-323) consumes it without translation (D7 LOCK).
- **STATE.md ## Harness Bridge append (D5 LOCK + D8 split)**: after each successful bridge dispatch, autopilot appends ONE line to `<project_root>/.planning/STATE.md` under the section `## Harness Bridge` (create header if absent). Format: `- <ISO8601>Z | phase=X.Y | plan=<id> | autopilot_sid=<sid>`. ENFORCED by `validators/harness_bridge_state_block.py` (D5+D5a) — scope limited to the `## Harness Bridge` subsection only; OTHER STATE.md sections (Current Plan / Progress / Decisions / Sessions / Blockers) are kha-executor-owned via `gsd-tools.cjs state advance-plan/update-progress/...` and are NOT subject to D5 append-only enforcement (D8 row split per gen-3 condition B2).
- **Orphan detection (D7a)**: after kha-executor returns (success or interruption), call `lib.autopilot_kha_bridge.detect_orphan_and_escalate(repo_root, phase, plan, orch_sid)`. If True (≥1 commit matching `({phase}-{plan})` AND no `{phase}-{plan}-SUMMARY.md` under `.planning/phases/*/`): autopilot HALTS the iteration. The helper internally acks `aborted_kha_plan_validator_fail` with key `{orch_sid}:{phase}:{plan}:orphan` AND appends `phase_event status='escalated' reason='orphan_commits_no_summary'`. Surface the advisory text to the operator; do NOT auto-redispatch.
- **Ralph deadlock advisory (D6 caller-site)**: if Phase 3 ralph would auto-edit a file under `.planning/` AND `KHA_PHASE` is set, autopilot Phase 3 wrapper (NOT engine/ralph.py per gen-3 condition B1 — escalate-branch consumer lives here in the autopilot caller) calls `lib.advisory_ack.resolve("aborted_kha_plan_validator_fail").ack(f"{sess.sid}:{KHA_PHASE}:<plan>:ralph_planning_dir")` and HALTS the iteration. Operator action: edit the `.planning/` file manually, then re-resume.

### Phase 2 — Verification (validators)
- Run the full validator registry via `engine.ralph.run_validators(VALIDATOR_NAMES, cwd=project_root)`.
- **v15.31 AC tree emit (debate-1778990144-679cb8 D2 — full activation)**: Immediately after the validator registry finishes, construct AC tree leaves from per-validator pass/fail results — for each validator `vname` in `VALIDATOR_NAMES`, create a `lib.ac_tree.AdvisoryLeaf(predicate=lambda _: 5 if passed else 1, axis=<axis_lookup(vname)>, description=vname)` where `axis_lookup` uses the validator→axis table from Phase 3 directive below (default axis=`완성도` if unmapped). Then call `lib.ac_tree.evaluate_emit(leaves, ctx=None, emit_fn=lib.event_store.EventStore(orch_sid).append)` — this writes one `ac.leaf_evaluated` event per validator into `state/debates/<orch_sid>/events.jsonl` and returns the aggregate verdict synchronously within the same Phase 2 step. The reduction at `handlers/stop/autopilot_continue.py:_reduce_ac_leaf_events` (landed v15.28) consumes these events on the same orch_sid stream, producing a live ac_verdict path used by the Stop hook in the same iteration. emit_fn binding lives inline at this Phase 2 call site per debate D2 ontology — no separate orchestrator signature change.
- If all PASS: advance to Phase 3.5.
- If any FAIL: Phase 3.

### Phase 3 — Fix loop (delegate to ralph)
- **v15.29 Wonder pre-strike (debate-1778990144-679cb8 D3)**: Before `Skill(harness-ralph)` dispatch, call `lib.wonder.record_strike(orch_sid, lib.wonder.compute_fingerprint(verdict='iterate', axis=<primary_axis>, failure_signature=hashlib.sha1('|'.join(sorted(failing_validator_names)).encode()).hexdigest()))` where `primary_axis` is looked up via the validator→axis table below (worst-axis priority on multi-validator failures: 완성도 > 안정 > 응집 > 결합 > 확장 > 사용). If `StrikeRecord.triggered` is True (2-Strike Rule), call `lib.wonder.write_reflection(orch_sid, fingerprint, summary)` BEFORE invoking ralph — reflection note feeds RF lineage; on `wonder.depth_exhausted`, escalate to user without ralph dispatch.
- Invoke `/harness-ralph` with the failing validators as `--validators` and the original `goal`.
- On `ralph.converge`: advance to Phase 3.5.
- On `ralph.hard_cap`: escalate to user — do NOT run another autopilot iteration.

**Validator → axis mapping** (v15.29, inline single-file surface — no separate registry mutation):

| Validator | Primary axis | Rationale |
|---|---|---|
| `ci` | 안정 | CI stability / release readiness |
| `codegen` | 확장 | code generation = extensibility scaffold |
| `collab` | 결합 | collaboration coupling patterns |
| `commit_layer_adjacency` | 결합 | layer adjacency = architectural coupling |
| `contract` | 안정 | contract breakage = regression surface |
| `convention` | 응집 | cohesion via convention consistency |
| `ddl` | 안정 | schema stability |
| `er` | 응집 | domain entity-relationship cohesion |
| `flow` | 사용 | user flow / usability |
| `git_flow` | 안정 | release-process stability |
| `handoff_drift` | 안정 | handoff state-consistency stability |
| `harness_bridge_state_block` | 안정 | kha↔harness bridge state-consistency (D5 LOCK debate-1779314852-338b28) |
| `hashline` | 완성도 | strict change-tracking completeness gate |
| `logical` | 응집 | logical DB model cohesion |
| `mutation_safety` | 안정 | mutation-class safety invariant |
| `openapi` | 결합 | API surface coupling contract |
| `prd` | 완성도 | requirement completeness gate |
| `private_content_leak` | 안정 | security-posture stability |
| `skeleton` | 확장 | extensibility scaffold |
| `skill_frontmatter` | 응집 | skill-metadata cohesion |
| `skill_quality_axes` | 사용 | skill usability axes |
| `skill_source_liveness` | 안정 | skill dead-reference stability |
| `subagent_refs` | 결합 | subagent reference coupling |
| `test` | 완성도 | test-pass completeness gate |

If a failing validator is not in the table, use axis=`완성도` as default (most conservative — gate-class). Wonder strike gates ralph dispatch in two cases: (a) `StrikeRecord.triggered=True` invokes `write_reflection` BEFORE ralph runs (strategic re-think first, mechanical fix after); (b) `wonder.depth_exhausted` event blocks ralph dispatch entirely and escalates to user. In all other cases ralph dispatch proceeds normally with the strike recorded for future-iteration accounting.

- **Per-branch ralph (D4, debate-1778307906-23b7b3)**: when `AUTOPILOT_PARALLEL=1` and any pane shard reported `status=failed`, invoke ralph SEQUENTIALLY (one failed pane at a time) in the parent claude-code Agent context with `cwd` set to that pane's worktree (`engine.ralph.run_validators(cwd=<worktree_path>)`). Do NOT spawn ralph from a pane subprocess (Agent tool inheritance does not survive subprocess fork — see `lib/team_worker_loop.py:25-28` invariant + `lib/autopilot_phase1_merge.py` INVARIANT comment). Worktree is preserved on `ralph.hard_cap` for inspection; surface `aborted_ralph_hardcap` + `worktree_path`.

### Phase 3.5 — DGE E2 evaluator dispatch (v15.38, debate-1779008782-230c36 conditions land)

Phase 2 PASS OR Phase 3 ralph.converge 직후, Phase 4 report 직전에 semantic
quality 검증 dispatch. validators (Tier 1 Mechanical) 통과를 전제로
evaluator subagent (Tier 2 Semantic) 가 5축 score + completeness boolean
산출. verdict 분기 — `approved` → Phase 4 직진, `iterate` → Phase 1
재진입, `escalate` → Phase 5 차단 + evaluator 사유 명시.

- **Eligibility check**:
  ```python
  # Required imports (all in scope for steps below — Eligibility, Prompt,
  # Dispatch routing, record_dispatch, Verdict routing, Persist):
  import subprocess
  import os
  import hashlib
  from pathlib import Path
  from lib.evaluator_dispatcher import (
      should_dispatch, record_dispatch, build_evaluator_prompt,
      invoke_evaluator_isolated, invoke_ensemble_evaluator,
      fallback_to_legacy_e2, DispatchEligibility, FallbackReason,
      SUBAGENT_TIMEOUT_SECONDS,
  )
  from lib.providers.base import ProviderUnavailableError
  from lib.paths import STATE_DIR

  phase_id = "phase_3.5"
  eligibility = should_dispatch(sess.sid, phase_id)
  ```
  - `DispatchEligibility.OVER_LIMIT` → Phase 3.5 skip silently, advance to Phase 4. (per-phase 최대 2회 dispatch 제한 — re-eval loop guard.)
  - `DispatchEligibility.DISABLED` → 동일 skip. (`PER_PHASE_EVAL_LIMIT<=0` admin opt-out.)
  - `DispatchEligibility.ELIGIBLE` → 아래 dispatch 진행.

- **Artifact build (P2 권장 default — seed hash baseline)**:
  - `artifact_under_evaluation` = current iteration diff summary (Phase 1/3 산출).
  - `artifact_sha256` baseline 비교 규칙: iteration 1 에서는 `prior_sha = sha256(seed.md if exists else goal_text)`; iteration N (N>=2) 에서는 `prior_sha = state/orchestrator/<sid>/iter_<N-1>_artifact.sha256` 읽기. P2 권장 (b) — debate-1779008782-230c36 미해소 blocker 의 결정형 default. seed 와 implementation 의 distance 정량화 + iteration 진행 시 점진 감소 기대 + single-iter run 도 즉시 비교 가능 (옵션 a empty-baseline 의 단점 / 옵션 c skip 의 verdict 신뢰도 ↓ 둘 다 회피).
  - `phase_locks` = Phase 0 debate ontology snapshot + paradox guard 사실 (test_pass=Phase 2 결과, citation_count=Phase 0 research_citations 수, ontology_match=ontology SHA-1 hash 일치 여부).
  - `axis_rubric` = `agents/harness-evaluator.md` `<scoring_rubric>` 5-axis + completeness boolean (정적 상수).

- **Prompt + isolation gate**:
  ```python
  prompt = build_evaluator_prompt(
      artifact=<iteration_diff_summary>,
      phase_locks=<ontology_snapshot + paradox guard facts>,
      axis_rubric=<5_axis_rubric_constant>,
  )
  # build_evaluator_prompt 는 isinstance str check 만 — isolation 검증은
  # invoke_evaluator_isolated 가 spawn 전 validate_prompt_isolation 자동
  # 호출 (LEAK_PATTERN_REGEX 매치 시 ValueError raise → CONFIG_ERROR
  # fallback 으로 분기). dispatcher bug surface 책임 분리.
  ```

- **Dispatch routing** (Tier 2 default / Tier 3 ensemble opt-in):
  - **Tier 2 (default)**: `AUTOPILOT_ENSEMBLE_EVAL` env 미설정 시:
    ```python
    # fallback_to_legacy_e2 signature: (reason, sid, phase_id,
    #   validators_passed, units_passed, known_defects=0) -> dict
    # Returns: {"event":"fallback", "verdict":..., "completeness":..., ...}
    # fallback_reason stays None on the genuine LLM path; set on every
    # fallback so the D2c producer below can mark cross_target correctly.
    fallback_reason = None
    try:
        raw_text, parsed = invoke_evaluator_isolated(prompt)
        verdict = parsed.get("verdict", "iterate")
        completeness = parsed.get("completeness", False)
    except subprocess.TimeoutExpired:
        fb = fallback_to_legacy_e2(
            FallbackReason.SUBAGENT_TIMEOUT, sess.sid, phase_id,
            validators_passed=True, units_passed=True, known_defects=0,
        )
        verdict, completeness, fallback_reason = fb["verdict"], fb["completeness"], fb["fallback_reason"]
    except ValueError:
        # Prompt isolation fail / dispatcher config bug = structural
        fb = fallback_to_legacy_e2(
            FallbackReason.CONFIG_ERROR, sess.sid, phase_id,
            validators_passed=True, units_passed=True, known_defects=0,
        )
        verdict, completeness, fallback_reason = fb["verdict"], fb["completeness"], fb["fallback_reason"]
    except ProviderUnavailableError:
        fb = fallback_to_legacy_e2(
            FallbackReason.SUBAGENT_EXCEPTION, sess.sid, phase_id,
            validators_passed=True, units_passed=True, known_defects=0,
        )
        verdict, completeness, fallback_reason = fb["verdict"], fb["completeness"], fb["fallback_reason"]

    # D2c PRODUCER (debate-1780564679-8mgxsd) — REQUIRED on the default
    # (single-LLM) path: persist the verdict to axis_scores.jsonl so the
    # deterministic Stop-hook E2 gate (handlers/stop/autopilot_continue.py →
    # lib.completion_gate.latest_fresh_evaluator_verdict) can READ it. The
    # Tier-2 path computes `verdict` locally; WITHOUT this emit the gate's read
    # source is permanently empty, so require_evaluator=True would fail-closed
    # to 'iterate'→escalate even after a faithfully-run 'approved' E2 (the
    # producer is what makes the happy path completable). MUST NOT pass an
    # explicit `ts` — log_verdict_event server-stamps time.time() so the
    # iteration freshness floor stays trustworthy (B4). If this emit is
    # skipped, the platform stays SAFE (fail-closed), but the run cannot
    # complete on E2.
    #
    # cross_target write side (2026-06-18): log_verdict_event marks the FIRST
    # genuine LLM E2 verdict on a generator artifact with
    # cross_target_first_invocation=True so operational_metrics.
    # get_dge_e2_cross_target_count can count it. cross_target=(fallback_reason
    # is None) — a validators+units fallback is NOT a real cross-provider
    # evaluation and must not increment the metric.
    from lib.axis_scores_log import log_verdict_event
    log_verdict_event(sess.sid, {
        "event": "evaluator_verdict", "verdict": verdict,
        "completeness": completeness, "phase_id": phase_id,
    }, cross_target=(fallback_reason is None))
    ```
  - **Tier 3 (opt-in)**: `AUTOPILOT_ENSEMBLE_EVAL=1` env 설정 시:
    ```python
    # 추가 import (Tier 3 path 전용):
    from lib.evaluator_dispatcher import axis_log_emit_for

    ensemble_verdict = invoke_ensemble_evaluator(
        prompt,
        sid=sess.sid, phase_id=phase_id,
        validators_passed=True, units_passed=True, known_defects=0,
        evaluator_specs=None,                     # → default pool
        emit_fn=axis_log_emit_for(sess.sid),      # ensemble.aggregated → axis_scores.jsonl
    )
    # EnsembleVerdict field 명: `.quorum_verdict` (NOT `.verdict`).
    # split=True 인 경우 ensemble.aggregate 가 자동으로 'escalate' 다운그레이드
    # (paradox layer + paradox_guard_all_pass=False 도 동일 path).
    verdict = ensemble_verdict.quorum_verdict
    completeness = all(v.completeness for v in ensemble_verdict.votes)
    ```

- **record_dispatch**:
  ```python
  record_dispatch(sess.sid, phase_id)  # per-(sid, phase_id) 카운터 +1
  ```
  성공/fallback/exception 모두 record (PER_PHASE_EVAL_LIMIT 의미 보존).

- **Verdict routing**:
  - `approved`: advance to Phase 4 normally.
  - `iterate`: Phase 1 재진입 (또는 ralph 가 직전 단계인 경우 Phase 3 재진입). `iteration_count >= max_iterations` 시 Phase 5 `iterate` 결정으로 escalate.
  - `escalate`: Phase 5 직진 + `next_action` 에 evaluator escalation 사유 명시 (`evaluate_completion` 결과 무시).

- **Persist artifact_sha256 for next iteration**:
  ```python
  state_dir = STATE_DIR / "orchestrator" / sess.sid
  (state_dir / f"iter_{sess.iteration}_artifact.sha256").write_text(
      hashlib.sha256(artifact_under_evaluation.encode("utf-8")).hexdigest()
  )
  ```

- **Observability + E2 platform record (debate-1780564679-8mgxsd D2c)**: 본 phase 의 verdict 는 `state/evaluator/<sid>/axis_scores.jsonl` 에 기록된다 — **Tier-2 default path 는 위 D2c PRODUCER 의 `log_verdict_event` 호출(caller 책임 — cross_target 마커 포함)**, **Tier-3 ensemble path 는 `emit_fn=axis_log_emit_for(sess.sid)`(dispatcher 책임)**. (구 문서는 "dispatcher 가 모든 path 에서 자동 append" 라고 했으나 이는 ensemble path 에만 사실이었음 — Tier-2 default 는 invoke_evaluator_isolated 가 verdict 를 반환만 하고 기록하지 않았다. 이 record 가 Stop-hook E2 gate 의 read source 이므로 Tier-2 producer emit 은 필수.) `axis_scores.jsonl` line count ≥3 시 `python -m cli.telemetry_report --evaluator-accuracy` 로 verdict 분포 + axis 평균 + completeness 비율 + fallback_reason 통계 추출.

### Phase 4 — Report
- Summary: accepted decisions, files touched, validator pass list, fix iterations used, total tokens (approx).
- Artifact: `<CLAUDE_HOME>/state/autopilot/<unix_ts>.md`.

### Phase 5 — Handoff + Goal-completion check (W19.1.1+, iteration W21+)
- **Parallel-run telemetry (D5, debate-1778307906-23b7b3)**: when `AUTOPILOT_PARALLEL=1` was set for this run AND the run reached a terminal state (`complete` | `escalate` | `aborted_*`), call `engine.orchestrator.record_parallel_run_outcome(sess, status=<terminal_status>, merge_conflicts=<count>, pane_failures=<count>)` (orchestrator wrapper that delegates to `lib.autopilot_flip_policy.log_parallel_run_outcome` with the session's sid). Observability only — no caller reads this counter for policy decisions; flip from `current_default()=0` requires a NEW debate citing `debate-1778307906-23b7b3 D5`.
- Wrap the run as a resumable super-session via `engine.orchestrator`:
  - At Phase 0 start (iteration 1 only): `sess = orchestrator.new_session(goal)` → mints `orch-<ts>-<rand>` sid, writes initial `state/orchestrator/<sid>/events.jsonl` + `phase-tree.md`.
  - **Shared sid registration (post W19.1.2+ enhancement)**: immediately after `new_session` returns, register the SAME sid with `lib.autopilot_state` so the Stop hook can cross-reference both systems: `from lib.autopilot_state import new_state, write_state; write_state(new_state(sess.sid, goal))`. This unifies `state/autopilot/<sid>.json` and `state/orchestrator/<sid>/` under one identifier; `scripts/handlers/stop/autopilot_continue.py` can then call `engine.orchestrator.load_session(sid) + evaluate_completion(...)` directly. If skipped (legacy path), the hook falls back to its inline boolean gate (validators_passed AND tests_passed AND blocking_question_count==0) — equivalent semantic, weaker iteration accounting.
  - At iteration entry: `orchestrator.bump_iteration(sess)` → appends `iteration_started` event + returns new iteration count.
  - After each phase: `orchestrator.update_phase(sess, root_phase_with_status)` and `orchestrator.link_child(sess, phase_id, child_sid)` for debate/ralph child sids.
  - **Goal-completion gate** (after Phase 4 report):
    ```python
    # E2 platform enforcement (debate-1780564679-8mgxsd): pass the Phase 3.5
    # verdict DIRECTLY via evaluator_verdict + require_evaluator=True — the same
    # contract the deterministic Stop hook (autopilot_continue.py) enforces from
    # the durable axis_scores log. A missing/None verdict (Phase 3.5 skipped or
    # DispatchEligibility.OVER_LIMIT) can NO LONGER complete: it falls through to
    # 'iterate' (below cap) / 'escalate' (at cap, D4 bounded). 'escalate' is
    # handled natively by decide_completion's short-circuit — no longer folded
    # into blocking_question_count, which now carries ONLY genuine Phase 4
    # escalations.
    decision = orchestrator.evaluate_completion(
        sess,
        validators_passed=<Phase 2 result>,
        tests_passed=<run_units result if applicable>,
        blocking_question_count=<Phase 4 escalations>,
        evaluator_verdict=phase_3_5_verdict,   # 'approved'|'iterate'|'escalate'|None
        require_evaluator=True,
        max_iterations=3,  # `engine.orchestrator.DEFAULT_MAX_ITERATIONS`
    )
    ```
    - `'complete'`: Phase 5 writes `next_action='done'` and exits. Super-session converged.
    - `'iterate'`: re-enter Phase 1 (or Phase 0 if accepted_decisions changed) with updated context. Caller invokes `bump_iteration` and recurses. Loop bounded by `max_iterations`.
    - `'escalate'`: Phase 5 writes `next_action` describing what the user must decide; return control. Super-session preserved for `--resume <sid>`.
- The Phase Tree Convention (HANDOFF.md) governs sub_phase decomposition; promotion / transition / pruning rules apply to `root_phase.sub_phases`.
- DO NOT modify HANDOFF.md from here — the super-session phase-tree lives at `state/orchestrator/<sid>/phase-tree.md` (per-run), not the global handoff doc.

## Non-Goals
- No multi-phase QA cycling beyond Phase 3 (OMC's 5-cycle QA is too expensive for our scale).
- No deep-interview branch — if `goal` is vague, we redirect, not auto-interview.
- No team worker mode — use `/harness-team` explicitly.

## Error handling
- Phase 0 hard_cap → abort with debate session id for inspection.
- Phase 2 validator registry entirely missing → abort with registry dump.
- Phase 3 ralph hard_cap → abort, report last failing validators, preserve event stores.

## Output

- artifacts produced across phases:
  - Phase 0 (debate): `state/debates/<sid>/events.jsonl` + `accepted_decisions` checklist
  - Phase 1 (executor): code/file changes per accepted decision; per-file commits
  - Phase 2 (validators): `validators/run_all` output + per-validator status lines
  - Phase 3 (ralph): `events.jsonl` of fix iterations (if invoked)
- status: `complete` (all phases passed) | `aborted_vague_goal` (Phase 0 redirect to interview) | `aborted_debate_hardcap` | `aborted_no_validators` | `aborted_ralph_hardcap` | `user_interrupt`.

## Failure behavior

- **vague goal at preflight**: redirect user to `/harness-interview` to produce a seed spec; abort with `aborted_vague_goal`. No phases run.
- **debate hard_cap (Phase 0)**: surface the failed debate `<sid>` for inspection; abort with `aborted_debate_hardcap`. NO subsequent phase runs.
- **executor partial commits (Phase 1)**: each accepted decision is committed atomically; on a per-decision failure, halt the remaining decisions but keep already-committed ones. Surface `partial_implementation` advisory with last-good commit hash.
- **validator registry empty (Phase 2)**: abort with `aborted_no_validators` + registry dump for diagnosis.
- **ralph hard_cap (Phase 3)**: report last failing validators; preserve `state/ralph/<sid>/events.jsonl`. Abort with `aborted_ralph_hardcap`. Already-committed Phase 1 changes remain.
- **calling pattern**: ALWAYS go through the `Skill` tool to invoke `/harness-debate` and `/harness-ralph` — never spawn Planner/Critic/Architect agents directly inline. (Round-3 P0 #3: previously docs read "Skill OR direct subagents" — direct subagent path removed for cohesion).

## Gate summary

- preflight: goal argument resolves to ONE concrete deliverable + non-trivial anchor (filepath or feature name); CLAUDE_HOME writable; `state/debates/`, `state/ralph/` exist or creatable.
- success criteria: ALL four phases reach terminal pass states — debate `converged`, executor commits applied, validators all pass, optional ralph `all_pass`.
- abort triggers: vague goal (no anchor); debate hard_cap; missing validator registry; ralph hard_cap; user interrupt at any phase boundary.

## Retry / Resume (W19.1.1+ first-class)

- checkpoint: super-session via `engine.orchestrator` — `state/orchestrator/<sid>/events.jsonl` is canonical (replayable), `phase-tree.md` is derived (regenerated each transition), `child_sids.json` maps phase_id → child engine sid (debate/ralph/team) via atomic write.
- resume command: `/harness-autopilot --resume <sid>` is first-class. `engine.orchestrator.load_session(sid)` replays events.jsonl, returns the root phase + child_sids. Caller reads `next_action` on the root and jumps to the matching phase. B5 cold-start: `FileNotFoundError` → `aborted_resume_unknown_sid`. B5 fail-closed: corrupt `child_sids.json` → `RuntimeError` (never silent reset).
- idempotent: per-invocation. Same sid resume reads the same events log; new invocation without `--resume` mints a new sid. Phase 1 commits remain git-level idempotent.
- stall detection: phase-level — debate gen counter + ralph iteration counter. Super-session has no global wall-clock timeout in MVP; D7 adds a researcher-step timeout when Phase 2 lands.
- TTY fallback (D4b): on `--resume <sid>` where the sid dir already exists, `engine.orchestrator.confirm_resume_or_new(sid)` checks `sys.stdin.isatty()`; non-tty (autopilot child spawn) → `'resume'` default; tty → interactive `r/n/a` prompt.

## Boundary with other commands

- vs `harness-debate`: this RUNS debate as Phase 0 then continues to executor + validator + ralph. Debate alone is decision-only, no implementation.
- vs `harness-ralph`: this runs ralph as Phase 3 (validator FAIL recovery). Ralph alone presumes you already have implementation + validators.
- vs `harness-ultrawork`: this is debate+execute+verify+fix for a SINGLE goal; ultrawork is parallel waves of independent slices, no validator loop.
- vs `kha-run-milestone`: this runs ad-hoc single goal end-to-end; run-milestone iterates roadmap-driven phases sequentially.
- vs `/goal` (Claude Code 공식, 2026-Q1+): `/goal`은 session-scoped prompt-based Stop hook으로 LLM(Haiku)이 매 턴 prose stop-condition을 평가. autopilot은 자체 Stop hook `scripts/handlers/stop/autopilot_continue.py` (debate-1778224899-c24de4 D3''='single')로 **deterministic state machine** 기반 multi-turn loop을 운영. 두 hook은 settings.json `Stop` 배열에서 **병렬 작동** — `/goal`은 prose 판정, autopilot은 `<autopilot mode='execute' sid=... iter=...>` tag 기반 state 진행. 사용자가 `/goal "..."`을 추가로 등록하면 두 조건 모두 충족해야 turn이 자연 종료. autopilot이 활성이면 `autopilot_continue.py`가 우선 (response_guard도 D3'' merge로 흡수). 공식 `/goal` 명세 주의사항: ① 500-turn 하드캡 없음 (그건 커뮤니티 클론 jthack/claude-goal). 사용자가 prose에 "or stop after N turns" 명시. ② `/goal pause` 서브커맨드 없음. `clear/stop/off/reset/none/cancel`만 존재. ③ nesting=replacement (두 번째 `/goal`이 첫 번째 덮어씀). ④ `--resume`/`--continue`는 active goal 복원하지만 turn-count/timer/token baseline은 리셋.
