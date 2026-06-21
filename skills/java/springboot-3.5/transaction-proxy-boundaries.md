---
name: transaction-proxy-boundaries
description: @Transactional/AOP/self-invocation/thread-hop을 proxy boundary 한 단위로 다룬다
keywords: transactional aop proxy self-invocation thread-hop async cglib propagation
intent: trace-proxy-boundary fix-self-invocation handle-thread-hop choose-propagation
paths: src/main/**/*Service*.java src/main/**/*Repository*.java
patterns: spring-framework-6 @Transactional @Async @Cacheable proxy-based-aop
requires: jpa-query-shape virtual-threads
phase: implement review debug
tech-stack: java
min_score: 2
---

# Transaction & Proxy Boundaries

> Spring의 `@Transactional`/`@Async`/`@Cacheable`는 proxy 기반이다 — 호출이 proxy를 가로지르지 않으면 어노테이션은 무효다.

## 의사결정 트리

### IF "@Transactional이 안 먹힌다" (Debug)
1. self-invocation 점검 — 같은 빈 안의 `this.foo()` 호출은 proxy를 거치지 않음. 다른 빈으로 추출하거나 `AopContext.currentProxy()` 사용
2. private/protected/final 메서드인지 — proxy가 못 감쌈. public 인스턴스 메서드여야 함
3. 빈이 진짜 Spring container 관리 빈인지 — `new`로 만든 객체에는 적용 안 됨

### IF thread hop이 발생하는 코드 (Implement|Review)
1. `@Async`/`CompletableFuture.supplyAsync`/별도 ExecutorService로 넘기면 트랜잭션·security·MDC가 자동으로 따라가지 않음
2. 트랜잭션이 필요하면 새 트랜잭션을 자식 thread에서 명시적으로 시작 (`PROPAGATION_REQUIRES_NEW`)
3. 컨텍스트는 ScopedValue/명시적 carrier로 전달 — ThreadLocal 자동 전파 가정 금지
4. virtual threads로 변경 시에도 proxy boundary는 동일 — pinning은 별도 문제 (virtual-threads skill 참조)

### IF transaction propagation 결정 (Plan|Implement)
1. 기본은 `REQUIRED` — 호출자 트랜잭션에 참여
2. "이 작업은 부모와 무관하게 commit/rollback" → `REQUIRES_NEW`. 단, 별도 connection 소비
3. "절대 트랜잭션 안에서 돌면 안 됨" → `NEVER`/`NOT_SUPPORTED`
4. read-only 메서드는 `readOnly=true` 명시 — Hibernate dirty check 비활성화로 비용 감소

### IF circular dependency 경고 (Refactor|Review)
1. 설계로 해결 — mediator service, event publication, 명확한 ownership
2. lazy/setter injection으로 가리지 않는다 — 더 큰 구조 문제의 신호

## 가이드

- 트랜잭션 경계는 service 메서드 단위가 기본. controller에 `@Transactional` 부착 금지 (jpa-query-shape 참조).
- `LazyInitializationException`은 트랜잭션/세션 경계 문제이지 ORM 옵션 문제가 아님 — fetch plan으로 해결.

## Gotchas

### self-invocation으로 어노테이션 silent 무효화
- `@Transactional` 메서드 A가 같은 빈의 B를 직접 호출 → B의 `@Transactional`은 적용 안 됨.

### CGLIB vs JDK proxy 가정
- final 클래스/메서드는 CGLIB proxy 생성 실패. interface 기반 설계 또는 final 제거.

### `@Async` + `@Transactional`을 같은 메서드에
- async가 새 thread에서 실행되므로 트랜잭션 컨텍스트가 끊김. 트랜잭션이 필요하면 async 호출 대상 메서드 안에서 새 트랜잭션 시작.

## Source

- `frameworks/backend/spring-framework/6.x/07_troubleshooting/2026-04-20__tech-kb-import__proxy-transaction-and-lazy-loading-pitfalls__6-x.md`
- `frameworks/backend/spring-framework/6.x/08_know-how/2026-04-26__local-spring__proxy-boundary-thread-model-and-transaction-habits__6-x.md`
- `frameworks/backend/spring-data-jpa/3.5.x/05_patterns/2026-04-26__local-spring__projection-fetch-plan-transaction-boundary-and-query-shape-patterns__3-5-x.md`
- `languages/java/21/05_patterns/2026-04-20__tech-kb-import__virtual-threads-structured-concurrency-and-locking-patterns__21.md`
