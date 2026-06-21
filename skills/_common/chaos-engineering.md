---
name: chaos-engineering
description: Chaos Engineering — Principles of Chaos 5원칙, blast radius 통제, AWS FIS, ChAP 패턴. active fault injection (vs reactive resilience)
keywords: chaos-engineering chaos-monkey simian-army aws-fis gremlin steady-state blast-radius fit chap fault-injection
intent: design-chaos-experiment hypothesize-steady-state contain-blast-radius automate-continuously plan-chap-style
paths:
patterns: chaos-monkey aws-fis stop-condition steady-state blast-radius
requires: service-resilience-patterns oncall-and-incident-response
phase: plan implement review deploy
tech-stack: any
min_score: 2
quality_axes_enforced: true
---

# Chaos Engineering — Active Fault Injection

> 핵심: Chaos는 **active fault injection** — circuit breaker(reactive)와 다른 디시플린. 가장 흔한 실수는 "장애 시뮬레이션"으로 오해 — 실제는 **steady-state hypothesis 검증**. AWS FIS / Gremlin / Azure Chaos Studio가 산업 표준 도구.

## 의사결정 트리

### IF Chaos 프로그램 시작 (Plan)
1. 5 원칙 적용 (Principles of Chaos):
   - Steady-state hypothesis 정의 (output metric, 내부 X)
   - Real-world 이벤트 모방 (network blip, instance kill 등)
   - Production에서 실험 (staging은 trust 부족)
   - 자동화 + 지속 실행
   - **Blast radius 최소화**
2. staging에서 1회 검증 후 production 점진 — AWS FIS 공식 권고

### IF Steady-state hypothesis 정의 (Implement)
1. **Output metric 선택** — 사용자 KPI (orders/sec, p99 latency, conversion rate). 내부 metric (CPU, GC) 금지
2. control vs experiment 두 그룹 동시 측정
3. 가설: "fault X 주입해도 metric Y는 baseline 대비 ±5% 안 변함"
4. 변동 시 **즉시 abort** (Gremlin "halt the experiment immediately")

### IF Blast radius 통제 (Implement)
1. 시작 — 단일 instance / 단일 AZ
2. 확장 조건 — 직전 단계 metric 안정 후
3. **Stop condition** — CloudWatch alarm 자동 abort (AWS FIS 패턴)
4. 항상 rollback path 준비 — Gremlin "every attack can be reverted immediately"

### IF AWS FIS 적용 (Implement)
| 개념 | 정의 (verbatim) |
|---|---|
| Experiment template | "the blueprint of your experiment. It contains the actions, targets, and stop conditions" |
| Action | "an activity that AWS FIS performs on an AWS resource during an experiment" |
| Target | "one or more AWS resources on which AWS FIS performs an action" |
| Stop condition | "a mechanism to stop an experiment if it reaches a threshold ... CloudWatch alarm" |

### IF ChAP 스타일 진화 (Plan)
1. **FIT (Failure Injection Testing, 2014)** — microservice 단위 failure 주입, 명시적 scoping
2. **ChAP (2016+)** — paired experiment + control cluster, 작은 traffic slice로 라우팅, 각 deploy마다 자동 실행
3. 미숙한 팀은 AWS FIS / Gremlin SaaS로 시작, 성숙 후 ChAP-style 자체 구축

## 가이드

- Simian Army 구성 (Netflix): Chaos Monkey (instance kill) / Latency Monkey (네트워크 지연 → FIT으로 진화) / Conformity Monkey (규칙 위반 → Spinnaker 통합) / Doctor Monkey (헬스체크) / Janitor Monkey (orphan 자원 → Spinnaker Swabbie) / Chaos Gorilla (AZ 단위) / Chaos Kong (region 단위).
- Janitor Monkey, Latency Monkey 는 deprecated — Spinnaker Swabbie / FIT으로 대체.
- AWS FIS는 "AWS Fault Injection **Service**" (구 Simulator) — 두 명칭 모두 docs에 등장.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | steady-state hypothesis가 KPI 기반 — 내부 metric 의존 X |
| 성능 효율성 | small blast radius로 비용/위험 통제 |
| 호환성 | Principles of Chaos는 cloud/언어 무관 |
| 사용성 | AWS FIS template 1줄로 간단 실험 시작 |
| 신뢰성 | stop condition + 즉시 revert로 실험 안전 |
| 보안 | production 실험은 PII/financial scope 제외 |
| 유지보수성 | automated continuous chaos가 회귀 차단 |
| 이식성 | AWS FIS / Gremlin / Azure Chaos Studio 무관 |
| 확장성 | ChAP-style automation으로 매 deploy마다 회귀 검증 |

## Gotchas

### Steady-state hypothesis를 내부 metric으로 정의
CPU/메모리/GC 같은 내부 지표는 사용자 영향 무관 변동 가능. **사용자 KPI** (orders/sec, p99 latency, conversion)만 사용.

### Production 직행 (staging 미경험)
AWS FIS docs verbatim: "before you use AWS FIS to run experiments in production, we strongly recommend that you complete a planning phase and run the experiments in a pre-production environment". staging 1회 검증 필수.

### Blast radius 무통제 — 처음부터 region 전체
단일 instance → 단일 AZ → region 단계적 확장. 처음부터 큰 영향 시 사고로 직결.

### Rollback path 미준비
Gremlin "every attack can be reverted immediately". rollback 검증 안 한 실험은 chaos 아닌 incident.

### Chaos를 stress test/load test와 혼용
chaos는 hypothesis-driven + control group 비교. load test는 capacity 측정. 둘은 별개 디시플린.

### 같은 실험을 1회만 실행
Principle 4: automate continuously. 1회 통과는 회귀 보호 0. 매 deploy 또는 일/주 단위 자동.

### Latency Monkey 신규 채택
deprecated — FIT/ChAP 또는 AWS FIS / Gremlin으로.

## Source

- https://principlesofchaos.org/ — "Chaos Engineering is the discipline of experimenting on a system in order to build confidence in the system's capability to withstand turbulent conditions in production"; 5 advanced principles verbatim, 조회 2026-05-10
- https://docs.aws.amazon.com/fis/latest/userguide/what-is.html — Experiment template / Action / Target / Stop condition verbatim, "complete a planning phase and run the experiments in a pre-production environment", 조회 2026-05-10
- https://www.gremlin.com/community/tutorials/chaos-engineering-the-history-principles-and-practice — "every attack can be reverted immediately"; "Halt the experiment immediately" workflow, 조회 2026-05-10
- https://www.gremlin.com/chaos-monkey/the-simian-army — Simian Army roster (Chaos Monkey/Gorilla/Kong, Latency, Conformity, Doctor, Janitor, Security), 조회 2026-05-10
- https://medium.com/netflix-techblog/chap-chaos-automation-platform-53e6d528371f — ChAP paired experiment + control clusters, "increase the safety, cadence, and breadth of experimentation", 조회 2026-05-10
- https://arxiv.org/pdf/1702.05849 — Basiri et al. "A Platform for Automating Chaos Experiments" (ChAP 학술 출처), 조회 2026-05-10
- https://en.wikipedia.org/wiki/Chaos_engineering — discipline 정의 + 산업 채택 사례, 조회 2026-05-10
