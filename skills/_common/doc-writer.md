---
keywords: PRD prd 요구사항 requirements 명세서 specification 문서작성 writing 생성 create 작성 write 설계문서 design-doc 유저스토리 user-story 도메인분석 domain-analysis 기획 planning 템플릿 template
intent: PRD작성해 요구사항작성해 명세서만들어 문서생성해 설계문서써줘 문서만들어 문서해 작성해
paths: docs/ design/ .claude/ requirements spec
patterns: requirements specification user-story acceptance-criteria given-when-then problem-statement persona scope
requires: context-docs
phase: plan
min_score: 3
---

# PRD 작성 가이드 (Document Writer)

> 원칙: **템플릿 기반 구조화 작성** — 빈 문서가 아닌 검증 가능한 트리 구조로 시작
> 템플릿: `~/.claude/templates/prd/` (9 entries: `architecture.md / changelog.md / context.md / domain/ / glossary.md / index.md / nfr.md / README.md / risks.md`)
> 선택 추가물: 도메인이 이벤트 / 알림을 다룰 때만 `notification.md` 추가 (templates 외 — 프로젝트 단위 생성).
> 참조 구현: `ecommerce/.claude/requirements/` (10도메인/28 US/21차 검증 완료)
> 검증: 작성 완료 후 `doc-verify.md` 스킬로 5 Quality Gates 검증

## 의사결정 트리

### IF 새 프로젝트 PRD 작성 (Plan)
1. 템플릿 복사 → 프로젝트에 배치
2. context.md 작성 (문제→목표→페르소나→범위)
3. 도메인 파일 생성 (의존성 순서)
4. 시스템 설계 문서 작성 (nfr→architecture→risks)
5. 용어집 + 변경이력
6. doc-verify 스킬로 검증

### IF 기존 PRD에 도메인 추가 (Plan)
1. domain/_template.md 복사 → 새 도메인 파일 생성
2. US + AC 작성
3. SSOT 연쇄 업데이트 (architecture, notification, glossary)
4. index.md 문서 맵 업데이트

### IF 기존 PRD 수정 (Plan)
1. 수정 대상 파일 Read
2. Edit으로 수정
3. SSOT 연쇄 업데이트
4. changelog.md 버전 추가

## Spec Bundle emit (forward 요구사항 stage — unified-pipeline 통합)

`_pipeline` 요구사항 stage(stages.core.yaml `requirements`)는 서술형 `requirements.md`에 더해 **stack-neutral Spec Bundle**(`<project>/.claude/spec/`)을 emit한다. reverse-prd와 동일한 단일 spec 계약이라, 요구사항이 그대로 forward test-gen(`lib.testgen`)으로 이어진다.

1. **스캐폴드 (CLI, greenfield)** — 도메인 식별 직후 1회:
   ```
   python -m cli.spec_bundle_emit --root <project> --out <project> --source-mode forward --domains a,b,c
   ```
   → `spec/manifest.yaml`(source_mode=forward, 명시 도메인), `spec/domain/<d>.feature` **scaffold**(`@id:<d>-TODO`). greenfield라 DDL 없으니 facet은 아직 안 나옴(idempotent — DDL stage 후 재실행하면 추가).
2. **행위 spine 저작 (이 스킬)** — 각 US를 `spec/domain/<d>.feature`의 `@id`'d Given-When-Then 시나리오로. **성공 AC + 에러 AC 동시**(아래 "AC 작성" 규칙 그대로). Gherkin엔 **행위만**(DB/API 구조는 facet으로, 절대 Gherkin에 X).
3. **facet 자동 합류** — DDL stage(`ddl`)가 `schema.sql` 생성 후 위 CLI 재실행 → `spec/facets/{logical,er}.schema` 자동 추가(저작된 `.feature`는 clobber 안 함).
4. **검증** — `python -m validators.spec_bundle`(@id 유일·manifest↔domain·facet 정합, advisory).

`requirements.md`/`domain/*.md` 2-track PRD는 유지하되, `.feature`는 그 GWT AC의 **기계가독 승격본**. forward·reverse가 같은 Spec Bundle 포맷으로 수렴.

## 작성 순서 (의존성 기반)

```
Phase 1: context.md
  문제 정의 → 목표/KPI → 페르소나 → 범위(In-Scope + Non-Goals)
  ※ 나머지 모든 문서의 기반. 여기가 틀리면 전부 틀린다.

Phase 2: domain/*.md (의존성 없는 것부터)
  _template.md를 복사하여 도메인별 파일 생성
  각 도메인: US → 기능 상세 → AC(성공+에러 쌍) → 상태 전이 → 동시성
  ※ 도메인 간 의존 관계 파악 후 하위부터 작성

Phase 3: nfr.md
  ISO 25010 8개 속성별 요구사항 + 측정 수치 + 측정 주기

Phase 4: architecture.md
  이벤트 목록 + 동기/비동기 경계 + 캐시 전략 + 역할 매트릭스
  ※ Phase 2의 모든 도메인 이벤트/API를 여기에 집약 (SSOT)

Phase 5: risks.md
  리스크 매트릭스 + 의존성 + 가정 + 거부된 대안

Phase 6: glossary.md + changelog.md
  본문에서 사용한 전문 용어 수집 → 정의

Phase 7: index.md
  문서 맵 + 기술 스택 요약 (모든 파일 완성 후 최종 작성)
```

## 템플릿 사용법

### 1. 프로젝트에 복사
```bash
cp -r ~/.claude/templates/prd/ <프로젝트>/.claude/requirements/
```

### 2. 도메인 파일 생성
```bash
cd <프로젝트>/.claude/requirements/domain/
cp _template.md user.md
cp _template.md product.md
cp _template.md order.md
# 도메인 수만큼 반복
```

### 3. {{플레이스홀더}} 채우기
모든 `{{...}}`를 실제 내용으로 교체.

## 도메인 파일 작성 규칙

### US 작성
```
- AS {{역할}} I WANT {{행동}} SO THAT {{가치}}
```
- 역할은 context.md 페르소나와 일치
- 행동은 구체적 (금지어 사용 금지)
- 가치는 비즈니스 관점

### AC 작성 — 성공+에러 쌍 동시 작성
모든 성공 AC에 대응하는 에러 AC를 **같이** 작성:

| HTTP | 용도 | 예시 |
|------|------|------|
| 400 | 유효성 실패 | 빈 필드, 형식 오류, 비즈니스 규칙 위반 |
| 404 | 리소스 없음 | 존재하지 않는 ID, 타인 리소스 접근 |
| 403 | 권한 없음 | 역할 불일치 |
| 409 | 충돌/중복 | 이메일 중복, UPSERT 충돌 |

### 에러 메시지 구조 통일
```json
{ "status": 404, "code": "XX001", "message": "요청한 리소스를 찾을 수 없습니다" }
```
- 코드 접두사: 도메인별 고유 (U=User, P=Product, O=Order 등)

### 목록 API 필수 명시 항목
- **정렬**: 기본 정렬 + 가능한 정렬 기준
- **필터**: 역할별/상태별/기간별
- **페이징**: 방식(오프셋/커서) + 기본 크기

### 상태 전이 필수 항목
```
[*] → 초기상태    : 생성 트리거
상태A → 상태B     : 전이 트리거
```
- 초기 상태(`[*]→`) 반드시 포함
- 허용 전이 + **금지 전이** 모두 명시

## SSOT 분배 규칙

도메인 파일 작성/수정 시 **반드시** 아래 파일도 업데이트:

| 변경 내용 | 업데이트 대상 | 조건 |
|----------|-------------|------|
| 새 이벤트 추가 | architecture.md (이벤트 목록, 페이로드, 토픽) | always |
| 새 API 추가 | architecture.md (역할 매트릭스) | always |
| 알림 관련 이벤트 | notification.md (알림 매핑 테이블) | **only if** 프로젝트가 notification.md를 채택했을 때 (이벤트 도메인 ON) |
| 동기 호출 추가 | architecture.md (동기/비동기 경계), risks.md (내부 의존성) | always |
| 새 전문 용어 | glossary.md | always |
| 새 성능/보안 요건 | nfr.md | always |

## 금지어 회피 (작성 시 적용)

작성 단계에서 금지어를 사전에 차단하면 검증 시 FAIL을 방지:

| 금지어 | 대체 표현 |
|--------|----------|
| 적절한/충분한 | 구체적 수치 (예: "5개 이상", "200ms 이내") |
| 빠르게/효율적으로 | P99 ≤ 1초, 캐시 히트율 ≥ 80% |
| 처리한다/관리한다 | 구체적 동사 (생성, 삭제, 조회, 변경, 차감, 복구) |
| ~할 수 있다 | ~한다 (필수), ~하지 않는다 (금지) |
| 등/기타 | 완전한 열거 |

## Non-Goals 3종 세트

의도적으로 제외하는 기능은 반드시 3가지를 명시:
1. **제외 항목**: 무엇을 빼는지
2. **제외 사유**: 왜 빼는지
3. **재검토 트리거**: 어떤 조건이 되면 다시 검토하는지 (정량적)

## Rejected Alternatives 작성법

| 필수 항목 | 설명 |
|----------|------|
| 대안명 | 검토한 기술/방법론 |
| 검토 사유 | 왜 검토했는지 |
| 장점 | 이 대안의 강점 |
| 단점 | 이 대안의 약점 |
| 기각 근거 | 현재 선택이 더 나은 이유 |
| 재검토 트리거 | 정량적 조건 (예: "상품 10만 건 초과 시") |

## Gotchas

### 검증 전에 SSOT부터
도메인 파일만 쓰고 architecture.md (그리고 프로젝트가 notification.md를 채택했다면 notification.md도) 업데이트를 빠뜨리면 검증에서 반드시 FAIL. 도메인 1개 완성할 때마다 SSOT 파일 동시 업데이트.

### context.md가 기반
페르소나 역할명이 도메인 US의 AS 역할과 불일치하면 추적성 FAIL. context.md 먼저 확정.

### 에러 AC 후작성 금지
"나중에 에러 케이스 추가하자"는 100% 누락. 성공 AC 작성 즉시 에러 AC도 작성.

### index.md는 마지막
모든 파일이 완성된 후 문서 맵 작성. 중간에 쓰면 파일 추가/삭제 시 불일치.

## 도구 사용 패턴 (Harness)
- 템플릿 복사: `Bash(cp -r ~/.claude/templates/prd/ <프로젝트>/.claude/requirements/)`
- 도메인 파일 생성: `Bash(cp domain/_template.md domain/<도메인명>.md)`
- 플레이스홀더 채우기: `Read` → `Edit`으로 `{{...}}` 교체
- SSOT 업데이트: `Read` architecture.md → `Edit`으로 이벤트/API 추가
- 작성 완료 후: doc-verify 스킬로 검증 (별도 실행)

## 에러 복구 패턴 (Harness)
- 도메인 간 용어 불일치 → context.md 페르소나/용어 확인 → 통일
- SSOT 누락 발견 → 도메인 파일의 이벤트/API 전수 조사 → architecture.md 일괄 반영
- 금지어 사용 → 구체적 수치/동사로 즉시 교체
