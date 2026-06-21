---
name: data-pipeline-governance
description: Data pipelines as contract + rerun systems — delivery semantics, schema compatibility, quality gates, and idempotent backfill made explicit before transforms.
keywords: data pipeline 파이프라인 batch stream 스트림 ETL ELT 데이터엔지니어링 schema-evolution schema-compatibility additive backward-compatible delivery-semantics at-least-once exactly-once dlq dead-letter checkpoint replay backfill rerun idempotent partition watermark completeness uniqueness freshness data-quality lineage
intent: 파이프라인설계해 스키마변경해 backfill해 데이터품질검증해 리런해 dlq설정해 contract만들어 schema호환성검토해
paths: data/ pipelines/ etl/ elt/ dbt/ airflow/ flink/ spark/ schemas/ contracts/ schemas/avro schemas/proto
patterns: airflow dbt spark flink kafka-streams beam dlt avro protobuf json-schema watermark checkpoint partition window backfill-ledger
requires: messaging-governance test-governance idempotency monitoring
phase: plan implement review
tech-stack: any
min_score: 2
---

# Data Pipeline Governance

데이터 파이프라인은 transform 코드가 아니라 **계약 경계**에서 운영적으로 실패한다. 4축으로 나눠 검토: delivery semantics, schema compatibility, quality gates, backfill idempotency.

## 의사결정 트리

### IF 새 파이프라인 설계 (Plan)
1. delivery semantics 명시 — at-least-once / at-most-once / effective-exactly-once 중 어느 것
2. 입력 스키마 contract 등록 — 어디서 옴, 누가 owner, 변경 정책 (additive only?)
3. 출력 sink 멱등성 — 같은 입력 N회 처리 = 1회 결과 (PK / merge / dedup window)
4. 품질 gate — completeness, uniqueness, freshness 임계값
5. backfill 시나리오 — 과거 N일 재처리 시 partition 단위 + rerun ledger
6. **→ messaging-governance 스킬: stream 파이프라인이면 broker 계약 같이 검토**

### IF 스키마 변경 (Implement)
1. 변경 분류 — additive(새 optional 필드) / breaking(필수 필드 제거·타입 변경·rename)
2. additive면 producer 먼저, consumer 나중 (forward compat). breaking이면 dual-write 기간 필요
3. registry(schema-registry / git) 호환성 모드 확인 — BACKWARD / FORWARD / FULL
4. consumer 영향 분석 — 어떤 downstream 테이블/대시보드/모델이 깨지는가
5. **→ test-governance 스킬: contract regression 테스트로 깨지는 consumer 사전 감지**

### IF Backfill / Rerun (Implement)
1. partition 경계 명시 — 일/시간 단위, 과거 N일 범위
2. rerun ledger — 어떤 partition을 누가 언제 재실행했는가 기록
3. idempotency 보장 — sink가 재실행 시 중복 누적 안 되는가 (MERGE vs APPEND)
4. downstream 통보 — backfill 동안 다운스트림 metric이 흔들릴 수 있음 사전 공지
5. dependency 순서 — 상류 backfill 끝난 뒤 하류 trigger
6. **→ idempotency 스킬: rerun 안전성 패턴 참고**

### IF 데이터 품질 게이트 (Review)
- [ ] **completeness**: row count가 예상 ±N% 안인가? null rate가 임계값 미만인가?
- [ ] **uniqueness**: PK/business key의 중복 0인가?
- [ ] **freshness**: 최신 데이터의 max(updated_at)가 SLA(예: 6시간) 안인가?
- [ ] **referential**: FK 깨진 row가 있는가?
- [ ] gate 실패 시 정책 — 알림만 / consumer 차단 / 자동 rollback?

### IF DLQ / 실패 처리 (Implement)
1. 실패 분류 — 일시적(네트워크 timeout) / 영구적(스키마 위반·파싱 실패)
2. 일시적 실패: retry with backoff → 한도 초과 시 DLQ
3. 영구적 실패: 즉시 DLQ + parsing-error 로그
4. DLQ owner와 review 주기 — DLQ가 grow-forever 되면 안 됨
5. replay 도구 — DLQ에서 골라 다시 메인 토픽으로 되돌리는 lane

## 4축 체크리스트

```
[Delivery]
□ semantics 명시 (at-least-once / exactly-once)
□ checkpoint 주기 / 위치 정의
□ replay 도구 + replay 시 side-effect 안전성

[Schema]
□ registry 또는 git 기반 schema 버전 관리
□ compatibility 모드 (BACKWARD / FORWARD / FULL) 명시
□ breaking change 시 dual-write 기간 합의
□ producer-consumer ownership 매트릭스

[Quality]
□ completeness / uniqueness / freshness 임계값
□ gate 실패 시 차단 vs 경고 정책
□ 결과 metric을 monitoring 대시보드로 노출

[Backfill]
□ partition 단위로 rerun
□ rerun ledger (누가/언제/어느 partition)
□ sink가 idempotent (MERGE 또는 dedup)
□ downstream 통보 채널
```

## 가이드

### Schema compatibility 모드 (Avro/Proto/JSON-Schema 공통)
- **BACKWARD**: 새 schema로 옛 데이터 읽기 가능 (consumer 먼저 업그레이드)
- **FORWARD**: 옛 schema로 새 데이터 읽기 가능 (producer 먼저 업그레이드)
- **FULL**: BACKWARD + FORWARD 둘 다
- 일반 권장: **BACKWARD** + additive only. consumer 업그레이드를 controllable.

### Watermark vs Event Time
스트리밍에서 늦게 도착하는(late) 이벤트를 어디까지 받을지 결정. watermark 너무 짧으면 late 데이터 버림, 너무 길면 latency 증가. SLO와 같이 결정.

### MERGE vs APPEND 결정
- **APPEND-only**: 단순. 하지만 backfill 시 중복 누적 → dedup 후처리 필수
- **MERGE (upsert)**: backfill safe. 하지만 PK 정의와 indexing 비용 발생
- 사실(immutable event) 테이블은 APPEND, 상태(state) 테이블은 MERGE.

### Lineage가 없으면 영향분석 불가
스키마 변경 시 "이거 누가 쓰지?"를 알아야 함. 최소한 source → table → consumer 매핑을 git README나 dbt manifest에 유지.

## Gotchas

### at-least-once를 exactly-once로 착각
대부분의 스트림 시스템은 기본 at-least-once. 같은 메시지가 2번 처리될 수 있음. sink 쪽에서 idempotency(PK + MERGE 또는 dedup 윈도우)로 보완해야 진짜 exactly-once 효과.

### 스키마에 필수 필드 추가 — 즉시 producer 깨짐
`ADD COLUMN NOT NULL` (또는 required field 추가)은 옛 producer를 즉시 깨뜨림. 항상 optional로 추가 → 일정 기간 dual-write → backfill → required 승격 4단계.

### Backfill이 stream과 동시 실행 — 순서 깨짐
batch backfill 도중 stream이 새 데이터 쓰면 같은 partition에서 race. backfill 동안 stream을 partition 단위로 pause하거나, MERGE로 commutative하게 설계.

### DLQ가 grow-forever
DLQ에 메시지가 쌓이는데 review/replay 안 함 → 진짜 incident 시 DLQ 의미 상실. owner 지정 + 주간 검토 + size 임계값 알림 필수.

### 품질 gate가 alert-only — 깨진 데이터가 그대로 흐름
"freshness < 6h" 알림만 보내고 consumer 차단 안 하면, 잘못된 데이터로 의사결정. tier-1 테이블은 gate 실패 시 hard-block 정책 필요.

### Watermark가 너무 길어 latency 폭발
"늦은 데이터 다 받자"고 watermark를 24h 잡으면 24h마다 윈도우 close → 대시보드 항상 24h 늦음. 99% late 데이터를 capture하는 최소값으로.

### Rerun ledger 없음 — 같은 backfill 중복 실행
"이 partition 누가 reprocess했지?" 추적 안 되면 두 사람이 동시에 다른 가정으로 backfill → 결과 divergence. rerun 명령은 항상 ledger에 row 추가하고 동시 실행 락.

### Lineage 없이 스키마 deprecate
"옛 컬럼 이제 안 쓰니까 drop"한 뒤 다음 분기에 비즈 팀이 깨진 대시보드 발견. drop 전 최소 N주 deprecation period + lineage 기반 consumer 통보.

### Stream의 ordering 가정
파티션 키가 잘못되면 같은 entity의 이벤트가 여러 파티션으로 → 순서 깨짐 → 상태 머신 잘못. 파티션 키는 entity ID(orderId, userId)로 고정.

## 도구 사용 패턴 (Harness)
- 스키마 diff: `Bash`로 schema-registry CLI 또는 `Grep`으로 git history의 schema 파일 비교
- partition 검사: SQL 또는 `Bash`로 metastore 쿼리
- DLQ 사이즈: monitoring 대시보드 또는 broker CLI

## 에러 복구 패턴 (Harness)
- 품질 gate 실패 → `Read`로 dbt test result / quality run log 확인 → 입력 source부터 역추적
- consumer 깨짐 보고 → `Grep`으로 lineage 매핑 파일 검색 → producer schema 변경 PR 추적
- backfill 멱등성 위반 → sink 테이블의 PK 충돌 / 중복 row count 확인 → MERGE 키 재검토

## Related (신규 그래프 cross-ref)

data-pipeline-governance가 보강되는 신규 노드:
- `data/iceberg-table-format.md` — Iceberg spec v2 (schema/partition/snapshot evolution), hidden partitioning, time-travel
- `data/spark-tuning-checklist.md` — Spark 3.5 + AQE (3.2+ default) + Iceberg 1.6 `write.distribution-mode=hash`
- `data/flink-streaming-job-shape.md` — Flink 1.20 LTS state backends, checkpointing, `withIdleness()` 의무
- `data/kafka-compaction-and-retention.md` — Kafka 4.0 KRaft, Tiered Storage 3.9 GA, schema BACKWARD/FORWARD/FULL
- `_common/dlq-reprocessing-wal.md` — WAL pattern (Netflix article) + Asset Management reprocessing
- `ml/metaflow-pipeline-shape.md` — Metaflow 2.19 ML pipeline (S3 artifact 자동 직렬화)
- `ml/feature-store-online-offline.md` — point-in-time correctness + train-serve skew 차단
- `_common/durable-execution.md` — Temporal activity exactly-once (transient 4% → 0.0001%)
