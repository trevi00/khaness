---
name: trace
description: Evidence-driven tracing workflow — orchestrates competing hypotheses via harness-tracer to explain WHY an observed result happened.
keywords: [trace, tracing, why, causal, hypothesis, evidence, rebuttal, discriminating-probe]
intent: [trace, explain, investigate, diagnose]
phase: debug
min_score: 2
---

# Trace Skill

Ambiguous, causal, evidence-heavy questions where the goal is to **explain why** an observed result happened — not to jump into fixing/rewriting code.

This is the orchestration layer on top of `harness-tracer` agent. Reusable operating lane: restate observation → generate competing explanations → gather evidence in parallel → rank → propose next probe.

## 좋은 진입 케이스

- 런타임 버그 / 회귀
- 성능 / 레이턴시 / 리소스 거동
- 아키텍처 premortem / postmortem
- 실험 결과 tracing
- 설정 / 라우팅 / 오케스트레이션 거동 설명
- "이 출력이 나왔다 — 원인을 역추적"

## 핵심 Tracing 계약

다음 구분을 항상 보존:

1. **Observation** — 실제 관찰된 것
2. **Hypotheses** — 경쟁하는 설명
3. **Evidence For** — 각 설명을 뒷받침하는 것
4. **Evidence Against / Gaps** — 반박하거나 아직 빠진 것
5. **Current Best Explanation** — 지금 선두 설명
6. **Critical Unknown** — 상위 설명들을 가르는 빠진 사실
7. **Discriminating Probe** — 불확실성을 가장 빨리 축소할 다음 수

다음으로 붕괴 금지:
- 일반적 fix-it 코딩 루프
- 일반적 debugger 요약
- 워커 출력 raw dump
- 증거 불완전한데 가짜 확신

## 증거 강도 계층

평탄하게 취급하지 말고 **랭크**:

1. 통제된 재현 / 직접 실험 / 유일하게 식별하는 아티팩트
2. tight provenance의 1차 아티팩트 (trace events, 로그, 메트릭, 벤치마크, 설정, git 이력, file:line 거동)
3. 같은 설명으로 수렴하는 독립 복수 소스
4. 단일 소스 코드경로 / 거동 추론 (유일하지 않음)
5. 약한 정황 (타이밍, 네이밍, 스택 순서, 과거 버그와의 유사성)
6. 직관 / 유추 / 추측

더 강한 증거 계층과 모순되면 약한 쪽을 명시적으로 down-rank.

## 강한 반증 규칙

모든 진지한 `/trace` 실행은 자기 선호 설명을 반증 시도해야 함.

각 상위 가설에 대해:
- For 증거 수집
- Against 증거 수집
- 그것이 만드는 **변별 예측** 명시
- 그것이 사실일 때 **설명하기 어려운** 관찰이 무엇인지 명시
- 선두와 차점을 구별하는 **가장 싼 프로브** 식별

down-rank 기준:
- 직접 증거가 모순
- 새 미검증 가정을 추가해야만 살아남음
- 경쟁 설명 대비 변별 예측이 없음
- 더 강한 대안이 더 적은 가정으로 같은 사실 설명
- 지지가 거의 정황 뿐인데 경쟁 설명은 더 강한 계층 증거
- 반박 라운드에서 패배

## 오케스트레이션 형태

Claude 내장 팀 모드 사용 (`/harness-team`).

Lead가:
1. 관찰된 결과 / "왜" 질문 정확히 재진술
2. tracing target 추출
3. 의도적으로 다른 후보 가설 **여러** 개 생성
4. 기본 **3개 tracer 레인** 스폰
5. 레인당 tracer 워커 1개 배정
6. 각 워커에 **for + against** 증거 수집 지시
7. 선두 vs 최강 대안 **반박 라운드**
8. 상위 레인들이 실제로 다른지 vs 같은 root로 수렴하는지 감지
9. ranked synthesis로 머지 (critical unknown + discriminating probe 포함)

워커들은 같은 설명을 병렬로 추구하지 말고 **의도적으로 다른** 설명을 추구해야 함.

## 기본 가설 레인 (v1)

프롬프트가 더 나은 분할을 강하게 시사하지 않으면:

1. **코드경로 / 구현 원인**
2. **설정 / 환경 / 오케스트레이션 원인**
3. **측정 / 아티팩트 / 가정 불일치 원인**

버그·성능·아키텍처·실험 tracing에 두루 쓰이도록 의도적으로 넓음.

## 필수 교차 검증 렌즈

초기 증거 패스 후 선두를 다음 렌즈로 압박 (관련될 때):

- **Systems**: 큐, 재시도, backpressure, 피드백 루프, upstream/downstream 의존, 경계 실패, 조율 효과
- **Premortem**: 현 선두가 불완전/틀렸다 가정. 나중에 창피할 실패 모드?
- **Science**: 통제, 교란 변수, 측정 편향, 대안 변수, 반증 가능한 예측

## 워커 계약

각 워커는 일반 executor가 아닌 **tracer 레인 소유자**.

반환 구조:
1. Lane
2. Hypothesis
3. Evidence For
4. Evidence Against / Gaps
5. Evidence Strength
6. Critical Unknown
7. Best Discriminating Probe
8. Confidence

## Leader Synthesis 계약

최종 답변은 concat이 아니라 synthesize.

반환:
1. Observed Result
2. Ranked Hypotheses
3. Evidence Summary by Hypothesis
4. Evidence Against / Missing Evidence
5. Rebuttal Round
6. Convergence / Separation Notes
7. Most Likely Explanation
8. Critical Unknown
9. Recommended Discriminating Probe
10. Additional Trace Lanes (optional)

하나가 지배적이어도 ranked shortlist 보존.

## 수렴 감지

워커들이 유사한 언어를 쓴다고 수렴 주장 금지. 수렴은 다음 중 하나 필요:
- 같은 **root causal mechanism**
- **독립 증거 스트림**이 같은 설명 가리킴

## Gotchas

- **조기 확신**: 대안 검토 전 원인 선언.
- **관찰 drift**: 선호 이론에 맞추려고 관찰 결과 재작성.
- **확증 편향**: 지지 증거만 수집.
- **Flat 가중**: 추측과 직접 아티팩트를 동등 취급.
- **Debugger 붕괴**: 설명 대신 구현으로 점프.
- **가짜 수렴**: 말만 비슷하고 실제로는 다른 root를 암시하는 대안 병합.
- **프로브 없음**: "확실하지 않음"으로 끝내지 말고 구체적 다음 단계로 끝내라.
