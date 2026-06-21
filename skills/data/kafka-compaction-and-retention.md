---
name: kafka-compaction-and-retention
description: Kafka 3.9+/4.0 cleanup.policy + Tiered Storage + KRaft 4.0 + schema compatibility 결정
keywords: kafka compaction retention tiered-storage kraft tombstone schema-registry cooperative-sticky cleanup-policy
intent: design-topic-policy enable-tiered-storage diagnose-compaction-stall plan-kraft-migration
paths:
patterns: cleanup.policy log.cleaner remote.storage.enable bootstrap-server cooperative-sticky
requires: messaging-governance
phase: plan implement review debug
tech-stack: any
min_score: 2
---

# Kafka Compaction + Retention + KRaft

> 핵심: cleanup.policy는 데이터 의미(상태 vs 시계열)에 결정되고, retention은 비용/규제로 결정된다. 둘을 묶어서 결정하면 운영 6개월 후 metadata 폭증 또는 silent data loss로 돌아온다.

## 의사결정 트리

### IF 신규 topic 설계 (Plan)
1. **데이터 의미 분류**:
   - event-sourced state / changelog / KTable backing → `cleanup.policy=compact` (key-keyed last-value)
   - audit / metric / 시계열 → `cleanup.policy=delete` + `retention.ms` (default 7d)
   - 둘 다 (최신 상태 보존 + TTL 상한) → `compact,delete`
2. key 결정 — compact topic은 **key=null 절대 금지** (broker 버전에 따라 drop 또는 compaction block)
3. segment 결정 — `segment.ms`(default 7d), `segment.bytes`(default 1GB). 저트래픽 compact topic은 segment.ms를 짧게(1d 이하) — 활성 segment는 절대 compact 안 됨

### IF retention > 7d 필요 (Plan)
1. Tiered Storage 검토 — 3.9 GA. `remote.storage.enable=true`, `local.retention.ms` < `retention.ms`
2. **제약**: compact topic + Tiered Storage 동시 불가. 이미 remote enable한 topic은 delete→compact 변경 불가
3. Schema Registry 호환 정책 결정 — BACKWARD(default, consumer 먼저 업그레이드) / FORWARD(producer 먼저) / FULL(독립 업그레이드 가능)

### IF compaction이 안 일어난다 (Debug)
1. **활성 segment**는 절대 compact 안 됨 — `segment.ms` 또는 `segment.bytes` 도달해서 roll됐는지 확인
2. `min.cleanable.dirty.ratio`(default 0.5) 미달 → dirty 비율 확인
3. log.cleaner thread silent death — `kafka.log:type=LogCleanerManager,name=uncleanable-partitions-count` JMX 확인. 단일 uncaught exception이면 thread가 영구 죽음
4. tombstone(`value=null`) 미삭제 — `delete.retention.ms`(default 1d) 경과 + roll + cleaner pass 모두 만족해야 실제 제거

### IF Kafka 4.0 마이그레이션 (Plan)
1. ZooKeeper 모드 완전 제거 — KRaft만. `--zookeeper` CLI 제거, `--bootstrap-server`로 통일
2. Java 요건 — broker Java 17+, client/Streams Java 11+
3. pre-upgrade metadata version ≥ 3.3 필요 — 단계적 KRaft 전환 끝낸 후 4.0
4. cooperative-sticky 전환 — eager(`range`/`roundrobin`) 단독에서 cooperative-sticky로 가려면 **2-rolling-bounce**: 1차 `cooperative-sticky,range`, 2차 `cooperative-sticky` 단독

## 가이드

- compact 토픽의 tombstone은 "삭제 이벤트" — consumer가 `delete.retention.ms` 안에 처리해야 의미 보존. 그 시간 안 처리되면 delete 자체를 못 봄.
- `cleanup.policy=compact,delete`는 "최신 상태 + 절대 TTL" — KTable 같은 매우 큰 changelog에 유용 (compact만 쓰면 영구 누적).
- Schema Registry FULL은 모든 장점이지만 schema design 제약이 강함 — 처음부터 명시적 default 부여.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | compaction은 순서 유지 (역순/무작위 아님), key별 마지막 값만 보존 |
| 성능 효율성 | Tiered Storage로 hot tier(disk) 비용 ↓, cold tier(S3) latency ↑ — read pattern 분석 후 적용 |
| 호환성 | Schema Registry 호환 모드로 producer/consumer 독립 배포 |
| 사용성 | JMX `uncleanable-partitions-count` 1개 메트릭이 cleaner 건강도 대표 |
| 신뢰성 | KRaft GA로 metadata는 자체 라프트 — ZK 동기화 실패 모드 제거 |
| 보안 | client 인증/SASL/ACL은 별개 축 — broker config로 분리 결정 |
| 유지보수성 | cleanup.policy + segment.ms + min.cleanable.dirty.ratio 3개로 모든 compact 동작 통제 |
| 이식성 | broker config는 self-managed/Confluent Cloud/MSK 무관 동일 |
| 확장성 | Tiered Storage로 retention 확장 시 broker disk 증설 불필요 |

## Gotchas

### 활성 segment는 절대 compact 안 됨
저트래픽 compact topic은 활성 segment가 영원히 roll 안 됨 → key의 옛 값이 남음. `segment.ms`를 1일 이하로 강제.

### log.cleaner thread silent death
broker 1대에서 단일 uncaught exception 시 cleaner thread가 영구 사망 — topic이 영원히 compact 안 됨. JMX `uncleanable-partitions-count` 모니터 필수.

### Tiered Storage + compact topic 동시 불가
`remote.storage.enable=true` 적용된 topic은 cleanup.policy를 delete→compact 변경 불가. 처음 설계 시 결정 못 미루기.

### tombstone 24h 안에 consumer 처리 못하면 delete 자체 누락
`delete.retention.ms` 기본 1일. consumer lag이 그보다 크면 삭제 이벤트를 못 봄 — 데이터 일관성 깨짐. lag SLO를 retention보다 짧게.

### cooperative-sticky 전환 1-step 시도 → assignment storm
eager(`range`)에서 cooperative-sticky 단독으로 한 번에 가면 protocol mismatch로 group 전체 재할당 폭주. 2-rolling-bounce 필수.

### Kafka 4.0에서 `--zookeeper` 사용
4.0에서 ZK 모드 제거 — 스크립트/도구가 `--zookeeper` 쓰면 즉시 실패. `--bootstrap-server`로 일괄 교체 필요.

## Source

- https://docs.confluent.io/platform/current/installation/configuration/topic-configs.html — `cleanup.policy` 설명, `delete.retention.ms` default 86400000(1d), `min.compaction.lag.ms` default 0, 조회 2026-05-10
- https://docs.confluent.io/kafka/design/log_compaction.html — "Ordering of messages is always maintained. Compaction will never reorder messages"; "These null payload messages are also called tombstones", 조회 2026-05-10
- https://cwiki.apache.org/confluence/display/KAFKA/KIP-405%3A+Kafka+Tiered+Storage — "production-ready since Kafka 3.9"; "does not support compact topics with tiered storage"; `local.retention.ms ≤ retention.ms`, 조회 2026-05-10
- https://kafka.apache.org/blog/2025/03/18/apache-kafka-4.0.0-release-announcement/ — "first major release to operate entirely without Apache ZooKeeper"; broker Java 17, client Java 11, 조회 2026-05-10
- https://docs.confluent.io/platform/current/schema-registry/fundamentals/schema-evolution.html — BACKWARD/FORWARD/FULL 정의 + upgrade order verbatim, 조회 2026-05-10
- https://cwiki.apache.org/confluence/display/KAFKA/KIP-429%3A+Kafka+Consumer+Incremental+Rebalance+Protocol — cooperative-sticky assignor (Accepted 2.4.0), 조회 2026-05-10
