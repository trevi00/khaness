---
name: observability
description: Boot 3.5 관측성 — Actuator metrics + Observation API + JFR/GC/container signal을 첫 버전부터 포함
keywords: observability metrics tracing micrometer observation prometheus jfr gc-log
intent: instrument-from-day-one wire-tracing capture-runtime-signals plan-slo
paths: src/main/**/*.java application.yml
patterns: spring-boot-3.5 micrometer Observation @Observed prometheus
requires: management-plane jvm-runtime-diagnostics
phase: plan implement review deploy
tech-stack: java
min_score: 2
---

# Observability (Boot 3.5)

> 관측성은 사후 부착이 아니라 첫 버전 contract — metrics/tracing/runtime signal을 baseline 아키텍처에 포함한다.

## 의사결정 트리

### IF 신규 서비스 부트스트랩 (Plan)
1. metrics: micrometer + Prometheus registry — `/actuator/prometheus`로 scrape 가능 상태로 시작
2. tracing: Observation API + Brave/OTel bridge — span context를 log에 MDC로 흘려 trace ID 검색 가능하게
3. runtime signal: JFR을 낮은 오버헤드로 운영 항시 켜기, GC 로그 출력
4. 위 셋을 deploy 후가 아닌 첫 PR에 포함 — 사고가 일어난 뒤 부착하면 baseline 비교가 불가

### IF SLO/SLI 정의 (Plan|Review)
1. 사용자가 보는 지표(p99 latency, error rate)를 micrometer custom metric으로 노출
2. health group `readiness`가 SLO에 영향을 주는 의존성만 평가하도록 — DB·외부 API 등
3. `info` endpoint에 build/version/commit 노출 → incident 시 버전 식별 즉시 가능

### IF "메트릭이 안 잡힌다" (Debug)
1. exposure 확인 — `management.endpoints.web.exposure.include`에 `prometheus`/`metrics` 포함됐는지
2. registry 의존성 — micrometer-registry-prometheus가 classpath에 있는지
3. tag cardinality 폭발은 별도 문제 — 사용자 ID·request ID 같은 high-cardinality 값을 tag로 쓰지 않는다

### IF "느려졌다, 어디부터?" (Debug)
1. metrics dashboard에서 p50/p99 latency, error rate 변화 시점 식별
2. tracing으로 느려진 endpoint의 span breakdown — DB? 외부 호출? 락?
3. 그래도 답이 없으면 JFR/heap dump로 JVM 레벨로 내려간다 (jvm-runtime-diagnostics 참조)

## 가이드

- Boot 3.x의 Observation API는 metrics와 tracing을 한 번의 instrumentation으로 — 별도 trace API 호출 불필요.
- 로그 포맷에 `traceId`, `spanId` 포함 — log → trace 점프 가능하게.

## Gotchas

### 관측성을 incident 후에 부착
- baseline 없이는 회귀 판정 불가. 첫 deploy부터 포함.

### high-cardinality tag
- userId/requestId를 tag로 쓰면 metric 시리즈가 폭발 — 비용·성능 양쪽 타격.

### tracing sampling rate 100%
- 운영 부하/비용 폭증. 1-10% sampling + 에러는 force-sample 권장.

## Source

- `frameworks/backend/spring-boot/3.5.x/05_patterns/2026-04-19__spring-docs__configuration-properties-profile-groups-and-observability-patterns__3-5-x.md`
- `frameworks/backend/spring-boot/3.5.x/04_usage/2026-04-19__spring-docs__service-connections-config-order-and-actuator-baseline__3-5-x.md`
- `frameworks/backend/spring-boot/3.5.x/06_templates/2026-04-19__spring-docs__backend-service-config-and-actuator-template__3-5-x.md`
- `languages/java/21/08_know-how/2026-04-20__tech-kb-import__jvm-tuning-gc-jfr-and-container-habits__21.md`
- `languages/java/25/05_patterns/2026-04-19__oracle-docs__scoped-values-structured-concurrency-and-preview-boundaries__25.md`

## Related (신규 그래프 cross-ref)

observability가 보강되거나 인접한 신규 노드:
- `infra/observability-otel-prom.md` — OTel Collector v0.110+ + tail-sampling collocation + Prometheus high-cardinality 차단 (Boot 3.5 Observation API 위 운영 layer)
- `_common/oncall-and-incident-response.md` — multi-window multi-burn-rate alerts (1h+5m / 6h+30m / 3d+6h) — SLO burn rate 운영 표준
- `_common/chaos-engineering.md` — observability metric을 chaos steady-state hypothesis로 사용 (KPI 기반)
- `_common/load-shedding-prioritized.md` — observability metric (concurrent count, p99 latency)이 shedding decision signal
- `_common/durable-execution.md` — Temporal worker metrics (`temporal_sticky_cache_size`)도 observability 대상
