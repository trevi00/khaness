---
name: jpa-query-shape
description: JPA endpoint를 query-shape contract로 — projection·fetch plan·entity graph + open-in-view 제거
keywords: jpa hibernate projection fetch-plan entity-graph open-in-view n-plus-one query-budget
intent: shape-queries kill-n-plus-one remove-open-in-view define-query-budget
paths: src/main/**/Repository*.java src/main/**/*Service*.java
patterns: spring-data-jpa hibernate @Query @EntityGraph Projection
requires: transaction-proxy-boundaries
phase: plan implement review debug
tech-stack: java
min_score: 2
---

# JPA Query Shape (Spring Data JPA 3.5)

> 각 endpoint는 query-shape contract를 가진다 — 무엇을 select하고, 어떻게 fetch하고, 몇 개의 query가 도는가.

## 의사결정 트리

### IF 새 read endpoint 설계 (Plan|Implement)
1. 응답에 필요한 필드만 explicit projection (interface/class projection 또는 DTO query) — 엔티티 통째 반환 금지
2. to-many association이 필요한가? → entity graph 또는 fetch join. 없으면 안 끌어온다
3. query budget 명시 — "이 endpoint는 query 1개" / "1 + N 허용 안함" 같은 contract를 PR에 적는다
4. open-in-view는 OFF (`spring.jpa.open-in-view=false`) — controller 단에서 lazy loading하지 않는다

### IF list endpoint가 운영에서만 폭발 (Debug)
1. 실제 query 수를 먼저 측정 — Hibernate statistics, p6spy, 또는 통합 테스트의 `assertSelectCount`
2. lazy to-many가 list iteration에서 N+1로 풀리는지 확인 → entity graph/fetch join/`@BatchSize`
3. 인덱스 튜닝은 query 수 줄인 뒤 — query 1000개를 빠르게 만들지 말고 1개로 만든다

### IF "controller에서 LazyInitializationException" (Debug|Refactor)
1. open-in-view에 의존 중 → 끄고, service 경계 안에서 모든 fetch 완료
2. controller가 entity를 직접 반환하고 있다면 DTO/projection으로 끊는다
3. service에서 fetch plan을 명시적으로 — repository method 시그니처에 entity graph 부착

### IF write endpoint (Implement|Review)
1. transaction 경계가 controller가 아닌 service에서 시작/종료
2. write 단위가 한 트랜잭션에 들어맞는지 — bulk update면 batch size 명시
3. 변경 전후 audit/event 발행은 같은 트랜잭션 vs after-commit 명확히

## 가이드

- repository method 시그니처 자체가 query-shape — 이름과 반환 타입에 contract가 보여야 함.
- pagination이 있는 list endpoint는 count query 모양도 검토 — slow count가 흔한 회귀 지점.

## Gotchas

### `findAll()` 반환을 그대로 controller에
- 엔티티 직렬화는 lazy proxy 트리거 + 무한 재귀 + 필요 없는 필드까지 노출. projection으로 끊는다.

### `@Transactional`을 controller에 부착
- transaction 경계는 service. controller는 HTTP 변환 책임.

### open-in-view를 default ON으로 방치
- controller 단 lazy loading이 우연히 동작 → 운영에서만 N+1 폭발. 명시적으로 OFF + 필요한 fetch는 service에서.

## Source

- `frameworks/backend/spring-data-jpa/3.5.x/01_docs/2026-04-20__tech-kb-import__entity-mapping-fetch-strategy-and-query-guide__3-5-x.md`
- `frameworks/backend/spring-data-jpa/3.5.x/05_patterns/2026-04-26__local-spring__projection-fetch-plan-transaction-boundary-and-query-shape-patterns__3-5-x.md`
- `frameworks/backend/spring-data-jpa/3.5.x/07_troubleshooting/2026-04-26__local-spring__open-in-view-lazy-collection-risk-and-query-budget-drift-troubleshooting__3-5-x.md`
- `frameworks/backend/spring-data-jpa/3.5.x/06_templates/2026-04-26__local-spring__spring-data-jpa-query-shape-template-with-projection-and-budget-baseline__3-5-x.md`
