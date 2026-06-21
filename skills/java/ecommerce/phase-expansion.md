---
keywords: phase expansion domain new entity add entity 확장 페이즈 도메인 추가 엔티티
intent: 도메인추가해 엔티티추가해 페이즈확장해 expanding project with new domain entities
paths: .claude/sentinels.yaml .claude/convention.md .claude/scripts/validators/
patterns: EXPECTED_ENTITIES EXPECTED_ENUMS Phase
requires:
min_score: 3
phase: implement
---

# Phase 확장 체크리스트

> 이커머스 프로젝트에 새 도메인/엔티티를 추가할 때, 아래 **모든 항목**을 빠짐없이 갱신해야 한다.
> 하나라도 누락하면 evaluator가 FAIL을 발생시키거나, 다음 Phase에서 불일치가 전파된다.

When adding new domain entities to the ecommerce project, ALL of the following must be updated:

## 1. 설계 문서 (Design Docs)

- [ ] **conceptual-er.md**: 엔티티 블록 + 관계 + Aggregate Root 표 + UNIQUE 표 + PRD 크로스 레퍼런스
- [ ] **logical-design.md**: 테이블 정의 + 인덱스 섹션 6 확장
- [ ] **DDL**: `init/XX-{domain}.sql` 파일 추가
- [ ] **openapi.yaml**: paths + schemas + standalone enums
- [ ] **flows/{domain}.md**: Mermaid 시퀀스 다이어그램
- [ ] **skeleton-design.md**: 파일 목록

## 2. PRD

- [ ] **domain/{domain}.md**: US (User Story) + AC (Acceptance Criteria)
- [ ] **index.md**: domain 참조 + US 범위 + US 수 업데이트
- [ ] **architecture.md**: 이벤트 + 역할 매트릭스

## 3. 컨벤션 + 구조 문서

- [ ] **convention.md**: `domain/{domain}/` + `interfaces/{domain}/` + kafka consumer 추가

## 4. Evaluator 데이터 구조 업데이트

각 evaluator의 하드코딩된 데이터 구조를 확장해야 한다 (canonical validator 모듈은 `~/.claude/scripts/validators/`):

### validators/er.py
- [ ] `EXPECTED_ENTITIES`
- [ ] `EXPECTED_ENUMS`
- [ ] `EXPECTED_UNIQUE`
- [ ] `EXPECTED_AGGREGATES`
- [ ] `EXPECTED_RELATIONSHIPS`
- [ ] `REQUIRED_ATTRS`
- [ ] `OPENAPI_SCHEMA_TO_ENTITY`
- [ ] `OPENAPI_ENUM_TO_ER`
- [ ] `CONVENTION_DOMAINS`

### validators/prd.py
- [ ] `EXPECTED_INDEX_REFS`
- [ ] `DOMAIN_FILES`

### validators/openapi.py
- [ ] `EXPECTED_STANDALONE_ENUMS`

## 5. 센티넬 갱신

- [ ] **sentinels.yaml**: ALL affected sections (er, logical, ddl, openapi, prd, flow, skeleton, codegen, contract)
- [ ] 각 evaluator의 하드코딩된 센티넬 상수가 sentinels.yaml과 일치하는지 확인

## 6. Backend 구현 컨벤션 (Agent 전달 필수)

아래 규칙을 Agent에게 위임 시 반드시 프롬프트에 포함:

- [ ] Controller는 Service만 주입 (Repository 직접 주입 금지)
- [ ] DTO는 모두 Lombok @Getter/@Setter 기반 (CommonHeaderDTO 상속)
- [ ] Wildcard import 금지 (explicit imports only)
- [ ] `@Table` 소문자 필수
- [ ] Kafka Consumer: 멱등성(`ProcessedEvent`) + DLT 패턴

## 7. Frontend

- [ ] **Router.tsx**: import + Route 추가
- [ ] **entities/{domain}/model.ts** + **api.ts**

## 8. Skeleton 검증 (필수 — Cycle 2에서 누락된 교훈)

> **IMPORTANT**: Phase 22-23에서 skeleton step을 생략하여 구조 정합성 미검증 상태로 구현 진행됨.
> 향후 모든 도메인 확장 시 아래 3단계를 반드시 실행해야 한다.

- [ ] **Generator**: skeleton-design.md 파일 목록 갱신 (§1 항목 6)
- [ ] **Evaluator**: `validators/skeleton.py` 검증 → 상위 3문서(CD+OA+Convention) ↔ skeleton 매핑 PASS 확인
- [ ] **Evaluator**: `validators/codegen.py` 검증 → skeleton 명시 파일이 디스크에 존재하는지 확인

이 3단계가 PASS한 후에만 Backend/Frontend 구현으로 넘어갈 것.

## 9. 검증 순서

Phase 확장 완료 후 evaluator를 아래 순서로 실행:

1. `validators/skeleton.py` (skeleton ↔ 상위 문서 매핑)
2. `validators/codegen.py` (skeleton 명시 파일 존재)
3. `validators/{domain}.py` (도메인별 evaluator)
4. `validators/prd.py`
5. `validators/er.py`
6. `validators/openapi.py`
7. `validators/ddl.py`
8. `validators/test.py`

> **IMPORTANT**: 각 evaluator가 PASS할 때까지 다음으로 넘어가지 말 것.
> FAIL 발생 시 원인을 수정하고 해당 evaluator를 재실행하여 PASS 확인 후 다음 단계 진행.

## 의사결정 트리

### IF 새 도메인 추가 요청 (Implement)
1. **[G] PRD**: domain/{domain}.md 작성 → index.md, architecture.md 갱신
2. **[E] validators/prd.py** PASS 확인
3. **[G] ER/논리설계**: conceptual-er.md + logical-design.md 확장
4. **[E] validators/er.py + validators/logical.py** PASS 확인
5. **[G] DDL**: init/XX-{domain}.sql 작성
6. **[E] validators/ddl.py** PASS 확인
7. **[G] OpenAPI + Flow**: openapi.yaml + flows/{domain}.md
8. **[E] validators/openapi.py + validators/flow.py** PASS 확인
9. **[G] Skeleton**: skeleton-design.md 파일 목록 갱신 + convention.md
10. **[E] validators/skeleton.py** PASS 확인 ← Cycle 2에서 누락된 단계
11. **[G] Evaluator**: validators/{domain}.py 선제 작성 + evaluator 데이터 확장 + sentinels.yaml
12. **[G] Backend 구현** (섹션 6 컨벤션 준수)
13. **[G] Frontend 구현** (섹션 7)
14. **[E] validators/codegen.py** PASS 확인 (skeleton 파일 전수 존재)
15. **[E] 전체 evaluator 순서대로 실행** (섹션 9)

### IF 기존 도메인에 엔티티 추가 (Implement)
1. conceptual-er.md에 엔티티 + 관계 추가
2. logical-design.md 테이블 + 인덱스 추가
3. DDL 기존 파일에 CREATE TABLE 추가 또는 새 파일 생성
4. openapi.yaml schema + path 추가
5. PRD에 관련 US/AC 추가
6. evaluator 데이터 구조 확장 (EXPECTED_ENTITIES 등)
7. sentinels.yaml 수량 갱신
8. 검증 순서대로 evaluator 실행

### IF evaluator FAIL 발생 (Debug)
1. FAIL 메시지에서 누락된 항목 확인
2. 해당 문서/코드 수정
3. sentinels.yaml 수량이 실제와 일치하는지 확인
4. evaluator 재실행하여 PASS 확인
5. 연쇄 영향 확인: 하나의 문서 수정이 다른 evaluator에 영향을 주는지 체크
