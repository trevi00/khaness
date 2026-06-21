# {{프로젝트명}} Convention Guide

> 생성일: {{날짜}}
> 파이프라인 4단계 산출물 — 9단계에서 고도화

---

## 1. 환경 설정

### 런타임/프레임워크 버전
| 구분 | 기술 | 버전 |
|------|------|------|
| Backend | {{프레임워크}} | {{버전}} |
| Backend Language | {{언어}} | {{버전}} |
| Frontend | {{프레임워크}} | {{버전}} |
| Frontend Language | TypeScript | {{버전}} |
| Database | {{DB}} | {{버전}} |
| Cache | {{캐시 (있으면)}} | {{버전}} |
| Queue | {{큐 (있으면)}} | {{버전}} |

### 들여쓰기/인코딩
```ini
# .editorconfig
root = true

[*]
charset = utf-8
end_of_line = lf
indent_style = space
indent_size = {{기본 들여쓰기}}
insert_final_newline = true
trim_trailing_whitespace = true

[*.{{백엔드 확장자}}]
indent_size = {{백엔드 들여쓰기}}

[*.{yml,yaml}]
indent_size = 2
```

---

## 2. 백엔드 컨벤션

### 패키지 구조
```
{{베이스 패키지}}/
├── domain/{{도메인}}/          # Entity, Repository, Service, Event, Exception
├── interfaces/{{도메인}}/      # Controller, Request DTO, Response DTO
├── infrastructure/             # Config, 외부 연동
└── global/                     # 공통 응답, 에러 코드, 예외 핸들러
```

### 클래스 네이밍
| 유형 | 규칙 | 예시 |
|------|------|------|
| Entity / Domain Model / VO / DTO | 도메인 명사 (Lombok DTO) | `{{엔티티 예시}}` |
| DAO / Mapper | `{Entity}DAO` 또는 `{Entity}Mapper` | `{{리포지토리 예시}}` |
| Service | `{Domain}Service` | `{{서비스 예시}}` |
| Controller | `{Domain}Controller` | `{{컨트롤러 예시}}` |
| Request DTO | `{Domain}{Action}Request` | `{{요청 예시}}` |
| Response DTO | `{Domain}Response` | `{{응답 예시}}` |
| Exception | `{Domain}{Condition}Exception` | `{{예외 예시}}` |
| Event | 과거형 | `{{이벤트 예시}}` |

### 메서드 네이밍
| 계층 | 패턴 | 예시 |
|------|------|------|
| Controller | HTTP 동사 기반 | `get{{도메인}}`, `create{{도메인}}` |
| Service | 비즈니스 동사 | `findById`, `create`, `cancel` |
| DAO/Mapper | MyBatis 매퍼 메서드 | `select{{Entity}}By{{조건}}`, `insert{{Entity}}`, `update{{Entity}}`, `delete{{Entity}}` |

---

## 3. 프론트엔드 컨벤션

### 파일 네이밍
| 유형 | 규칙 | 예시 |
|------|------|------|
| Component | PascalCase.tsx | `{{컴포넌트 예시}}.tsx` |
| Page | PascalCase + Page | `{{페이지 예시}}Page.tsx` |
| Hook | use + camelCase.ts | `use{{훅 예시}}.ts` |
| API module | camelCase.ts | `{{API 예시}}Api.ts` |
| Type file | camelCase.ts | `{{타입 예시}}.ts` |
| 폴더 | kebab-case | `{{폴더 예시}}/` |

### 타입 정의
```typescript
// 도메인 모델 — 백엔드 Response DTO와 필드명 일치 (camelCase)
interface {{도메인}} {
  id: number;
  // ...
}

// Enum — const assertion
const {{도메인}}Status = { {{상태값들}} } as const;
type {{도메인}}Status = (typeof {{도메인}}Status)[keyof typeof {{도메인}}Status];

// 폼 데이터
interface {{도메인}}FormData { /* ... */ }
```

---

## 4. 교차 컨벤션 (FE-BE 공통)

### API URL 설계
```
{{HTTP Method}}  /api/{{리소스(복수형)}}              목록/생성
{{HTTP Method}}  /api/{{리소스(복수형)}}/{id}          상세/수정/삭제
{{HTTP Method}}  /api/{{리소스(복수형)}}/{id}/{{액션}}  상태 변경
```
- **복수 명사**, 동사 금지
- 계층 표현: `/api/{{부모}}/{parentId}/{{자식}}`

### JSON 필드 네이밍: **{{camelCase or snake_case}}**
```json
{ "{{필드예시A}}": 1, "{{필드예시B}}": "값", "createdAt": "2026-01-01T00:00:00+09:00" }
```

### 에러 응답 형식
```json
{
  "status": {{HTTP 상태코드}},
  "code": "{{도메인코드}}",
  "message": "{{에러 메시지}}",
  "timestamp": "{{ISO 8601}}",
  "path": "/api/{{경로}}"
}
```
검증 에러(400): `errors[]` 배열 추가 — `[{ "field": "{{필드}}", "value": null, "reason": "{{사유}}" }]`

### 에러 코드 체계
| 접두사 | 도메인 |
|--------|--------|
| {{코드1}} | {{도메인1}} |
| {{코드2}} | {{도메인2}} |

### 날짜 포맷: **ISO 8601**
```
{{예시: 2026-04-08T14:30:00+09:00}}
```
- Backend: `spring.jackson.serialization.write-dates-as-timestamps: false` (Spring Boot 3.x 기본값)
- Frontend: `dayjs(date).format('YYYY.MM.DD HH:mm')`

### 페이지네이션 응답
```json
{
  "content": [...],
  "page": 0,
  "size": {{기본 페이지 크기}},
  "totalElements": {{전체 수}},
  "totalPages": {{전체 페이지 수}}
}
```
- 페이지 인덱스: **0-based** (Spring Data 기본)
- 기본 크기: {{기본값}}
- 최대 크기: {{최대값}}

---

## 5. Git 컨벤션

### 브랜치 전략
```
main ← develop ← feature/{{티켓}}-{{설명}}
                ← bugfix/{{티켓}}-{{설명}}
                ← hotfix/{{버전}}-{{설명}}
```

### 커밋 메시지 (Conventional Commits)
```
{{type}}({{scope}}): {{설명}}
```
type: `feat`, `fix`, `refactor`, `docs`, `style`, `test`, `chore`, `perf`, `ci`

---

## 6. 정합성 검증 체크리스트

- [ ] Controller URL ↔ Frontend API URL 1:1 매핑
- [ ] Response DTO 필드명 ↔ Frontend Type 필드명 일치
- [ ] ErrorCode enum ↔ Frontend 에러 상수 동기화
- [ ] 페이지네이션 응답 필드 일치
- [ ] 날짜 필드 ISO 8601 통일
- [ ] enum 값 문자열 일치

---

<!-- 작성 체크리스트 (작성 완료 후 삭제) -->
<!--
- [ ] 모든 {{플레이스홀더}} 실제 값으로 교체
- [ ] .editorconfig 파일 실제 생성 확인
- [ ] 백엔드 패키지 구조 프로젝트에 반영
- [ ] 프론트엔드 디렉토리 구조 프로젝트에 반영
- [ ] API URL 규칙이 PRD AC의 When 절 URL과 일치
- [ ] JSON 필드 네이밍 FE-BE 통일 확인
- [ ] 에러 응답 형식이 PRD 에러 AC와 일치
- [ ] 에러 코드 접두사가 PRD 도메인 수와 일치
-->
