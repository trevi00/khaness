---
name: grpc-service-contracts
description: gRPC-java 1.81 + grpc-kotlin 1.5 — proto3 wire 호환 규칙, 16 status code, deadline propagation, keepalive 정합
keywords: grpc protobuf proto3 status-code deadline keepalive interceptor metadata reserved field-number streaming bidi
intent: design-grpc-contract reserve-deleted-fields map-status-codes propagate-deadline tune-keepalive
paths: src/main/proto src/main/java
patterns: io.grpc ManagedChannelBuilder ServerBuilder StatusRuntimeException reserved Context.current
requires: api-contracts virtual-threads
phase: plan implement review debug
tech-stack: java
min_score: 2
quality_axes_enforced: true
---

# gRPC Service Contracts (Java/Kotlin)

> 핵심: gRPC 호환은 **field number** 기반 — 한 번 사용한 번호는 영구 reserved. 가장 흔한 사고는 "안 쓰는 필드 삭제 후 같은 번호 재사용" → silent data corruption. 두 번째는 status code 16종을 이해하지 못하고 throw → 모두 UNKNOWN으로 묻힘.

## 의사결정 트리

### IF 신규 proto 작성 (Plan)
1. service 단위 분리 — 한 .proto = 한 도메인. 깊은 내포 message보다 평탄 구조
2. 필드 번호 규칙 — 1–15 (1-byte tag) hot 필드 우선, 16+ rare 필드. 100+ 예약
3. type 선택 — int64 vs sint64 (negative-heavy면 sint64). bool/enum/string/bytes 명확
4. proto3 + `optional` keyword (3.15+) — "unset" vs "explicit zero" 구분 필요 시
5. 4 RPC 종류 결정 — unary / server streaming / client streaming / bidi

### IF 필드 삭제/리네임 (Implement)
1. **반드시 `reserved`** — `reserved 2, 15, 9 to 11; reserved "foo", "bar";`
2. 같은 번호 재사용 절대 금지 — wire format identifies by 번호, decoder가 silent 해석 변경
3. type 변경 — int32 ↔ int64 wire-safe (truncation 위험 알림). sint32 ↔ int32 **NOT 호환** (negative 손상)
4. rollout 순서 — reader 먼저 deploy (새 필드/type 인식), 그 후 writer

### IF Status code 매핑 (Implement)
16종 표준 (0–16):
| Code | 의미 |
|---|---|
| OK(0) | 성공 |
| CANCELLED(1) | client/server 취소 |
| INVALID_ARGUMENT(3) | 입력 검증 실패 (HTTP 400) |
| DEADLINE_EXCEEDED(4) | 타임아웃 |
| NOT_FOUND(5) | 리소스 없음 (404) |
| ALREADY_EXISTS(6) | 중복 (409) |
| PERMISSION_DENIED(7) | 권한 없음 (403) |
| RESOURCE_EXHAUSTED(8) | rate limit / 4MiB 초과 |
| FAILED_PRECONDITION(9) | state mismatch |
| UNAUTHENTICATED(16) | 인증 실패 (401) |
| UNAVAILABLE(14) | downstream 장애 (503) |
| INTERNAL(13) | 서버 버그 |
| UNIMPLEMENTED(12) | 미구현 (501) |

**`StatusRuntimeException(Status.<CODE>.withDescription(msg))` 던짐** — 일반 예외는 UNKNOWN으로 묶여 root cause 손실.

### IF Deadline + Cancellation (Implement)
1. client — `stub.withDeadlineAfter(N, SECONDS).call(...)`. 항상 명시 (default 무한)
2. server — `Context.current().getDeadline()` 또는 `withCancellation()`로 downstream 전파
3. Kotlin coroutine — `withContext`는 gRPC `Context` 전파 안 함. `Context.current().wrap(...)` 또는 `GrpcContextElement` 사용

### IF Keepalive 튜닝 (Implement)
- client default: KEEPALIVE_TIME=INT_MAX (비활성), TIMEOUT=20s
- server default: KEEPALIVE_TIME=2h, TIMEOUT=20s, **PERMIT_KEEPALIVE_TIME=5min** (이보다 자주 ping → GOAWAY ENHANCE_YOUR_CALM)
- client/server 둘 다 함께 설정. mismatch 시 connection 끊김

## 가이드

- **maxInboundMessageSize default 4MiB** — client + server 양쪽 명시. 큰 payload는 streaming 또는 chunking
- Kotlin 매핑 — unary `suspend fun`, server streaming `Flow<T>`, client streaming `Flow<Req>`, bidi Flow→Flow
- Interceptor — auth/tracing은 ServerInterceptor + Metadata. 절대 request payload 변형 X

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | proto3 wire format이 backward/forward compat 보장 (reserved 사용 시) |
| 성능 효율성 | binary protobuf + HTTP/2 multiplex로 REST 대비 throughput ↑ |
| 호환성 | proto3가 Java/Kotlin/Go/C++/Python/Swift/Node 등 동일 contract |
| 사용성 | 16 status code 표준화 — error mapping 결정 트리 단순 |
| 신뢰성 | deadline propagation으로 cascade timeout 차단 |
| 보안 | TLS + Metadata 기반 auth (ServerInterceptor) |
| 유지보수성 | reserved 강제로 schema evolution 안전 |
| 이식성 | grpc-kotlin Flow 매핑으로 coroutine 표준 |
| 확장성 | streaming 4종으로 unary 외 패턴 흡수 |

## Gotchas

### Field number reuse → silent data corruption
삭제 후 같은 번호 재사용 시 wire decoder가 잘못 해석. 항상 `reserved <num>; reserved "<name>";` 적용.

### proto3 default 0/false/"" — "unset" 구분 불가
scalar field가 0이면 "explicit 0"인지 "missing"인지 구분 불가. `optional` keyword (3.15+) 또는 wrapper type 사용.

### 4MiB 초과 silent stall
client/server 양쪽 default 4MiB. 한쪽만 늘리면 RESOURCE_EXHAUSTED. 양쪽 동시 설정.

### 일반 예외 throw → UNKNOWN으로 묶임
`throw new RuntimeException(...)` 하면 client는 status code UNKNOWN만 받음. `StatusRuntimeException(Status.<CODE>...)` 명시.

### Keepalive client/server mismatch → GOAWAY ENHANCE_YOUR_CALM
client가 5분보다 자주 ping → server가 abusive로 판단해 connection 종료. 양쪽 함께 설정.

### sint vs int wire 불호환
int32 ↔ sint32 wire format 다름. 변경 시 negative 데이터 corruption.

### Kotlin coroutine에서 deadline 누락
`withContext` switching 시 gRPC Context 전파 안 됨. `Context.current().wrap(...)` 또는 `GrpcContextElement` 명시.

## Source

- https://protobuf.dev/programming-guides/proto3/ — "This number cannot be changed once your message type is in use"; "Reusing a field number makes decoding wire-format messages ambiguous"; `reserved` syntax, 조회 2026-05-10
- https://grpc.io/docs/guides/status-codes/ — 16 status codes verbatim (OK ~ UNAUTHENTICATED), 조회 2026-05-10
- https://grpc.io/docs/what-is-grpc/core-concepts/ — 4 RPC types (unary/server/client/bidi); deadline + cancellation semantics, 조회 2026-05-10
- https://grpc.io/docs/guides/keepalive/ — client KEEPALIVE_TIME=INT_MAX default, server PERMIT_KEEPALIVE_TIME=5min, 조회 2026-05-10
- https://grpc.io/docs/languages/kotlin/basics/ — Kotlin coroutine 매핑 (suspend / Flow), 조회 2026-05-10
- https://github.com/grpc/grpc-java/releases — v1.81.0 (2025-05-01) Android API 23+, 조회 2026-05-10
- https://grpc.github.io/grpc-java/javadoc/io/grpc/ManagedChannelBuilder.html — `maxInboundMessageSize` default 4 MiB, 조회 2026-05-10
