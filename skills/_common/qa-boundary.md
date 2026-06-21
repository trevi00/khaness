---
name: qa-boundary
description: Producer-Consumer 경계면(boundary) 정합성 사전 검증 — 두 컴포넌트를 통합할 때 양쪽을 동시에 읽고 shape/타입/경로/상태 매핑을 교차 비교하여 런타임 폭발 전에 contract mismatch를 잡는다. Integration 시점에 사용. fullstack-debug(런타임 디버깅), verification-before-completion(완료 게이트), ultraqa(자동 루프)와 영역 분담.
keywords: boundary contract coherence cross-check producer-consumer producer consumer contract-mismatch interface-contract dto-shape api-shape response-shape schema-mapping shape-mismatch openapi grpc avro 경계면 계약 정합성 양쪽동시 인터페이스 계약검사 contract mismatch 매핑 shape 정합성검증
intent: boundary-cross-check contract-check two-side-read interface-coherence shape확인해 정합성검증해 경계면검증해 경계대조해 계약확인해 양쪽일치해 인터페이스맞춰 contract맞춰 boundary확인
paths: src/api src/hooks src/types src/dto src/contracts contracts openapi proto avro schemas
patterns: openapi grpc graphql kafka rest fetch axios httpclient retrofit dio json-rpc
phase: implement
min_score: 2
---

# QA Boundary — Producer-Consumer 경계면 정합성 검증

> 원천: revfactory/harness `qa-agent-guide.md` (SatangSlide 7개 버그 사례) — Next.js 의존성 제거하여 일반화.
> 도입: 2026-05-05, debate session `debate-1777963974-4e8915` 분리 PR 결의.

## 핵심 원리: "양쪽 동시 읽기"

경계면 버그는 두 컴포넌트가 *각각* 올바른데 *연결 지점에서* 계약이 어긋날 때 발생한다. 한쪽만 읽어서는 못 잡는다. 정적 코드 리뷰(타입체크, 빌드)도 제네릭 캐스팅·`any`·런타임 unwrapping에 무력.

**규칙**: 통합 코드를 작성·리뷰할 때 producer 파일과 consumer 파일을 **동시에 열어서** shape를 비교하라.

| 검증 대상 | 왼쪽 (producer) | 오른쪽 (consumer) |
|---|---|---|
| API 응답 shape | route/handler의 응답 직렬화 코드 | client의 fetch 호출 + 타입 바인딩 |
| 라우팅 | 페이지/엔드포인트 파일 경로 | 코드 내 모든 link/redirect/router.push 값 |
| 상태 전이 | 상태 머신 정의(맵/enum) | 실제 status 업데이트 호출 |
| 데이터 매핑 | DB 컬럼명 / 메시지 스키마 | API 응답 필드명 → 클라이언트 타입 |

## 의사결정 트리

### IF 통합 코드 작성 (Implement)
1. **Producer-Consumer 페어 식별** — 어떤 두 파일이 계약으로 연결되는가
2. **양쪽 파일을 동시 Read** — 절대 한쪽만 보고 추측 금지
3. **6 패턴 체크리스트** 적용 (아래 §6 패턴)
4. 불일치 발견 시 **양쪽 모두 수정 필요한지** 판단 (대개 producer 우선이지만, 깨진 contract는 consumer가 잘못 가정한 경우도 흔함)

### IF 통합 코드 리뷰 (Review)
1. PR diff에서 **경계면 변경**(producer 또는 consumer 한쪽만 변경)이 있는지 검사
2. 한쪽만 변경됐다면 → 반드시 반대편 파일을 같이 read 후 일치 여부 판정
3. 6 패턴 체크리스트 PASS/FAIL 표기
4. FAIL 항목은 **파일:라인 + 양쪽 인용**으로 코멘트 (한쪽만 인용하면 안 됨)

### IF 신규 통합 모듈 설계 (Plan)
1. **계약을 SSOT로 명시** — OpenAPI / GraphQL schema / Proto / Avro / JSON Schema 중 하나를 선택해 둘 다 그것을 reference로 하도록 설계
2. 코드 생성 가능하면 활용 (openapi-generator, protoc, avro-tools 등)
3. SSOT 부재 상황에서는 양쪽 코드에 **계약 주석**으로 페어 명시 (예: `// pair: src/types/order.ts::OrderResponse`)

### IF "런타임 동작 디버깅" 시점 (Debug)
→ 이 스킬 아님. **`fullstack-debug.md`** 사용 (런타임 흐름 추적은 그쪽 책임).

### IF "완료 직전 증거 확인" 시점 (Pre-completion)
→ 이 스킬 아님. **`verification-before-completion.md`** 사용 (메타 게이트).

## 6 Boundary 패턴 (Stack 무관 일반화)

### 패턴 1: 응답 shape ↔ 클라이언트 타입
**증상**: `xxx.filter is not a function`, `Cannot read property 'foo' of undefined`, 빈 배열로 보이는데 데이터 있음.

**검증**:
1. producer가 직렬화하는 객체의 *최외곽* shape 추출 (예: `{items: [...], total: N}` vs `[...]`)
2. consumer가 fetch 결과를 어떻게 unwrap하는지 확인 (`.items` 접근? 직접 배열로 처리?)
3. **래핑 일치** 확인 — producer가 `{data: ...}` 래핑하면 consumer도 `.data` unwrap

**특히 주의**:
- 페이지네이션: `{items, total, page}` vs 단순 배열
- 즉시응답(202 Accepted) vs 최종 결과의 shape 차이
- 단일 객체 vs 배열 (`/users/:id` vs `/users`)

### 패턴 2: 라우트/파일 경로 ↔ 링크/네비게이션
**증상**: 404, 화면 깜빡임 후 이상한 페이지, 새 탭 열기는 되는데 in-app navigation 안 됨.

**검증**:
1. producer = 페이지/엔드포인트 파일들의 실제 URL 경로 (route group, 동적 세그먼트, 접두사 포함)
2. consumer = 코드 내 모든 link/href/router.push/redirect 값
3. **각 link 값이 실제 페이지 파일과 매칭**되는지 1:1 검증
4. 그룹/접두사가 URL에서 제거/유지되는지 framework convention 확인

### 패턴 3: 상태 머신 정의 ↔ 실제 status 업데이트
**증상**: 영원히 대기 상태, 특정 단계에서 멈춤, 일부 분기로 영영 안 들어감.

**검증**:
1. producer = 상태 전이 맵/enum/규칙 정의 (`STATE_TRANSITIONS` 같은 SSOT)
2. consumer = 모든 `.update({status: ...})` / `setState` / `entity.status = ...` 호출 site
3. **모든 정의된 전이가 코드에서 실행되는가** (죽은 전이 검출)
4. **모든 코드 전이가 정의된 전이인가** (무단 전이 검출)
5. 중간 상태 → 최종 상태 전환이 누락되지 않는지

### 패턴 4: 엔드포인트 ↔ 호출자 1:1 매핑
**증상**: 백엔드는 동작하는데 UI는 변화 없음, 또는 그 반대.

**검증**:
1. 모든 엔드포인트(API route, RPC method, message topic) 목록 추출
2. 모든 호출자(hook, client method, subscriber) 목록 추출
3. **A: 엔드포인트는 있지만 호출하는 코드가 없음** → 의도적 관리 API인지, 호출 누락인지 판단
4. **B: 호출 코드는 있지만 엔드포인트가 없음** → 404 빌트인 버그
5. 의도적 미호출(관리 API 등)은 코드/문서에 명시

### 패턴 5: 즉시응답 ↔ 비동기 결과 shape
**증상**: response 받자마자 `.failedItems` 같은 필드 접근하고 크래시. 또는 결과 폴링이 영원히 끝남.

**검증**:
1. producer가 즉시 반환하는 shape (`{status: "accepted", jobId}`)와 비동기 완료 후 결과 shape (`{status: "done", failedItems}`)이 다른가
2. consumer가 즉시응답에서 비동기 결과 필드를 접근하는지 검사
3. 비동기 결과는 **별도 폴링/웹훅/이벤트로 받는다**는 컨벤션이 양쪽에 표시되어 있는지

### 패턴 6: 데이터 매핑 (DB 컬럼 ↔ API 필드 ↔ UI 타입, 케이스 변환)
**증상**: 이미지 안 보임, 사용자 이름 빈 값, "데이터 있는데 화면에 안 떠".

**검증**:
1. DB 컬럼명 (대개 snake_case)
2. ORM 매핑 (camelCase 변환?)
3. API 응답 필드명 (어느 케이스인가)
4. 클라이언트 타입 정의 (어느 케이스인가)
5. **3 layer 모두에서 일관된 명명 규칙** 확인. 한 layer만 다르면 모든 케이스 변환 코드 점검
6. 옵셔널 필드: `null` vs `undefined` vs 키 자체 부재 — 양쪽이 같은 가정인가

## Skill Boundary (영역 분담)

| 시점 | 스킬 | 차이 |
|---|---|---|
| **Plan/Implement: 통합 시점 사전 정합성 교차검증** | `qa-boundary` | 양쪽 정적 read + shape 비교 — 런타임 전 차단 |
| Debug: 런타임 흐름 추적 | `fullstack-debug` | DB→Backend→Frontend 흐름 코드레벨 디버깅 |
| Review: 자동 QA 루프 | `ultraqa` | test/build/lint 사이클 자동 실행 + 진단·수정 |
| Review: 완료 주장 직전 메타 게이트 | `verification-before-completion` | "X 동작합니다" 발화 직전 증거 확인 |

> 같은 풀스택 도메인이지만 phase가 다르다. 통합 *코드를 짤 때* qa-boundary, 통합 코드가 *런타임에 안 될 때* fullstack-debug, *완료 주장 직전* verification.

## Stack Examples (부록 — 일반화 패턴 매핑)

### Spring Boot + REST API
- Producer: `@RestController`의 `@GetMapping` 메서드 반환 객체 (DTO)
- Consumer (server-to-server): `RestTemplate`/`WebClient` + DTO 클래스
- 패턴 6 주의: Jackson `@JsonProperty` / `application/properties`의 `spring.jackson.property-naming-strategy`
- 패턴 4: `@RequestMapping` 모음 ↔ `@FeignClient` 인터페이스

### Express/Node + Frontend
- Producer: `app.get(path, (req, res) => res.json(...))`의 객체 shape
- Consumer: `fetch` / `axios` + TypeScript 타입 정의
- 패턴 1 주의: `res.json({data: ...})` 래핑 vs 직접 객체 — `Array.isArray` 가드로 양쪽 호환 가능하지만 명시적 contract가 우월

### FastAPI + 클라이언트 SDK
- Producer: pydantic `Response Model` (FastAPI는 자동 OpenAPI 생성)
- Consumer: `openapi-generator`로 SDK 자동생성 → 매번 SDK 재생성으로 패턴 1·6 자동 회피
- 패턴 5 주의: `BackgroundTasks` / `202` 명시적 표기

### Flutter + REST/gRPC
- Producer: 서버 endpoint
- Consumer: `dio` / `retrofit` + freezed/json_serializable 모델
- 패턴 6 주의: `JsonKey(name: 'snake_case_field')` 매핑이 모든 필드에 일관되게 적용
- 패턴 3 주의: enum 직렬화는 서버와 동일 문자열 사용 (`@JsonValue('PENDING')`)

### Kafka/Pub-Sub Producer-Consumer
- Producer: 메시지 직렬화 (Avro/Proto/JSON)
- Consumer: 역직렬화 + 비즈니스 처리
- 패턴 1 + 패턴 6: schema registry 활용 (Confluent / Karapace) — schema evolution 시 forward/backward compat 명시
- 패턴 4: 토픽 ↔ consumer group 1:N 매핑 (의도적 다중 소비자 vs 누락 소비자)

## Gotchas

### 빌드 통과 ≠ 정상 동작
TypeScript 제네릭 캐스팅(`fetchJson<T>`)은 런타임 응답이 T가 아니어도 컴파일 통과. 빌드만 보고 PASS 처리하면 패턴 1 버그 100% 누락. 반드시 producer 직렬화 코드까지 같이 읽기.

### "한쪽만 살짝 수정"이 가장 위험
PR diff가 producer 또는 consumer 한쪽만 건드리면 즉시 6 패턴 체크리스트 가동. "이 변경은 frontend만이라" 같은 자기 안심 멘트가 가장 흔한 구멍.

### Optional 필드의 null vs undefined vs 부재
세 가지 표현이 의미상 다르게 해석되면 패턴 1 버그. 양쪽 코드에서 동일한 default(`?? ''` vs `|| ''` vs `if (x === undefined)`) 사용하는지 검증.

### 응답 wrapping 일관성 부재
일부 엔드포인트는 `{data: ...}` 래핑, 일부는 직접 반환. consumer가 일관된 unwrap 함수를 거치는지 확인. 혼재하면 매번 boundary 체크 필요.

### 코드 생성기를 쓰면서도 수동 타입 작성
openapi-generator / proto-codegen이 SSOT인데 옆에 손으로 쓴 타입이 있으면 drift. 자동 생성된 타입만 사용하고 import 경로를 lock.

### 상태 전이 맵을 갱신하면서 코드 누락
패턴 3에서 새 상태 추가 시 (a) 맵 정의, (b) 진입 코드, (c) UI 분기 셋 다 동시 수정 안 하면 영원히 대기 버그. 셋이 같은 PR에 들어가야 함.

## 도구 사용 패턴 (Harness)
- 양쪽 동시 read: 단일 메시지에서 producer + consumer 파일을 병렬 Read
- 6 패턴 체크: PR 리뷰 시 이 스킬을 의식적으로 의사결정 트리로 적용
- 신규 boundary 추가: SSOT(OpenAPI/Proto/Avro)부터 정의, 코드 생성 도구 활용
