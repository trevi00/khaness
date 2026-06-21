---
description: Run the Planner-Critic-Architect debate on a design topic. Converges until Architect returns consecutive approvals on an identical ontology_snapshot, or the hard cap (4 generations) is hit.
user-invocable: true
argument-hint: "design topic"
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent, TaskCreate, TaskUpdate
category: design
mutates: yes
long-running: yes
external-deps: none
---

You are orchestrating the **harness debate engine** on behalf of the user.

## Inputs
Argument: the design topic (everything after the command name). If empty, ask the user for one sentence describing the decision they need, then stop and wait for a reply.

## Session
- Resolve `CLAUDE_HOME` from env, fall back to `~/.claude`.
- Mint a session id: `debate-<unix_ts>-<random6>`.
- Events go to `<CLAUDE_HOME>/state/debates/<session_id>/events.jsonl` via `lib.event_store.EventStore`.
- Record every proposal / critique / verdict / convergence event with `gen`, `actor`, `payload`, `hash`.

## Protocol
For each generation (max 4):

1. **Planner**
   - Build a self-contained prompt including:
     - `topic` (the argument)
     - `context`: Grep the codebase for keywords in the topic, include 3-5 relevant file excerpts inside a `<files_to_read>` block
     - `prior_generation` (Architect's previous `ontology_snapshot`, if any)
     - `critic_feedback` (previous Critic's `blocker` attacks, if any)
     - `prior_debates` (**M1 — resurface failed/accepted directions, 2026-06-16**): in **generation 1 only**, run `python -m cli.debate_aggregate --topic "<2-4 key terms from the topic>" --format planner-context` and include its stdout verbatim (empty stdout ⇒ include nothing). This deterministic reader surfaces prior debates on a similar topic — REJECTED/STALLED directions (do NOT re-propose as-is without addressing why they failed) + ACCEPTED decisions (you MAY build on). **Advisory only — the Planner weighs it; it NEVER auto-vetoes a proposal.** Closes the previously dead-end `cli.debate_aggregate.aggregate()` reader (write side wired, read side 0); mirrors AutoScientists "preserve + resurface success/failure to cut redundant exploration". Later generations already carry `prior_generation`/`critic_feedback`, so skip there.
     - `recurring_blockers` (**M8 — pre-empt the dominant Critic axis, cross-session**): in **generation 1 only**, run `python -m cli.debate_aggregate --format blocker-advisory` and include its stdout verbatim (empty stdout ⇒ include nothing). This aggregates the Critic blocker AXIS distribution across all prior debates (the recurring friction the Planner keeps drawing — assumption/failure/simplification) and names the dominant one to pre-empt, so this proposal converges with fewer gens. **Advisory only — never a veto.** Sibling of M14: `lib.debate_stagnation` terminates a *single* debate on blocker plateau; this spends the *cross-session* blocker signal it explicitly defers. Skip in later generations.
     - `criticism_diversity` (**M30 — cross-session criticism-diversity + severity health, finer-grained sibling of M8**): in **generation 1 only**, run `python -m cli.debate_aggregate --format criticism-diversity` and include its stdout verbatim (empty stdout ⇒ include nothing). Where `recurring_blockers` aggregates the coarse blocker AXIS, this spends the blocker CONTENT signal: overlap_rate (criticisms rarely repeat = healthy), the cross-session severity distribution + HIGH-rate, and the one live advisory predicate `UNSPEC_UNCALIBRATED` (≥20% of recent blockers carry no recognizable severity ⇒ emit a canonical HIGH/MED/LOW). Measured over a **trailing window** of the most-recent N=20 blocker-bearing sessions so improving vocabulary turns the advisory off. **Advisory only — measurement context, never a veto, no over-flag assertion.** Converged design debate-1781617065-m30a01 gen-3 (LOCK sha1 `f28a57e4`). Skip in later generations.
   - Spawn via the Agent tool with `subagent_type=harness-planner`.
   - **Research-augmented (W19.1.1+)**: Planner has `WebSearch + WebFetch`. If the topic involves a library/framework whose API/best-practice may have shifted (≥6 months) OR a pattern with competing implementations, Planner cites authoritative sources via `research_citations[]`. Each citation must be `load_bearing_for: D<N>`.
   - Parse the returned JSON. On parse failure, retry ONCE; then escalate to the user.
   - Append a `proposal` event (citations preserved in payload). **Include `topic` (the debate argument) in the gen-1 proposal payload** so cross-session readers (`cli.debate_aggregate`, the M1 `prior_debates` block above) can recover what this session was about — the planner does not emit `topic_restatement`, so the orchestrator must persist it.

2. **Critic** *(skippable on fast path — see below)*
   - Build a prompt with `proposal` and `context`.
   - Spawn `subagent_type=harness-critic`.
   - **Citation integrity (W19.1.1+)**: Critic has `WebFetch`. If proposal carries `research_citations`, Critic verifies each one — outdated/version-mismatched/non-load-bearing citation = `axis: assumption` blocker. Critic may WebFetch the URL to validate the claim.
   - Parse critique JSON. Append `critique` event.
   - **Self-report cross-check (debate-1778307906-23b7b3 step_5 audit, 2026-05-09)**: scan critique JSON for any `tool unavailable` / `WebFetch not available` / `Critic has only ...` self-report claims. For each tool the Critic claimed missing, call `lib.agent_tool_audit.verify_self_report_consistency('harness-critic', self_reported_missing=[<tools>])`. If the returned mismatch list is non-empty, append a `self_report_mismatch` event with `lib.agent_tool_audit.render_advisory(...)` payload.
   - **Severity escalation (A1, commit c14e53c, 2026-05-10)**: also call `lib.agent_tool_audit.classify_severity(mismatches, has_research_citations=<True iff this gen's proposal carried `research_citations[]`>)`. The returned severity drives policy:
     - `"clean"` (no mismatch): proceed normally.
     - `"advisory"` (mismatch but no citations claimed): observability only, no verdict change. Critic stays as-spawned.
     - `"invalidate"` (mismatch AND citations claimed verified): the citation-integrity path may have been silently skipped. Append a `verdict_invalidated_by_severity` event with `render_advisory(..., severity="invalidate")` payload. The orchestrator's convergence check at step 4 MUST treat this gen's architect verdict as `rejected` regardless of its declared status — write the architect's verdict event normally for forensics, but feed `rejected` into the convergence rule. Do NOT auto-respawn the Critic in the same gen.
   - **Isolation leak scan (defense-in-depth, 2026-05-09)**: call `lib.debate_output_audit.scan_for_isolation_leaks(<full critique text>)`. If non-empty, append an `isolation_leak_observed` event with `lib.debate_output_audit.render_leak_advisory('harness-critic', leaks)` payload. Catches platform-isolation degradation (subagent output mentioning `state/debates/`, `events.jsonl`, sid prefixes, prior-turn phrases, role-override injection attempts, Korean equivalents). Observability only — Architect treats leaks as a verdict confidence reducer.

3. **Architect**
   - Build a prompt with `proposal`, `critique` (or empty if fast-pathed), and `context`.
   - **`severity_calibration` (M30 — per-debate calibrated-severity table, ALL gens)**: run `python -m cli.debate_aggregate --format severity-calibration --session-id <session_id>` and include its stdout verbatim (empty stdout ⇒ include nothing). This triage-neutrally surfaces ONLY the THIS-debate blockers whose canonical severity changes triage — the UNSPEC cohort (no recognizable label) or a raw label that normalizes to a different bucket (e.g. `blocker`→HIGH) — so the judge can triage the critique without re-reading a chaotic severity vocabulary. **Calibration context only — NOT a claim the Critic over-flags, NEVER a veto; the Architect still weighs each blocker on its merits.** Injected for ALL generations (harmlessly empty below the table threshold). Converged design debate-1781617065-m30a01 gen-3 (LOCK sha1 `f28a57e4`); read-only, appends no events, leaves the convergence rule + ontology-SHA computation untouched.
   - **LOCK target embedding (2-strike codified 2026-05-19)**: if the prior generation's verdict was `conditional` AND emitted a non-empty `ontology_snapshot.fields`, embed that JSON verbatim in this Architect prompt under a `# LOCK target JSON (copy verbatim)` section + explicit "MUST reproduce BYTE-IDENTICAL" instruction. See `~/.claude/skills/_common/architect-lock-reproduction-discipline.md` — shape divergence (e.g., `[{name, value}]` → `[{id, type, value}]`) blocks convergence despite `verdict=approved`. Wave 7 후속 15 + 후속 16 evidence.
   - Spawn `subagent_type=harness-architect`.
   - **Evidence review (W19.1.1+)**: Architect has `WebFetch`. Architect emits `evidence_review[]` — one entry per citation with `judgment: accepted | rejected | irrelevant`. A decision depending on a `rejected` or `irrelevant` citation cannot appear in `accepted_decisions`. This is the Designer-evaluator (DGE E1) automation per CLAUDE.md.
   - Parse verdict JSON. Append `verdict` event (evidence_review preserved in payload).
   - **Isolation leak scan (defense-in-depth, 2026-05-09)**: call `lib.debate_output_audit.scan_for_isolation_leaks(<full verdict text>)`. If non-empty, append an `isolation_leak_observed` event with actor=`harness-architect` payload. Same defense-in-depth contract as Critic step (observability only, no auto-respawn). Architect leaks are particularly concerning because they may indicate verdict was influenced by forbidden context.
   - **Cross-vendor jury advisory (OPT-IN, ADVISORY-ONLY; operator decision 2026-06-18 — closes built-but-unwired `external_jury`)**: AFTER appending this gen's architect `verdict` event, call `engine.jury_advisory.jury_advisory(architect_prompt, architect_verdict=<this gen's verdict string>)`. This runs `engine.external_jury.ask_jury` on available NON-Claude vendors (codex/ollama) as a second opinion that surfaces the C-2 single-vendor-bias check (Planner/Critic/Architect are all Claude, so a Claude blind spot is invisible to the whole loop). If the returned payload is `skipped=False`, append it as a `jury_advisory` event (`es.append('jury_advisory', actor='external_jury', gen=<gen>, payload=<dict>)`); the `disagreement` / `agrees_with_architect` fields flag whether a cross-vendor panel diverged from Claude. **OPT-IN**: a no-op unless `DEBATE_EXT_JURY=1` (default off → `skipped_reason='opt_out'`, no jury call, behavior-preserving). **ADVISORY-ONLY — this MUST NOT feed step 4**: the deterministic convergence check below consumes ONLY the harness-architect `verdict` event + its `ontology_snapshot.fields` SHA-LOCK. The jury payload carries no `ontology_snapshot`/`sha` key and never changes `effective_verdict`. Rationale: a non-Claude panel cannot reproduce the architect snapshot byte-identical, so letting a jury decide would break deterministic convergence (M24); the jury is a forensic disagreement signal, not a judge. Fail-soft: `jury_advisory` never raises into the loop (provider down / 0 members → `skipped` event or none).

4. **Convergence check** (primary rule — Architect-verdict based) — **DETERMINISTIC (M24, debate-1781603679 sibling pattern of M14)**
   - AFTER appending this gen's architect `verdict` event (with its `ontology_snapshot.fields`), run the single deterministic consumer — do NOT hand-compute the SHA-1 or eyeball the rule:
     ```bash
     python -m cli.debate_converge_check --session-id <session_id> --gen <gen>
     ```
   - Branch mechanically on the exit code (stdout is one JSON line `{converged, status, this_sha, prev_sha, severity_invalidated, reason, error}`):
     - `3` = **CONVERGED** → break the loop, emit the step-5 converged output.
     - `0` = not converged → next generation. The JSON `status` says `rejected` (feed critique blockers as `critic_feedback`) or `conditional` (feed `conditions` as extra Planner input).
     - `4` = fail-CLOSED (verdict missing / parse) → escalate (operator-visible); do NOT treat as converged.
     - `2` = argparse usage error (won't happen on a correct call) — treat as `4`.
   - The CLI OWNS the single primary `convergence {status: converged|conditional|rejected}` event append (idempotent per gen), applies the **A1 severity override** internally (a `verdict_invalidated_by_severity` event for this gen forces effective verdict `rejected`, with `reason` citing `severity=invalidate forced rejection`), and computes the **canonical** `sha1(ontology_snapshot.fields)` (`lib.debate_convergence.snapshot_sha1`). The convergence RULE is unchanged — only its evaluation is now deterministic: the convergence DECISION (the append of `converged`/sha) is CLI-owned and cannot be hand-faked, BUT the `verdict` events it reads are authored by the orchestrator LLM and are NOT a trust boundary (a careless re-run could append a fake verdict — the orchestrator is an already-trusted actor, not an attacker). M10 (debate-1781937446-1281b5 D4) fail-closes only on a *contradictory* same-gen duplicate verdict; real provenance enforcement (making the CLI the sole author of the verdict append, "B2") is deferred to its own debate. Verified against the live debate sessions (M22/M18/M15) reproducing their hand-computed sha matches; tests in `tests/test_debate_convergence.py`.
   - Distinct from M14's `convergence{status: early_hard_cap}` event (step 4.5) — partitioned by `status`; consumers MUST filter by status.
   - Also log the `lib.similarity.compute_snapshot_similarity` score as a backup signal (does NOT decide convergence — Critic C-3 mitigation).

4.5. **Early hard-cap signal — DETERMINISTIC (M14, 2026-06-16; replaces the v15.40 inline pseudocode)**

   debate-1779008782-230c36 (4-gen hard_cap — Architect ontology re-abstract drift) 동기. `lib.debate_stagnation` 의 oscillation/stagnation/blocker_plateau 3-detector 가 verdict != approved 인 gen 마다 적용해 조기 hard_cap 한다. **이 step의 모든 로직 + 이벤트 append는 단일 결정론적 CLI `cli.debate_stagnation_check` 가 소유** — 마크다운은 step 4의 convergence event append 이후 그 CLI를 한 번 호출하고 **exit code로 분기만** 한다. (구 인라인 ~40줄 pseudocode 를 LLM이 일부만 실행하면 이벤트가 찢겼다; 이제 CLI가 안 돌면 fire 안 할 뿐 부분 실행은 불가능하다.)

   - **Operator overrides** (env, all optional): `DEBATE_DISABLE_EARLY_HARDCAP=1` → 본 step 전체 skip (아래 호출 자체를 안 함, legacy 4-gen). `DEBATE_OSCILLATION_WINDOW` / `DEBATE_STAGNATION_WINDOW` / `DEBATE_BLOCKER_WINDOW=N` (default 4/3/3) → **CLI가 직접 읽는다** (마크다운은 그냥 호출; 양의 정수만 인정, parse-fail/N≤0 → default).
   - **호출 (단 1줄, `DEBATE_DISABLE_EARLY_HARDCAP=1` 이면 생략)**:
     ```
     python -m cli.debate_stagnation_check --session-id <session_id> --gen <gen> --verdict <this gen's architect verdict>
     ```
     CLI는 stdout 에 JSON 1줄 `{recommend, early_hard_cap, reasons, skipped, error, gen}` 을 쓰고, **포렌식 `early_hard_cap_recommendation` 이벤트 + (fire 시) terminal `convergence{status:early_hard_cap}` 이벤트를 스스로 append** 한다. **마크다운은 이 이벤트들을 직접 append 하지 않는다** — append 책임은 전부 CLI에 있다. `--verdict approved` → CLI self-skip (exit 0); `--verdict` 누락/None → CLI fail-CLOSED (exit 4).
   - **exit code 기계적 분기** (LLM이 할 일은 이 정수 분기뿐):
     - `3` = early_hard_cap **fired** → 루프 중단, step 5 hard-cap output 으로 `status=early_hard_cap` 출력 (escalation=True, **구현 금지**). 이벤트는 CLI가 이미 append 했으니 추가 append 하지 말 것.
     - `4` = CLI 내부 에러 / **fail-CLOSED** (또는 stdout JSON `error` != null) → 루프 중단 + **operator-visible escalation** (status=error, escalation=True). **절대 silent continue 금지.**
     - `0` = clean (fire 없음) → 다음 generation 진행.
     - `2` = argparse usage error (정상 호출이면 안 남) — 발생 시 `4` 와 동일하게 escalate.
   - **LOAD-BEARING invariant**: terminal `convergence{status:early_hard_cap}` 는 *루프 종료* 마커이고, step 4의 per-gen `convergence{status: conditional|rejected}` 는 *gen-verdict* 마커다. 둘은 `status` 로 partition — 소비자는 반드시 status 로 필터해야 하며 `last_by_type('convergence')` 를 gen-verdict 로 가정하면 안 된다. (`debate_aggregate._summarize_session` 은 M14에서 status==early_hard_cap / recommendation.recommend 로 column 을 읽도록 amend됨 — EventStore 가 append-only 라 verdict 이벤트는 patch 불가하기 때문.)
   - **검증**: CLI seam 은 `tests/test_debate_stagnation_check.py` (exit code + event-append 멱등), detector 자체는 `tests/test_debate_stagnation.py` 의 `_self_check()` (71 assertions, run_units 회귀) 로 커버. 진짜 정체에서만 fire.

5. **Hard cap**
   - If gen reaches 4 without convergence: append `{status: "hard_cap", last_verdict: ...}` and exit loop.
   - Return the last verdict with `escalation = true`; do NOT implement anything.
   - **v15.40 차이점**: step 4.5 의 `early_hard_cap` 도 본 step 의 hard_cap 과 동일 output 경로 — output schema (`status` field) 만 `early_hard_cap` vs `hard_cap` 구분. 모두 `escalation=True` + 미구현.

## Fast path (gen 1 Critic bypass)
Skip step 2 in generation 1 ONLY IF all of these hold:
- Planner's `open_questions` array is empty
- The topic matches any keyword in `lib.phase_detector.STRICT_DESIGN_KEYWORDS`
- No `critic_feedback` was passed in (not resuming a prior session)

If the Architect approves the Critic-less gen 1 proposal, converge. Otherwise gen 2 runs with Critic.

## Output to the user
When converged:
- Print the Architect's final `ontology_snapshot.fields` as a numbered list.
- Print `accepted_decisions` as a checklist the user can act on.
- Print the absolute path to `events.jsonl`.
- Print `self_doubt_note` verbatim.

When hard-cap hit:
- Print every generation's `verdict` summary (1 line each).
- Print: "convergence failed after 4 generations — user decision required".
- Do NOT implement any decision unilaterally.

## Audit log (A2 wiring, commit 7aff8b7, 2026-05-10)

Every Planner / Critic / Architect dispatch within this session is recorded to `state/subagent_invocations/<session_id>.jsonl` via `lib.subagent_invocation_log.record_invocation(...)` immediately AFTER the Agent tool returns (so a successful return is observed before the audit append — failed dispatches are surfaced via the existing parse-failure path, not the audit log).

Required fields:
- `sid`: this debate's session id (`debate-<unix_ts>-<random6>`).
- `agent_name`: `"harness-planner"` | `"harness-critic"` | `"harness-architect"`.
- `tools`: read each agent's frontmatter via `lib.agent_tool_audit.expected_tools(agent_name)` — record what the agent is **declared** to have, not what it self-reports having.
- `generation`: current debate gen (1..4).
- `role`: `"planner"` | `"critic"` | `"architect"`.

Optional `extra` payload may include the topic excerpt, fast-path bypass flag, etc. — use sparingly (the canonical artifact for full payload is `events.jsonl`; this log is a cross-session retrospective grep target, not a duplicate).

**Origin field (E1 closure 2026-05-10)**: directive-emitted records MUST set `extra["origin"] = lib.subagent_invocation_log.ORIGIN_DIRECTIVE` so post-hoc grep can split directive-recorded entries from PostToolUse-hook-recorded entries (`ORIGIN_HOOK`). The PostToolUse hook (`handlers/post_tool/agent_invocation_audit.py`) records the same dispatch automatically as the platform safety net; both records are kept for cross-correlation.

Operator forensics:
```python
from lib.subagent_invocation_log import search_by_agent
search_by_agent("harness-critic", since_ts="2026-05-10T00:00:00Z")
```
returns every Critic invocation since the cutoff across **all** debate sessions — pair with the per-session `events.jsonl` for full-fidelity replay.

Failure mode: `record_invocation` raises `ValueError` only on bad sid / agent_name (path traversal, empty). Wrap in `try/except ValueError` if defensive; do NOT swallow other exceptions (the underlying `jsonl_append` is already fail-soft via `lib.logging`).

## Non-goals
- Do NOT implement accepted decisions. That is the next user action.
- Do NOT modify files outside `<CLAUDE_HOME>/state/debates/`.
- Do NOT spawn sub-tasks beyond the three debate agents (planner, critic, architect).
- Do NOT inline Planner/Critic/Architect logic in this orchestrator — always go through the Agent tool so subagent prompts stay isolated.

## Output

- session dir: `<CLAUDE_HOME>/state/debates/<session_id>/`
- events log: `events.jsonl` — append-only event sourcing (`proposal`, `critique`, `verdict`, `convergence`).
- per-generation actor outputs embedded in `payload` of each event.
- final user-facing message: numbered `ontology_snapshot.fields`, `accepted_decisions` checklist, absolute path to `events.jsonl`, `self_doubt_note` verbatim.
- status: `converged` (Architect approved + snapshot hash stable) | `hard_cap` (4 gen reached without convergence) | `early_hard_cap` (v15.40 — step 4.5 stagnation/oscillation/blocker_plateau detector fired before gen=4) | `aborted_parse_failure` (JSON parse failed twice on same actor) | `aborted_no_topic` (empty argument).

## Failure behavior

- **empty topic argument**: ask user once for one-sentence design decision; abort (`aborted_no_topic`) if reply is also empty. No session dir created.
- **actor JSON parse failure**: retry the same actor with the same prompt ONCE. On second failure, log `parse_failure` event and escalate to user (`aborted_parse_failure`). Do NOT silently substitute a default verdict.
- **Architect verdict missing/invalid**: treated as `parse_failure` (above).
- **fast-path bypass eligibility**: if gen 1 Critic is skipped per fast-path rules (empty `open_questions` + STRICT_DESIGN_KEYWORDS keyword + no `critic_feedback`) AND Architect approves the Critic-less proposal → converged. Otherwise fall through to gen 2 with full Critic. Gen-1-only convergence WITHOUT fast-path is a documentation contract, not a rule — never short-circuit on first approval alone.
- **hard cap (4 generations)**: print every gen's verdict summary + "convergence failed after 4 generations — user decision required". Implementation is then user's responsibility — engine does NOT auto-implement.

## Gate summary

- preflight: topic argument non-empty after trim; CLAUDE_HOME resolves; `state/debates/` writable.
- success criteria: convergence event written with `status=converged`. For non-fast-path: previous-and-current gen's `ontology_snapshot.fields` SHA-1 hash matches AND verdict=`approved`.
- abort triggers: empty topic after re-prompt; double parse failure on any actor; hard cap reached.

## Retry / Resume

- checkpoint: `events.jsonl` is the canonical replay log. Each generation's `proposal`/`critique`/`verdict` events let an external caller reconstruct any prior state.
- resume command: not implemented at command level — re-running `/harness-debate <topic>` mints a NEW session id. Manual resume = read prior `events.jsonl` and feed last verdict's `ontology_snapshot` as `prior_generation` to a fresh Planner call.
- idempotent: NO at session level (each invocation = new sid). YES per generation (re-running the same prompt at the same gen with the same input deterministically reaches the same verdict barring LLM nondeterminism).
- stall detection: gen counter monotonic — if a generation passes without producing a `verdict` event within reasonable wall time, treat as failure (no auto-retry beyond actor-level retry above).

## Boundary with other commands

- vs `harness-autopilot`: this **decides**, autopilot **executes**. Debate output (accepted_decisions) is autopilot's input.
- vs `harness-ralph`: this is design convergence; ralph is implementation/test verification persistence.
- vs `harness-team`: team fans out the SAME prompt to multiple AIs for diverse opinions; debate runs DIFFERENT roles (Planner/Critic/Architect) for structured convergence on a single decision.
- vs `harness-interview`: interview gathers context (questions); debate decides on a topic given context.
