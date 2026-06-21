---
keywords: 컨벤션 convention 네이밍 naming 코딩규칙 코딩스타일 codestyle 들여쓰기 indent 포맷 format 패키지 package 브랜치 branch 커밋 commit 에디터 editorconfig prettier checkstyle 정합성 consistency URL url 불일치 mismatch 동기화 sync 필드명 camelCase snake_case 에러코드 errorcode 페이지네이션 pagination 응답형식 response-format
intent: 컨벤션설계해 코딩규칙정해 네이밍정해 프로젝트설정해 규칙만들어 컨벤션확인해 컨벤션해 규칙확인해
paths: .editorconfig .prettierrc .eslintrc checkstyle.xml build.gradle package.json src/api src/types
patterns: editorconfig prettier eslint checkstyle spotless conventional-commits openapi springdoc swagger
requires: backend frontend code-quality
phase: plan
min_score: 3
---

# Project Convention Design Guide

> 원칙: **FE-BE 정합성이 곧 품질** — 네이밍 1개 불일치 = 연동 버그 1개
> 템플릿: `~/.claude/templates/convention/convention-template.md`
> API 명세: `~/.claude/templates/api-spec/` (OpenAPI 3.0 — SDD 핵심)
> 파이프라인: 4단계(초안+OpenAPI 초안) → 9단계(고도화+OpenAPI 완성) → 11단계(계약 검증)
> 검증: C1-C10 이진 체크리스트 (PASS/FAIL)

프로젝트 시작 시 백엔드-프론트엔드 전체 컨벤션을 한 번에 설계하고, 프론트-백엔드 정합성을 검증하는 가이드.

> **스택 적용 범위**: 아래 §0(스택 중립 원칙)은 모든 스택에 적용. §2/§3의 Java·React 예시는 해당 스택일 때만. Flutter/Dart, Kotlin/Android, 그 외 스택은 각자 스킬 트리(`flutter/*`, `kotlin/*`, `typescript/react/*`)의 보완 문서를 추가로 참조. 섹션 2·3은 편집 시 복붙 템플릿이 아닌 **원리 예시**로 읽을 것.

## 0. 스택 중립 원칙 (모든 프로젝트 필수)

> 언어·프레임워크에 무관하게 항상 참이어야 하는 규칙. 스택별 스킬 문서는 이 원칙을 구체화만 하고 **부정하지 않는다**.

1. **네이밍은 한 방향으로 통일** — 같은 레이어 안에서 camelCase/snake_case/kebab-case 혼재 금지. 경계에서만 변환(e.g. DB snake ↔ API camel).
2. **동일 개념에 동일 이름** — `userId`/`user_id`/`uid`를 한 시스템에서 섞지 않는다. 용어집(glossary)을 먼저 정의.
3. **에러 응답은 구조화** — 단순 메시지 문자열 금지. `{status, code, message}` 최소 3필드 + 도메인 prefix 코드 체계.
4. **시간은 ISO 8601** — 어느 스택이든 직렬화 포맷은 ISO 8601 UTC offset 포함(`2026-04-24T09:00:00+09:00`). 타임스탬프 숫자 금지(명시적 선택이 아니면).
5. **API URL/Action은 복수 명사 + 동사 금지** — REST든 WebSocket Action이든 `/orders`, `ORDER_CREATE`식. 레이어 구분은 경로로.
6. **정합성은 검증 자동화** — FE/BE 또는 agent/서버 필드 불일치는 텍스트 비교로 감지 가능해야. OpenAPI, JSON schema, 또는 간이 grep 대조 스크립트.
7. **버전 고정** — 의존성 버전에 `^`/`~`/`latest` 사용 금지. 재현 가능한 빌드.
8. **컨벤션 위반은 CI 게이트** — 검증을 사람에게 맡기지 않는다 (editorconfig/linter/형식 검사).

> 아래 §2(Java/Spring Boot), §3(React/TypeScript)은 위 8개 원칙의 **한 가지 구체화 예시**. 다른 스택에서는 같은 원칙을 그 스택의 관용구로 번역하라.

## 의사결정 트리

### IF 새 프로젝트 컨벤션 설계 (Plan)
1. 템플릿 복사: `cp ~/.claude/templates/convention/convention-template.md <프로젝트>/.claude/convention.md`
2. **환경 설정** — `.editorconfig`, 들여쓰기, 인코딩, 프레임워크 버전
3. **백엔드 컨벤션** — 패키지 구조, 클래스/메서드/DTO 네이밍
4. **프론트엔드 컨벤션** — 디렉토리 구조, 파일/컴포넌트/훅 네이밍
5. **교차 컨벤션** — API URL, JSON 필드, 에러 응답, 날짜, 페이지네이션
6. **Git 컨벤션** — 브랜치 전략, 커밋 메시지
7. **C1-C8 검증** 실행
8. 모든 `{{플레이스홀더}}` 실제 값으로 교체 확인

### IF 프론트-백엔드 정합성 검증 (Review)
1. Controller URL ↔ Frontend API URL 대조
2. Response DTO 필드명 ↔ Frontend Type 필드명 대조
3. ErrorCode enum ↔ Frontend 에러 처리 대조
4. 페이지네이션 응답 형식 일치 확인
5. 날짜 포맷 통일 확인 (ISO 8601)

## 1. 환경 설정

### .editorconfig (프로젝트 루트)
```ini
root = true

[*]
charset = utf-8
end_of_line = lf
indent_style = space
indent_size = 2
insert_final_newline = true
trim_trailing_whitespace = true

[*.java]
indent_size = 4

[*.{yml,yaml}]
indent_size = 2

[Makefile]
indent_style = tab
```

### 프레임워크 버전 고정
```
# backend/build.gradle
plugins { id 'org.springframework.boot' version '3.5.3' }
java { sourceCompatibility = '17' }

# frontend/package.json — 정확한 버전 (^, ~ 제거)
"dependencies": {
  "react": "18.3.1",
  "typescript": "5.6.3"
}
```

## 2. 백엔드 네이밍 — **예시: Java/Spring Boot** (타 스택은 번역하여 적용)

### 패키지 구조
```
com.company.project/
├── domain/{도메인}/          # Entity, Repository(인터페이스), Service, Event, Exception
├── interfaces/{도메인}/      # Controller, Request DTO, Response DTO
├── infrastructure/           # Config, Kafka, Redis, 외부 연동
└── global/                   # CommonResponse, ErrorCode, GlobalExceptionHandler
```

### 클래스 네이밍
| 유형 | 규칙 | 예시 |
|------|------|------|
| Entity | 도메인 명사 | `Order`, `OrderItem` |
| Repository | `{Entity}Repository` | `OrderRepository` |
| Service | `{Domain}Service` | `OrderService` |
| Controller | `{Domain}Controller` | `OrderController` |
| Request DTO | `{Domain}{Action}Request` | `OrderCreateRequest` |
| Response DTO | `{Domain}Response` | `OrderResponse`, `OrderDetailResponse` |
| Exception | `{Domain}{Condition}Exception` | `OrderNotFoundException` |
| Enum | PascalCase | `OrderStatus` |
| Event | 과거형 | `OrderCreated`, `PaymentCompleted` |
| Custom Annotation | `@TransactionalRequired` | `@TransactionalReadOnly` |

### 메서드 네이밍
| 계층 | CRUD | 예시 |
|------|------|------|
| Controller | GET/POST/PUT/DELETE | `getOrder`, `createOrder`, `updateOrder`, `deleteOrder` |
| Service | 비즈니스 동사 | `findById`, `create`, `cancel`, `search` |
| Repository | Spring Data 쿼리메서드 | `findByStatusAndCreatedAtAfter` |

## 3. 프론트엔드 네이밍 — **예시: React/TypeScript** (타 스택은 번역하여 적용)

### 파일 네이밍
| 유형 | 규칙 | 예시 |
|------|------|------|
| Component | `PascalCase.tsx` | `OrderList.tsx` |
| Page | `PascalCase.tsx` + Page 접미사 | `OrderListPage.tsx` |
| Hook | `camelCase.ts` + use 접두사 | `useOrders.ts` |
| API module | `camelCase.ts` | `orderApi.ts` |
| Type file | `camelCase.ts` | `order.ts` |
| Store | `camelCase.store.ts` | `cart.store.ts` |
| 폴더 | `kebab-case` | `add-to-cart/`, `product-detail/` |

### Type/Interface 네이밍
```typescript
// 도메인 모델
interface Order { id: number; status: OrderStatus; ... }

// Enum (const assertion)
const OrderStatus = { PENDING: 'PENDING', PAID: 'PAID' } as const;
type OrderStatus = (typeof OrderStatus)[keyof typeof OrderStatus];

// 폼 데이터
interface OrderFormData { ... }

// API 요청/응답
interface OrderCreateRequest { ... }
interface OrderListResponse { content: Order[]; totalElements: number; ... }
```

## 4. 교차 컨벤션 (FE-BE 공통)

### API URL 설계
```
# 복수 명사, 동사 금지, 계층 표현
GET    /api/orders              목록
GET    /api/orders/{id}         상세
POST   /api/orders              생성
PUT    /api/orders/{id}         수정
DELETE /api/orders/{id}         삭제
POST   /api/orders/{id}/cancel  상태 변경 (액션)

# 검색
GET    /api/orders?status=PENDING&page=0&size=20&sort=createdAt,desc
```

### JSON 필드 네이밍: **camelCase 통일**
```json
{ "orderId": 1, "totalAmount": 35000, "createdAt": "2026-04-07T14:30:00+09:00" }
```
Spring Boot 기본이 camelCase이므로 별도 설정 불필요. snake_case가 필요한 외부 API는 `@JsonProperty`로 개별 매핑.

### 에러 응답 형식
```json
{
  "status": 404,
  "code": "O001",
  "message": "주문을 찾을 수 없습니다",
  "timestamp": "2026-04-07T14:30:00+09:00",
  "path": "/api/orders/999"
}
```
검증 에러(400)에는 `errors[]` 배열 추가: `[{ "field": "items", "value": null, "reason": "..." }]`

### 날짜 포맷: **ISO 8601**
```
2026-04-07T14:30:00+09:00
```
Spring Boot: `spring.jackson.serialization.write-dates-as-timestamps: false`
Frontend: `dayjs(order.createdAt).format('YYYY.MM.DD HH:mm')`

### 페이지네이션 응답
```json
{ "content": [...], "page": 0, "size": 20, "totalElements": 153, "totalPages": 8 }
```

### 디자인 토큰 컴플라이언스 (FE)
프론트엔드에서 하드코딩 색상 사용 금지 — 디자인 토큰 또는 Tailwind 시스템 색상만 허용:

| 금지 | 허용 | 이유 |
|------|------|------|
| `text-[#ef6253]` | `text-bid-buy` | 시맨틱 토큰 |
| `bg-[#41b979]` | `bg-bid-sell` | 시맨틱 토큰 |
| `bg-[#f4f4f4]` | `bg-gray-100` | 시스템 색상 |
| `text-[#dc2626]` | `text-danger` | 기존 토큰 |

**감사 명령**: `Grep("text-\\[#|bg-\\[#|border-\\[#", "src/")` = 0건 (global.css @theme 내부 제외)

**토큰 추가 기준**:
- 기존 토큰(danger/success/warning/primary)과 역할이 같으면 → 재사용
- 시각적으로 다른 도메인 전용 색상이면 → `@theme`에 신규 토큰 추가 (예: `--color-bid-buy`)

## 5. Git 컨벤션

### 브랜치 전략
```
main ← develop ← feature/{ticket}-{description}
                ← bugfix/{ticket}-{description}
                ← hotfix/{version}-{description}
```

### 커밋 메시지 (Conventional Commits)
```
feat(order): 주문 취소 API 추가
fix(payment): 결제 금액 계산 오류 수정
refactor(user): 회원 서비스 레이어 분리
```
type: `feat`, `fix`, `refactor`, `docs`, `style`, `test`, `chore`, `perf`, `ci`

## 6. 프론트-백엔드 정합성 검증

### Level 1: 수동 대조 (최소한)
```
# Controller URL과 Frontend API 모듈 대조
Grep("@GetMapping|@PostMapping|@PutMapping|@DeleteMapping")  → URL 추출
Grep("client.get|client.post|client.put|client.delete")      → URL 추출
→ 양쪽 URL 목록 비교
```

### Level 2: OpenAPI 명세 기반 계약 (필수 — SDD 핵심)

#### 9단계: OpenAPI spec 작성 (Design-First)
```bash
# 템플릿 복사
cp ~/.claude/templates/api-spec/openapi-template.yaml <프로젝트>/.claude/design/openapi.yaml

# PRD AC의 When/Then → paths/responses 변환
# convention의 네이밍/에러/페이징 규칙 → components/schemas 반영
# DB 설계의 Entity 필드 → Request/Response 스키마 반영
```

#### 10단계: OpenAPI → 코드 자동 생성 (Codegen)
```bash
# FE 타입 자동 생성 (필수)
npx openapi-typescript .claude/design/openapi.yaml -o frontend/src/shared/types/generated.ts

# BE 검증: springdoc으로 런타임 spec 자동 생성 → 설계 spec과 대조
# build.gradle: implementation 'org.springdoc:springdoc-openapi-starter-webmvc-ui:2.8.0'
```
- FE는 `generated.ts`의 타입을 import → 필드명 불일치 = **TS 컴파일 에러**
- BE는 OpenAPI spec과 Controller가 일치하는지 11단계에서 검증

#### 11단계: 계약 검증
```bash
# 설계 spec ↔ 런타임 spec 대조
curl http://localhost:8080/v3/api-docs -o runtime-spec.json
# openapi.yaml ↔ runtime-spec.json 경로/스키마 대조
```

### Level 3: 이진 검증 체크리스트 (C1-C8, 모두 PASS 필수)

| # | 체크 항목 | PASS 기준 | 측정 방법 |
|---|----------|----------|----------|
| C1 | 환경 설정 파일 존재 | .editorconfig 존재 + convention.md 존재 | `Glob(".editorconfig")` |
| C2 | 프레임워크 버전 고정 | 버전 번호에 `^`, `~` 없음 | `Grep("\\^\\|~", "package.json")` = 0 |
| C3 | API URL 일치 | Controller URL = Frontend API URL (1:1) | Grep 양쪽 URL 추출 → 대조 |
| C4 | DTO 필드명 일치 | Response DTO 필드 = Frontend Type 필드 | Read 양쪽 → 필드 대조 |
| C5 | 에러 코드 동기화 | ErrorCode enum = Frontend 에러 상수 | Grep 양쪽 에러 코드 → 대조 |
| C6 | 페이지네이션 통일 | content/page/size/totalElements 필드 일치 | Grep 페이지네이션 응답 → 구조 대조 |
| C7 | 날짜 포맷 통일 | ISO 8601 사용, timestamps=false | Grep 날짜 관련 설정 확인 |
| C8 | enum 값 문자열 일치 | BE enum 값 = FE const 값 | Grep 양쪽 enum → 대조 |
| C9 | OpenAPI spec 존재 | `.claude/design/openapi.yaml` 존재 | `Glob("openapi.yaml")` |
| C10 | OpenAPI ↔ PRD 일치 | OpenAPI paths 수 = PRD AC의 API 엔드포인트 수 | paths 카운트 ↔ AC When 절 카운트 |

**4단계(초안)**: C1-C2 검증 (설정 파일 존재 + 버전 고정)
**9단계(고도화)**: C1-C10 전체 검증 (OpenAPI spec 포함)
**10단계(codegen)**: OpenAPI → FE 타입 자동 생성 후 빌드 통과 확인
**11단계(계약 검증)**: C3-C10 재검증 (구현 후 실제 코드 ↔ OpenAPI 대조)

## Gotchas

### camelCase ↔ snake_case 혼재
Spring Boot는 기본 camelCase, 프론트가 snake_case를 기대하면 모든 필드가 undefined. 프로젝트 시작 시 한 가지로 통일하고 문서화할 것.

### ErrorCode 불일치
백엔드 ErrorCode enum을 수정하고 프론트엔드 에러 처리를 안 고치면 사용자에게 "알 수 없는 오류" 표시. ErrorCode 변경 시 양쪽 동시 업데이트 필수.

### API URL 오타
`/api/orders` vs `/api/order` (단수/복수) 불일치는 가장 흔한 연동 버그. URL을 프론트에서도 상수로 관리: `const API = { orders: { list: '/api/orders' } }`.

### 페이지네이션 0-based vs 1-based
Spring Data는 0-based (page=0이 첫 페이지), 일부 프론트 라이브러리는 1-based. 프론트에서 `page - 1`로 변환하거나, 공통 훅에서 처리.

### 컨벤션 문서 미업데이트
컨벤션을 정하고 코드에서 어긴 뒤 문서를 안 고치면 새 팀원이 혼란. `.claude/convention.md`를 항상 최신 상태로 유지.

### OpenAPI 에러 예시 누락 (2-Strike: ecommerce-v2 회고)
Generator가 첫 번째 엔드포인트에만 에러 예시(example)를 넣고 뒤쪽 엔드포인트에서 생략하는 패턴이 반복됨. **모든 에러 응답(400/401/404/409)에 example 블록을 필수로 포함**해야 한다. PRD의 에러 코드(U001, C001, P001 등)가 OpenAPI에 1:1로 나타나야 Evaluator가 검증 가능.

### 내부 전용 API 보안 미명시 (2-Strike: ecommerce-v2 회고)
"내부 시스템 전용" API에 보안 정의 없이 노출하면 외부 접근 가능. 슬라이스 초기에는 bearerAuth(Admin)으로 보호하고, 마이크로서비스 전환 시 내부 인증으로 교체하는 전략을 OpenAPI description에 명시할 것.

### Docker MySQL init 스크립트 재실행 불가
`docker-entrypoint-initdb.d`의 SQL은 **볼륨 최초 생성 시에만** 실행된다. Phase 확장으로 새 DDL 파일(예: `03-community.sql`)을 추가해도 기존 볼륨이 있으면 적용되지 않는다. 새 DDL 추가 시 수동 적용 필수: `docker exec -i ecommerce-mysql mysql -uroot -proot ecommerce < init/03-community.sql`. 또는 `docker compose down -v`로 볼륨 삭제 후 재생성 (데이터 초기화 주의).

## 도구 사용 패턴 (Harness)
- 컨벤션 문서: `Write`로 `.claude/convention.md` 생성
- 환경 설정: `Write`로 `.editorconfig`, `.prettierrc` 생성
- 정합성 검증: `Grep`으로 양쪽 URL/타입 추출 → 대조
- Spring OpenAPI: `Bash`로 spec 추출 → 타입 생성

## 에러 복구 패턴 (Harness)
- URL 불일치 → `Grep`으로 Controller/API 모듈 URL 추출 → 비교 → 수정
- 필드명 불일치 → `Read`로 Response DTO + Frontend Type 동시 확인 → 어느 쪽을 수정할지 판단
- 에러 코드 불일치 → `Grep("ErrorCode|error_code|ERROR_MESSAGES")`로 양쪽 검색 → 동기화
