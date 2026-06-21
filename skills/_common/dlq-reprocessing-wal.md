---
name: dlq-reprocessing-wal
description: DLQ + reprocessing + write-ahead log — Kafka DLQ 패턴, poison message 격리, replay tooling, schema evolution 안전
keywords: dlq dead-letter-queue reprocessing wal write-ahead-log kafka poison-message replay tombstone exactly-once
intent: design-dlq-pipeline isolate-poison-message replay-failed-events guarantee-exactly-once handle-schema-drift
paths:
patterns: dlq dead-letter-queue write-ahead-log replay-tool poison-message
requires: messaging-governance idempotency
phase: plan implement review deploy debug
tech-stack: any
min_score: 2
quality_axes_enforced: true
---

# DLQ + Reprocessing + Write-Ahead Log

> 핵심: event-driven 시스템에서 fail 처리는 **즉시 retry** 또는 **무한 stuck**가 아닌 **격리(DLQ) + 분석 + 재실행(reprocess)** 3단계. Netflix Asset Management Platform과 WAL article이 산업 표준 패턴 정착. WAL은 메시지 시스템 자체 다운에도 데이터 보존하는 안전망.

## 의사결정 트리

### IF DLQ 파이프라인 설계 (Plan)
1. main topic + DLQ topic 분리 — `events.user.created` + `events.user.created.dlq`
2. consumer 실패 정책 (3 단계):
   - **즉시 retry (transient)**: network blip, 5xx — exponential backoff (3-5회)
   - **DLQ 격리 (poison)**: deserialization 실패, business rule violation — DLQ로
   - **drop (irrecoverable)**: schema mismatch + reprocess 무의미 — log + drop
3. DLQ message에 metadata 추가 — `original_topic`, `failure_reason`, `consumer_id`, `attempt_count`, `first_seen_at`
4. retention — DLQ는 main의 2-3배 (분석 시간 확보)

### IF Reprocessing pipeline (Implement)
1. replay tool — DLQ 메시지를 batch 또는 stream으로 main topic 재발행
2. **idempotency 강제** — consumer가 message ID 기반 dedup (참조: `idempotency.md`)
3. partial reprocess — DLQ에서 특정 시점/원인 필터링 후 재발행 (`failure_reason=schema_mismatch`)
4. dry-run mode — 실제 재발행 전 영향 범위 추정 (메시지 수, 영향 받을 entity 수)

### IF Write-Ahead Log (WAL) 적용 (Implement)
1. **producer 직전 WAL** — Kafka send 전에 local WAL (예: SQLite, RocksDB)에 먼저 write
2. Kafka send 성공 시 WAL row 삭제. 실패/timeout 시 retry from WAL
3. Kafka 자체 다운 시에도 WAL에 데이터 보존 → 복구 후 drain
4. WAL size 제한 — disk full 시 producer block 또는 alert. 무제한 절대 X

### IF Schema evolution + DLQ 상호작용 (Plan)
1. schema registry (Confluent/Apicurio) — BACKWARD compat 모드 강제
2. consumer가 새 schema 못 읽으면 → DLQ + `failure_reason=schema_mismatch`
3. consumer 업그레이드 후 reprocess — 같은 message 재시도하면 성공
4. **breaking change**는 새 topic 신설 (참조: `api-migration-replay-traffic`)

### IF Poison message 진단 (Debug)
1. DLQ 모니터링 — `dlq_message_count_total{reason="..."}` Prometheus counter + alert (rate > N/min)
2. 패턴 분석 — top failure reason / source consumer / payload sample
3. 수동 inspection — Kafka tool (kcat) 또는 GUI (Conduktor)로 raw 확인
4. fix + reprocess loop — patch deploy 후 DLQ 일괄 replay

## 가이드

- DLQ 자체에도 retention/retention.bytes 명시 — 무한 누적 시 cluster disk 고갈
- 재발행 시 메시지 순서 보존이 필요하면 partition key 유지
- WAL은 latency 추가 비용 — high-throughput 워크로드는 batch WAL (group commit)

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | poison message 격리로 main consumer 정상 진행 |
| 성능 효율성 | WAL group commit으로 latency 비용 분산 |
| 호환성 | Kafka/Pulsar/Kinesis 무관 동일 패턴 |
| 사용성 | replay tool 1 command로 DLQ → main 재발행 |
| 신뢰성 | WAL이 message broker 다운에도 데이터 보존 |
| 보안 | DLQ 접근 RBAC — 실패 메시지에 PII 포함 가능 |
| 유지보수성 | failure_reason 카테고리화로 패턴 분석 자동 |
| 이식성 | 메시지 시스템 변경 시 WAL/DLQ 패턴 재사용 |
| 확장성 | partition별 DLQ 분리로 throughput scale |

## Gotchas

### 즉시 retry로 무한 루프
poison message를 즉시 retry 시 같은 fail 무한. 3-5회 retry 한도 + DLQ 격리 강제.

### DLQ 메시지에 metadata 누락
`failure_reason`/`attempt_count`/`source_topic` 없이 raw payload만 보내면 분석 불가. metadata wrapper 강제.

### WAL 무제한 누적 → disk full
Kafka 다운이 길어지면 WAL이 disk 꽉 채움 → producer 자체 crash. 임계 (예: 10GB) + alert + producer block.

### Idempotency 없이 reprocess
DLQ replay 시 같은 message 두 번 처리 → 부작용 (이메일 중복 발송, 결제 중복). consumer idempotency-key 강제.

### Schema registry 없이 형식 변경
producer가 새 필드 추가 → consumer 깨짐 → DLQ 폭주. schema registry BACKWARD compat 강제.

### DLQ retention이 main과 동일
main 7일이면 DLQ 7일 — 분석 시간 부족. DLQ는 14-30일 권장.

### Reprocess 시 partition key 변경
같은 entity의 메시지가 다른 partition으로 → 순서 깨짐. replay 시 원본 partition key 보존.

## Source

- https://netflixtechblog.com/building-a-resilient-data-platform-with-write-ahead-log-at-netflix-127b6712359a — WAL pattern: producer 직전 local log, broker 다운에도 데이터 보존, 조회 2026-05-10
- https://netflixtechblog.com/data-reprocessing-pipeline-in-asset-management-platform-netflix-46fe225c35c9 — Asset Management Platform reprocessing pipeline: failure metadata + replay tooling, 조회 2026-05-10
- https://docs.confluent.io/platform/current/schema-registry/fundamentals/schema-evolution.html — BACKWARD/FORWARD/FULL compatibility 정의 + upgrade order, 조회 2026-05-10
- https://kafka.apache.org/documentation/#topicconfigs — `retention.ms` / `retention.bytes` per topic config, 조회 2026-05-10
- https://www.confluent.io/blog/error-handling-patterns-in-kafka/ — Kafka error handling: retry / DLQ / drop 3-strategy, 조회 2026-05-10
