---
name: flink-streaming-job-shape
description: Flink 1.20 LTS / 2.0 결정 — state backend, checkpointing, watermark, Iceberg sink upsert
keywords: flink streaming state-backend rocksdb hashmap forst checkpoint watermark iceberg-sink unaligned upsert
intent: shape-streaming-job choose-state-backend tune-checkpoint diagnose-backpressure plan-2-0-migration
paths:
patterns: org.apache.flink HashMapStateBackend EmbeddedRocksDBStateBackend ForSt withIdleness
requires: kafka-compaction-and-retention iceberg-table-format
phase: plan implement review debug
tech-stack: any
min_score: 2
---

# Flink Streaming Job Shape (1.20 LTS / 2.0)

> 핵심: state backend 결정이 latency/scalability 절반을 좌우하고, checkpoint 결정이 reliability/cost 나머지 절반을 좌우한다. 1.x→2.x state 비호환은 명시 — savepoint forward path 없음.

## 의사결정 트리

### IF 신규 streaming job 설계 (Plan)
1. Flink 버전 — production은 1.20 LTS (1.20.4 2026-04 patch까지 적용). 2.0은 신규 그린필드 + 1.x 기존 state 없는 경우만
2. state backend — state ≤ 1GB/task + low latency → `HashMapStateBackend`(default 1.20). state ≥ 10GB or incremental snapshot 필요 → `EmbeddedRocksDBStateBackend`. cloud-native 빠른 rescaling → ForSt(2.0+, default 여부 미확정 — 공식 docs 재확인)
3. exactly-once 필요 → `execution.checkpointing.mode=EXACTLY_ONCE` + checkpoint interval (보통 1–5분)
4. backpressure 빈번 + checkpoint timeout → `execution.checkpointing.unaligned=true` + `aligned-checkpoint-timeout=30s` (hybrid)

### IF event-time + late data (Implement)
1. WatermarkStrategy 명시 — `forBoundedOutOfOrderness(Duration.ofSeconds(N))`
2. **Kafka 같은 다중 partition 소스 + 일부 partition idle** → `withIdleness(Duration.ofMinutes(1))` 필수. 안 쓰면 idle partition이 watermark stall
3. window에 `allowedLateness()` — late event 허용 윈도우 명시
4. watermark alignment — 빠른 source가 느린 source 기다리게 (cross-partition skew 방지)

### IF Iceberg sink + upsert (Implement)
1. SQL: `INSERT INTO t /*+ OPTIONS('upsert-enabled'='true') */`
2. **partitioned table + upsert** → equality fields에 partition source column **반드시 포함**. 누락 시 silent dedup 실패
3. commit interval = checkpoint interval. 알람 룰: `elapsedSecondsSinceLastSuccessfulCommit > N×interval` (보통 12배)
4. distribution: 파티션 테이블이면 partition key, 비파티션이면 equality fields로 HASH

### IF backpressure 진단 (Debug)
1. JobMaster UI → vertex별 backpressure ratio 확인
2. 원인 1: state size 폭증 → RocksDB로 전환 또는 state TTL
3. 원인 2: 외부 sink slow → async I/O 도입 또는 sink 병렬도 증가
4. 원인 3: checkpoint barrier alignment block → unaligned checkpoint 활성

### IF 1.x → 2.0 마이그레이션 (Plan)
1. **state 비호환** — savepoint forward path 없음. parallel run + cutover 계획
2. 제거된 API: DataSet, Scala DataStream/DataSet, SourceFunction, SinkFunction(V1), TableSource/TableSink, Per-job deployment
3. Java 8 dropped — minimum 11, default 17, 21 supported
4. config: `flink-conf.yaml` → `config.yaml` (표준 YAML)

## 가이드

- 1.20은 LTS — 패치 지속 (1.20.4 = 2026-04-22, FLINK-38483 unaligned recovery 수정). production safe.
- 2.0의 ForSt(disaggregated state)는 cloud-native 패러다임이지만 default 여부는 master docs 재확인 필요 — 단언 회피.
- 모든 Kafka 소스에 `withIdleness()` 의무화 — 단일 idle partition 1개로 전체 윈도우 stall 사고가 흔함.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | exactly-once는 checkpoint barrier + transactional sink 양쪽 만족 시만 보장 |
| 성능 효율성 | RocksDB는 HashMap 대비 "an order of magnitude slower"; large state 전제 시만 채택 |
| 호환성 | 1.x ↔ 2.x state 비호환 — version pin frontmatter 의무 |
| 사용성 | JobMaster UI backpressure ratio + checkpoint history 가 1차 진단 도구 |
| 신뢰성 | unaligned checkpoint는 exactly-once + 1 concurrent checkpoint 한정 |
| 보안 | sink credential은 외부 secret manager 경유 (Kafka SASL/Iceberg catalog auth 분리) |
| 유지보수성 | Iceberg upsert 체크리스트(equality ⊃ partition cols) 매 PR 검증 |
| 이식성 | YARN/K8s/standalone 무관, 같은 jar 동작 |
| 확장성 | rescaling은 savepoint 경유 — incremental snapshot 사용 시 cost ↓ |

## Gotchas

### 1.x → 2.x state 비호환
공식 release note 명시: "State Compatibility is not guaranteed between 1.x and 2.x." savepoint forward 없음 → parallel run + cutover만 가능.

### Kafka 소스에 `withIdleness()` 누락
일부 partition이 idle이면 watermark가 그 partition 기준 멈춤 → window 영원히 안 닫힘. 모든 Kafka source에 의무화.

### Iceberg upsert + partitioned table에서 partition column이 equality fields 누락
silent dedup 실패 — 잘못된 row가 쌓임. write 직후 check 안 하면 디버깅 매우 어려움.

### unaligned checkpoint + concurrent checkpoint 동시 활성
공식 docs: "does not support concurrent unaligned checkpoints." 둘 다 켜면 checkpoint 불완전. EXACTLY_ONCE + 1 concurrent로 한정.

### HashMapStateBackend로 large state 운영
incremental snapshot 미지원 → savepoint 크기가 state 크기와 선형 증가. >10GB state면 RocksDB 전환.

## Source

- https://nightlies.apache.org/flink/flink-docs-release-1.20/docs/ops/state/state_backends/ — "If nothing else is configured, the system will use the HashMapStateBackend"; RocksDB "Only state backend to support incremental snapshots", "an order of magnitude slower", 조회 2026-05-10
- https://nightlies.apache.org/flink/flink-docs-master/release-notes/flink-2.0/ — "State Compatibility is not guaranteed between 1.x and 2.x"; DataSet/SourceFunction/SinkFunction/per-job 제거, 조회 2026-05-10
- https://flink.apache.org/2025/03/24/apache-flink-2.0.0-a-new-era-of-real-time-data-processing/ — Flink 2.0 release 2025-03-24, ForSt disaggregated, 조회 2026-05-19
- https://flink.apache.org/2026/04/22/apache-flink-1.20.4-release-announcement/ — 1.20.4 patch (FLINK-38483 unaligned recovery 수정), 조회 2026-05-19
- https://nightlies.apache.org/flink/flink-docs-release-1.20/docs/ops/state/checkpointing_under_backpressure/ — "does not support concurrent unaligned checkpoints"; only EXACTLY_ONCE + 1 concurrent, 조회 2026-05-10
- https://iceberg.apache.org/docs/latest/flink-writes/ — "When using UPSERT mode with a partitioned table, source columns of corresponding partition fields must be included in the equality fields", 조회 2026-05-10
- https://github.com/apache/iceberg/issues/15305 — upsert 시 data + equality delete 같은 sequence number 이슈, 조회 2026-05-10
