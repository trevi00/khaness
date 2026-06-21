# OpenAPI 명세 템플릿

> SDD(Spec-Driven Development) 핵심 산출물
> PRD AC + convention + DB 설계 → 기계 가독 API 계약
> 이 명세가 코드 생성, 타입 생성, 계약 테스트의 SSOT

## 설계 원칙

1. **PRD가 원본** — OpenAPI는 PRD AC의 기계 가독 변환이다
2. **Convention이 규칙** — 네이밍, 에러 형식, 페이지네이션은 convention.md 준수
3. **DB 설계가 스키마** — Response/Request 스키마는 Entity 필드에서 파생
4. **이 명세가 계약** — FE 타입과 BE Controller는 이 파일에서 자동 생성

## 사용법

### 1. 프로젝트에 복사
```bash
cp ~/.claude/templates/api-spec/openapi-template.yaml <프로젝트>/.claude/design/openapi.yaml
```

### 2. PRD → OpenAPI 변환 규칙

| PRD 요소 | OpenAPI 매핑 |
|---------|------------|
| US의 API (When 절) | `paths` 경로 + HTTP method |
| AC 성공 응답 (Then 2XX) | `responses` 200/201/204 |
| AC 에러 응답 (Then 4XX) | `responses` 400/404/403/409 |
| 기능 상세 필드 | `schemas` Request/Response properties |
| 상태 전이 규칙 상태값 | `schemas` enum |
| 역할별 접근 제어 | `security` + 경로별 설명 |
| 페이징/정렬/필터 | `parameters` query params |

### 3. 코드 생성 (Codegen)

#### FE 타입 자동 생성
```bash
# OpenAPI → TypeScript 타입
npx openapi-typescript .claude/design/openapi.yaml -o frontend/src/shared/types/generated.ts
```

#### BE Controller 인터페이스 (선택)
```bash
# OpenAPI → Spring Controller interface
# openapi-generator-cli 사용
npx @openapitools/openapi-generator-cli generate \
  -i .claude/design/openapi.yaml \
  -g spring \
  -o backend/src/main/java \
  --additional-properties=interfaceOnly=true
```

### 4. 검증

#### A1: PRD ↔ OpenAPI 경로 대조
```
PRD AC의 When 절 URL 목록 ↔ OpenAPI paths 목록 → 1:1 일치
```

#### A2: OpenAPI ↔ FE 타입 대조
```
OpenAPI schemas ↔ generated.ts 타입 → 자동 일치 (codegen이므로)
```

#### A3: OpenAPI ↔ BE Controller 대조
```
OpenAPI paths ↔ Controller @*Mapping URL → 1:1 일치
```

## 산출물 위치
```
project/.claude/design/
└── openapi.yaml           # API 명세 (SSOT)

project/frontend/src/shared/types/
└── generated.ts           # OpenAPI에서 자동 생성된 타입

project/backend/
└── (Controller가 OpenAPI 경로와 일치하는지 검증)
```
