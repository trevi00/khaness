---
name: api-contracts
description: Backend API as a versioned, deprecation-aware contract — field/status/error envelope/pagination governance with deprecation period and consumer-driven testing.
keywords: api-contract api-versioning rest http openapi swagger graphql grpc deprecation sunset header path-versioning header-versioning backward-compatible breaking-change additive status-code error-envelope pagination cursor consumer-driven contract-test pact stripe-style
intent: API버저닝해 contract설계해 deprecation정해 sunset header걸어 status코드정해 error envelope만들어 pagination contract정해 호환성지켜
paths: api/ src/api src/controllers src/routes openapi.yaml swagger.yaml proto/ graphql/ contracts/
patterns: openapi swagger oas3 pact apig spectral redoc grpc-gateway protobuf graphql-codegen api-blueprint
requires: test-governance idempotency rollback-readiness security
phase: plan implement review
tech-stack: any
min_score: 2
---

# API Contracts

API는 endpoint 모음이 아니라 **버전 + 상태 의미 + 비호환성 처리**의 contract. 4축: field/type compat, status semantics, error envelope, pagination — 그리고 deprecation period가 명시되어야 함.

## 의사결정 트리

### IF 새 API 정의 (Plan)
1. versioning style 결정 — path(`/v1/...`), header(`API-Version`), media type(`application/vnd.x.v1+json`) 중
2. response shape — 필드 스키마, type, nullable 여부, default
3. status code 표준화 — 200/201/202/204, 4xx 분류, 5xx 일관성
4. error envelope — `{code, message, details?, traceId?}` 같은 단일 형식
5. pagination — offset vs cursor, page size 한도, total count 포함 여부
6. **→ test-governance 스킬: contract regression 테스트로 회귀 방지**

### IF Field 변경 (Implement)
1. 분류 — additive(새 optional field), breaking(필수 추가, type 변경, rename, 삭제)
2. additive면 minor 버전 + changelog. consumer는 새 필드 무시 가능
3. breaking이면 새 major 버전. 옛 버전 유지 + deprecation period
4. nullable 필드 추가는 additive로 취급 (consumer가 null 처리해야 함)
5. enum 값 추가는 borderline — 옛 consumer가 unknown enum 처리 못 하면 breaking

### IF Status / Error 변경 (Implement)
1. status code 변경(예: 200 → 201) = breaking — client가 status 분기에 의존
2. error code 추가(envelope의 `code` 필드 새 값) = additive로 취급, default handler가 fallback
3. error code rename 또는 의미 변경 = breaking
4. error message 변경 = non-breaking이지만 client가 메시지로 분기하면 위험 — code 기반 분기 권장

### IF Deprecation (Plan)
1. 필요한 경우 — security, 비즈니스 로직 변경, 더 좋은 design 발견
2. period 결정 — 보통 6개월~1년. 내부 API는 짧게, 공개 API는 길게
3. 신호 — `Deprecation` 헤더 + `Sunset` 헤더 (RFC 8594) + 문서 + changelog
4. usage tracking — 옛 버전 호출 client 식별 → 마이그레이션 도움
5. forced cutoff — period 끝나면 410 Gone 또는 새 버전으로 redirect

### IF API 변경 PR Review (Review)
- [ ] OpenAPI/Proto schema diff — additive only인지
- [ ] breaking change 시 새 major 버전인지
- [ ] deprecation 도입 시 period + sunset header
- [ ] consumer 영향 분석 (lineage 또는 usage analytics)
- [ ] contract test가 새 schema 기준 통과
- [ ] error envelope 일관성

## Compatibility 계약 체크리스트

```
[Field / Type]
□ 새 필드는 optional (required 추가 금지)
□ 필수 필드 삭제 금지
□ type narrowing 금지 (string → enum)
□ rename은 alias 유지 + deprecation

[Status Codes]
□ 같은 endpoint의 success status 변경 금지
□ 4xx 분류 일관성 (validation은 400 vs 422 통일)
□ 새 status는 client default handler 가능

[Error Envelope]
□ 모든 error 응답이 같은 형식
□ machine-readable code 필드 (UI message 분기 X)
□ traceId 포함 (디버깅)
□ 5xx에 내부 정보 노출 금지

[Pagination / Lists]
□ size 상한 (보통 100)
□ cursor 또는 offset 일관
□ total count는 비싼 경우 optional
□ 빈 결과의 형식(`[]` vs `null`) 통일

[Deprecation]
□ Deprecation 헤더 + Sunset 날짜
□ changelog + migration guide
□ usage tracking → 마이그레이션 push
□ period 만료 후 410 또는 redirect
```

## 가이드

### Versioning style 비교
- **Path versioning** (`/v1/`, `/v2/`): 명시적이고 cache-friendly. 버전 폭증 시 dedup 어려움.
- **Header versioning** (`API-Version: 2026-01`): URL 안 바뀜. 일자 기반 versioning(Stripe 스타일) 가능. 디버깅·로깅 시 헤더 누락 흔함.
- **Media type** (`Accept: application/vnd.x.v2+json`): RESTful 정통. 도구 지원이 약함.
- 일반: 외부 공개 API는 path, 내부 마이크로서비스는 header. 일관성이 중요.

### Stripe-style date versioning
버전을 `2026-01-15` 같은 날짜로. client가 등록한 날짜 기준으로 server가 응답 변환. major 버전 폭증 회피 + breaking change를 incremental하게.

### Error envelope 디자인
```json
{
  "code": "user_not_found",       // machine-readable, snake_case
  "message": "User does not exist", // human, 영어 + 다국어는 별도 i18n 키
  "details": [                       // optional, validation 등 다중 에러
    {"field": "email", "code": "invalid_format"}
  ],
  "traceId": "abc123"                // 분산 trace ID
}
```

### Pagination — cursor가 안전
offset pagination은 데이터가 추가/삭제되면 row 빠지거나 중복. cursor(또는 keyset)는 안정적. 단점은 임의 페이지 jump 불가.

### Consumer-driven contract test
producer의 OpenAPI snapshot보다 consumer가 "이렇게 쓴다"는 contract(Pact)를 producer가 통과하는 게 진짜 호환성. 여러 consumer면 여러 pact.

## Gotchas

### 두 서비스가 공유하는 HTTP DTO는 필드 add/remove에 배포순서 결합
공유 DTO 필드 변경(특히 `@NotNull` 추가/제거)은 양쪽 동시배포 의존 — 우리만 먼저 배포하면 상대 서비스가 400(예: 후킹서버 acceptance). → (1) **nullable/하위호환 추가**로 'we-first 안전' 우선, (2) 불가피한 동시변경은 deploy-together를 **PR 본문 메모가 아니라 명시 체크항목/배포 GATE**로 강제. (스키마 ALTER-before-deploy와 별개의 DTO-계약 변종. poslink #59)

### "additive"라며 enum 값 추가
옛 consumer가 unknown enum을 exception으로 처리하면 breaking. proto는 default `UNKNOWN`, JSON은 client에서 fallback 강제 필요. 안전 가정 못 하면 새 버전.

### Required 필드 추가
"명시 안 하면 422 validation error" — 옛 client 즉시 깨짐. nullable optional로만 추가, 기존 API 버전엔 노출 안 함.

### Status code 의미 변경 (200 → 202)
async로 바꾸면서 status를 200(완료)에서 202(accepted)로 → client가 200만 success로 처리하면 다 fail. 새 endpoint 또는 새 버전.

### Error message 기반 client 분기
`if (e.message === "User not found") ...` 같은 client 코드는 message만 바꿔도 깨짐. machine-readable `code` 필드 + client가 그걸로 분기하도록 가이드.

### Sunset header 없이 그냥 endpoint 삭제
하루 아침에 410 Gone 응답하면 사용 중인 client 다 fail. 최소 6개월 deprecation period + 마지막 N개월 강한 통보.

### OpenAPI는 있는데 실제 API와 drift
spec 따로, 코드 따로 → 응답에 spec에 없는 필드 / spec에 있는 필드 누락. 매 PR마다 spec ↔ 실제 응답 contract test.

### Pagination total count가 비싸서 N+1
큰 테이블에 `count(*)` 매 요청 실행 → DB 비용 폭발. cursor pagination + total은 optional("나중에 필요하면 별도 endpoint").

### Trailing slash 인식 차이
`/users` vs `/users/` 다르게 처리하면 client가 한 쪽으로 통일 안 됨 → 일부 fail. 항상 redirect 또는 둘 다 같은 응답.

### 시간 형식 inconsistent
같은 API 안에서 `created_at`은 ISO 8601, `updated_at`은 unix timestamp 같은 혼용 → client 파싱 코드 복잡. UTC ISO 8601(`2026-04-26T12:00:00Z`)로 통일.

### Breaking change 한꺼번에 v2 launch
v1 → v2가 너무 많이 바뀌면 마이그레이션 비용 폭발 → 6개월 후에도 v1 80% 사용. 작은 단위 deprecation으로 점진 진화.

### 내부 API는 contract 안 지켜도 된다는 가정
"우리만 쓰니까"가 다른 팀/서비스에는 외부. consumer가 1개라도 contract test 가치 있음.

### Error code namespace 충돌
multiple service가 같은 `code: "not_found"` 쓰면 client가 source 모름. service prefix(`user.not_found`, `order.not_found`).

## 도구 사용 패턴 (Harness)
- spec diff: `Bash`로 `oasdiff` 또는 `openapi-diff` 실행
- contract test: `Bash`로 pact-broker, postman, dredd
- usage analytics: API gateway 로그 → 옛 버전 client 식별
- linting: `Bash`로 `spectral` 또는 `vacuum`로 OpenAPI 규칙 검사

## 에러 복구 패턴 (Harness)
- consumer가 갑자기 4xx 폭증 → 최근 schema PR diff + deprecation header 추가 여부 확인
- "version not found" → version routing 또는 header 파싱 점검
- contract test red → producer 코드와 spec drift, 둘 중 어느 게 source of truth인지 결정 후 정렬
- deprecation 통보 안 갔다 → usage analytics로 affected client 식별 후 별도 통보

## Related (신규 그래프 cross-ref)

api-contracts가 결합되는 신규 노드:
- `java/lang/grpc-service-contracts.md` — proto3 wire format + 16 status codes + reserved field 강제
- `kotlin/android/graphql-apollo-android.md` — Apollo Kotlin 4.x cache key (`__typename` + `id`) + fetchPolicy 5종
- `_common/webhook-delivery-and-signing.md` — Stripe/GitHub/Slack HMAC-SHA256 + 5분 timestamp tolerance + raw body
- `_common/api-migration-replay-traffic.md` — Falcor → GraphQL Federation, replay traffic 3-step + sticky canary
- `_common/edge-gateway-routing.md` — Envoy JWT authn filter + retry budget
