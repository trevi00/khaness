---
name: iceberg-table-format
description: Apache Iceberg 테이블 결정 — schema evolution / partition spec / snapshot 격리 / time-travel을 batch+stream 양쪽에서 일관되게
keywords: iceberg table-format schema-evolution snapshot partition-spec time-travel hidden-partitioning lakehouse
intent: design-table-format govern-schema-evolution tune-storage-layout plan-rollback
paths:
patterns: org.apache.iceberg pyiceberg spark.sql.catalog FlinkCatalog Trino-Iceberg
requires: db-design messaging-governance
phase: plan implement review
tech-stack: any
min_score: 2
---

# Apache Iceberg Table Format

> Iceberg는 "파일을 모아둔 테이블"이 아니라 metadata-driven snapshot 격리 + 안전한 schema/partition 진화를 약속하는 contract. 그 contract를 깨면 lakehouse가 아니라 그냥 비싼 parquet 더미가 된다.

## 의사결정 트리

### IF 신규 데이터셋 설계 (Plan)
1. write engine이 Spark·Flink·Trino·dbt 중 ≥ 2개로 늘 가능한가? → Iceberg 채택 (Hive/Delta보다 멀티 엔진 안전)
2. partition 후보 컬럼이 시간(`event_ts`)인가? → **hidden partitioning** (`days(event_ts)`)으로 — 사용자 쿼리에 partition column 노출 금지
3. row 수 추정: 작은 파티션 다수(≪128MB)면 future read amplification → write task에 `target-file-size-bytes` 명시 (기본 512MB)
4. compaction 정책을 production 가기 전에 결정 — `rewrite_data_files` 주기, `rewrite_manifests` 트리거 임계

### IF schema 변경 요청 (Implement|Review)
1. 안전한 변경 화이트리스트: **add column / rename column / reorder / widen type (int→long, float→double) / make optional**
2. 위험한 변경: **drop column** — 즉시 반영되지만 historical snapshot은 여전히 보유. drop 전 모든 reader 호환성 확인
3. **금지**: type narrowing(long→int), required로 좁히기 — Iceberg가 거부하지만 우회 시 reader breakage
4. partition spec 변경은 schema와 분리 결정 — `ALTER TABLE ... REPLACE PARTITION FIELD`. 과거 파일은 옛 spec 유지(spec evolution이라 재작성 불필요)

### IF "쿼리가 느려졌다" (Debug)
1. metadata 폭발 의심 — `SELECT count(*) FROM table.manifests` 가 수만 단위면 `rewrite_manifests` 필요
2. small file 문제 — `table.files`로 파일당 byte 분포 확인. p50 < 64MB면 `rewrite_data_files(strategy='binpack')`
3. partition pruning 실패 — Spark plan에 `IcebergScan` filter pushdown 확인. column transform 함수가 hidden partition function과 정합인지 (`year(ts)` vs `days(ts)`)
4. snapshot 누적 — `table.history` ≫ 100이면 `expire_snapshots(older_than=...)` 정책 누락

### IF rollback / 사고 복구 (Debug|Review)
1. 현재 snapshot 식별 — `SELECT snapshot_id FROM table.snapshots ORDER BY committed_at DESC`
2. `CALL system.rollback_to_snapshot('table', <id>)` — atomic. WAL 같은 추가 작업 없음
3. rollback 후 downstream consumer가 캐시한 file path는 무효 — Trino/Spark caching layer flush 필요
4. **time-travel은 점검 도구지 운영 패턴 아님** — 매 쿼리마다 `FOR VERSION AS OF`로 과거 읽기 = 캐시 가능성 0, 비용 폭증

## 가이드

- Catalog 선택은 다른 결정과 분리: REST catalog가 멀티 엔진 호환의 default. Hive Metastore는 legacy 호환 시만.
- Streaming write(Flink)와 batch compaction(Spark)이 같은 테이블을 쓸 때 — `commit.retry.num-retries` 늘리고 `write.distribution-mode=hash`로 파티션 충돌 줄이기.
- 파일 포맷은 Parquet default. ORC는 Hive 마이그레이션 케이스만, Avro는 row-level append-heavy 워크로드 한정.

## 9축 품질 체크

| 축 | 적용 | 검증 방법 |
|---|---|---|
| 기능 적합성 (정확성) | snapshot isolation으로 reader가 partial write 못 봄 | 동시 write 중 read 결과 = 마지막 commit snapshot |
| 성능 효율성 | partition pruning + manifest skipping | EXPLAIN plan에 `IcebergScan filtered files=N/M` 출력 |
| 호환성 | 멀티 엔진 (Spark/Flink/Trino/dbt) 동시 read/write | 각 엔진에서 동일 query 결과 일치 |
| 사용성 | hidden partition으로 사용자가 transform 함수 안 알아도 됨 | 쿼리 작성에 `partition_col` 등장 여부 0 |
| 신뢰성 | rollback으로 atomic 복구 | `rollback_to_snapshot` 후 row count 일치 |
| 보안 | 파일 권한 + catalog ACL 분리 | catalog는 RBAC, S3는 bucket policy로 이중화 |
| 유지보수성 | schema evolution rule 매트릭스 + spec evolution 분리 | breaking change 시 reject 자동화 |
| 이식성 | S3/GCS/Azure Blob/HDFS 객체 스토어 무관 | catalog property `warehouse=` 만 교체 |
| 확장성 | spec evolution으로 partition 변경 시 historical 재작성 X | partition 변경 후 read latency 변화 < 5% |

## Gotchas

### `SELECT *` 후 파티션 컬럼이 안 보인다
hidden partitioning은 의도. 사용자가 `event_ts`로 쿼리하면 Iceberg가 `days(event_ts)` 파티션으로 자동 변환. 명시적으로 `bucket(16, user_id)` 같은 transform 결과를 쓰고 싶으면 `partition` 메타 필드를 system 함수로 추출.

### drop column 직후 디스크 사용량이 그대로
당연 — historical snapshot이 column 데이터 보유. `expire_snapshots` + `remove_orphan_files` 둘 다 돌아야 실제 삭제. 둘은 별개 maintenance op.

### Spark `MERGE INTO`가 partition 전체를 재작성
Copy-on-write가 default. Streaming/잦은 update면 `write.merge.mode=merge-on-read`로 — 단, read 시 delete file scan 추가 비용. 둘 중 워크로드 패턴으로 선택.

### Flink streaming write와 Spark batch compaction이 같은 테이블에서 충돌
commit conflict로 둘 다 retry 폭증. 해결: streaming write는 `write.distribution-mode=hash` + 파티션별 writer 분산, compaction은 streaming 정지 시간대 또는 `rewrite.partial-progress.enabled=true`로 부분 진전.

### `expire_snapshots` 정책 없이 운영 6개월
metadata.json이 수백 MB로 폭증. 모든 plan operation이 느려짐. 운영 진입 전 정책 결정: 보통 `older_than = 7 days` AND `retain_last = 100`.

### REST catalog vs Hive Metastore 혼용
같은 테이블을 다른 catalog로 등록하면 commit 동기화 불가 — atomic 보장이 catalog 단위라 두 catalog가 서로 모름. 단일 catalog로 통일.

## Source

- https://iceberg.apache.org/spec/ — Iceberg Table Spec v2 (schema/partition/snapshot 정의), 조회 2026-05-10
- https://iceberg.apache.org/docs/latest/evolution/ — schema/partition evolution rules verbatim, 조회 2026-05-10
- https://himalayas.app/companies/netflix/jobs/data-engineer-5-playback — "tuning Spark applications and optimizing storage layouts (e.g., using Iceberg)" verbatim, 조회 2026-05-10
- https://netflixtechblog.com/iceberg-at-netflix-fa6d7e3115d9 — Netflix 자체 운영 패턴 (compaction, manifest rewrite), 조회 2026-05-10
