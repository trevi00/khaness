---
name: edge-gateway-routing
description: Edge Gateway / L7 routing — Envoy 1.38, Istio control/data plane, Spring Cloud Gateway (Zuul 후속), JWT/mTLS/rate limit
keywords: envoy istio zuul spring-cloud-gateway service-mesh sidecar jwt mtls rate-limit listener filter-chain cluster
intent: choose-edge-gateway design-l7-routing setup-mtls-termination tune-rate-limit migrate-from-zuul
paths:
patterns: envoy listener filter_chain cluster route Istio sidecar
requires: service-resilience-patterns transport-reliability
phase: plan implement review deploy debug
tech-stack: any
min_score: 2
quality_axes_enforced: true
---

# Edge Gateway / L7 Routing (Envoy / Istio / Spring Cloud Gateway)

> 핵심: Netflix Zuul (2013/2018)이 시작이지만 산업은 **Envoy Proxy 위 Istio**로 수렴. JVM 백엔드는 **Spring Cloud Gateway** (Zuul 후속, Reactor 기반). retry storm + sidecar injection 실패가 흔한 운영 사고.

## 의사결정 트리

### IF Edge Gateway 선택 (Plan)
| 신호 | 권장 |
|---|---|
| K8s + service mesh + multi-cloud | **Istio** (Envoy data plane + Istiod control plane) |
| K8s 없는 standalone L7 routing | **Envoy** 직접 배포 |
| JVM/Spring 백엔드 + reactive | **Spring Cloud Gateway** (Spring Boot 3+, WebFlux) |
| 단순 ingress only | NGINX Ingress / Traefik |

### IF Envoy filter chain 설계 (Implement)
표준 chain 순서:
1. Listener (port bind, TLS termination)
2. HTTP Connection Manager (HCM)
3. JWT Auth filter — `jwt_authn` (signature/issuer/audiences 검증)
4. Rate limit — `local_rate_limit` (token bucket: max_tokens / tokens_per_fill / fill_interval ≥50ms) 또는 global `ratelimit`
5. Router filter (마지막) → Cluster로 전달

### IF Istio mTLS 설정 (Implement)
1. Istiod = CA, workload별 cert 자동 발급
2. PeerAuthentication 정책 — `STRICT` (mTLS only), `PERMISSIVE` (mixed), `DISABLE`
3. AuthorizationPolicy로 identity 기반 ACL
4. cert rotation은 자동 — staleness 모니터링만

### IF Retry budget 튜닝 (Implement)
1. 정적 `max_retries` 보다 **retry budget** 권장 (`budget_percent`, `min_retry_concurrency`)
2. 메트릭 — `upstream_rq_retry_overflow` 모니터링 (budget 소진 시 증가)
3. retry storm 차단 — 동시 retry 비율을 active request의 N% 이하로

### IF Zuul → Envoy/SCG 마이그레이션 (Plan)
1. Zuul 1 (servlet, blocking) → SCG (Reactor) 또는 Envoy
2. Zuul 2 (Netty, async) 운영 중이면 점진 — feature flag로 percentage 전환
3. filter 패턴 매핑 — Zuul Pre/Route/Post → Envoy listener/network/HTTP filter

### IF Sidecar injection 실패 (Debug)
공식 docs Common Problems 체크리스트:
1. namespace label `istio-injection=enabled` 확인
2. `hostNetwork: true` 면 injection 자체 skip
3. kube-apiserver `no_proxy`에 `.svc` 포함 확인
4. `holdApplicationUntilProxyStarts: true` — app이 proxy보다 먼저 시작 race 차단
5. `cluster-autoscaler.kubernetes.io/safe-to-evict: true` annotation

## 가이드

- Envoy v1.38.0 (2026-04-23, quarterly cadence). v3 xDS API only — v2 제거.
- SCG 4.x: Java 17+ 필수 (Spring Boot 3 baseline).
- Istio 아키텍처는 1.5+ Istiod 단일화 — 구 Pilot/Galley/Citadel 분리 다이어그램은 stale.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | filter chain 순서로 인증 → rate limit → routing 결정적 |
| 성능 효율성 | local rate limit이 global보다 latency ↓ (50ms+ fill_interval) |
| 호환성 | Envoy v3 xDS는 Istio/Consul/standalone 모두 지원 |
| 사용성 | SCG는 Java 개발자에게 익숙한 reactive API |
| 신뢰성 | retry budget이 retry storm 차단 |
| 보안 | mTLS 자동 cert rotation, JWT authn filter |
| 유지보수성 | Istio 1.5+ Istiod 단일화로 운영 부담 ↓ |
| 이식성 | Envoy는 어떤 cloud/orchestrator에서도 동일 동작 |
| 확장성 | sidecar injection으로 새 워크로드 자동 mesh 편입 |

## Gotchas

### Static `max_retries`로 retry storm
정적 한도는 cluster 전체로 확산. **retry budget** (`budget_percent`)로 active request 비율 기반.

### Sidecar injection이 silent skip
`hostNetwork: true` 또는 namespace label 누락 시 injection 안 되고 일반 pod로 동작 — mTLS 안 됨, traffic 가시성 0. 항상 label + 검증.

### App이 proxy보다 먼저 시작
race로 일부 초기 request가 mesh 우회. `holdApplicationUntilProxyStarts: true` 설정.

### `no_proxy`에 `.svc` 누락
kube-apiserver가 cluster 내부 trafffic을 외부 proxy로 → 인증 실패. `no_proxy`에 `.svc` 명시.

### Local vs Global rate limit 혼용
local은 instance별 token bucket (분산 환경에서 sum 초과 가능). global rate limit service (gRPC) 별도 구축 — latency cost 감수.

### Zuul 1 → Envoy 즉시 전환
Zuul 1 filter 코드는 Envoy로 1:1 변환 안 됨. 점진 — feature flag로 endpoint별 전환, 메트릭 비교.

## Source

- https://github.com/envoyproxy/envoy/releases — v1.38.0 (2026-04-23), quarterly release cadence (15th of quarter), 조회 2026-05-10
- https://www.envoyproxy.io/docs/envoy/latest/intro/life_of_a_request — Listener / Filter chain / Cluster / Route 정의, 조회 2026-05-10
- https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/jwt_authn_filter — JWT verification (signature/audiences/issuer), 조회 2026-05-10
- https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/local_rate_limit_filter — token bucket params (max_tokens, tokens_per_fill, fill_interval ≥50ms), 429 on empty, 조회 2026-05-10
- https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/upstream/circuit_breaking — retry budget (`budget_percent`, `min_retry_concurrency`), `upstream_rq_retry_overflow`, 조회 2026-05-10
- https://istio.io/latest/docs/ops/deployment/architecture/ — Istiod control plane "service discovery, configuration and certificate management", Envoy data plane sidecar, 조회 2026-05-10
- https://istio.io/latest/docs/ops/common-problems/injection/ — sidecar injection failure modes, 조회 2026-05-10
- https://netflixtechblog.com/open-sourcing-zuul-2-82ea476cb2b3 — Netflix Zuul 2 (2018-05-21) Netty async, 80+ clusters, >1M RPS, 조회 2026-05-10
