---
name: workflow-orchestration
description: Durable workflow orchestration — Temporal vs Conductor-OSS vs Cadence, deterministic replay, saga pattern, sticky worker
keywords: workflow-orchestration temporal conductor cadence durable-execution saga deterministic-replay sticky-worker continue-as-new versioning
intent: choose-workflow-engine design-saga handle-workflow-versioning prevent-non-determinism scale-workers
paths:
patterns: temporal conductor cadence workflow.sleep getVersion patched ContinueAsNew
requires: service-resilience-patterns idempotency
phase: plan implement review debug
tech-stack: any
min_score: 2
quality_axes_enforced: true
---

# Workflow Orchestration (Temporal / Conductor-OSS / Cadence)

> 핵심: workflow 코드 = **deterministic replay from event history**. activity = side effect (idempotent). 가장 흔한 사고는 **non-determinism** — `Date.now()`/`Math.random()`/native `setTimeout` 직접 사용 시 replay 불일치. metaflow(ML)와 직교 — 일반 microservice business workflow.

## 의사결정 트리

### IF Workflow engine 선택 (Plan)
| 신호 | 권장 |
|---|---|
| 다언어 SDK + commercial support | **Temporal** (Go/Java/Python/.NET/TS/PHP, mTLS, Data Converter) |
| Netflix 호환 + JSON DSL workflow | **Conductor-OSS** (Orkes 거버넌스, conductor-oss/conductor) |
| Uber/Cadence 호환 (Temporal 전신) | **Cadence** (CNCF, Go/Java) |
| ML pipeline (data + train + serve) | metaflow (별도 노드) |

Temporal이 다수 선택. Conductor-OSS는 Netflix legacy 호환 시. Cadence는 Uber 코호트.

### IF Workflow + Activity 분리 (Implement)
1. **Workflow function** — deterministic replay 가능, 외부 호출 X, side effect 없음
2. **Activity** — DB write / 외부 API / 무거운 연산. workflow에서 호출만, retry/timeout은 activity 옵션
3. workflow 안에서 시간 — `workflow.now()` (replay-safe), `Date.now()` 절대 X
4. workflow 안에서 random — 시드 기반 deterministic RNG

### IF Saga pattern (Implement)
1. **Orchestration** (중앙 workflow) — Temporal/Conductor가 상태 머신 + LIFO 보상 트랜잭션 자동
2. **Choreography** (이벤트 분산) — 각 service가 이벤트 reaction. 디버깅 어려움
3. 권장: 양방향 결제/예약 등 critical path는 orchestration. 약결합 노티는 choreography
4. activity 단위에 idempotency-key 필수 (참조: `idempotency.md`)

### IF Worker scaling (Implement)
1. **non-sticky** — 모든 worker가 task queue에서 task pick. 첫 진입에 좋음
2. **sticky queue** — workflow state cache 가진 worker에 후속 task pin. history replay 비용 ↓
3. sticky 5초 default — fall back to non-sticky
4. 메트릭 `temporal_sticky_cache_size` 모니터

### IF Workflow versioning (Implement)
1. **`getVersion` / `patched`** API — 옛 history는 옛 코드 path, 새 history는 새 path
2. **Worker Versioning** (Temporal 1.20+) — worker build ID로 deploy 분리
3. 절대 금지 — 운영 중 deterministic-breaking 코드 변경 (조건문 추가/제거)

### IF Non-determinism 진단 (Debug)
1. workflow code 안에 `Date.now()`, `Math.random()`, `setTimeout`, file I/O, network call → 즉시 제거
2. worker 로그에서 `non-deterministic` 또는 `history mismatch` 에러 검색
3. SDK 제공 deterministic 변종 사용 — `workflow.sleep`, `workflow.now`, side effect API

## 가이드

- Temporal v1.30.4 (2026-04). Cadence는 Temporal 창업자들이 fork — execution history core 동일.
- Conductor: 원 `Netflix/conductor` archived (2023-12). active 개발은 `conductor-oss/conductor` (Orkes + community).
- 운영 cluster size — Temporal은 namespace 단위 격리, Conductor는 task definition 단위.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | deterministic replay로 worker crash 후 정확 복원 |
| 성능 효율성 | sticky queue로 history shipping 비용 ↓ |
| 호환성 | Temporal SDK 6 언어, Conductor JSON DSL은 언어 무관 |
| 사용성 | saga 보상 자동 LIFO — manual rollback 코드 0 |
| 신뢰성 | activity retry/timeout/heartbeat로 transient fail 흡수 |
| 보안 | Temporal Data Converter로 client-side payload 암호화 |
| 유지보수성 | versioning API로 long-running workflow 안전 진화 |
| 이식성 | OSS Temporal/Cadence는 self-host, Temporal Cloud는 managed |
| 확장성 | task queue 분리 + worker pool로 horizontal scale |

## Gotchas

### `Date.now()` / `Math.random()` workflow 안 사용
deterministic replay 깨짐 — worker crash 후 다른 결과 → history mismatch. SDK 제공 `workflow.now()` / 시드 RNG 사용.

### Workflow 안에서 외부 API 직접 호출
side effect = activity 책임. workflow에서 직접 호출 시 replay 시 중복 호출. activity로 추출.

### 운영 중 deterministic-breaking 코드 변경
새 if/loop 추가 시 기존 in-flight workflow가 history mismatch. `getVersion`/`patched` 또는 Worker Versioning 사용.

### history size 무한 증가
긴 loop workflow는 event history 누적. **Continue-As-New** API로 새 workflow execution 시작 (history reset).

### Signal vs Query 혼동
Signal = 상태 변경 (history event), Query = 읽기 전용 (mutation 금지). Query 안에서 state 수정 시 silent corruption.

### Child workflow 폭증
각 child가 자체 history. parent에서 1만 child spawn 시 history 폭증. batch 또는 Continue-As-New로 분할.

## Source

- https://docs.temporal.io/workflow-definition — workflow function = deterministic replay, activity = side effect, 조회 2026-05-10
- https://docs.temporal.io/sticky-execution — sticky queue per-worker auto-named, 5s default poll, `temporal_sticky_cache_size` metric, 조회 2026-05-10
- https://docs.temporal.io/develop/safe-deployments — `getVersion`/`patched` versioning API, Worker Versioning, 조회 2026-05-10
- https://temporal.io/blog/saga-pattern-made-easy — orchestration vs choreography, LIFO compensation, 조회 2026-05-10
- https://github.com/temporalio/temporal/releases — v1.30.4 (2026-04-10), 조회 2026-05-10
- https://temporal.io/temporal-versus/cadence — Temporal vs Cadence (창업자 fork, SDK 차이), 조회 2026-05-10
- https://conductor-oss.org/ — conductor-oss/conductor (Orkes 거버넌스, 2023-12 fork), 조회 2026-05-10
- https://cadenceworkflow.io/faq/cadence-vs-temporal — Cadence FAQ (Uber 호환), 조회 2026-05-10
