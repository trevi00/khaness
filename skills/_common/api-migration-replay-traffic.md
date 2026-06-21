---
name: api-migration-replay-traffic
description: API backend swap 산업 표준 — replay traffic 3-step pipeline + sticky canary + diff comparison. Netflix Falcor→GraphQL 사례
keywords: api-migration replay-traffic shadow-traffic sticky-canary dark-launch diff-comparison schema-evolution backend-swap
intent: design-api-migration capture-replay-traffic compare-payload-diff plan-sticky-canary cut-over-zero-downtime
paths:
patterns: replay-traffic shadow-traffic sticky-canary canary-deployment dark-launch
requires: experimentation-and-ab-testing service-resilience-patterns
phase: plan implement review deploy
tech-stack: any
min_score: 2
quality_axes_enforced: true
---

# API Migration with Replay Traffic + Sticky Canary

> 핵심: 백엔드 API swap (e.g., legacy → GraphQL/gRPC, monolith → microservice)에서 가장 위험한 건 **payload diff** + **error rate spike**. Netflix Falcor → GraphQL Federation 마이그레이션이 산업 표준 절차 정착: **replay traffic 3-step (capture/replay/compare) → AB test → sticky canary → 100% cut-over**. 이 패턴은 Stripe API versioning, AWS service migration 등에 동일.

## 의사결정 트리

### IF API backend swap 계획 (Plan)
1. **선결 조건** — 새 backend가 기존 API contract 100% 표면 호환 (response schema, status code, header)
2. 3 단계 게이트 통과:
   - Stage 1: replay traffic (production data, test env에서 실행)
   - Stage 2: sticky canary (소수 user 1-5%, 실제 production)
   - Stage 3: gradual rollout (5% → 25% → 50% → 100%)
3. rollback path 항상 보존 — feature flag 1개로 즉시 복귀
4. observability 사전 — 양쪽 backend 동시 메트릭 (latency p50/p99, error rate, payload size)

### IF Replay Traffic 3-step pipeline 구축 (Implement)
1. **Capture** — production HTTP request 샘플링 (트래픽 일부 % 또는 특정 endpoint)
2. **Replay** — 같은 request를 test env의 old + new backend 양쪽에 동시 전송
3. **Compare** — payload 필드별 diff (key 누락, value mismatch, type 변경, extra field)
   - 무시 필드 화이트리스트 (timestamp, request_id 등 비결정성)
   - diff rate < 0.1% 까지 새 backend fix → 새 capture → 재실행 (반복)

### IF Sticky Canary 결정 (Implement)
1. **sticky** = user/device hash 기반 — 같은 사용자는 항상 같은 backend (state 일관성)
2. 단순 random canary는 stateful API에서 inconsistency 유발 (장바구니, session)
3. canary 비율 — 1% → 5% → 25% (각 단계 24시간 metrics 안정 확인)
4. 자동 abort 조건 — error rate 2× 초과, p99 latency 1.5× 초과, 5분 burn rate (참조: oncall-and-incident-response)

### IF Diff comparison 자동화 (Implement)
1. response payload — JSON canonical form (key 정렬 + whitespace 정규화) 후 SHA-256
2. 무시 필드 — `dynamic_paths.yaml` 화이트리스트 (timestamp, ETag, request_id, server-side ID)
3. type 변경 — `42` (int) vs `"42"` (string) silent 호환 깨짐 — 명시 검출
4. extra field — 기본 ignore (forward compat). missing field만 fail
5. error case — error code 매핑 표 검증 (status + error code 정합)

### IF cut-over (Deploy)
1. 100% sticky canary 안정 7일 후 cut-over
2. 구 backend는 30일 dark mode 운영 (긴급 rollback 대비)
3. 30일 후 구 backend deprecate. metric/log 보관은 추가 90일

## 가이드

- replay traffic은 **PII 마스킹** 필수 — production 데이터를 test env로 옮기므로 GDPR/규제 준수
- 비결정성 차단 — random/timestamp/RNG seed가 응답에 포함되면 diff 항상 발생. 양쪽 동일 seed 강제
- 새 backend의 **읽기/쓰기 분리** — 쓰기 mutation은 dual-write (양쪽 동시) 또는 한쪽만 적용
- 마이그레이션 metric은 별도 dashboard — 일반 metric과 섞이면 혼동

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | replay diff 0.1% 이하로 payload 정합성 보장 |
| 성능 효율성 | sticky canary가 점진적 부하 증가 — capacity 사전 검증 |
| 호환성 | 새 backend가 기존 API contract 100% 표면 호환 |
| 사용성 | feature flag 1개로 instant rollback |
| 신뢰성 | 자동 abort 조건 (error rate, p99) — manual judgment 의존 X |
| 보안 | replay 데이터 PII 마스킹, test env 격리 |
| 유지보수성 | 30일 dark mode 운영으로 rollback 안전망 |
| 이식성 | Falcor/REST/GraphQL/gRPC 무관 동일 절차 |
| 확장성 | replay capture %를 점진 늘려 회귀 catch rate 증가 |

## Gotchas

### Random canary in stateful API
session/cart 데이터를 가진 API에서 random canary 시 같은 사용자가 두 backend 번갈아 호출 → state inconsistency. **sticky canary** (user hash 기반) 강제.

### Replay diff에 timestamp 포함 → 100% diff
`created_at`/`updated_at`/`request_id` 같은 비결정 필드 무시 화이트리스트 없으면 모든 response가 diff. 사전에 dynamic_paths.yaml 정리.

### Type change silent (int ↔ string)
`{"id": 42}` vs `{"id": "42"}` — JSON parser는 둘 다 받아도 client 다운스트림에서 다르게 동작. type-aware diff 필수.

### 30일 dark mode 없이 cut-over
Production cut-over 후 사고 시 즉시 rollback 불가 (구 backend 코드 이미 폐기). 30일 dark mode + feature flag 보존.

### PII 마스킹 누락한 replay
production 사용자 데이터가 test env로 흘러 GDPR/CCPA 위반. capture 시점에 PII detector로 마스킹 강제.

### sticky canary의 hash key를 session ID로
session ID는 만료/회전 — 같은 사용자가 시간 따라 다른 backend로 라우트. user_id 또는 device_id로 stable hash.

### dual-write 정합성 미검증
mutation을 양쪽 backend 동시 write 시 partial fail (한쪽 성공, 다른쪽 실패) — eventual inconsistency. write는 한쪽만 하고 다른쪽은 read-only로 검증 권장.

## Source

- https://netflixtechblog.com/seamlessly-swapping-the-api-backend-of-the-netflix-android-app-3d4317155187 — Netflix Android Falcor → GraphQL Federation 마이그레이션 (2020-09): replay testing "captured production traffic for desired paths and replayed the traffic against the two services"; sticky canary + AB test 절차, 조회 2026-05-10
- https://thenewstack.io/netflixs-testing-strategies-for-migrating-to-graphql/ — Netflix testing strategies (replay test, AB test, sticky canary 단계) 정리, 조회 2026-05-10
- https://www.infoq.com/presentations/netflix-api-graphql-federation/ — InfoQ Netflix GraphQL Federation 발표, schema migration 운영 사례, 조회 2026-05-10
- https://docs.stripe.com/api/versioning — Stripe date-based API versioning + monthly backward-compatible release (동일 패턴 산업 적용 사례), 조회 2026-05-10
