---
name: jvm-runtime-diagnostics
description: GC/JFR/heap-dump/thread-dump/container 신호 진단 — 튜닝 플래그를 만지기 전에 증거부터 모은다
keywords: jvm gc g1 zgc jfr heap-dump thread-dump container cgroup memory-leak
intent: diagnose-before-tune capture-evidence size-heap inspect-pinning
paths:
patterns: java jcmd jfr -XX:+UnlockDiagnosticVMOptions
requires:
phase: review debug deploy
tech-stack: java
min_score: 2
---

# JVM Runtime Diagnostics

> GC 플래그는 워크로드 모양·정지 민감도·네이티브 메모리 압력을 알아야 의미를 가진다 — 진단 → 결정 → 튜닝 순서를 지킨다.

## 의사결정 트리

### IF "메모리 이슈/GC 문제로 보이는" 증상 (Debug)
1. 먼저 JFR 또는 GC 로그를 켠다 — `-XX:StartFlightRecording=...` 또는 `-Xlog:gc*`. 증거 없이 플래그를 바꾸지 않는다
2. heap dump(`jcmd <pid> GC.heap_dump`) + thread dump(`jcmd <pid> Thread.print`)를 같이 수집
3. retention 문제(장기 컬렉션, ThreadLocal, 리스너, 클래스로더)인지 heap-size 문제인지 분리 — 많은 "메모리 이슈"가 heap 크기보단 retention 문제

### IF GC 선택 검토 (Plan|Deploy)
1. 정지 민감도(p99 latency budget) 정의 → ZGC vs G1을 먼저 비교. "최신=최고"가 아닌 워크로드 매칭
2. heap·direct memory·thread 수·네이티브 오버헤드를 deployment 설계 단계에 포함 — cgroup-aware default만 믿지 않는다
3. Java 25의 compact object headers는 product 기능이지만 자동 튜닝 승리는 아님 — 측정으로 확인

### IF 컨테이너 환경 (Deploy|Review)
1. cgroup 메모리 한계 vs `-Xmx`·direct memory·thread stack·메타스페이스 합계가 한계 안에 들어오는지 검증
2. 컨테이너 OOM-kill은 heap OOM과 다름 — 네이티브/스레드 누수 가능성 점검
3. 가상 스레드 사용 시 carrier 스레드 수가 OS 스레드 한계를 초과하지 않는지 — pinning 진단도 같이

## 가이드

- 튜닝 변경은 한 번에 하나 — 여러 플래그를 동시에 바꾸면 효과 분리가 불가.
- JFR을 운영 기본값으로 (낮은 오버헤드) — 사고 후 사후 수집보다 사전 항시 기록이 가치 큼.

## Gotchas

### 플래그 변경 = 튜닝 (X)
- 증거 없는 플래그 변경은 folklore. JFR/dump 분석이 우선.

### "OOM이니까 -Xmx 올린다"
- retention 누수는 heap을 키워도 시간만 늘어남. 누가 잡고 있는지 dump로 본다.

### container default를 신뢰
- cgroup-aware JVM도 direct memory·thread stack·JIT code cache는 별도 계산. 컨테이너 한계 ≠ heap 한계.

## Source

- `languages/java/21/08_know-how/2026-04-20__tech-kb-import__jvm-tuning-gc-jfr-and-container-habits__21.md`
- `languages/java/21/07_troubleshooting/2026-04-20__tech-kb-import__optional-equals-streams-and-memory-leak-troubleshooting__21.md`
- `languages/java/25/05_patterns/2026-04-19__oracle-docs__scoped-values-structured-concurrency-and-preview-boundaries__25.md`
