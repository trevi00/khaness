---
name: sre-operations
description: SRE as operational decision governance — error budgets, incident command handoff, dependency outage triage, and maintenance window risk made explicit beyond alerts and dashboards.
keywords: sre slo sli error-budget budget-burn launch-freeze incident-command handoff role-continuity dependency-outage fallback customer-update maintenance-window rollback freeze blast-radius operator-load on-call escalation runbook postmortem
intent: SLO정해 error-budget계산해 incident대응해 handoff하 dependency장애대응해 maintenance잡아 freeze걸어 runbook작성해 on-call정해
paths: sre/ runbooks/ slo/ alerts/ docs/sre/ incidents/ postmortems/ on-call/
patterns: prometheus grafana pagerduty opsgenie victorops alertmanager slo-generator sloth nobl9 datadog newrelic
requires: monitoring debugging trace finops infra-change-readiness
phase: review deploy
tech-stack: any
min_score: 2
---

# SRE Operations

SRE는 알림과 대시보드가 아니라 **운영 의사결정의 거버넌스**. 4축: error budget, incident handoff, dependency outage, maintenance risk.

## 의사결정 트리

### IF SLO / Error Budget 정의 (Plan)
1. SLI 선택 — availability(2xx 비율), latency(p95 < N ms), correctness(데이터 정확성) 중
2. SLO target — 99.9%(43m/month) / 99.95%(21m) / 99.99%(4m) 중
3. error budget — 100% - SLO. 한 달 동안 N분 다운 허용
4. burn rate alert — 1h 동안 budget 5% 소진 또는 6h 동안 10% 같은 fast/slow 분리
5. budget exhaustion 정책 — launch freeze trigger
6. **→ monitoring 스킬: SLI 메트릭 수집 패턴**

### IF Incident 발생 (Review)
1. severity 분류 — SEV1(전면 장애) / SEV2(일부 기능) / SEV3(degraded)
2. roles — Incident Commander, Communications Lead, Operations Lead 분리
3. timeline 기록 — 시점, 가설, 행동, 결과
4. customer comm — 영향 범위 / ETA / 완화 단계
5. handoff — 교대 시 role + 현재 가설 + 다음 행동을 명시 전달
6. **→ debugging 스킬: 시스템적 디버깅 패턴**
7. **→ trace 스킬: 분산 trace로 원인 추적**

### IF Dependency Outage Triage (Review)
1. blast radius — 어느 사용자/기능/리전 영향
2. fallback 가용 — cache, stale data, degraded mode 어느 옵션
3. customer update obligation — 외부 통보 필요? 언제? 어디에?
4. 의존 owner와 동시 통신 — 우리만 보는 view 아니게
5. workaround — 의존 빠지고 핵심 기능 살릴 path

### IF Maintenance Window 잡을 때 (Plan)
1. 시간대 — 트래픽 낮음 + 운영자 가용
2. freeze overlap — 이벤트/분기말 freeze와 충돌 없게
3. operator load — 동시간 다른 변경 작업 없게 (operator 1인이 여러 변경 monitoring 금지)
4. blast radius — 한 번에 영향 범위 제한 (canary → fleet)
5. rollback checkpoint — 시점별 revertable
6. **→ infra-change-readiness 스킬: live apply readiness 점검**
7. **→ rollback-readiness 스킬: rollback 절차 검증**

### IF Error Budget 회고 (Review)
- [ ] 이번 달 budget 소진율 — 50% 미만이면 launch 정상, 75%+ 이면 freeze 검토
- [ ] burn rate alert가 작동했는가
- [ ] incident별 budget 영향 — 실제 다운타임 vs 인지된 다운타임
- [ ] dependency가 우리 budget을 얼마나 소진시키는가
- [ ] postmortem action item이 closed 되고 있는가

## 4축 체크리스트

```
[Error Budget]
□ SLI 명시 (availability/latency/correctness)
□ SLO target과 budget 계산식
□ burn rate alert (fast/slow)
□ exhaustion 시 freeze 정책

[Incident Handoff]
□ Incident Commander / Comms / Ops 역할 분리
□ timeline + 가설 + 행동 기록
□ 교대 시 명시 전달 형식
□ customer comm 채널과 빈도

[Dependency Outage]
□ blast radius framing
□ fallback 가용 (cache, degraded mode)
□ customer 통보 의무 분류
□ workaround path

[Maintenance Risk]
□ change-window calendar 등록
□ freeze overlap 검사
□ operator load 분산
□ rollback checkpoint
```

## 가이드

### Burn rate alert 패턴 (Multi-window)
- **Fast**: 1h 동안 budget 5%+ 소진 → 즉시 page (incident)
- **Slow**: 6h 동안 budget 10%+ 소진 → ticket (review)
- 두 window 같이 보면 false positive 줄임 (둘 다 trigger 시 alert).

### Incident Commander의 핵심 책임
- 결정 (mitigate vs investigate)
- 우선순위 (어떤 가설 먼저 검증)
- 커뮤니케이션 routing (Comms Lead에게 위임)
- "지금 우리는 X를 시도 중, 결과 N분 후" 같이 timeline 명시

### Customer Update 결정 트리
- **외부 트래픽 영향 + > 5min**: status page 업데이트 + tweet/이메일
- **일부 기능 + < 30min**: status page만
- **internal only**: 내부 채널만
- 너무 자주 update하면 noise, 너무 안 하면 신뢰 잃음. 30-60분 간격이 보통.

### Postmortem은 blameless + actionable
"누가 잘못했나" 보다 "왜 이 시스템에서 이 실수가 가능했나". action item마다 owner + ETA + verification. open postmortem이 grow-forever면 학습 없음.

### Dependency outage의 "공동 통신"
같은 cloud 장애를 우리도 보고 있으면 우리도 affected. 우리가 처음 발견한 척 통보하기 전에 dependency 측 status page 확인 + link해서 통보 — 사용자 혼란 줄임.

## Gotchas

### SLO가 100% — error budget 0
"우리는 다운타임 0이 목표"는 budget 0 → 모든 변경이 risk. realistic SLO(99.9-99.95%) + budget으로 변경 속도와 안정성 trade-off.

### Alert가 너무 많아 ignore
모든 metric에 alert 걸면 incident 시 진짜 신호를 못 봄. SLI 기반 burn rate alert만 page, 나머지는 ticket. alert 수 < 일주일에 owner당 5개가 sustainable.

### Incident handoff가 verbal only
교대 시 Slack 한 줄로 끝내면 새 IC가 가설/행동 모름 → 이미 했던 것 반복. 형식: "현재 상태 + 가설 + 다음 행동 + 미해결 질문" 4줄 의무.

### Maintenance window가 freeze와 겹침
이벤트(블프, 셀럽 게스트) 기간에 인프라 변경 → 사고 시 둘 다 영향. freeze calendar를 SRE owns하고 모든 change-window가 cross-check.

### Operator 한 명이 동시 변경 2개
DB 마이그레이션 + 배포를 같은 사람이 monitoring하면 alert 들어와도 어느 쪽 원인인지 모름. one-operator-one-change.

### Dependency 장애를 우리 incident처럼
upstream(예: AWS S3) 장애를 우리 코드 버그로 추적하다 시간 낭비. 첫 5분 내 dependency status check 의무.

### Freeze 풀린 직후 대량 deploy
freeze 끝나자마자 막혀 있던 deploy가 한꺼번에 → 사고 시 어떤 변경이 원인 식별 어려움. 점진 풀기.

### Postmortem action이 영원히 open
"action: foo system 개선" 6개월째 open이면 학습 안 됨. 모든 action에 ETA + owner + 분기별 review.

### Error budget을 launch만 보는 view
"이번 달 budget 남았으니 막 배포하자"가 사고 유발. budget은 risk 한도, 의도적 소진이지 free spending 아님.

### SLI가 합성(synthetic) only
synthetic prober로만 측정하면 실제 사용자 경험 누락 — RUM(real user monitoring) 또는 service-level 메트릭과 결합.

### Communications Lead가 별도 없음 — IC 다중 부담
IC가 결정 + 통보 + 디버깅 다 하면 burnout + 통보 누락. SEV1+은 무조건 Comms Lead 별도 지정.

### Maintenance "그냥 빠르게 끝나"
30분 예정이 2h되는 경우 흔함. window 시작 시 hard deadline + rollback trigger 시점 명시. deadline 도래 시 자동 rollback.

## 도구 사용 패턴 (Harness)
- SLO 계산: `Bash`로 promQL 쿼리 또는 SLO generator(sloth, nobl9) 사용
- incident timeline: 별도 docs(Notion, Confluence) — Harness Write로 timeline 자동 생성 가능
- runbook 검색: `Grep`으로 `runbooks/` 디렉토리에서 alert title 매칭
- on-call 일정: PagerDuty/Opsgenie API

## 에러 복구 패턴 (Harness)
- alert noise 폭증 → SLO 기반 alert로 재분류, non-SLI는 ticket으로 강등
- incident 디버깅 정체 → 가설 트리로 분기, 동시 가설 2-3개 병렬 시도
- dependency outage 영향 분석 → 의존 mapping 문서 + 영향 메트릭(에러율, latency) 시간 정렬
- postmortem action stale → 분기 review에서 ETA 재설정 또는 deprecate

## Related (신규 그래프 cross-ref)

sre-operations가 전제하거나 보강하는 신규 노드:
- `_common/oncall-and-incident-response.md` — Google SRE Book IC/Ops/Comms 역할 + PagerDuty SEV1-5 + multi-burn-rate alerts (1h+5m / 6h+30m / 3d+6h)
- `_common/chaos-engineering.md` — active fault injection (Principles of Chaos 5원칙 + AWS FIS + ChAP)
- `_common/load-shedding-prioritized.md` — Netflix Zuul priority threshold (2020 + 2024 service-level)
- `_common/service-resilience-patterns.md` — resilience4j 2.59 (Hystrix maintenance mode 대체)
- `infra/observability-otel-prom.md` — OTel SDK + tail-sampling + Prometheus high-cardinality 차단
- `_common/durable-execution.md` — Temporal activity exactly-once (Netflix 보고 transient 4% → 0.0001%)
