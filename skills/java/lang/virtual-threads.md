---
name: virtual-threads
description: Loom 가상 스레드의 적합성 판단 — blocking I/O에서만 이득, pinning·structured concurrency 경계 명시
keywords: virtual-threads loom pinning structured-concurrency scoped-value executor blocking-io
intent: choose-concurrency-model audit-pinning bound-task-lifecycle
paths:
patterns: java.lang.Thread Executors.newVirtualThreadPerTaskExecutor StructuredTaskScope ScopedValue
requires: jvm-runtime-diagnostics
phase: plan implement review debug
tech-stack: java
min_score: 2
---

# Virtual Threads (Loom)

> Virtual threads are a scaling tool for blocking I/O — not a license to ignore pinning, cancellation, or shared-state discipline.

## 의사결정 트리

### IF "이 작업에 가상 스레드를 쓸까?" (Plan|Implement)
1. 워크로드가 I/O 대기 중심(HTTP·DB·외부 호출)인가? → Yes면 후보
2. CPU-바운드(인코딩·해싱·연산 루프)인가? → No, 플랫폼 스레드/병렬 스트림이 적절. Oracle Thread API 문서가 long-running CPU 작업엔 부적합 명시
3. 동기 코드를 단순한 스레드-퍼-요청 모양으로 유지하고 싶은가? → Yes면 `Executors.newVirtualThreadPerTaskExecutor()` 적합

### IF "성능이 안 올라간다" (Debug|Review)
1. 병목이 CPU 포화인지 I/O 대기인지 먼저 분리 — JFR/스레드 덤프로 확인
2. `synchronized` 블록 안에서 blocking I/O? → carrier 스레드 pinning. `ReentrantLock`으로 교체 검토
3. JNI/네이티브 콜 내 blocking? → 동일하게 pinning. `-Djdk.tracePinnedThreads=full`로 진단

### IF 동시 작업 수명주기를 묶고 싶다 (Implement|Review)
1. Java 25에서 `StructuredTaskScope`는 여전히 preview — 빌드/런타임에 `--enable-preview` 정책 명시 후에만 사용
2. cancellation·deadline·join 경계를 코드에 명시. fork→join까지 한 책임 단위로 본다
3. 컨텍스트 전파는 `ThreadLocal` 대신 `ScopedValue`(Java 25 영구) — 단방향 전달, 작은 수의 키, 묶을 값이 많으면 immutable carrier 1개로

## 가이드

- 가상 스레드 풀은 만들지 않는다. per-task executor가 의도된 모델.
- 테스트 fixture를 공유하면 동시성 버그처럼 보이는 상태 누수가 발생 — 픽스처 격리가 우선.

## Gotchas

### Pinning을 "성능 튜닝" 문제로 오인
- pinning은 정확성/스케일 문제. 풀 사이즈 조정으로 가려지지 않는다.

### `ScopedValue` 키를 너무 많이 바인딩
- API 문서가 소수 사용을 권고. 여러 값이 함께 흘러야 하면 record/holder 1개로 묶는다.

### "preview 문법이 컴파일됐다 = 운영 가능"
- `StructuredTaskScope`는 Java 25에서 preview. 컴파일·런타임 양쪽에 `--enable-preview` 필요, 클래스 파일이 해당 release에 묶임.

## Source

- `languages/java/21/05_patterns/2026-04-19__oracle-openjdk__virtual-threads-switch-patterns-and-sequenced-collections__21.md`
- `languages/java/21/05_patterns/2026-04-20__tech-kb-import__virtual-threads-structured-concurrency-and-locking-patterns__21.md`
- `languages/java/21/05_patterns/2026-04-26__local-java__virtual-thread-task-shape-fixture-isolation-and-time-boundary-patterns__21.md`
- `languages/java/21/07_troubleshooting/2026-04-26__local-java__pinning-shared-fixture-leak-and-full-context-test-drift-troubleshooting__21.md`
- `languages/java/25/05_patterns/2026-04-19__oracle-docs__scoped-values-structured-concurrency-and-preview-boundaries__25.md`
