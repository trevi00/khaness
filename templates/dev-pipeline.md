# 개발 파이프라인 (Development Pipeline)

> 원칙: **모든 단계는 생성-검증 쌍** (Generator-Evaluator 패턴)
> 방법론: **Spec-Driven Development** — 명세가 SSOT, 명세에서 코드 생성, 구현을 명세로 검증
> 출처: [Anthropic Harness Design](https://www.anthropic.com/engineering/harness-design-long-running-apps)
> 검증 실패 시 해당 단계로 복귀하여 수정 후 재검증

---

## 파이프라인 단계

| # | 단계 | 생성 (Generator) | 검증 (Evaluator) | 스킬 |
|---|------|-----------------|-----------------|------|
| 1 | 요구사항 명세 | 요구사항 수집 → 명세서 작성 | 명세서 완성도 검증 (TCPF, 금지어, 추적성) | doc-writer → doc-verify |
| 2 | PRD 문서화 | 템플릿 기반 트리 구조 PRD 작성 | Fresh Agent 이진 게이트 검증 (20 PASS/FAIL) | doc-writer → doc-verify |
| 3 | 기능 플로우차트 | 도메인별 시퀀스/플로우 다이어그램 생성 | US/AC와 플로우 1:1 대조 검증 | flow-design → doc-verify |
| 4 | 환경/컨벤션 초안 | 개발 환경, 프레임워크 버전, 들여쓰기 + **OpenAPI 초안** | 설정 파일 존재 + 일관성 확인 (C1-C2) | convention |
| 5 | 개념적 설계 | ER 다이어그램 생성 (엔티티, 관계) | PRD 도메인과 ER 엔티티 1:1 대조 | db-design → doc-verify |
| 6 | 논리적 설계 | 정규화, 관계 상세화, 제약조건 | 정규화 규칙 + PRD 상태 전이 반영 검증 | db-design |
| 7 | 물리적 설계 | DDL + 클래스 다이어그램 생성 | ER ↔ 클래스 다이어그램 ↔ DDL 3자 대조 | db-design + flow-design → doc-verify |
| 8 | 뼈대 설계 | 프로젝트 디렉토리 구조 생성 | 빌드 통과 확인 (compileJava / tsc) | scaffolding → build-loop |
| 9 | 완벽한 컨벤션 + **OpenAPI 완성** | 전 규칙 + **OpenAPI 3.0 spec 작성** (SDD 핵심) | C1-C10 전체 + OpenAPI ↔ PRD 대조 | convention |
| 10 | 뼈대 고도화 + **codegen** | BE: DDD+EDD, FE: FSD + **OpenAPI → generated.ts** | S1-S7 + codegen 빌드 통과 | scaffolding + backend + frontend → build-loop |
| 11 | 프론트-백 **계약 검증** | — (검증 전용) | OpenAPI ↔ Controller URL ↔ FE API ↔ DTO 대조 | convention (review) |
| 12 | 개발 진행 | 도메인별 점진적 구현 (컴파일 루프) | 매 단위 컴파일 + 서버 시작 + curl 테스트 | build-loop |
| 13 | 구현-문서 불일치 검증 | — (검증 전용 단계) | 각 US/AC를 코드에서 Grep 검증 (Spec Verification) | doc-verify |
| 14 | E2E 테스트 | Playwright MCP로 배치 자동 테스트 | 크롬 스크린샷 + API 응답 확인 | verification |
| 15 | 테스트 코드 작성 | 단위/통합 테스트 작성 | 커버리지 목표 달성 확인 | testing |

---

## 검증 실패 시 복귀 규칙

```
검증 FAIL 발생
    │
    ├── 해당 단계의 생성물 수정
    │
    ├── SSOT 연쇄 업데이트 (이전 단계 산출물에 영향 있으면)
    │
    └── 재검증 → PASS 시 다음 단계로 진행
```

**DDR 수렴 기준 적용**: 검증 반복 시 DDR < 0.1이면 다음 단계로 진행.

---

## Gate 분류 체계 (GSD 흡수)

각 파이프라인 단계의 검증 실패 시 4가지 Gate 유형으로 분류하여 대응:

| Gate | 목적 | 동작 | 복구 |
|------|------|------|------|
| **Pre-flight** | 작업 시작 전 사전조건 | 조건 미충족 → 진입 차단 | 누락 항목 수정 후 재시도 |
| **Revision** | 산출물 품질 평가 | 피드백 루프 (max 3회) | Generator가 피드백 반영 → Evaluator 재평가 |
| **Escalation** | 자동 해결 불가 | 워크플로우 일시 중단, 옵션 제시 | 개발자 결정: [A] Force-pass + override, [D] Defer to backlog, [R] 수동 개입 |
| **Abort** | 계속 진행 시 손상/낭비 | 즉시 중단, 상태 보존 | 근본 원인 조사 후 체크포인트에서 재시작 |

### Gate 선택 흐름
```
사전조건 확인 → Pre-flight Gate (저비용, 결정론적)
    ↓ 통과
산출물 생성 후 → Revision Gate (피드백 루프, max 3회)
    ↓ 3회 초과에도 미해결
자동 해결 불가 → Escalation Gate (개발자 결정)
    ↓ 계속 진행이 위험한 경우
즉시 중단 필요 → Abort Gate (상태 보존)
```

### 파이프라인 단계별 Gate 적용

| 단계 | Pre-flight | Revision | Escalation |
|------|-----------|----------|-----------|
| 1-2 PRD | requirements/ 존재 | doc-verify FAIL → 수정 (3회) | 모호한 requirement |
| 3 플로우 | PRD 완료 확인 | mermaid-validate FAIL → 수정 | US↔플로우 불일치 |
| 5-7 DB설계 | ERD 완료 확인 | verify-er FAIL → 수정 | 설계 결정 충돌 |
| 8-10 뼈대 | 설계 완료 확인 | build FAIL → 수정 | 아키텍처 결정 필요 |
| 12 구현 | 뼈대 빌드 통과 | 컴파일 FAIL → 수정 | 도메인 간 의존성 |
| 14 E2E | 서버 시작 가능 | 테스트 FAIL → 수정 | 환경 문제 |

### Iteration Cap 규칙
- Revision Gate는 **최대 3회** 반복
- 3회 초과 시 자동으로 Escalation Gate로 전환
- Escalation에서 개발자가 [A] Force-pass 선택 시 override 문서화 필수

---

## 파이프라인 자동 라우팅 (GSD /kha-advance 흡수)

현재 상태를 감지하여 다음 단계를 자동으로 결정:

### Safety Gates (진행 전 확인)
1. `.claude/STATE.md` 또는 `.planning/.continue-here.md` 존재 → 미완료 작업 먼저 해결
2. 이전 단계 검증 FAIL 미해결 → Revision 또는 Escalation Gate 적용
3. 에러 상태 → 디버깅 먼저

### 라우팅 규칙

| 조건 | 다음 단계 |
|------|----------|
| PRD 없음 | 1단계: doc-writer |
| PRD 있으나 doc-verify 미통과 | 1단계: doc-verify |
| PRD 통과, 플로우차트 없음 | 3단계: flow-design |
| 플로우차트 있으나 컨벤션 없음 | 4단계: convention |
| 컨벤션 있으나 DB 설계 없음 | 5단계: db-design |
| DB 설계 있으나 DDL 없음 | 7단계: db-design (물리적) |
| DDL 있으나 뼈대 없음 | 8단계: scaffolding |
| 뼈대 있으나 빌드 미통과 | 8단계: build-loop |
| 빌드 통과, 구현 미완료 | 12단계: build-loop (도메인별) |
| 구현 완료 | 14단계: verification |
| 검증 통과 | ship (PR 생성) |

### 상태 감지 방법
- `.claude/requirements/` 존재 여부 → PRD 단계
- `.claude/design/flows/` 존재 여부 → 플로우차트 단계
- `src/main/java/` 존재 여부 → 구현 단계
- `./gradlew compileJava` 성공 여부 → 빌드 상태

---

## 단계별 산출물

| # | 단계 | 산출물 | 위치 |
|---|------|--------|------|
| 1-2 | 요구사항/PRD | 트리 구조 PRD (16+ 파일) | `<project>/.claude/requirements/` |
| 3 | 플로우차트 | Mermaid 시퀀스/플로우 다이어그램 | `<project>/.claude/design/flows/` |
| 4 | 환경 설정 | .editorconfig, docker-compose.yml 등 | `<project>/` |
| 5 | 개념적 설계 | ER 다이어그램 (Mermaid) | `<project>/.claude/design/er/` |
| 6 | 논리적 설계 | 정규화된 스키마 정의 | `<project>/.claude/design/schema/` |
| 7 | 물리적 설계 | DDL + 클래스 다이어그램 | `<project>/.claude/design/ddl/`, `<project>/.claude/design/class/` |
| 8-10 | 뼈대 | 프로젝트 소스 코드 구조 | `<project>/backend/`, `<project>/frontend/` |
| 9 | 컨벤션 + OpenAPI | 컨벤션 문서 + API 명세 | `<project>/.claude/convention.md`, `<project>/.claude/design/openapi.yaml` |
| 11 | 컨벤션 검증 | 검증 리포트 | (검증 결과만, 별도 파일 불필요) |
| 12 | 구현 | 소스 코드 | `<project>/backend/src/`, `<project>/frontend/src/` |
| 13 | Spec 검증 | 불일치 리포트 | (검증 결과만) |
| 14 | E2E 테스트 | 스크린샷 + 테스트 결과 | `<project>/e2e/` |
| 15 | 테스트 코드 | 단위/통합 테스트 | `<project>/backend/src/test/`, `<project>/frontend/src/__tests__/` |

---

## Generator-Evaluator 매핑

```
[Generator 스킬]          [Evaluator 스킬/방법]            [이진 기준]
doc-writer         ─────→  doc-verify (Fresh Agent)        G1-G5 (20 PASS/FAIL)
flow-design        ─────→  doc-verify (크로스 검증)         F1-F7
db-design          ─────→  doc-verify (3자 대조)            D1-D9
convention         ─────→  convention (review + OpenAPI)   C1-C10
scaffolding        ─────→  build-loop (컴파일 + codegen)   S1-S7
build-loop         ─────→  doc-verify (Spec Verification)  B1-B4
verification       ─────→  Playwright MCP (E2E)            E1-E4
testing            ─────→  커버리지 + 계약 테스트            T1-T5
```

## SDD (Spec-Driven Development) 체인

```
PRD AC (When/Then)
    │
    ├──→ OpenAPI spec (openapi.yaml) ← SSOT for API contract
    │       │
    │       ├──→ FE: openapi-typescript → generated.ts (자동 타입)
    │       │       → 필드명 불일치 = TS 컴파일 에러
    │       │
    │       ├──→ BE: Controller URL + DTO 필드 → OpenAPI spec 대조
    │       │       → 경로/스키마 불일치 = 계약 테스트 FAIL
    │       │
    │       └──→ 11단계: 설계 spec ↔ 런타임 spec ↔ FE 타입 3자 대조
    │
    └──→ 13단계: PRD AC ↔ 코드 Grep (Spec Verification)
```

## 템플릿 위치

| 단계 | 템플릿 | 위치 |
|------|--------|------|
| 1-2 | PRD | `~/.claude/templates/prd/` (9파일) |
| 3 | 플로우차트 | `~/.claude/templates/flowchart/` (3파일) |
| 4/9 | 컨벤션 | `~/.claude/templates/convention/` (1파일) |
| 5-7 | DB 설계 | `~/.claude/templates/db-design/` (3파일) |
| 9-11 | API 명세 (SDD) | `~/.claude/templates/api-spec/` (2파일) |
| 전체 | 파이프라인 | `~/.claude/templates/dev-pipeline.md` |

---

## 사용법

### 새 프로젝트 시작 시
```bash
cp ~/.claude/templates/dev-pipeline.md <project>/.claude/pipeline.md
```
각 단계 완료 시 체크하며 진행. 검증 실패 시 해당 단계로 복귀.

### 진행 상황 추적
```markdown
- [x] 1. 요구사항 명세 — 생성 완료, 검증 PASS
- [x] 2. PRD 문서화 — 생성 완료, 검증 PASS (DDR 0.0, 5라운드)
- [ ] 3. 기능 플로우차트 — 진행 중
- [ ] 4. 환경/컨벤션 초안
...
```
