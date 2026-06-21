---
name: graphql-apollo-android
description: Apollo Kotlin 4.x — KMP-first GraphQL client, normalized cache, fetchPolicy, graphql-transport-ws subscription
keywords: apollo graphql kotlin kmp normalized-cache fetchpolicy subscription graphql-transport-ws cache-key fragment query mutation
intent: setup-apollo-client design-cache-keys choose-fetch-policy migrate-from-apollo-3 handle-pagination-cursors
paths: app/src/main/kotlin app/src/main/graphql
patterns: ApolloClient toFlow @typePolicy CacheKeyGenerator HttpInterceptor fetchPolicy
requires: coroutines-flow-viewmodel-and-compose-state-boundaries api-contracts
phase: plan implement review debug
tech-stack: kotlin
min_score: 2
quality_axes_enforced: true
---

# Apollo Kotlin — GraphQL Client (4.x)

> 핵심: Apollo Kotlin 4.x는 KMP-first GraphQL 클라이언트. **Apollo 3 → 4는 패키지명 + plugin id breaking change** (`com.apollographql.apollo3` → `com.apollographql.apollo`). 가장 흔한 실패는 **cache key 누락** — `__typename` + `id` 없으면 query path로만 캐싱돼 cross-query reuse 0.

## 의사결정 트리

### IF Apollo 4 채택 (Plan)
1. version pin — Apollo Kotlin 4.3.x (2026-05). Apollo 3.x는 maintenance mode — 신규 채택 금지
2. Kotlin 2.0+ + AGP 8.0+ 요구
3. Gradle plugin: `id("com.apollographql.apollo") version "4.x.x"`
4. KMP module이면 commonMain에 schema/query 배치 — Android/iOS 동시 사용

### IF ApolloClient 구성 (Implement)
```kotlin
val apolloClient = ApolloClient.Builder()
    .serverUrl("https://api.example.com/graphql")
    .normalizedCache(SqlNormalizedCacheFactory("apollo.db"))
    .addHttpInterceptor(AuthInterceptor(tokenProvider))
    .webSocketServerUrl("wss://api.example.com/graphql")
    .build()
```

### IF fetchPolicy 결정 (Implement)
| 정책 | 사용처 |
|---|---|
| `CacheFirst` (default) | 일반 read — cache hit 시 network skip |
| `NetworkOnly` | mutation 후 강제 refresh |
| `CacheAndNetwork` | UI 즉시 표시 + 백그라운드 갱신 (Flow 2회 emit) |
| `CacheOnly` | offline-first 화면 |
| `NetworkFirst` | freshness 우선 — fallback to cache |

### IF Normalized Cache key 설정 (Implement)
1. **모든 entity에 `id` + `__typename` 강제** — schema에 명시 안 됐으면 client에서 `@typePolicy(keyFields: "id")` directive
2. cache key generator — `TypePolicy("Type", "id")` 등록
3. 누락 시 같은 entity가 다른 query path마다 별도 cache 항목 → 메모리 폭증, stale UI

### IF Subscription (Implement)
1. **graphql-transport-ws** (newer, Apollo 4 default) vs **graphql-ws** (legacy subscriptions-transport-ws)
2. server protocol 확인 후 client 정렬 — mismatch 시 connection 즉시 close
3. `apolloClient.subscription(Q()).toFlow().collect { ... }` — Flow 기반, lifecycle-aware 수집

### IF Apollo 3 → 4 마이그레이션 (Plan)
1. plugin id — `com.apollographql.apollo3` → `com.apollographql.apollo`
2. import — `com.apollographql.apollo3.*` → `com.apollographql.apollo.*` (전수 교체)
3. WebSocket protocol 명시 — 4.x default가 graphql-transport-ws로 변경됨. legacy 서버는 명시 설정
4. response handling — `response.hasErrors()` 명시 검사 (4.x는 partial data + errors 동시 반환 가능)

### IF Pagination (Implement)
1. cursor 기반 → `@connection` directive 또는 custom `CacheKeyGenerator`
2. offset 기반 → 권장 X (cache invalidation 어려움)
3. Apollo 4 `Pagination` API로 자동 cursor merge — manual은 race condition 위험

## 가이드

- schema sync — `./gradlew downloadApolloSchema` 자동화 (CI 의존성). 누락 시 빌드/런타임 mismatch.
- error policy — GraphQL `errors[]` ≠ HTTP error. HTTP 200 + `errors` 가능. `response.hasErrors()` 항상 체크.
- KMP 사용 시 schema는 commonMain에, platform-specific interceptor는 androidMain/iosMain.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | typed query 클래스로 compile-time schema 검증 |
| 성능 효율성 | normalized cache로 cross-query 객체 재사용 |
| 호환성 | KMP — Android/iOS/JVM/JS/Native 동일 query 코드 |
| 사용성 | Flow 기반 subscription으로 lifecycle-aware |
| 신뢰성 | fetchPolicy 5종으로 offline/freshness 트레이드오프 명시 |
| 보안 | HttpInterceptor로 token rotation + tenant 분리 |
| 유지보수성 | schema codegen으로 server contract 자동 동기화 |
| 이식성 | Apollo 4 KMP-first — KMP 모듈 그대로 iOS 재사용 |
| 확장성 | `@typePolicy` + custom CacheKeyGenerator로 도메인별 cache 정책 |

## Gotchas

### Cache key 누락 (`__typename` + `id` 부재)
가장 흔한 함정. entity가 query path별로 별도 캐싱 → 메모리 폭증 + stale UI. schema에 강제 또는 `@typePolicy` directive로 명시.

### graphql-ws vs graphql-transport-ws protocol mismatch
Apollo 4 default는 graphql-transport-ws. legacy 서버는 graphql-ws → connection 즉시 close. server 확인 후 client 명시.

### `response.hasErrors()` 검사 누락
HTTP 200 + GraphQL errors 동시 발생 가능. data 처리만 하고 errors 무시 시 silent corruption. 항상 `if (response.hasErrors()) handle(response.errors)` 분기.

### Apollo 3 → 4 import 부분 마이그레이션
`com.apollographql.apollo3.*` 한 모듈만 남으면 plugin id 충돌 + 빌드 실패. 전수 교체 필수.

### Cursor pagination 수동 merge
`@connection` 또는 Apollo 4 `Pagination` API 미사용 시 race condition + 중복 row. 수동 merge 회피.

### Schema drift (downloadApolloSchema 자동화 누락)
backend 변경이 client에 안 반영 → 런타임에서 파싱 실패. CI에 schema download task 의존성 등록.

## Source

- https://www.apollographql.com/docs/kotlin — Apollo Kotlin docs entry, 조회 2026-05-10
- https://www.apollographql.com/docs/kotlin/migration/4.0 — plugin id `com.apollographql.apollo3` → `com.apollographql.apollo`, 패키지 변경 verbatim, 조회 2026-05-10
- https://www.apollographql.com/docs/kotlin/essentials/queries — Query/Mutation/Subscription `.execute()` / `.toFlow()` 표준, 조회 2026-05-10
- https://www.apollographql.com/docs/kotlin/caching/normalized-cache — `TypePolicy("Type", "id")` cache key, fetchPolicy 5종, 조회 2026-05-10
- https://www.apollographql.com/docs/kotlin/essentials/subscriptions — graphql-transport-ws (newer, default in 4.x), graphql-ws (legacy), 조회 2026-05-10
- https://www.apollographql.com/docs/kotlin/advanced/interceptors-http — `addHttpHeader` + `HttpInterceptor` auth 패턴, 조회 2026-05-10
- https://github.com/apollographql/apollo-kotlin/releases — 4.3.x stable (2026-05), 조회 2026-05-10
- https://netflixtechblog.com/seamlessly-swapping-the-api-backend-of-the-netflix-android-app-3d4317155187 — Netflix Android Falcor → GraphQL Federation 마이그레이션, replay testing 3-step pipeline + sticky canary 패턴 (2020-09), 조회 2026-05-10
