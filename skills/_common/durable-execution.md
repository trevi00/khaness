---
name: durable-execution
description: Durable execution — long-running step의 exactly-once 실행, Temporal/Conductor activity 단위, transient fail 0.0001%로 감소
keywords: durable-execution exactly-once long-running activity heartbeat retry-policy timeout-config saga compensation
intent: design-durable-step configure-retry-policy heartbeat-long-task wire-saga-compensation prevent-double-execution
paths:
patterns: temporal activity heartbeat retryPolicy maximumAttempts startToCloseTimeout
requires: workflow-orchestration idempotency
phase: plan implement review debug
tech-stack: any
min_score: 2
quality_axes_enforced: true
---

# Durable Execution (Long-running Step Exactly-Once)

> 핵심: workflow는 control flow, **activity는 side effect** — durable execution의 핵심 단위. Netflix Temporal article (2025) 보고: transient failure rate 4% → **0.0001%**. activity 단위 retry/timeout/heartbeat 설정이 정밀하면 사실상 exactly-once 보장. workflow-orchestration의 reliability axis.

## 의사결정 트리

### IF Activity 설계 (Implement)
1. **단일 책임** — 한 activity = 한 side effect (DB write OR 외부 API OR 파일 I/O)
2. **Idempotency 강제** — activity input에 idempotency-key 포함, retry 시 같은 결과 (참조: `idempotency.md`)
3. timeout 3종 결정:
   - `startToCloseTimeout` — 한 attempt의 max duration
   - `scheduleToStartTimeout` — task queue에서 worker 픽업까지
   - `scheduleToCloseTimeout` — 전체 (attempt 합산)
4. retry policy — `initialInterval`, `backoffCoefficient` (보통 2.0), `maximumInterval`, `maximumAttempts`

### IF Long-running activity (>30분) (Implement)
1. **Heartbeat 필수** — `Activity.getExecutionContext().heartbeat(progress)` 정기 호출
2. heartbeat timeout — `heartbeatTimeout` 명시 (보통 1-5분). 미수신 시 worker 죽었다고 간주, retry trigger
3. checkpoint state — heartbeat에 progress 정보 포함, retry 시 그 시점부터 재개
4. cancellation 처리 — heartbeat가 `CanceledFailure` 던지면 cleanup 후 propagate

### IF Saga 보상 트랜잭션 (Implement)
1. orchestration 패턴 — workflow가 activity 순차 실행, 실패 시 LIFO로 보상
2. **각 activity에 대응 compensating activity** 정의 — `chargeCard` ↔ `refundCard`
3. workflow 코드:
   ```
   try {
     A1.execute()
     A2.execute()
     A3.execute()  // fail
   } catch {
     A2.compensate()
     A1.compensate()
     throw
   }
   ```
4. compensating activity도 idempotent + retry policy

### IF Retry policy 튜닝 (Implement)
| 신호 | 권장 |
|---|---|
| transient network blip | `maximumAttempts: 5`, `initialInterval: 1s`, `backoffCoefficient: 2.0` |
| 외부 API rate limit | `nonRetryableErrorTypes: ["RateLimitExceeded"]` 명시 또는 별도 rate-limited retry |
| business rule violation | `nonRetryableErrorTypes` 등록 — retry 무의미 |
| flaky integration | `maximumAttempts: 10` + `maximumInterval: 5min` |

### IF Non-determinism in workflow (Debug)
1. workflow 안에서 — `Date.now()` / `Math.random()` / `setTimeout` / 외부 호출 절대 X (참조: `workflow-orchestration.md`)
2. 모든 side effect는 activity로 추출
3. SDK 제공 deterministic 변종 — `workflow.now()`, `workflow.sleep`, seeded RNG

### IF Worker scaling (Implement)
1. task queue 분리 — high-priority vs background activity 별도 queue + worker pool
2. concurrent activity execution — `setMaxConcurrentActivityExecutionSize` (default ~100)
3. worker count — heartbeat-driven activity는 worker당 충분한 thread (CPU 코어 ≥ activity 수)

## 가이드

- Temporal `Activity.getInfo().attempt` — 현재 attempt 번호 확인 (idempotency 추가 안전망)
- compensating activity는 main과 같은 timeout 정책. 보상 실패는 manual review 필요
- workflow history 크기 — long-running은 Continue-As-New로 분할 (참조: `workflow-orchestration`)

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | activity exactly-once + workflow deterministic = end-to-end exactly-once |
| 성능 효율성 | retry exponential backoff로 downstream 부하 통제 |
| 호환성 | Temporal/Conductor/Cadence 모두 동일 abstraction |
| 사용성 | retry policy 1개 데코레이터로 모든 transient 처리 |
| 신뢰성 | Netflix 보고 transient failure 4% → 0.0001% |
| 보안 | activity input의 idempotency-key 위변조 방지 (참조: `webhook-delivery-and-signing`) |
| 유지보수성 | activity 단위 격리로 변경 영향 최소 |
| 이식성 | activity API는 워크플로우 엔진 무관 동일 |
| 확장성 | task queue 분리로 priority별 worker pool 독립 |

## Gotchas

### Activity 안에 여러 side effect
한 activity에 DB write + 외부 API + 이메일 발송 → partial success 시 retry 모호. 단일 책임 강제.

### Heartbeat 누락 (long activity)
30분+ activity에서 heartbeat 없으면 worker 죽었다고 간주 → 의도치 않은 retry. `Activity.heartbeat()` 정기 호출 + `heartbeatTimeout` 명시.

### Compensating activity가 non-idempotent
보상 실패 시 retry → 중복 환불/중복 알림. main activity와 동일 idempotency 강제.

### Non-retryable error 미등록
RateLimitExceeded / BusinessRuleViolation 같이 retry 무의미한 error도 `maximumAttempts`까지 retry → 비용 폭증. `nonRetryableErrorTypes` 명시.

### Workflow에 직접 외부 호출
`fetch()` / DB query를 workflow 함수 안에 넣으면 deterministic replay 깨짐. activity로 추출.

### Activity input에 mutable reference
객체 reference 전달 시 retry 사이 변경 가능. value type 또는 immutable snapshot.

### Task queue 단일화 (priority 미분리)
critical activity가 background activity와 같은 queue → background이 worker 점유 시 critical 지연. queue 분리.

## Source

- https://netflixtechblog.com/how-temporal-powers-reliable-cloud-operations-at-netflix-73c69ccb5953 — Netflix Temporal 도입 (2025-12), transient failure rate 4% → 0.0001%, activity-level retry/timeout, 조회 2026-05-10
- https://docs.temporal.io/activities — `startToCloseTimeout`, `scheduleToStartTimeout`, `scheduleToCloseTimeout` 3종 timeout, 조회 2026-05-10
- https://docs.temporal.io/encyclopedia/retry-policies — retry policy params (initialInterval, backoffCoefficient, maximumInterval, maximumAttempts, nonRetryableErrorTypes), 조회 2026-05-10
- https://docs.temporal.io/develop/python/cancellation — heartbeat + cancellation propagation, 조회 2026-05-10
- https://temporal.io/blog/saga-pattern-made-easy — orchestration vs choreography, LIFO compensation, 조회 2026-05-10
- https://docs.temporal.io/develop/worker-performance — `setMaxConcurrentActivityExecutionSize` worker tuning, 조회 2026-05-10
