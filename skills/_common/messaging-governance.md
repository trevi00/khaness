---
name: messaging-governance
description: Messaging as delivery governance — message contracts, ack/idempotency, retry/DLQ, and ordering/backpressure made reviewable beyond broker defaults.
keywords: messaging 메시징 message-broker kafka rabbitmq sqs nats pubsub ack acknowledgment idempotency retry dlq dead-letter ordering partition prefetch backpressure consumer-group offset-commit redelivery poison-pill schema event-key compatibility producer consumer 메시지 큐 queue topic subscription
intent: 메시징설계해 토픽만들어 컨슈머구현해 dlq설정해 retry정책정해 ordering보장해 ack전략결정해 backpressure다뤄 partition설계해 idempotent컨슈머만들어
paths: messaging/ events/ kafka/ rabbitmq/ pubsub/ src/messaging src/events consumer/ producer/ schemas/
patterns: kafka rabbitmq sqs nats pubsub spring-kafka spring-amqp confluent kafka-streams celery sidekiq bull bullmq pulsar event-bus message-router outbox transactional-outbox
requires: data-pipeline-governance idempotency monitoring
phase: plan implement review
tech-stack: any
min_score: 2
---

# Messaging Governance

브로커 기능을 외우는 게 아니라 **delivery, replay, side-effect, ordering 가정**을 명시하는 게 핵심. 4축: contract, ack/idempotency, retry/DLQ, ordering/backpressure.

## 의사결정 트리

### IF 새 메시지/이벤트 정의 (Plan)
1. event key 결정 — 어떤 entity 단위로 ordering / partition / dedup 되는가
2. schema 등록 + 호환성 모드 (BACKWARD / FORWARD / FULL) — `data-pipeline-governance` 4-step 참고
3. producer-consumer ownership 매트릭스 — 누가 published, 누가 subscribe, 누가 schema owner
4. delivery semantics — at-least-once 기본, exactly-once는 broker+consumer 조합으로만 가능
5. retention — broker 보관 기간이 consumer downtime 허용 한도와 맞는가

### IF Consumer 구현 (Implement)
1. ack 시점 결정 — 처리 전 ack(at-most-once) / 처리 후 ack(at-least-once) — 후자가 기본
2. **idempotency 필수** — 같은 메시지 N회 도착해도 결과 1회 (event ID + dedup table)
3. side-effect는 ack 전에 commit — DB write 후 ack 실패 시 redelivery로 안전
4. poison message 처리 — 파싱 실패 / 영구 실패는 즉시 DLQ
5. **→ idempotency 스킬: consumer 멱등성 패턴 참고**

### IF Retry / DLQ 정책 (Implement)
1. retry 사유 분류 — 일시적(timeout, 5xx) → retry / 영구적(4xx, 파싱) → 즉시 DLQ
2. retry backoff — exponential + jitter, 최대 N회 (보통 3-5회)
3. retry topic 분리 — 메인 토픽에서 in-place retry는 head-of-line blocking 위험
4. DLQ owner와 review 주기 — 주간 검토 안 하면 DLQ는 의미 없음
5. replay 도구 — DLQ → 메인 토픽 또는 patch 후 재처리 lane

### IF Ordering / Backpressure (Implement)
1. ordering 필요 범위 — global ordering(거의 불가능) vs per-key ordering(파티션 키로)
2. partition key — entity ID로 고정. 잘못된 키면 같은 entity 이벤트가 분산 → 순서 깨짐
3. consumer concurrency — 파티션 수 ≥ consumer 수 (반대면 idle)
4. prefetch / batch size — 작으면 throughput 손실, 크면 redelivery 비용
5. backpressure 신호 — lag growing → 알림 → autoscale 또는 producer rate limit

### IF 메시징 회고 (Review)
- [ ] DLQ size — 늘고 있는가? 0이면 retry 너무 관대?
- [ ] consumer lag — 정상 시간대에도 늘어나면 capacity 부족
- [ ] redelivery rate — 너무 높으면 ack 전 처리 실패 / idempotency 문제
- [ ] ordering 위반 — entity 단위 timeline 검사
- [ ] schema 변경 호환성 — breaking change 발견 시 dual-write 기간 합의

## 4축 체크리스트

```
[Contract]
□ event key 정의 (partition / ordering / dedup 기준)
□ schema 버전 관리 + 호환성 모드
□ producer-consumer ownership 명시

[Ack / Idempotency]
□ ack 시점이 처리 후 (at-least-once 기본)
□ consumer가 dedup 테이블 또는 outbox로 멱등
□ side-effect commit이 ack 전 (또는 transactional outbox)

[Retry / DLQ]
□ retry 사유 분류 (transient vs permanent)
□ retry topic 분리 (head-of-line blocking 방지)
□ DLQ owner 지정 + 주간 review
□ replay lane 존재

[Ordering / Backpressure]
□ partition key가 entity ID
□ partition 수 ≥ consumer 수
□ lag 알림 + autoscale 또는 rate limit
□ prefetch / batch 튜닝
```

## 가이드

### Transactional Outbox 패턴
DB write + 메시지 publish를 atomic하게 보장하려면, 같은 트랜잭션 안에서 outbox 테이블에 row 삽입. 별도 publisher가 outbox에서 읽어 broker로 전송 + ack 후 outbox row 삭제. dual-write 문제(DB는 됐는데 publish 실패) 방지.

### Exactly-once는 시스템 단위, broker 단위 아님
Kafka exactly-once semantics(EOS)는 producer-broker-consumer 조합 + transactional commit + offset commit이 모두 한 트랜잭션이어야 성립. 보통은 at-least-once + idempotent consumer가 더 단순하고 안전.

### Head-of-line blocking
같은 파티션 안에서 메시지 1개가 stuck(처리 무한 retry)이면 뒤 메시지 다 막힘. retry topic으로 옮기고 메인 진행 → 별도 worker가 retry topic 처리.

### Consumer group rebalancing
consumer 추가/제거 시 partition 재할당 동안 처리 중단. 자주 일어나면 deploy 시 짧은 lag spike. sticky partition assignment + cooperative rebalancing으로 완화.

### per-key ordering이 진짜 필요한가
"순서 보장" 요구는 비싸다. 많은 경우 idempotent + last-write-wins(timestamp 비교)로 충분. 진짜 ordering 필요는 상태 머신이나 회계 같은 도메인.

## Gotchas

### ack를 처리 전에 함 — 메시지 loss
"받자마자 ack"하면 처리 도중 consumer crash 시 메시지 사라짐. 항상 처리 + side-effect commit 후 ack. broker가 자동 ack 모드면 명시적으로 manual ack로 변경.

### Idempotency 없는 at-least-once consumer
at-least-once는 redelivery 가능성을 전제. dedup 없이 처리하면 중복 결제 / 중복 이메일 / 카운터 2배. event ID 기반 dedup table 또는 outbox 필수.

### Retry topic 없이 in-place retry
같은 토픽에서 retry하면 retry 메시지가 새 메시지를 막음(head-of-line blocking). retry 전용 토픽 + delay queue로 분리.

### Partition key를 timestamp나 random
partition 키를 entity ID로 안 하고 timestamp/random으로 두면 같은 entity 이벤트가 여러 partition으로 → ordering 깨짐 → 상태 머신 손상.

### DLQ size 알림 없음
DLQ가 grow-forever인데 알림이 없으면 incident 시 "원래 DLQ에 N만 개 있었는데 진짜 새 문제는 어느 거?" 판별 불가. DLQ size 변화율로 알림.

### Schema breaking change를 hot deploy
producer가 새 schema로 publish 시작했는데 옛 consumer는 못 읽음 → 메시지 stuck/discard. additive only + 일정 기간 dual-write + consumer 업그레이드 후 producer 변경.

### Consumer concurrency > partition 수
파티션 4개에 consumer 8개 두면 4개는 idle. autoscale 정책에 max = partition 수 제약 추가. 또는 partition 수를 늘림(broker별 절차).

### Long-running consumer가 ack 안 함
처리에 30초+ 걸리는 consumer에서 broker session timeout(보통 10초)이 짧으면 broker가 consumer 죽었다 판단 → rebalance + redelivery. heartbeat 또는 max.poll.interval 조정.

### Retention < consumer downtime
broker 보관 기간이 7일인데 consumer가 7일+ 다운되면 메시지 잃음. 보관 기간을 SLO + 안전 margin으로 잡고, 장기 다운 시 archive replay 절차 마련.

### Replay 시 side-effect 재실행
DLQ에서 메인 토픽으로 replay했는데 consumer가 idempotent 아니면 side-effect(이메일/결제) 중복. replay 도구는 dry-run 모드 + dedup 검증 후 push.

## 도구 사용 패턴 (Harness)
- consumer lag: broker CLI(kafka-consumer-groups, sqs receive_count) 또는 monitoring 메트릭
- DLQ 검사: broker UI 또는 `Bash`로 receive without ack
- schema diff: registry CLI 또는 git history에서 schema 파일 diff

## 에러 복구 패턴 (Harness)
- redelivery 폭증 → consumer 로그에서 ack timing 확인 → idempotency 또는 side-effect commit 순서 점검
- 특정 entity 이벤트 누락 → partition 키 추적, 같은 entity가 여러 partition에 분산되었는지 확인
- DLQ 갑자기 성장 → 최근 producer/consumer 배포 추적, schema 변경 PR 확인 후 dual-write 구간 점검

## Related (신규 그래프 cross-ref)

messaging-governance가 전제하는 신규 노드:
- `data/kafka-compaction-and-retention.md` — Kafka 4.0 KRaft, Tiered Storage 3.9 GA, schema BACKWARD/FORWARD/FULL
- `_common/dlq-reprocessing-wal.md` — DLQ pipeline 정밀 (Netflix WAL article + Asset Management Platform article 기반)
- `_common/webhook-delivery-and-signing.md` — outbound 메시지 (Stripe/GitHub/Slack HMAC-SHA256 + timestamp)
- `_common/durable-execution.md` — Temporal activity가 메시지 consumer 패턴의 deterministic 변종
- `data/flink-streaming-job-shape.md` — Kafka source `withIdleness()` 의무화, Iceberg sink upsert
