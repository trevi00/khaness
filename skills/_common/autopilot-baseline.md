---
name: autopilot-baseline
description: autopilot Phase 4 E2 evaluator의 paradox guard / 5축 advisory / 완성도 boolean GATE에 대한 baseline 통계 — example_project-analysis 47-step + 384/384 tests / 회귀 0 evidence에서 추출. evaluator가 verdict='approved' 결정 시 reference data로 활용.
keywords: [autopilot, evaluator, paradox-guard, completeness-gate, 5-axis, baseline, e2, verdict]
intent: [evaluate, verdict, audit, benchmark, codify-completion]
phase: review
min_score: 4
---

# Autopilot Baseline — Phase 4 E2 Evaluator Reference

> **사용자 비전 (CLAUDE.md DGE E1/E2 분리 직속)**: paradox guard (`test_pass AND research_citation_count>=3 AND ontology_match`) 충족 시에만 `verdict='approved'`. 5축 advisory 1~5 score + 완성도 strict boolean GATE.
>
> **본 스킬의 책임**: evaluator가 verdict 산출 시 "이 점수가 baseline 대비 평균/상위/하위 어느 분위인지" 판단 가능한 정량 reference. 본 분석 폴더의 47-step evidence를 압축.
>
> **검증 출처**: `/home/user/example_project-analysis/` 세션 (47 step + 59 commit + 외부 9600 LOC / 384/384 tests / 회귀 0 / 시스템 평균 4.555 [28-sub] / 4.53 [9-cat] / Δ 0.025).

## 핵심 원칙 (CLAUDE.md DGE E2 직속)

### paradox guard 3-condition (AND 결합, all-true 필수)

```
verdict='approved' ⟺ test_pass=True
                  ∧ research_citation_count >= 3
                  ∧ ontology_match=True
```

하나라도 false → `verdict ∈ {iterate, escalate}` + 구 E2 fallback (validators + run_units) 자동 활성.

### 완성도 strict boolean GATE (5축 외 별도 axis)

```
완성도=True ⟺ validators_pass_pct == 100%
            ∧ unit_pass_pct == 100%
            ∧ known_defects == 0
```

5축 (응집·결합·확장·안정·사용)은 1~5 advisory score (informative). 완성도만 strict — false면 verdict='approved' 차단.

### Judge-Generator 분리 (provider 수준)

- evaluator: `OpenAIProvider` (codex exec subprocess) — Anthropic 가족 차단
- generator: claude-code parent context (Anthropic)
- `EVALUATOR_MODEL` env unset → Codex CLI default 위임 (`""`)
- `EVALUATOR_ALLOW_SAME_FAMILY=1` → testing-only override

## 의사결정 트리

### IF E2 dispatch (autopilot Phase 4 자동 1회 OR `/harness-evaluate <orch_sid>`)
1. paradox_guard 3-condition 계산
2. all-true → 본 baseline의 5축 advisory + 완성도 GATE 평가
3. one-false → fallback (validators + run_units)
4. LLM/subagent timeout → fallback 동일

### IF verdict 결정
- 완성도=True AND 5축 평균 ≥ 본 baseline 평균 → `approved`
- 완성도=True AND 5축 평균 < baseline 평균 → `iterate` (조정 후 재dispatch)
- 완성도=False → `iterate` 또는 `escalate` (defect 수 비례)

### IF baseline 갱신 (living)
- 새 evidence 1000+ test passes 누적 시 본 스킬의 §baseline 통계 갱신
- 새 5축 분포 변동 (±0.3) 시 advisory anchor 재산출

## §1. 47-step Evidence 압축

본 분석 폴더 `example_project-analysis` 47-step의 누적 지표 (paradox guard / 5축 / 완성도 baseline 산출 근거):

| 지표 | 값 |
|---|---|
| 총 step | 47 (abstraction-first 33 + integration 7 + 메타 11, impl-1 ~ impl-51) |
| 외부 commits | 37 (5 branch) |
| 외부 LOC 추가 | 9600 |
| 외부 test passes | 384/384 (D11 mock-parity 138/140 외) |
| 회귀 | 0 (47 step 전체) |
| 분석 폴더 commits | 59 |
| 시스템 평균 (9-cat) | 4.53 (612/135 셀) |
| 시스템 평균 (28-sub) | 4.555 (1913/420 셀) |
| 두 view 일관성 (Δ) | +0.025 (모든 도메인 ±0.5 통과) |

## §2. Paradox Guard 3-condition Baseline

### 2.1 test_pass 만족 빈도

47 step 중:
- test_pass=True: **47 / 47 (100%)** — 회귀 0 invariant
- test_pass=False: 0 — fallback dispatch 0회

**Baseline**: production-grade abstraction-first 적용 시 test_pass=True가 expected default. False가 발생하면 즉시 abort + 원인 추적.

### 2.2 research_citation_count 분포

본 분석에서 evidence-grounded citation 평균:

| step 분류 | citation 수 평균 | 분포 |
|---|---|---|
| abstraction-first 변형 (V1~V16) | 3~5건 | PATTERNS-CATALOG entry SHA + 변형 ID + 적용 commit |
| integration step | 4~6건 | 안티패턴 매트릭스 + 회귀 감쇄 패턴 + 이전 sub-task SHA |
| 메타 (skill / template 작성) | 5~8건 | 분석 폴더 path + AUTOPILOT-PLAN 명시 + 외부 commit evidence + 짝 스킬 |

**Baseline**: 평균 citation 수 ≥ **3건**이 paradox guard 최소 기준. 본 47-step 평균 ~5건 — `research_citation_count>=3` 자연 만족.

### 2.3 ontology_match 만족 패턴

ontology = 본 분석 폴더의 3-tier backbone (PATTERNS-CATALOG + SCORING-RUBRIC + VERIFICATION) snapshot.

- 매 sub-task가 PATTERNS-CATALOG V1~V16 중 하나에 매핑 → ontology_match=True
- integration step도 안티패턴 매트릭스 5 케이스 중 하나에 매핑 → match=True (반례 카테고리지만 명시적)
- 미매핑 case 0건 (47/47 매핑)

**Baseline**: ontology_match=True가 expected. False → ontology 확장 후보 (V17, V18, ... 추가 또는 새 anti-pattern 추가).

## §3. 5축 Advisory Anchor (1~5 score)

본 분석 47-step의 5축 평균 분포:

### 3.1 응집 (Cohesion)

| 점수 | 의미 | 본 분석 분포 |
|---|---|---|
| 1 | 26K 모놀리식 진입 시 본문 logic 변경 | 0회 (분석 폴더는 monolith 진입 시 변경 < 0.5% 유지) |
| 3 | 부분 분리 (책임 1~2개 분리) | 일부 helper 분리 케이스 |
| 5 | 단일 책임 crate + 명확한 boundary | 신규 모듈/crate 23 application (V1~V16) |

**Baseline 평균**: **4.53** (M.응집 sub-attribute 평균과 일치). approved verdict 임계 ≥ 4.0.

### 3.2 결합 (Coupling)

| 점수 | 의미 | 본 분석 분포 |
|---|---|---|
| 1 | tight coupling, 변경 chain | 0회 |
| 3 | 일부 trait 추상 | 일부 |
| 5 | trait + REGISTRY + DI | 다수 (Lib REGISTRY 패턴) |

**Baseline 평균**: **4.53** (M.결합 sub). approved 임계 ≥ 4.0.

### 3.3 확장 (Extensibility, derived)

E.확장 = avg(M.응집 + M.결합 + M.모듈 + C.공존 + C.상호) / 5

| 도메인 분포 | 점수 | 본 분석 도메인 |
|---|---|---|
| Top (5.0) | provider-routing / openai-compat / mcp-plugins | D4 / D7 / D8 |
| 중간 (4.4~4.6) | allsolution / worker-queue / permission-trust / session-events / psmux-team / nl-cron / user-modeling | D2/D3/D5/D6/D10/D14/D15 |
| Bottom (3.4) | discord-ops / operator-hud | D1 / D9 (모놀리식) |

**Baseline 평균**: **4.4** 전 도메인 평균. approved 임계 ≥ 4.0.

### 3.4 안정 (Stability, R.무결 + R.결함 + R.회복 평균)

| 점수 | 의미 |
|---|---|
| 1 | retry 0 + 재기동 손실 + idempotent 안 됨 |
| 3 | 일부 retry + 일부 cold-resume + 일부 idempotent (upsert) |
| 5 | 4-tier fallback + durable artifact + append-only/idempotent/monotonic/WAL |

**Baseline 평균**: **4.60** (R.* 평균). approved 임계 ≥ 4.0.

### 3.5 사용 (Usability, U.학습 + U.보호 평균)

| 점수 | 의미 |
|---|---|
| 1 | 명령 학습 비용 높음 + mutate 게이트 0 |
| 3 | 일부 doc + 일부 confirm 토큰 |
| 5 | next_command chain + 모든 mutate 토큰 + private 채널 격리 |

**Baseline 평균**: **4.53** (U.* 평균). approved 임계 ≥ 4.0.

### 3.6 5축 종합 baseline

```
평균 (47-step):    응집 4.53  결합 4.53  확장 4.40  안정 4.60  사용 4.53
종합 평균:         4.518
approved 임계:    각 축 ≥ 4.0 AND 종합 평균 ≥ 4.3
iterate 임계:     각 축 ≥ 3.0 AND 종합 평균 ≥ 3.5
escalate 임계:    어느 축이든 < 3.0
```

## §4. 완성도 Strict Boolean GATE 통계

본 분석 47-step의 완성도 GATE 만족 빈도:

### 4.1 validators_pass_pct == 100%

- 47 / 47 step에서 외부 repo `cargo test -p <crate>` 100% pass
- 분석 폴더 자체 validator는 적용 안 함 (read-only)

**Baseline**: 100% 만족 = expected default.

### 4.2 unit_pass_pct == 100%

- 외부 384/384 tests 100% pass 누적
- 신규 test만 카운트: 47 step에서 ~250+ 신규 unit/integration tests 추가, 0 failures

**Baseline**: 100% 만족 = expected default.

### 4.3 known_defects == 0

- D1 chunk silent fail (impl-24 `3acb3bb`)이 유일한 detected defect → 즉시 fix (시스템 점수 +1/420 unlock)
- 그 외 47 step에서 known_defects=0 유지

**Baseline**: 0 = expected default. Detected → 즉시 fix → 0 복귀가 normal flow.

## §5. Verdict 결정 Matrix

본 baseline 기반 evaluator verdict 결정:

| paradox_guard | 5축 평균 | 완성도 | verdict |
|---|---|---|---|
| all-true | ≥ 4.3 | True | **approved** |
| all-true | 3.5 ~ 4.3 | True | iterate (5축 조정) |
| all-true | < 3.5 | True | iterate (5축 약점 fix) |
| all-true | any | False | iterate (완성도 우선) |
| one-false | — | — | iterate OR escalate (fallback 활성) |

## §6. 5축 약점별 Fix 권고

verdict='iterate' 시 evaluator가 reporting할 5축 약점별 권고:

| 약축 | 약점 패턴 | Fix 권고 (PATTERNS-CATALOG 참조) |
|---|---|---|
| 응집 | 모놀리식 monolith | V7 helper 분리 + delegate refactor + integration step 안티패턴 회피 |
| 결합 | tight chain | V4 adapter wiring + V5 noop+factory + REGISTRY 도입 |
| 확장 | 새 component 추가 cost 높음 | V3 enum variant + V16 호모모피즘 + workspace.dependencies |
| 안정 | retry/fallback 부재 | V9 silent→explicit + V10 state machine + V12 fire-history pure state |
| 사용 | doc/토큰 부재 | next_command chain + confirm 토큰 + private 채널 격리 (U.보호 anchor 5) |

## Self-improvement loop

본 baseline은 **living statistics**. 갱신 트리거:

1. **새 1000+ test passes 누적** → §1 외부 LOC + test passes 갱신
2. **신규 변형 V17, V18 등록** → §2.3 ontology snapshot 확장
3. **5축 평균 ±0.3 변동** → §3 anchor 분포 재산출
4. **새 paradox guard condition** (예: license_pass) → §2에 4th condition 추가

## Gotchas

### baseline을 단일 값으로 오용
4.53은 평균. Top 도메인 5.0 / Bottom 3.4 분포 존재. verdict 산출은 **분포 위치**로 결정 (top tier / 중간 / bottom). 평균만으로 approved/iterate 결정하지 않는다.

### completeness GATE를 5축에 통합
완성도는 strict boolean — 5축 advisory와 평균 못 함. 별도 axis로 처리.

### paradox guard fail 후 fallback에 의존
fallback (validators + run_units)은 paradox guard 통과 못한 케이스의 최소 보장. fallback이 자주 발화하면 ontology / citation 정책 보강 필요 — fallback은 emergency parachute지 정상 path 아님.

### Judge-Generator 분리 violation
`EVALUATOR_MODEL=claude-*` 설정은 testing-only. production에서 Anthropic 가족 evaluator 차단 — 자기 평가 paradox 회피가 본 분리의 목적.

### Living baseline을 frozen reference로 오용
본 baseline은 47-step 시점 snapshot. 1000+ step 누적되면 분포 변동 가능. 매 1000+ test passes 누적 시 §1 갱신.

## 짝 스킬 (peer / 글로벌 메타 자산 일습)

본 H5 스킬로 Stage 3 5-skill 짝 완성:

| 스킬/template | 역할 | DGE phase |
|---|---|---|
| `~/.claude/skills/_common/abstraction-first.md` (H2) | 16 변형 / 33 application | Designer (E1 변형 선정) |
| `~/.claude/skills/_common/repeat-error-tracker.md` (H1) | 9 entry + anti-pattern matrix | negative space (회피) |
| `~/.claude/skills/_common/iso25010-scoring.md` (H3) | 28 sub × 9 카테고리 | Evaluator (정량 평가) |
| `~/.claude/templates/verification/` (H4) | 5 Gates + 3-tier backbone + audit matrix | Designer 검증 (audit) |
| **`~/.claude/skills/_common/autopilot-baseline.md` (H5, 본)** | paradox guard + 5축 + 완성도 baseline | **Evaluator (E2 verdict baseline)** |

CLAUDE.md DGE 전 phase + autopilot Phase 4 E2 모두 보편 도구로 cover됨.

## 도구 사용 패턴 (Harness)

- E2 dispatch 직전: `Read ~/.claude/skills/_common/autopilot-baseline.md` (본 파일) — paradox guard 3-condition + 5축 baseline lookup
- verdict 결정 시: §5 matrix 참조
- iterate verdict: §6 약점별 fix 권고로 next round 가이드
- baseline 갱신: `Edit` 본 파일에 §1 통계 + §2 분포 + §3 평균 갱신

## 에러 복구 패턴 (Harness)

- paradox_guard fail 반복 → ontology 확장 (PATTERNS-CATALOG V17, V18 추가) 또는 citation 정책 강화 (분석 폴더 SHA 인용)
- 5축 평균 baseline 미달 → §6 약점별 PATTERNS-CATALOG 변형 적용 후 재dispatch
- 완성도 boolean fail → defect 즉시 fix (V9 silent→explicit type 활용 가능)
- LLM/subagent timeout → fallback 정상 — emergency parachute로 인정 + EVALUATOR_MODEL env 확인

## 출처 인용

| 출처 | 위치 |
|---|---|
| 분석 폴더 evidence | `/home/user/example_project-analysis/` (47 step, impl-1 ~ impl-51, 59 commit) |
| VERIFICATION matrix | `.claude/requirements/VERIFICATION.md` §9 (15 × 28 = 420 셀, 시스템 평균 4.555) |
| SCORING anchor | `.claude/requirements/SCORING-RUBRIC.md` (1·3·5 anchor) |
| PATTERNS variants | `.claude/requirements/PATTERNS-CATALOG.md` (16 변형 / 33 application — ontology snapshot 출처) |
| CLAUDE.md DGE E2 | `~/CLAUDE.md` §1 핵심 3원칙 — paradox guard 3-condition + 완성도 strict boolean GATE 정의 |
| 외부 commits | `/home/user/example_project/` (5 branch / 37 commit / 9600 LOC / 384/384 tests / 회귀 0) |
| AUTOPILOT-PLAN §3 H5 | `synthesis/AUTOPILOT-PLAN.md` (본 스킬의 의도 lock) |
| W19.1.1+ amendment | debate-1778248254-0b7092 (4 gen 수렴, ontology SHA-1 21fb480910cf...) |
