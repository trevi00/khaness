---
description: DGE E2 Evaluator 수동 호출 — 6축 (응집·결합·확장·안정·사용+완성도) 진단 점수 + verdict (approved|iterate|escalate). paradox guard 3-condition + completeness boolean GATE으로 self-validation paradox 회피. autopilot Phase 4 자동 dispatch와 동등한 entry. `--ensemble` (v15.35.2+) → 다중 provider 풀 합의 (codex + ollama 등).
user-invocable: true
argument-hint: "<orch_sid> [--phase=<phase_id>] [--json] [--ensemble]"
allowed-tools: Read, Write, Bash, Grep, Glob, Agent
category: verify
mutates: yes
long-running: yes
external-deps: none
---

You are orchestrating **harness-evaluate** — DGE E2 evaluator manual entry. Per debate-1778248254-0b7092 (4-gen converged) + Phase A interview lock.

## Inputs

- `orch_sid`: target super-session id (e.g., `orch-1778248216-bff1e3`). Must exist under `state/orchestrator/<sid>/`. Empty → abort `aborted_no_sid`.
- `--phase=<phase_id>`: optional phase to evaluate. Default `phase_4` (autopilot Phase 4 hook target).
- `--json`: machine-readable output (default plaintext rendering).
- `--ensemble` *(v15.35.2+)*: switch dispatch from single-evaluator (Agent path) to multi-provider quorum (`lib.evaluator_dispatcher.invoke_ensemble_evaluator`). Default pool = codex + ollama (host-conditional graceful degradation to N=1 if ollama absent). Output adds per-vote breakdown + quorum size + split flag. Mutually compatible with `--json`.

## Protocol

### 1. Pre-flight gates

1. Verify `state/orchestrator/<orch_sid>/events.jsonl` exists. Missing → `aborted_unknown_sid`.
2. Resolve evaluator model: `lib.evaluator.resolve_evaluator_model()` — returns `""` (delegate to Codex CLI default) when EVALUATOR_MODEL unset; raises `ConfigError` if EVALUATOR_MODEL is Anthropic-family without EVALUATOR_ALLOW_SAME_FAMILY=1. Surface error verbatim → `aborted_config_error`.
3. Check dispatch eligibility: `lib.evaluator_dispatcher.should_dispatch(orch_sid, phase_id)` — must return ELIGIBLE (not OVER_LIMIT or DISABLED). OVER_LIMIT → `aborted_over_per_phase_limit` with current counter shown.

### 2. Build evaluator inputs

Collect from orchestrator state:
- `artifact_under_evaluation`: most recent commit diff associated with the phase (via `git diff` or `state/orchestrator/<sid>/artifacts/<phase_id>.txt` if present)
- `phase_locks`: Designer ontology snapshot (read from linked debate child sid's last verdict event) + paradox-guard inputs:
  - `test_pass` from latest validators+units run
  - `research_citation_count` from linked research artifact (e.g., `state/research/allsolution/*.md` or debate Architect's evidence_review)
  - `ontology_match` flag from comparing artifact-claimed-ontology vs Designer-locked ontology
- `axis_rubric`: standard 5-axis guide + completeness boolean criteria (load from `agents/harness-evaluator.md`)

### 3. Paradox guard (deterministic, pre-LLM)

`lib.evaluator.paradox_guard(test_pass, citation_count, ontology_match)` returns `ParadoxGuardResult`. If `passes=False`:
- DO NOT invoke harness-evaluator subagent
- Call `fallback_to_legacy_e2` (positional args 모두 필수 — v15.40.1 fix 패턴):
  ```python
  fb = fallback_to_legacy_e2(
      FallbackReason.PARADOX_GUARD_FAIL, orch_sid, phase_id,
      validators_passed=test_pass, units_passed=test_pass,
      known_defects=defect_count,
  )
  verdict_str, completeness = fb["verdict"], fb["completeness"]
  fallback_reason = fb["fallback_reason"]
  ```
- Log the fallback event via `lib.axis_scores_log.log_axis_event(orch_sid, fb)` (fb 가 이미 schema-compatible dict)
- Skip to step 6 (output)

### 4. Spawn harness-evaluator subagent (D3 isolation)

`lib.evaluator_dispatcher.build_evaluator_prompt(artifact, phase_locks, axis_rubric)` → render prompt. Validate via `validate_prompt_isolation()` — match → reject before spawn (dispatcher bug; do NOT silently scrub).

`Agent(subagent_type="harness-evaluator", prompt=<rendered>)` with timeout=120s (`SUBAGENT_TIMEOUT_SECONDS`). On timeout/exception path (positional args 명시):
```python
import subprocess
try:
    result = Agent(subagent_type="harness-evaluator", prompt=rendered)
except subprocess.TimeoutExpired:
    fb = fallback_to_legacy_e2(
        FallbackReason.SUBAGENT_TIMEOUT, orch_sid, phase_id,
        validators_passed=test_pass, units_passed=test_pass,
        known_defects=defect_count,
    )
    verdict_str, completeness = fb["verdict"], fb["completeness"]
    # then step 5 (skip parse)
except Exception:
    fb = fallback_to_legacy_e2(
        FallbackReason.SUBAGENT_EXCEPTION, orch_sid, phase_id,
        validators_passed=test_pass, units_passed=test_pass,
        known_defects=defect_count,
    )
    verdict_str, completeness = fb["verdict"], fb["completeness"]
```
`fallback_to_legacy_e2` return type: `FallbackResult` TypedDict (9 keys, v15.40.4 commit 89c8c3c).

**Audit log (A2 wiring, commit 7aff8b7, 2026-05-10; E1 origin tag 2026-05-10)**: immediately after the Agent tool returns (success OR caught timeout/exception — record both paths so forensics can correlate timeout incidence), call `lib.subagent_invocation_log.record_invocation(orch_sid, "harness-evaluator", tools=lib.agent_tool_audit.expected_tools("harness-evaluator"), generation=0, role="evaluator", extra={"phase_id": phase_id, "fallback": fallback_reason or "none", "origin": lib.subagent_invocation_log.ORIGIN_DIRECTIVE})`. The fallback path's `record_invocation` is what later forensics use to distinguish "evaluator was healthy" from "evaluator failed N times this week" — do NOT skip the log on the fallback branch.

### 4b. Alternative dispatch — ensemble (`--ensemble`, v15.35.2+)

When `--ensemble` is passed, replace step 4's single-subagent `Agent` call with a Python-level call to `lib.evaluator_dispatcher.invoke_ensemble_evaluator`:

```python
from lib.evaluator_dispatcher import (
    build_evaluator_prompt,
    invoke_ensemble_evaluator,
    axis_log_emit_for,
)

prompt = build_evaluator_prompt(artifact, phase_locks, axis_rubric)
# Variable name 'ensemble_result' (NOT 'verdict') — step 6 의 dict
# literal `{event:'verdict', ..., verdict: <str>}` 에 객체가 그대로
# 들어가 JSON serialize fail 방지. step 6 에서 str unpack 사용.
ensemble_result = invoke_ensemble_evaluator(
    prompt,
    sid=orch_sid, phase_id=phase_id,
    validators_passed=test_pass, units_passed=test_pass, known_defects=defect_count,
    evaluator_specs=None,                      # → default pool (codex + ollama if avail)
    emit_fn=axis_log_emit_for(orch_sid),       # ensemble.aggregated → axis_scores.jsonl
)
# step 6 에서 사용할 str + breakdown 미리 unpack:
verdict_str = ensemble_result.quorum_verdict   # str 'approved'|'iterate'|'escalate'
ensemble_completeness = all(v.completeness for v in ensemble_result.votes)
```

Returns `lib.ensemble_evaluator.EnsembleVerdict` (7 fields — see EnsembleVerdict docstring §Caller-side accessor guide for `.verdict` vs `.quorum_verdict` distinction, v15.40.3 broken history):
- `quorum_verdict`: 'approved' | 'iterate' | 'escalate' (ensemble paradox layer applied — `paradox_guard_all_pass=False` AND raw quorum=='approved' is downgraded to 'escalate')
- `quorum_size` / `threshold`: ⌈N/2⌉ majority size
- `votes`: tuple[EvaluatorVote] per spec (provider/verdict/completeness/paradox_guard_passes/fallback_reason/axis_scores)
- `split`: True if no majority (every label below threshold OR tied at max)
- `escalation_reasons`: tuple[str] explaining split + paradox-layer downgrades
- `paradox_guard_all_pass`: bool — every vote had paradox_guard_passes=True

Pre-conditions enforced:
- `validate_evaluator_pool([s.provider for s in specs])` raises on Anthropic-family contamination (testing-only escape hatch from `lib.evaluator.EVALUATOR_ALLOW_SAME_FAMILY` does NOT apply at ensemble layer — pool must always be cross-provider)
- Per-spec `validate_prompt_isolation(prompt)` enforced inside each `invoke_fn` (default codex path via `invoke_evaluator_isolated`; ollama path via `_invoke_ollama_evaluator`)
- Per-spec `subprocess.TimeoutExpired` / Exception → fallback vote (paradox_guard_passes=False, verdict from `fallback_to_legacy_e2`)

Audit log (single ensemble-mode `record_invocation` with `extra={"ensemble": True, "pool_size": <N>, "providers": [...]}`).

Skip step 4's single-subagent block AND step 5's parse/clamp (per-vote clamp is already applied inside `_vote_from_parsed`). Proceed to step 6 with `verdict_str` (string) + `ensemble_completeness` (bool) + `ensemble_result.votes` (breakdown).

### 5. Parse + post-LLM normalization (D5 clamp)

Parse subagent JSON. On parse failure: retry once; second failure → fallback path with `SUBAGENT_EXCEPTION`.

`parsed` 는 JSON parse 결과 = **dict** (Python `dict[str, Any]`, NOT dataclass). 따라서 access 는 dict subscript:

```python
import json
parsed = json.loads(<subagent_raw_output>)  # dict
verdict_raw = parsed.get("verdict", "iterate")        # str
completeness = bool(parsed.get("completeness", False))  # bool

from lib.evaluator import clamp_verdict_on_completeness
clamped_verdict, clamp_reason = clamp_verdict_on_completeness(
    verdict_raw, completeness,
)
# clamp_reason 가 None 이 아니면 axis_scores.jsonl 에 clamp event 발생
```

if completeness=False AND verdict='approved', clamp to 'iterate' + emit clamp event to `axis_scores.jsonl`.

Build final `EvaluatorVerdict` dataclass (`lib.evaluator.EvaluatorVerdict`, 7 fields: verdict / paradox_guard / axis_scores / reasons / model_used / sid / fallback_reason).

### 6. Persist + dispatch counter

- `lib.axis_scores_log.log_verdict_event(orch_sid, {event:'verdict', phase, verdict, axes, completeness, model_used, fallback_reason?, clamp?}, cross_target=(fallback_reason is None))` — required schema_version field auto-injected. **cross_target write side (2026-06-18)**: `log_verdict_event` marks the FIRST genuine LLM E2 verdict on a generator artifact with `cross_target_first_invocation=True` so `operational_metrics.get_dge_e2_cross_target_count` (read side) can count it — the previously-absent write half of that metric. Pass `cross_target=(fallback_reason is None)`: a paradox-guard / timeout / exception fallback is validators+units only, NOT a real cross-provider evaluation, so it must not increment the metric. On the `--ensemble` path the marker is the caller's responsibility too — pass `cross_target=ensemble_result.paradox_guard_all_pass` (a fully-fallback quorum should not count).
  - **str values 만 dict 안에 들어가야 함** (JSON serialize-able). single-subagent path 는 `parsed.verdict` 사용, ensemble path 는 step 4b 의 `verdict_str` 사용 — 절대 `ensemble_result` 전체 객체 또는 EnsembleVerdict / EvaluatorVerdict dataclass 를 dict value 로 넣지 말 것.
  - `axes` dict value 는 `{cohesion: int 1-5, coupling: int 1-5, ...}` — ensemble path 의 votes 의 worst-axis reduction 또는 첫 vote 의 axis_scores 사용 가능.
  - `completeness` 는 step 4b ensemble 의 경우 `ensemble_completeness` (all votes pass) 사용.
- `lib.evaluator_dispatcher.record_dispatch(orch_sid, phase_id)` — increment counter regardless of fallback or LLM path (loop guard accounting).

### 7. Output

Plaintext (default):
```
Evaluator verdict for <orch_sid> @ <phase_id>: <verdict>
  Axes (1-5): cohesion=N coupling=N extensibility=N stability=N usability=N
  Completeness: <True|False> (validators=B units=B defects=N)
  Paradox guard: <passes|failed>
  Model: <model_id>  Fallback: <none|reason>
  Reasons:
    - <axis>:<code>: <detail>
    ...
  Dispatch counter: <phase_id>=<N>/<PER_PHASE_EVAL_LIMIT>
```

Plaintext (`--ensemble`):
```
Ensemble verdict for <orch_sid> @ <phase_id>: <quorum_verdict>
  Quorum: <quorum_size>/<N> (threshold=<⌈N/2⌉>)  Split: <True|False>
  Paradox layer: <all_pass|downgraded>
  Per-vote breakdown:
    - [<provider>] <evaluator_id>: <verdict>  completeness=<bool>  paradox=<bool>  [fallback: <reason>]
    ...
  Escalation reasons (if any):
    - <reason>
  Dispatch counter: <phase_id>=<N>/<PER_PHASE_EVAL_LIMIT>
```

JSON (`--json` or `--json --ensemble`): full `EvaluatorVerdict` dataclass OR `EnsembleVerdict` dataclass (votes serialized) + dispatch counter.

## Exit codes

- 0: success (verdict produced — any of approved/iterate/escalate)
- 1: aborted_unknown_sid OR aborted_no_sid
- 2: aborted_config_error (cross-provider invariant violation)
- 3: aborted_over_per_phase_limit
- 4: aborted_isolation_violation (prompt scrub failed — dispatcher bug)

## Non-Goals

- 자동 dispatch from Phase 4 — `lib.evaluator_dispatcher` does that path; this command is the manual operator entry. **`--ensemble` does NOT change Phase 4 auto-dispatch** — autopilot still calls `invoke_evaluator_isolated` (single-evaluator path). Switching autopilot to ensemble requires operator token gate (CLAUDE.md L0 NEVER 자동, runtime policy mutation).
- Multi-orch fan-out — one sid per invocation.
- Generator side modification — evaluator is read-only on artifact + test results.
- Re-running validators+units — caller must ensure latest run is fresh; this command consumes the last result.
- `--ensemble` does NOT mutate the default pool composition — `_build_default_ensemble_specs()` returns host-conditional codex + ollama (when available). Custom pool injection (e.g., `--pool=codex,deepseek`) deferred to next cycle.

## Failure behavior

- **paradox guard fail with clean tests**: verdict='escalate' (operator review required: why does guard fail when tests pass?)
- **paradox guard fail with failing tests**: verdict='iterate' (regression — fix tests first)
- **subagent timeout/exception with clean tests**: verdict='iterate' (LLM failed transiently; objective tests are clean)
- **subagent timeout/exception with failing tests**: verdict='iterate' (regression mode)
- **prompt isolation violation**: hard abort exit 4 — operator must inspect `lib/evaluator_dispatcher.py` template

## Boundary with other commands

- vs `/harness-debate`: debate is design-time E1 (Designer evaluator). This is post-Generator E2.
- vs `/harness-autopilot`: autopilot Phase 4 자동 호출이 본 명령과 동일 entry. 수동 호출은 부분 phase 평가 또는 retroactive 검토용.
- vs `/harness-ralph`: ralph는 validator FAIL 후 fix loop. 본 명령은 verdict 생성만 (fix 미실행).

## Self-doubt

본 명령의 가장 큰 위험: paradox guard short-circuit이 **upstream에서** 호출자 (autopilot Phase 4) 책임이지만, 본 CLI는 step 3에서 자체 가드를 다시 돈다. 이중 보호 — 비용은 1 deterministic call (LLM 호출 없음). 만약 향후 paradox guard가 expensive해지면 (예: 외부 API call 추가), 본 CLI에서 redundant call 회피 옵션 별도 결정 필요.
