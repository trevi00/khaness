---
description: Verify/fix persistence loop — run selected validators, if any fail delegate a minimum-change fix to an executor, re-validate, repeat until all PASS or hard_cap.
user-invocable: true
argument-hint: "<goal> [--max-iter N] [--validators a,b,c]"
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent, TaskCreate, TaskUpdate
category: remediate
mutates: yes
long-running: yes
external-deps: none
---

You are orchestrating the **harness-ralph** skill — the validators-driven fix loop from `engine.ralph`.

## Inputs
- `goal`: one-line description of what "done" means (used in the fix-agent prompt context).
- `--max-iter N` (optional; default `engine.ralph.MAX_ITERATIONS` = 10).
- `--validators a,b,c` (optional; defaults to the full `VALIDATOR_NAMES` registry minus ones that always skip on this project).

If `goal` is missing, ask once and stop.

## Protocol

1. **Session init**:
   ```python
   from engine.ralph import new_session_id, ralph_store, run_validators, check_iteration, build_fix_prompt, record_iteration
   sid = new_session_id()
   store = ralph_store(sid)
   ```
   Print `sid` to the user.

2. **Iteration loop**:
   For `iter` in `1..max_iter`:
   a. `outcomes = run_validators(validator_names, cwd=project_root)`
   b. `result = check_iteration(iter, outcomes, max_iterations=max_iter)`
   c. `record_iteration(store, result, fix_prompt=<current> if not result.converged else None)`
   d. If `result.converged`: break with "done".
   e. If `result.hard_cap`: break with "escalate — last failing validators: [...]".
   f. Else (`next_action == "fix"`):
      - `prompt = build_fix_prompt(outcomes)` + user's `goal` for context.
      - Spawn `Agent(subagent_type="general-purpose", prompt=<fix_prompt + goal>)`.
      - **Audit log (A2 wiring, commit 7aff8b7, 2026-05-10; E1 origin tag 2026-05-10)**: immediately after the fix Agent returns, call `lib.subagent_invocation_log.record_invocation(sid, "general-purpose", tools=[<tools claimed at dispatch>], generation=iter, role="ralph-fixer", extra={"failing_validators": [<names>], "goal": goal, "origin": lib.subagent_invocation_log.ORIGIN_DIRECTIVE})`. The cross-session forensics target ("how many ralph fix iterations did we run on validator X this month?") needs the per-iteration record.
      - After the fix agent returns, continue to next iteration.

3. **On convergence**:
   - Report: "ralph converged at iteration X; all validators PASS."
   - Print `store.path` so the user can inspect events.

4. **On hard_cap**:
   - Report: "ralph reached hard_cap={max_iter}; user decision required."
   - List the unresolved validator names + their last output tail.
   - Do NOT auto-escalate to another mode.

## Non-Goals
- No PRD-driven mode (OMC's `prd.json`). Validators are the acceptance criteria.
- No mandatory deslop pass (OMC's `--no-deslop` deferred to Wave 7).
- No reviewer sign-off — validators PASS = done.

## Error handling
- All `VALIDATOR_NAMES` missing from registry → abort before iteration 1.
- Fix agent fails (Agent tool error) → log to event_store, retry once, then escalate.

## Output

- session dir: `state/ralph/<sid>/` with `events.jsonl` (per-iteration validator + fix events).
- per-iteration: validator output captured + executor agent's commit hashes (if applicable).
- final summary: pass/fail per validator at last iteration + total iterations + last failing diff (if `hard_cap`).
- status: `all_pass` (every selected validator passed) | `hard_cap` (max-iter reached, some failing) | `aborted_no_validators` | `aborted_no_goal`.

## Failure behavior

- **goal missing**: prompt user once for one-line goal; abort with `aborted_no_goal` on second empty.
- **selected validator(s) not in registry**: list available validators, abort with `aborted_no_validators` (no fix attempted).
- **fix-agent error** (Agent tool exception, malformed diff, refused commit): retry the SAME iteration's fix once with the same prompt; second failure → log + skip to next iteration (do not infinite-loop on a broken fix).
- **validator pass→fail regression** (iteration N+1 has fewer passing than N): preserve iteration N's commit but log regression event; continue if max-iter remaining.
- **max-iter reached without all_pass**: status `hard_cap`. Per-validator fail diff preserved in `events.jsonl`. Already-committed fixes remain in git — manual review needed.

## Gate summary

- preflight: goal non-empty; selected validators all exist in `validators.VALIDATOR_NAMES`; max-iter > 0; project has clean git working tree (so per-iteration commits are isolatable).
- success criteria: every selected validator passes at iteration ≤ max-iter.
- abort triggers: goal missing after re-prompt; unknown validator; max-iter hit (escalates to user, not hard abort).

## Retry / Resume

- checkpoint: `state/ralph/<sid>/events.jsonl` — append-only per-iteration log. Resumable.
- resume command: not first-class — re-running `/harness-ralph <goal>` mints a new sid. To continue from prior session: read `events.jsonl` last validator status, manually re-invoke fix-agent for failing ones.
- idempotent: per-iteration NO (each iteration produces new commits). Across re-runs: depends on git state — if prior commits address same issues, validators may pass on iteration 1.
- stall detection: monotonic counter; if a validator passes count is non-decreasing for 3 consecutive iterations without reaching all_pass → user-visible "no progress" advisory before hard_cap.

## N-Strike research escalation (W19.1.1+)

When the same validator fingerprint fails across iterations and reaches `RESEARCH_DISPATCH_THRESHOLD` (debate-1778161608-713bdc gen 4: F2 = 2, single source via `lib.repeat_error_tracker.STRIKE_THRESHOLD`):

**Deterministic seam (M18, debate-1781594208-53fee4)** — the dispatch decision and the artifact→skill-candidate consumption are owned by `cli.strike_research_consume`, NOT by skippable prose. The ONLY LLM step is the irreducible `Agent` spawn between the two CLI calls. Run these three mechanical steps in order:

1. **Dispatch gate** (pre-spawn, deterministic):
   ```bash
   python -m cli.strike_research_consume dispatch \
     --session-id <sid> --fingerprint <fp> --strike-count <N> \
     --tool-name <tool> --error-excerpt "<≤400-char normalized sample>"
   ```
   - exit **3** → DISPATCH: stdout is one JSON line with a `payload` field. Proceed to step 2 with that payload.
   - exit **0** → skip (below threshold / per-fingerprint quota exhausted / standalone with no super-session). Do nothing; continue the loop.
   - exit **4** → fail-CLOSED (escalate, operator-visible). The CLI owns `should_dispatch` + `record_dispatch` (locked `lib.strike_dispatcher`, `PER_FINGERPRINT_DISPATCH_LIMIT=3`) and emits a `research_dispatched` event — so the dispatch is recorded even if the spawn never happens.
2. **Spawn** (the irreducible LLM step): `Agent(subagent_type="harness-researcher", …)` using the `payload` from step 1's stdout verbatim. The researcher produces `state/research/strikes/<fingerprint>.md` (root cause + sources + a proposed permanent change: skill_gotcha / hook_rule / settings_change) but does NOT commit and does NOT edit skills/hooks/settings directly.
3. **Consume** (post-artifact, deterministic):
   ```bash
   python -m cli.strike_research_consume consume \
     --session-id <sid> --fingerprint <fp>
   ```
   - The CLI parses the artifact and routes by (verdict × change_type): **skill_gotcha + accepted_change** → no-degradation gate (`lib.repro_probe.build_probe` reproduction probe **AND** `_secret_scan_pass`) → on accept, STAGE a candidate via the reused `lib.skill_candidate_detector` (cid `skill-wonder-<fp>`, `activation.confirm_token="enable-skill"`, D3 clobber-guard `collision_policy`); **hook_rule / settings_change** → operator-escalation-only (`<fp>.escalation.json`, NEVER auto-staged — they touch the NEVER-auto settings/hooks surface); **no_research_available / escalate_to_user** OR a non-deterministic (403/Cloudflare/transient-lock) probe → forensic/operator-escalation, never silent fail-closed (condition B6).
   - exit **0** = clean (staged/escalated/forensic); exit **4** = fail-CLOSED (NOTHING staged). Idempotent per (sid, fingerprint): a replay is a no-op. `consume` NEVER calls `record_dispatch` (D4 invariant — dispatch and consume cannot double-count the quota).
   - **Activation stays operator-gated**: a staged candidate sits in `skill-candidates/` until an operator spends the `enable-skill` token. The deterministic loop has no auto-activation edge.
4. Ralph's next iteration receives the researcher's proposed change as additional fix-prompt context, so the iteration N+1 fix is informed by external research, not just the LLM's training memory.
5. Per-fingerprint dispatch quota is `PER_FINGERPRINT_DISPATCH_LIMIT = 3` per (sid, fingerprint) tuple — same fingerprint dispatching researcher 4+ times in one super-session is blocked (F7 atomic_counter safeguard via `state/orchestrator/<sid>/dispatch_counter.json`).
6. Standalone `/harness-ralph` (not invoked by autopilot) does NOT auto-dispatch — step 1 returns exit 0 (no super-session sid). The PostToolUse advisory `<research-dispatch-advisory>` notifies the user that researcher invocation is available; user invokes manually if desired.

## Boundary with other commands

- vs `harness-autopilot`: ralph is invoked AS Phase 3 of autopilot when validators fail; standalone ralph presumes implementation already exists.
- vs `kha-remediate-audit-findings`: ralph is validator-FAIL-driven (mechanical); remediate-audit-findings is audit-finding-driven (human-curated priority).
- vs `kha-remediate-code-review`: ralph runs validators and patches; remediate-code-review consumes REVIEW.md findings and applies fixes, no validator re-run.
- vs `harness-debate`: debate decides (no implementation); ralph implements + verifies.
