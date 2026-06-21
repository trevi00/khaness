---
name: db-change-review
description: DB change as a review discipline — migration safety, query plan delta, lock order, and backup/restore drill made explicit before any DDL/DML hits production.
keywords: db-change migration ddl alter-table query-plan explain index-change lock-order deadlock long-running-tx backup restore point-in-time-recovery pitr backfill expand-contract online-ddl pt-online-schema-change gh-ost foreign-key cascade column-drop charset collation collation-mismatch hot-rollback dml batch-update transaction-size
intent: db변경검토해 마이그레이션검토해 ddl적용해 alter검토해 인덱스추가해 query-plan확인해 backup검증해 restore드릴해 lock검토해 backfill계획해 컬럼drop해
paths: migrations/ migration/ db/migrations sql/ flyway/ liquibase/ schema/ V*__*.sql changelog/ ddl/ init/
patterns: flyway liquibase rails-migrations django-migrations alembic knex prisma-migrate sqitch goose dbmate gh-ost pt-online-schema-change
requires: db-design rollback-readiness infra-change-readiness data-pipeline-governance
phase: plan implement review
tech-stack: any
min_score: 2
---

# DB Change Review

`db-design`이 **무엇을 만들 것인가**라면, 이 스킬은 **이미 운영 중인 스키마/데이터를 어떻게 바꿀 것인가**. 4축: migration safety, query plan delta, lock order, backup/restore drill.

## 의사결정 트리

### IF 새 마이그레이션 작성 (Plan)
1. 변경 분류 — additive(컬럼/인덱스 추가) / mutative(타입/제약 변경) / destructive(drop/rename)
2. additive 외엔 **expand-contract 필수** — 한 release에 read-write 전환 묶지 말 것
3. **online vs blocking** 판단:
   - 작은 테이블(< 100K rows): 직접 ALTER 가능
   - 큰 테이블: pt-online-schema-change / gh-ost / pg_repack 또는 dual-write
4. backfill 전략 — chunked update + 진행률 + resume 가능한 cursor
5. rollback 마이그레이션 또는 expand-contract phase 분할
6. **→ rollback-readiness 스킬: expand-contract 패턴 참고**

### IF Query Plan 영향 검토 (Implement)
1. 변경 전 `EXPLAIN`/`EXPLAIN ANALYZE`로 baseline 저장 (대표 쿼리 N개)
2. 변경 후 같은 쿼리 다시 EXPLAIN — type/rows/key/extra 비교
3. 새 인덱스 추가 시 **기존 인덱스와 겹치지 않는지** (중복 인덱스는 write 비용만 추가)
4. composite index 순서 — selectivity 높은 컬럼 먼저, range는 마지막
5. covering index 가능성 — SELECT 컬럼이 모두 index leaf에 있으면 table lookup 제거
6. 통계 갱신 (`ANALYZE TABLE` / `VACUUM ANALYZE`) — DDL 후 실행 안 하면 옛 통계로 잘못된 plan

### IF Lock Order / 동시성 (Implement)
1. ALTER TABLE의 lock level — MySQL `ALGORITHM=INPLACE,LOCK=NONE` 가능 여부 확인
2. 외래 키 추가 — 자식 테이블 전체 스캔 + lock. 큰 테이블엔 위험
3. UPDATE/DELETE batch — 한 트랜잭션에 1만 row 이상 묶지 말 것 (replication lag, undo log 폭주)
4. lock order 일관성 — 여러 트랜잭션이 같은 순서로 row lock 획득해야 deadlock 회피
5. long-running transaction 모니터 — `pg_stat_activity` / `information_schema.innodb_trx`
6. **→ messaging-governance 스킬: outbox 사용 시 트랜잭션 경계 참고**

### IF 데이터 변경 (DML / Backfill) (Implement)
1. dry-run 먼저 — `SELECT count(*) WHERE <condition>`로 영향 row 수 측정
2. 트랜잭션 단위 결정 — chunk 크기, commit 빈도, replication lag 임계
3. idempotent — 재실행해도 결과 같음 (WHERE 조건이 변경 후에도 0건이어야)
4. 진행률 / resume — 마지막 처리 ID/timestamp 기록 → 중단 시 이어서
5. 결과 검증 — before/after row count + sample row 비교

### IF Backup / Restore Drill (Plan)
1. backup 종류 — full / incremental / WAL/binlog continuous
2. RPO(허용 데이터 손실 시간) / RTO(복구 시간) 명시
3. **분기별 1회 restore drill** — 옛 backup으로 별도 환경 복구, 데이터 검증
4. PITR(point-in-time recovery) 가능 시간 범위 확인
5. backup 검증 — checksum, schema 비교, 샘플 쿼리
6. cross-region 또는 cross-account backup 보관 (single point of failure 회피)

### IF Pre-Apply Review (Review)
- [ ] 변경 분류 명시(additive/mutative/destructive) + expand-contract 단계 표시
- [ ] EXPLAIN before/after 첨부
- [ ] lock level / 예상 시간 / online tool 사용 여부
- [ ] backfill 필요 시 chunk 크기 + 예상 시간
- [ ] rollback 절차 또는 다음 phase 명시
- [ ] backup 가용 시간 / restore 절차 동일성 확인
- [ ] 변경 직전 통계 / replication lag / disk 여유

## 4축 체크리스트

```
[Migration Safety]
□ 변경 분류 (additive/mutative/destructive)
□ expand-contract phase 분할 (mutative/destructive 시)
□ online tool 또는 lock-free 전략 (큰 테이블)
□ rollback 마이그레이션 또는 dual-write 기간

[Query Plan Delta]
□ EXPLAIN before/after 비교
□ 중복 인덱스 없는지
□ composite 순서 selectivity 기반
□ DDL 후 통계 갱신

[Lock Order]
□ ALTER lock level (INPLACE/NONE 가능 여부)
□ FK 추가 시 자식 테이블 크기 검토
□ UPDATE batch chunk 크기
□ long-running tx 모니터 + 알림

[Backup / Restore]
□ RPO/RTO 명시
□ 분기별 restore drill 기록
□ PITR 범위 확인
□ cross-region backup 보관
```

## 가이드

### Online Schema Change tools
- **pt-online-schema-change** (Percona): shadow table + trigger로 점진 복제 → atomic rename. FK 가진 테이블엔 까다로움.
- **gh-ost** (GitHub): binlog 기반, trigger 없음. replica 활용. MySQL 전용.
- **pg_repack**: PostgreSQL bloat 정리 + 일부 DDL.
- **공통 위험**: 디스크 2배 필요, replication lag, foreign key handling. dry-run / rehearse 필수.

### Expand-Contract 5 phase (재게)
1. expand: 새 컬럼/테이블 추가 (additive)
2. dual-write: app이 옛/새 양쪽에 write
3. backfill: 옛 데이터를 새 컬럼으로 채움 (chunked)
4. switch read: app이 새 컬럼 read
5. contract: 옛 컬럼 사용 멈춘 후 N주 dwell → drop

각 phase는 독립 release. 하나로 묶으면 rollback 불가능.

### EXPLAIN 비교의 함정
EXPLAIN은 **plan**만 보여주지 실제 실행 시간 아님. EXPLAIN ANALYZE(PostgreSQL/MySQL 8+) 또는 small subset 실행해 실측. 통계가 stale이면 EXPLAIN도 거짓.

### Replication lag
큰 batch UPDATE/DELETE는 primary에선 빠르지만 replica는 single-thread replay → lag 폭증. chunk + sleep 또는 row-based replication 활용. lag 모니터링과 임계값 알림.

### Foreign Key 추가 비용
ALTER TABLE ADD CONSTRAINT FK는 자식 테이블 전체 스캔 + 검증 lock. 수백만 row면 분 단위. NOT VALID(PostgreSQL) → 별도 VALIDATE로 분리하거나, app 레벨 검증 후 FK 생략 선택.

### Backup이 정상이라는 착각
"매일 backup 잘 됨" 로그만 보고 안심하면 실제 restore에서 schema mismatch / 깨진 dump 발견. 분기별 drill 의무 — 별도 host에 복구 + 핵심 쿼리 결과 비교.

## Gotchas

### ALTER TABLE의 ALGORITHM=COPY 무자각
MySQL에서 INPLACE 불가능한 변경(예: PK 변경, charset 변경)은 자동 COPY로 떨어짐 → 전체 테이블 lock + 디스크 2배. 사전에 `ALGORITHM=INPLACE` 명시로 강제 → 안 되면 에러로 알 수 있음.

### 인덱스 추가 후 통계 갱신 빠뜨림
새 인덱스가 있어도 옵티마이저가 옛 통계로 옛 plan 선택. DDL 후 `ANALYZE TABLE` / `VACUUM ANALYZE` 즉시. autostats가 실행될 때까지 기다리지 말 것.

### `DROP COLUMN`을 같은 release에 묶음
app 코드에서 컬럼 사용 빼고 같은 release에 drop → rollback 시 옛 코드가 없는 컬럼 참조 → 전면 장애. drop은 독립 release + N주 dwell.

### Big UPDATE one transaction
`UPDATE big_table SET ... WHERE ...` 전체를 한 트랜잭션 → undo log 폭주, replication lag, lock 보유 분 단위. PRIMARY KEY 기준 1만~10만 chunk + commit 사이 sleep.

### FK CASCADE의 숨은 row 변경
`ON DELETE CASCADE`로 1 row 지웠는데 자식 테이블 수만 row 동시 삭제 → lock + lag. CASCADE는 명시적 / 영향 범위 측정 후만 사용.

### Charset / Collation mismatch in JOIN
새 테이블은 `utf8mb4_0900_ai_ci`인데 기존 join 대상은 `utf8mb4_general_ci` → JOIN 시 인덱스 미사용 + 전체 스캔. 신규 테이블은 기존 collation에 맞춤 또는 일괄 마이그레이션 계획.

### "online" tool인데 FK 때문에 fail
gh-ost / pt-online-schema-change는 FK 가진 테이블에 제약 많음. 옵션 매뉴얼 확인 + 사전 dry-run + rollback 경로.

### Backfill resume 못 함
backfill 도중 fail → 처음부터 다시 → 이미 처리된 row 다시 처리(idempotent 아니면 깨짐) 또는 시간 2배. 마지막 처리 PK/timestamp 저장 + WHERE pk > :last 형태.

### `EXPLAIN`만 보고 production에 적용
test data가 작으면 plan 좋아 보임. production 통계 / 데이터 분포로 EXPLAIN 해야 함 — staging에 prod-like data subset 또는 production replica에 EXPLAIN.

### Backup drill 안 한 RTO
"RTO 1시간"이라 적었지만 실제 drill에선 4시간 — 인덱스 재빌드 / FK 재검증 / app 캐시 warmup 미반영. drill 결과로 RTO 갱신.

### PITR 가능 범위 모름
binlog/WAL retention이 24h인데 incident 36h 후 발견 → 그 시점 복구 불가. retention을 RPO + 안전 margin으로 확장.

### Dual-write 누수
expand-contract 중 일부 코드 경로가 dual-write 빠짐 → 새 컬럼이 옛 컬럼과 불일치 → contract 후 데이터 손상. checksum/sample 비교로 dwell 기간 마지막에 검증.

## 도구 사용 패턴 (Harness)
- 마이그레이션 파일: `Glob`으로 `migrations/V*__*.sql` 또는 `db/migrate/*.rb`
- EXPLAIN: `Bash`로 `mysql -e "EXPLAIN ..."` 또는 `psql -c "EXPLAIN ANALYZE ..."`
- lock 모니터: `Bash`로 `SHOW PROCESSLIST` / `pg_stat_activity` / `information_schema.innodb_trx`
- backup 검증: `Read`로 backup manifest, `Bash`로 restore drill 결과 로그
- replication lag: broker별 명령 (`SHOW SLAVE STATUS`, `pg_stat_replication`)

## 에러 복구 패턴 (Harness)
- "ALTER stuck" → process kill 시 데이터 손상 위험. innodb_trx 확인 → online tool 전환 또는 maintenance window 재계획
- "FK validation 실패" → NOT VALID로 추가 후 분리된 VALIDATE, 또는 위반 row 식별 + 수정
- "replication lag spiking" → batch chunk 줄이기 + sleep 추가, row-based replication 확인
- "restore에서 schema mismatch" → backup 시점 schema와 현재 schema diff, 마이그레이션 로그 추적
- "EXPLAIN이 전과 같은데 실제 느려짐" → 통계 stale → ANALYZE 실행, buffer pool 상태 확인
