---
name: load-shedding-prioritized
description: Prioritized load shedding — Netflix Zuul priority threshold 패턴, service-level shedding, criticality tier, 503 vs queue
keywords: load-shedding prioritized criticality tier zuul priority-threshold backpressure 503 sre overload
intent: design-load-shedding classify-criticality set-priority-threshold drop-low-priority handle-overload
paths:
patterns: priority-threshold criticality-tier load-shed 503-overloaded
requires: edge-gateway-routing service-resilience-patterns
phase: plan implement review deploy debug
tech-stack: any
min_score: 2
quality_axes_enforced: true
---

# Prioritized Load Shedding

> 핵심: 과부하 시 **모든 요청 균등 거부 X** — criticality tier별로 우선순위 결정. Netflix가 Zuul gateway에 priority threshold 패턴 정착시켜 2020 + 2024 article 두 편으로 산업 표준화. retry storm 차단을 회피용 503보다 **calculated drop**이 정답.

## 의사결정 트리

### IF Load shedding 도입 (Plan)
1. criticality tier 정의 (3-5단계):
   - **Tier 1 (사용자 결제/재생)**: 절대 drop 금지
   - **Tier 2 (사용자 탐색/검색)**: 과부하 후반 drop
   - **Tier 3 (백그라운드 sync, 알림)**: 과부하 초반 drop
   - **Tier 4 (analytics, 로깅)**: 부하 감지 즉시 drop
2. priority 라벨 — request header `X-Request-Priority: 1-4` 또는 endpoint별 tier 매핑 테이블
3. shedding decision point — edge gateway (Zuul/Envoy) 또는 service entry. **둘 중 하나만** (이중 차단 시 cascading)

### IF Priority threshold 결정 (Implement)
1. signal — concurrent request count, queue depth, p99 latency, error rate (어느 한 임계 초과 시)
2. **stepwise threshold**: 75% 부하 → tier 4 drop, 85% → tier 3 drop, 95% → tier 2 drop. tier 1은 마지막 보루
3. response code — drop 대상에 **503 Service Unavailable + `Retry-After`** 헤더. 429 (rate limit)와 구분
4. 회복 시 hysteresis — 부하 60% 이하로 떨어지면 tier 4부터 단계적 복구 (oscillation 차단)

### IF Service-level shedding (Implement)
edge gateway 외에도 각 service entry에서 자체 shedding:
1. service가 자기 capacity 가장 정확히 앎 — local concurrent count 기반
2. SLA contract — caller에게 priority header 강제, 미부여 시 tier 3 default
3. shedding metric — `shed_count_total{tier="3"}` Prometheus counter

### IF Retry storm 차단 (Implement)
1. drop 응답에 **`Retry-After`** 명시 — caller가 즉시 재시도 X
2. caller 측은 exponential backoff + jitter
3. tier 1 trafic은 retry budget 큼, tier 4는 retry budget 0 (Envoy `budget_percent`로)

### IF Criticality 분류 진단 (Review)
1. 모든 endpoint를 1-4 tier 중 하나로 매핑 — 미분류 endpoint는 tier 3 default
2. 분기 테스트 — 합성 부하로 75% 도달 시 tier 4 drop 확인
3. metric dashboard — tier별 RPS / shed rate / p99 latency

## 가이드

- Netflix Zuul priority threshold 패턴 (2020) — 이후 service-level prioritization (2024)으로 확장
- 두 layer 동시 적용 시 **edge가 먼저 drop** → service 진입 전 차단. service-level은 edge가 못 본 internal call에 적용
- 인증/인가는 shedding 전 — 인증 실패는 tier 무관 즉시 401/403

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | tier 1은 절대 drop X — 결제/재생 critical path 보장 |
| 성능 효율성 | calculated drop이 cascading failure보다 cheap |
| 호환성 | 표준 503 + `Retry-After` 헤더 — RFC 7231 compatible |
| 사용성 | header 1개 (`X-Request-Priority`)로 caller 분류 |
| 신뢰성 | hysteresis로 oscillation 차단 |
| 보안 | priority spoofing 차단 — internal-only header, 외부 caller는 default tier |
| 유지보수성 | tier 매핑 테이블 1개로 모든 endpoint 분류 |
| 이식성 | Zuul/Envoy/Spring Cloud Gateway 무관 — 헤더 + 임계 |
| 확장성 | tier 추가 (5단계 → 7단계)는 임계 추가만 |

## Gotchas

### 모든 tier에 동일 임계 적용
75%에서 모든 tier 동시 drop 시 사용자 결제까지 영향. **stepwise threshold** (75/85/95%) 강제.

### Drop 응답에 `Retry-After` 누락
caller 즉시 재시도 → retry storm. always `Retry-After: <seconds>` 또는 `Retry-After: <HTTP-date>`.

### Edge + service 양쪽 ignore-coupled
edge가 drop했는데 service도 drop 시도 → cascading. 한 layer만 drop, 다른 layer는 pass-through.

### Hysteresis 없는 단순 임계
부하 75% 근처에서 throttle on/off 폭주 (oscillation). 회복 임계 60% 같은 dual band.

### Priority spoofing
외부 caller가 `X-Request-Priority: 1` 임의 부여 → 사용자가 자기 요청을 critical로 위장. internal-only header (gateway가 strip 후 재주입).

### Tier 매핑 미분류 endpoint
새 endpoint 추가 시 tier 분류 누락 → tier 3 default가 안전하지만 critical path가 tier 3 fall-through 시 사고. 매핑 테이블 review CI gate 추가.

### 503 vs 429 혼용
429 = rate limit (요청 한도 초과), 503 = capacity 부족 (일시 과부하). 둘 의미 다르므로 명확히.

## Source

- https://netflixtechblog.com/keeping-netflix-reliable-using-prioritized-load-shedding-6cc827b02f94 — Netflix Zuul priority threshold pattern (2020), tier-based shedding, 조회 2026-05-10
- https://netflixtechblog.com/enhancing-netflix-reliability-with-service-level-prioritized-load-shedding-e735e6ce8f7d — service-level prioritized shedding (2024-06), 다층 적용 사례, 조회 2026-05-10
- https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/upstream/circuit_breaking — Envoy retry budget로 retry storm 차단, 조회 2026-05-10
- https://datatracker.ietf.org/doc/html/rfc7231#section-7.1.3 — `Retry-After` 헤더 표준 (HTTP/1.1), 조회 2026-05-10
- https://sre.google/sre-book/handling-overload/ — Google SRE Book "Handling Overload" Ch.21, criticality 4단계, 조회 2026-05-10
