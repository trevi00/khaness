---
name: pattern-switch-records
description: record patterns + sealed hierarchies + pattern switch — data-oriented dispatch을 큰 instanceof 체인 대신 사용
keywords: pattern-matching record-pattern sealed-interface switch data-oriented-programming exhaustiveness
intent: model-domain dispatch-by-shape replace-visitor refactor-instanceof-chain
paths:
patterns: java.lang sealed record switch
requires:
phase: plan implement review
tech-stack: java
min_score: 2
---

# Pattern Switch + Records (Data-oriented Dispatch)

> sealed + record + pattern switch는 닫힌 도메인의 dispatch를 컴파일러가 검증하는 단일 단위로 만든다.

## 의사결정 트리

### IF 도메인이 자연스럽게 닫혀있다 (Plan|Implement)
1. 후보 타입을 `sealed interface`로 모델링하고 `permits`로 구현체를 명시
2. 구현체는 가능한 `record`로 — 구조 분해를 record pattern으로 받을 수 있어야 dispatch 코드가 짧아짐
3. dispatch는 pattern `switch`로 작성 — 컴파일러가 exhaustiveness를 강제. 새 case 추가 시 누락 site가 컴파일 오류로 드러남

### IF 큰 `instanceof` 체인 / visitor가 있다 (Refactor|Review)
1. 분기 대상이 닫힌 집합인지 먼저 검토 — 열려있으면 polymorphism이 더 적합
2. 닫혀있으면 sealed로 좁히고, `if (x instanceof Foo f) { ... }` → `case Foo f -> ...`로 이동
3. 분기 직후 record 접근자만 호출하면 record pattern으로 한 번에 해체: `case Point(int x, int y) -> ...`

### IF "패턴 스위치가 어색하다" (Review|Debug)
1. 도메인이 사실 열려있는가? — 외부 확장이 필요하면 polymorphism 유지
2. case 분기에 부수 효과 로직이 많은가? — record pattern으로 데이터만 추출하고 처리는 호출 측 함수로 분리
3. guarded pattern (`case X x when cond`)이 너무 많으면 sealed 모델링 자체를 다시 검토

## 가이드

- Java 21에서 record patterns(JEP 440), pattern switch(JEP 441) 영구 기능. baseline에 포함 가능.
- Java 25에서 primitive types in patterns/instanceof/switch는 여전히 preview — 영구 기능과 섞지 않는다.
- 순서 의미가 contract면 `SequencedCollection`/`SequencedMap`으로 first/last/reversed를 표현. record dispatch와 자연스럽게 결합된다.

## Gotchas

### 도메인이 열린 상태에서 sealed 강제
- 외부 모듈이 새 구현체를 만들어야 하는 경우라면 sealed가 오히려 확장성을 막는다.

### exhaustiveness를 default로 회피
- `default ->`로 새 case 컴파일 오류를 무력화하지 말 것. exhaustiveness는 sealed의 핵심 보상.

### preview 기능을 데모 코드에 슬쩍 넣기
- primitive patterns(Java 25 preview)는 컴파일·런타임 양쪽에 `--enable-preview` 필요. baseline 예제와 분리.

## Source

- `languages/java/21/05_patterns/2026-04-19__oracle-openjdk__virtual-threads-switch-patterns-and-sequenced-collections__21.md`
- `languages/java/25/04_usage/2026-04-19__oracle-docs__module-imports-compact-source-and-preview-boundaries__25.md`
- `languages/java/25/05_patterns/2026-04-26__local-java__preview-boundary-release-policy-and-module-surface-patterns__25.md`
