---
name: service-resilience-patterns
description: resilience4j 2.x — CircuitBreaker / Bulkhead / Retry / RateLimiter / TimeLimiter aspect order 결정, Hystrix 폐기 전환
keywords: resilience4j circuit-breaker bulkhead retry rate-limiter time-limiter hystrix fallback aspect-order
intent: choose-resilience-pattern tune-circuit-breaker order-aspects diagnose-retry-storm migrate-from-hystrix
paths:
patterns: resilience4j @CircuitBreaker @Bulkhead @Retry CallNotPermittedException
requires: transport-reliability sre-operations
phase: plan implement review debug
tech-stack: any
min_score: 2
quality_axes_enforced: true
---

# Service Resilience Patterns (resilience4j 2.x)

> 핵심: Hystrix는 2018부터 maintenance mode (Netflix 자체 발표), 신규 채택 금지. resilience4j 2.x가 산업 표준. 가장 흔한 실패는 **aspect order** — Retry가 CircuitBreaker 바깥에 있으면 OPEN 상태도 retry하여 storm 발생.

## 의사결정 트리

### IF 외부 호출에 resilience 적용 (Plan)
| 신호 | 패턴 |
|---|---|
| 응답 latency 가변·downstream 죽음 | **CircuitBreaker** |
| transient 실패 (5xx, network blip) | **Retry** (지수 backoff + jitter 필수) |
| 동시 호출 폭주로 caller 자원 고갈 | **Bulkhead** |
| 외부 SLA 호출 한도 | **RateLimiter** |
| 응답 무한 대기 | **TimeLimiter** (CompletableFuture 필요) |

### IF CircuitBreaker tuning (Implement)
1. default: `failureRateThreshold=50%`, `slidingWindowSize=100`, `minimumNumberOfCalls=100`, `waitDurationInOpenState=60s`, `permittedNumberOfCallsInHalfOpenState=10`
2. **low-traffic endpoint** → `minimumNumberOfCalls`를 5–20으로 낮추기 (default 100이면 트립 안 됨)
3. **slow call**도 failure로 간주 → `slowCallDurationThreshold` + `slowCallRateThreshold` 설정 또는 TimeLimiter 결합
4. downstream 복구 시간 가변이면 → `waitIntervalFunctionInOpenState`로 exponential backoff (60s 고정값 flapping 방지)

### IF Bulkhead 종류 선택 (Implement)
1. 동기 호출 + 이미 thread pool 관리 → `SemaphoreBulkhead` (default max 25 concurrent, 오버헤드↓)
2. blocking I/O를 caller thread와 분리 + queue buffering → `ThreadPoolBulkhead` (CompletableFuture 필수)
3. **`@CircuitBreaker` + `ThreadPoolBulkhead` 직접 결합 금지** — 동기 메서드에 같이 붙이면 런타임 에러. async chain으로 구성

### IF aspect order 결정 (Implement)
1. default 순서: `Retry( CircuitBreaker( RateLimiter( TimeLimiter( Bulkhead( Function ) ) ) ) )` — Retry가 가장 바깥
2. 위 default는 **retry storm** 위험 — CB가 OPEN으로 `CallNotPermittedException` 던지면 Retry가 재시도
3. 해결: `retryExceptions`에서 `CallNotPermittedException` 명시 제외, **또는** `retryAspectOrder`를 `circuitBreakerAspectOrder`보다 낮게 설정 (Retry를 CB 안쪽에)

### IF Hystrix 코드베이스 마이그레이션 (Plan)
1. Hystrix는 maintenance mode — 신규 채택 금지
2. Spring Cloud Circuit Breaker (`spring-cloud-starter-circuitbreaker-resilience4j`)로 추상화 후 단계적 전환
3. 메트릭 — `resilience4j-micrometer` + Prometheus scrape으로 OPEN 전이 모니터링

## 가이드

- fallback은 cached/static value 우선. fallback 안에서 다른 외부 호출 → cascading 실패 위험.
- annotation 기반(`@CircuitBreaker`)은 Spring Boot 3.x + AOP 의존. functional Decorators는 reactive/non-Spring 친화.
- 2.4.0 (2024-03)에서 Spring Boot 4 / Spring Cloud 5 지원 추가. 마이그레이션 시 starter 모듈명 확인.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | CircuitBreaker state 6종(CLOSED/OPEN/HALF_OPEN/METRICS_ONLY/DISABLED/FORCED_OPEN) 결정적 전이 |
| 성능 효율성 | OPEN 상태는 즉시 fail-fast, downstream 부하 차단 |
| 호환성 | annotation + functional + Spring Cloud Circuit Breaker 3 통합 경로 |
| 사용성 | actuator endpoint(`/actuator/circuitbreakerevents`)로 운영 가시성 |
| 신뢰성 | bulkhead로 caller 자원 격리, retry storm 차단 |
| 보안 | rate limiter로 외부 SLA 위반 방지 + DoS 보호 |
| 유지보수성 | aspect order 명시로 실행 순서 결정적 |
| 이식성 | JVM 기반(Java/Kotlin/Scala) 모두 동일 동작 |
| 확장성 | 패턴 추가는 Decorators chain 1줄 — OCP |

## Gotchas

### Retry storm via outer-Retry
default aspect order에서 Retry가 CircuitBreaker 바깥. CB가 OPEN으로 `CallNotPermittedException` 던지면 Retry가 그것까지 재시도 → CPU/네트워크 폭증. `retryExceptions` 제외 또는 aspect order 역전 필수.

### `minimumNumberOfCalls`(default 100) 미달 시 트립 안 됨
저트래픽 endpoint에서 100건 모이기 전엔 100% 실패해도 OPEN으로 안 감. 5–20으로 낮춰야 함.

### TimeLimiter 누락 → slow call이 failure로 집계 안 됨
CircuitBreaker 기본 집계는 예외 기반. downstream이 timeout 직전까지 buffer hold만 하면 OPEN으로 안 감. `slowCallDurationThreshold` + `slowCallRateThreshold` 명시 또는 TimeLimiter 결합.

### `@CircuitBreaker` + `ThreadPoolBulkhead` 직접 조합
동기 메서드에 둘 다 붙이면 런타임 에러. ThreadPoolBulkhead는 `CompletableFuture` 반환 필수. async chain으로 구성.

### fallback 안에서 외부 호출 재발생
fallback이 다른 외부 시스템 호출 → 그 자체도 별도 CircuitBreaker로 감싸지 않으면 cascading 실패. fallback은 cached/static value 우선.

### `waitDurationInOpenState`(60s) 고정 + 복구 시간 mismatch
DB 재기동 5분 걸리는데 60초 후 HALF_OPEN → 또 fail → flapping. exponential backoff (`waitIntervalFunctionInOpenState`) 사용.

## Source

- https://resilience4j.readme.io/docs/circuitbreaker — state 6종 verbatim, defaults (`failureRateThreshold=50`, `slidingWindowSize=100`, `minimumNumberOfCalls=100`, `waitDurationInOpenState=60000ms`), 조회 2026-05-10
- https://resilience4j.readme.io/docs/bulkhead — Semaphore (max 25 concurrent default) vs ThreadPool (`CompletableFuture` 필수), 조회 2026-05-10
- https://resilience4j.readme.io/docs/getting-started-3 — Spring Boot 3 starter, default aspect order `Retry(CB(RateLimiter(TimeLimiter(Bulkhead(Func)))))`, 조회 2026-05-10
- https://github.com/resilience4j/resilience4j/releases/tag/v2.4.0 — 2.4.0 (2024-03-14), Spring Boot 4 / Spring Cloud 5 지원, 조회 2026-05-10
- https://github.com/resilience4j/resilience4j/issues/1657 — aspect order 명시화 (`<aspect>AspectOrder` 설정), 조회 2026-05-10
- https://github.com/Netflix/Hystrix — "Hystrix is no longer in active development, and is currently in maintenance mode"; "leverage open and active projects like resilience4j for new internal projects", 조회 2026-05-10
