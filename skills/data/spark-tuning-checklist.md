---
name: spark-tuning-checklist
description: Spark 3.5 + Iceberg 1.6 튜닝 — AQE/distribution-mode/CoW vs MoR 결정 + small file/skew 진단
keywords: spark iceberg aqe partition file-size cow mor skew broadcast advisory adaptive
intent: tune-spark-iceberg-job diagnose-skew handle-small-files choose-write-mode
paths:
patterns: org.apache.spark spark.sql.adaptive iceberg-spark-runtime DataFrameWriterV2
requires: iceberg-table-format
phase: plan implement review debug
tech-stack: any
min_score: 2
---

# Spark + Iceberg Tuning Checklist

> 핵심: AQE는 3.2+에서 default ON이고 Iceberg는 1.2+에서 `write.distribution-mode=hash`가 default — 이 둘이 정합되지 않으면 small file과 skew가 동시에 폭증한다. 튜닝의 90%는 두 default를 알고 그 위에서 결정.

## 의사결정 트리

### IF 신규 Spark + Iceberg job 설계 (Plan)
1. AQE 활성 확인 — `spark.sql.adaptive.enabled=true` (3.2+ default). 끄지 않는다.
2. partition size 정합 — `spark.sql.adaptive.advisoryPartitionSizeInBytes`(default 64MB)를 Iceberg `write.target-file-size-bytes`(default 512MB)에 맞추거나 의도적으로 작게(64–128MB) 유지하면서 compaction 일정 명시
3. distribution-mode 결정 — 균등 키면 `hash`(default), skew 키면 `range`, **`none`은 manifest 폭증 원인이라 금지**
4. write mode 결정 — read-heavy면 CoW(default), 잦은 row-level update/delete면 `write.delete.mode=merge-on-read` + 주기 compaction

### IF small file 누적 (Debug)
1. `SELECT * FROM table.files` 로 파일당 byte 분포 확인 — p50 < 64MB면 small file 문제
2. `CALL system.rewrite_data_files(table=>'t', strategy=>'binpack', options=>map('target-file-size-bytes','536870912'))` — target에 맞게 binpack
3. manifest도 같이 — `CALL system.rewrite_manifests('t')`
4. snapshot 누적 — `expire_snapshots(older_than => now() - interval '7' day, retain_last => 100)` 정책 확인

### IF skew 또는 OOM (Debug)
1. AQE skew join 활성 확인 — `spark.sql.adaptive.skewJoin.enabled=true` (default). `skewedPartitionFactor`(5.0), `skewedPartitionThresholdInBytes`(256MB)
2. broadcast OOM — `BROADCAST` hint는 `autoBroadcastJoinThreshold` 무시하고 강제 broadcast (driver/executor OOM 위험). 큰 dim에는 `SHUFFLE_HASH` 또는 `MERGE` hint
3. write 단계 skew — partition 키가 편향되면 `write.distribution-mode=range`로 전환 (단일 task가 거대 partition 쓰는 패턴 방지)

## 가이드

- AQE의 `coalescePartitions`가 작동하려면 input shuffle partition 수가 충분히 커야 함 — `spark.sql.shuffle.partitions` 기본 200을 데이터 크기에 비례해 늘리기.
- CoW는 read 빠르고 write 비용 높음(파일 전체 재작성), MoR는 반대 — Streaming write + 잦은 update면 MoR + 주기 compaction이 정답.
- `partitionedBy`에 hidden partitioning(`days(event_ts)`) 사용 권장 (참조: `iceberg-table-format.md`).

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | AQE skew detection이 exchange 후 통계 기반 — exchange 없는 plan(broadcast)에는 무력 |
| 성능 효율성 | advisoryPartitionSize ≈ target-file-size 정합 시 shuffle output이 후속 write에 정렬 |
| 호환성 | Spark 3.5 + iceberg-spark-runtime-3.5 stable. Spark 4.0은 iceberg-spark-runtime 미공개(2026-05) |
| 사용성 | `EXPLAIN FORMATTED` 출력에 AQE rule 적용 흔적 확인 가능 |
| 신뢰성 | `expire_snapshots` 누락 시 metadata.json 폭증 → plan 시간 증가 |
| 보안 | catalog ACL과 S3 bucket policy 이중화 (iceberg-table-format 정책 상속) |
| 유지보수성 | rewrite_data_files / rewrite_manifests / expire_snapshots / remove_orphan_files 4종 maintenance op 분리 |
| 이식성 | Spark 위 동일 코드가 EMR/Dataproc/Databricks/Glue 무관 동작 (catalog property만 교체) |
| 확장성 | partition spec evolution으로 historical 재작성 없이 partition 변경 |

## Gotchas

### `write.distribution-mode=none` (pre-1.2 default) 잔존
1.2 이전 default `none`은 task당 partition당 파일 1개 → manifest 폭증 + small file. 모든 신규 테이블 `hash`로 명시 강제.

### AQE `advisoryPartitionSizeInBytes` 64MB와 Iceberg target 512MB 불일치
defaults만 따르면 coalesce된 shuffle partition이 target보다 작은 파일을 쏟아냄. 둘을 동일 값(예: 256–512MB)으로 정렬하거나 후속 compaction 일정 명시.

### `BROADCAST` hint가 driver OOM 유발
hint는 `autoBroadcastJoinThreshold` 무시 — "small" side가 실제로 작지 않으면 driver/executor heap 폭발. 의심되면 `SHUFFLE_HASH`나 `MERGE`로 교체.

### CoW가 잦은 row-level update에서 write amplification
DELETE 1건이 파일 전체 재작성 — update-heavy 워크로드에서는 `merge-on-read`가 정답이지만, read 비용을 위한 compaction 주기를 같이 결정해야 함.

### AQE 비활성 환경에서 skew 미탐지
일부 운영팀이 "old behavior"를 위해 AQE 끄는 경우 — skew straggler + shuffle OOM의 직접 원인. 끄지 말고 개별 rule(`coalescePartitions`/`skewJoin`)을 끈다.

## Source

- https://spark.apache.org/docs/latest/sql-performance-tuning.html — "AQE ... enabled by default since Apache Spark 3.2.0"; skew defaults `skewedPartitionFactor=5.0`, `advisoryPartitionSizeInBytes=64MB`, 조회 2026-05-10
- https://iceberg.apache.org/docs/latest/spark-writes/ — "hash — This mode is the new default and requests that Spark uses a hash-based exchange" (Iceberg 1.2+ default), 조회 2026-05-10
- https://iceberg.apache.org/docs/1.6.0/configuration/ — `write.target-file-size-bytes=536870912` (512MB), `write.delete/update/merge.mode=copy-on-write` defaults, 조회 2026-05-10
- https://iceberg.apache.org/docs/1.6.0/maintenance/ — rewrite_data_files / rewrite_manifests / expire_snapshots / remove_orphan_files 절차, 조회 2026-05-10
- https://github.com/apache/iceberg/issues/13358 — Spark 4.0용 iceberg-spark-runtime 미공개 (2026-05 시점, 운영은 3.5 유지), 조회 2026-05-10
- https://www.databricks.com/blog/2020/05/29/adaptive-query-execution-speeding-up-spark-sql-at-runtime.html — "AQE skew join optimization detects such skew automatically from shuffle file statistics", 조회 2026-05-10
