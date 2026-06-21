---
description: 사용자 vision의 처음 설계 최고화 진입점 — deep-interview + research + debate + autopilot을 한 entry로 composition. 명확한 goal부터 자율 실행 완료까지. 묶음 슬래시이므로 component 안정성 ≥1개월 충족 후 도입 (HANDOFF re-open trigger 발화 — 사용자 재요청 4회+).
user-invocable: true
argument-hint: "<goal>"
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Skill, Agent, TaskCreate, TaskUpdate, AskUserQuestion
category: run
mutates: yes
long-running: yes
external-deps: WebSearch, WebFetch, mcp__context7__*
---

You are orchestrating **harness-allsolution** — the composed entry point for "처음 설계에서 최고의 설계를 하는거. 그리고 목적까지 오토파일러로 진행하는거" (사용자 vision, 다회 재발화).

## 정체성

이 슬래시는 **새 infrastructure 0** — 기존의 `/harness-interview` + `harness-researcher` agent + `/harness-autopilot`(이미 `/harness-debate` + ralph + handoff 포함)을 단일 entry로 composition합니다. 묶음의 anti-pattern 위험 (component별 ROI/안정성 차이를 약한 link 기준 통합)은 **각 component를 별도 invocation 가능 상태로 보존**하여 회피 — allsolution이 break되어도 component 슬래시들은 그대로 작동.

## 언제 쓰는가

- **AllSolution**: 새 feature/bugfix를 처음부터 끝까지 자율 진행하고 싶을 때. 명확화 + 외부 컨텍스트 수집 + 5축 설계 + 자동 구현/검증/수정 fix loop를 한 번에.
- **vs `/harness-autopilot`**: autopilot은 "goal이 충분히 명확하다" 가정. allsolution은 명확화도 사이클에 포함.
- **vs `/harness-interview`**: interview는 명확화만. allsolution은 명확화 후 실제 자율 실행까지.
- **vs `/harness-debate`**: debate는 단일 결정 수렴만. allsolution은 결정 + 실행.

## Inputs

- `goal`: 1줄~몇 단락. 명확하지 않아도 OK — Phase 0이 명확화함.
- 빈 인자: 사용자에게 한 줄 goal 묻고 그래도 비면 abort (`aborted_no_goal`).

## Protocol

### Phase A — Clarification (`/harness-interview`)

`Skill("harness-interview", args=<goal>)` 호출. 항상 실행 (autopilot의 vague-goal 분기와 달리 forced). 출력: clarified seed spec (ambiguity ≤ threshold).

- interview hard_cap 도달 → escalate to user (사용자 답변 필요).
- 사용자 abort → `aborted_user_quit_interview`.

### Phase B — Research dispatch (proactive)

`Agent(subagent_type="harness-researcher", prompt=<seed_spec + topic 정보>)`로 디스패치.

researcher의 fallback chain: local → context7 → WebSearch → WebFetch → Playwright (per agents/harness-researcher.md). 4-tier query strategy로 공식 docs / 대기업 엔지니어링 블로그 / 커뮤니티 / arxiv·scholar 논문 모두 커버.

산출: `state/research/allsolution/<unix_ts>.md` (researcher가 직접 작성). decision-relevant external context.

- researcher의 `verdict: no_research_available` → Phase C에 빈 context로 진행 (autopilot이 codebase 내부 결정만으로 판단).
- 6분 timeout (D7 implementation condition) — 초과 시 부분 결과로 진행.

**Audit log (A2 wiring, commit 7aff8b7, 2026-05-10; E1 origin tag 2026-05-10)**: after the Agent returns (success OR timeout fallback), call `lib.subagent_invocation_log.record_invocation(allsolution_sid, "harness-researcher", tools=lib.agent_tool_audit.expected_tools("harness-researcher"), generation=0, role="allsolution-researcher", extra={"phase": "B", "timed_out": <bool>, "origin": lib.subagent_invocation_log.ORIGIN_DIRECTIVE})`. PostToolUse hook records this dispatch automatically as a safety net.

### Phase C — Autonomous run (`/harness-autopilot`)

`Skill("harness-autopilot", args=<seed_spec + research_context_path>)` 호출. autopilot이 다음을 실행:

1. **Phase 0 — Design**: `/harness-debate` (research-augmented Planner-Critic-Architect, W19.1.1+). research_citations 활용.
2. **Phase 1 — Implementation**: accepted_decisions 기반 Wave parallel 구현.
3. **Phase 2 — Verification**: validators 전체 실행.
4. **Phase 3 — Fix loop**: 실패 시 `/harness-ralph` 자동 호출 (수렴까지).
5. **Phase 4 — Report**: 산출물 요약.
6. **Phase 5 — Handoff**: super-session 저장 (`state/orchestrator/<sid>/`), `next_action` 기록.

autopilot이 hard_cap 시 escalate — allsolution도 같은 sid 보존하여 사용자가 `--resume <sid>`로 재개 가능.

### Break instrumentation (deterministic — closes the self-doubt "break 빈도 측정 미구현")

Mint one `allsolution_sid` for this run (e.g. `allsol-<unix_ts>`) and, at EVERY phase
boundary below, record the phase OUTCOME via the deterministic recorder so the operator
can see WHICH phase breaks and how often (the composition's single-break-point risk):

```bash
python -c "import sys; sys.path.insert(0,'scripts'); from lib.allsolution_metrics import record_phase; record_phase('<allsolution_sid>','<phase>','<status>')"
```
- `<phase>` ∈ {`A_interview`, `B_research`, `C_autopilot`, `D_synthesis`}
- `<status>` ∈ {`ok` (completed), `broke` (failed/aborted), `escalated` (hard_cap → user), `skipped` (intentionally not run, e.g. research no-op)}

Record `ok` after a phase succeeds, `escalated` on a hard_cap/abort that hands to the
user, `broke` on an unexpected failure, `skipped` when a phase is intentionally bypassed.
Aggregate any time with `python -m lib.allsolution_metrics` (per-phase break_rate +
most-fragile phase). This is fail-soft — a recording error never blocks the run.

### Phase D — Synthesis

allsolution 자체의 종합 산출물 작성: `state/allsolution/<unix_ts>.md`.

내용:
- Phase A: clarified spec
- Phase B: research artifact path + key citations
- Phase C: autopilot super-session sid + 결과 요약
- 다음 행동 추천 (또는 `done`)

## Non-Goals

1. **PreToolUse 차단**: allsolution은 advisory + composition만. 사용자 도구 호출 차단하지 않음.
2. **새로운 LLM provider 통합**: 기존 harness-debate + harness-researcher 인프라 사용.
3. **multi-goal scheduling**: 한 번에 하나의 goal. 여러 개 필요 시 사용자가 sequential 호출.
4. **재검토 트리거**: ① 분리 invocation cost가 사용자 인지 부담으로 1주 ≥5회 측정 (HANDOFF deferred 명시) ② 각 component (interview, researcher, autopilot) 안정 운영 ≥1개월 — 두 조건 모두 충족 시 묶음 debate. **현 시점 (2026-05-08): trigger 발화** — 사용자가 vision 재요청 4회+. 따라서 implement.

## Failure behavior

- **goal 빈 인자**: 한 번 재질문, 그래도 비면 `aborted_no_goal`.
- **interview hard_cap**: escalate to user (allsolution은 사용자 답변 없이 진행 안 함).
- **researcher no_research_available**: 빈 context로 Phase C 진행 (autopilot이 처리).
- **autopilot hard_cap (debate / ralph 어느 쪽)**: super-session sid 보존 + escalate. 사용자가 `/harness-autopilot --resume <sid>`로 재개 가능.
- **idempotent**: NO at session level (각 호출 = 새 trace). YES at sub-component level (autopilot --resume 사용 시).

## Output

- artifact: `state/allsolution/<unix_ts>.md` (Synthesis 산출물)
- intermediate: `state/interview/<sid>/`, `state/research/allsolution/<ts>.md`, `state/orchestrator/<sid>/`
- status: `complete` | `aborted_no_goal` | `aborted_user_quit_interview` | `aborted_autopilot_hardcap` | `escalated`

## Boundary with other commands

- vs `/harness-interview`: 단일 명확화 단계만 vs 명확화→실행 전체.
- vs `/harness-debate`: 단일 결정 수렴 vs 결정+실행+검증.
- vs `/harness-autopilot`: 명확한 goal 가정 vs 명확화부터 시작.
- vs `/harness-ralph`: 검증 실패 fix loop vs 처음부터 끝까지.
- vs `/harness-team`: 단일 agent execution vs 병렬 worker fanout (team mode 통합은 future work).

## 사용 예

```
/harness-allsolution "scripts/lib/handoff_drift.py에 promotion 자동 적용 (yaml flat→nested 재구성) 함수 추가 + 테스트"
```

위 호출은:
1. interview가 "promotion 자동 적용"의 정확한 의미 / failure semantic / rollback 요구사항 명확화.
2. researcher가 yaml round-trip best practice (PyYAML round-trip vs ruamel.yaml comment preservation 등) 외부 사례 수집.
3. autopilot이 5축 debate → 구현 → validators → ralph 사이클로 수렴.
4. Synthesis 산출물에 다음 행동 추천.

## Self-doubt

이 묶음의 가장 큰 risk는 **단일 break point 존재** (interview가 죽으면 전체 죽음). 완화책: component 슬래시는 모두 별도 invocation 가능 상태 유지 — allsolution이 break되어도 사용자가 component를 직접 호출 가능. 그러나 break 빈도 측정은 별도 metric 필요 (현재 미구현).

이 슬래시 자체의 deferred에서 closure로 전환된 근거는 HANDOFF의 명시적 re-open trigger (사용자 재요청). 그 이상의 정량 근거는 운영 데이터 누적 후 검증.
