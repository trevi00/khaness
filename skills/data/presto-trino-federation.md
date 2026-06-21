---
name: presto-trino-federation
description: Trino 480 vs PrestoDB 0.297 fork 식별 + Iceberg v2 / FTE / federation 결정
keywords: trino prestodb presto federation iceberg fault-tolerant resource-group spill velox catalog
intent: choose-presto-fork design-federation tune-fte handle-broadcast-oom identify-fork
paths:
patterns: trino prestodb iceberg-connector fault-tolerant-execution exchange-manager
requires: iceberg-table-format
phase: plan implement review debug
tech-stack: any
min_score: 2
---

# Presto vs Trino Federation

> 핵심: 2020년 fork 이후 "Presto"라는 단어는 **항상** PrestoDB(Linux Foundation, prestodb.io) 또는 Trino(원 창업자, trino.io) 중 어느 쪽을 의미하는지 명시해야 한다. 두 fork는 connector 매트릭스/FTE/release cadence 모두 다르다. 채용공고/문서의 "Presto/Trino" 표기는 둘 다 받겠다는 의미일 가능성 — 단정 회피.

## 의사결정 트리

### IF 신규 query engine 채택 (Plan)
1. **default 권고: Trino** — Iceberg v2 spec 완전, Fault-Tolerant Execution(FTE) 보유, 빅테크 채택 다수(Netflix/Lyft/Stripe/Salesforce/LinkedIn — Starburst 2차 출처 명시)
2. **PrestoDB 채택 조건**: Meta 호환성 / Velox C++ 엔진(Presto Native) / Presto-on-Spark 필요 시
3. fork 식별 — repo URL이 `trinodb/trino` vs `prestodb/presto`, 버전 numbering(Trino 480+ vs PrestoDB 0.297) 두 가지로 구분
4. Iceberg 워크로드 → Trino (v2 equality delete, time-travel `FOR TIMESTAMP/VERSION AS OF`, branch/tag 모두 지원)

### IF 다중 source federation (Implement)
1. 단일 cluster에 catalog 다수 attach — Iceberg + Hive + PostgreSQL + Kafka 같은 SQL에서 join
2. Coordinator CBO가 join order 결정 — `trino.io/docs/current/optimizer/cost-based-optimizations.html` 통계 수집(`ANALYZE TABLE`) 의무
3. Network transfer 비용 — 작은 dim은 Iceberg, 큰 fact는 Hive에 두고 적절한 join hint
4. catalog 종류 (Trino) — HMS/Glue/JDBC/REST/Nessie/Snowflake 6종

### IF FTE(Fault-Tolerant Execution, Trino 전용) 결정 (Plan)
1. **batch/ETL 워크로드** → `retry-policy=TASK` + Exchange Manager(S3/HDFS spool) — Spark 대체 가능 영역
2. **interactive query** → `retry-policy=QUERY` 또는 retry 비활성 (latency 우선)
3. spill-to-disk는 legacy → FTE+TASK retry로 대체 (Trino docs 명시)

### IF broadcast OOM 또는 resource group 문제 (Debug)
1. Resource Group은 **admission control만** — 메모리 한도 강제 안 함, 신규 쿼리만 대기
2. broadcast hint 강제 시 driver/coordinator OOM 가능 — `distributed_join` session property로 강제 분산
3. spill 활성에도 broadcast OOM 발생 — 큰 "small" side를 SHUFFLE_HASH로

## 가이드

- "Netflix가 Trino를 쓴다" 단정은 Starburst 등 2차 출처에서만 — Netflix 자체 tech blog 1차 출처는 Iceberg + Maestro 통합만 명시. **Iceberg가 Netflix 작품**이므로 Iceberg-first 워크로드는 Trino가 자연스럽다는 약한 표현이 안전.
- 2014 Netflix Presto 글의 "Presto"는 fork 이전 PrestoDB — 인용 시 시점 명시.
- ANSI SQL 표준화는 Trino가 더 적극 (`SHOW TABLES FROM catalog.schema`, `WITH RECURSIVE` 등).

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | Iceberg v2 equality delete 처리는 Trino full, PrestoDB 후행 |
| 성능 효율성 | FTE+TASK retry로 ETL 신뢰성 확보, 단 exchange overhead 추가 |
| 호환성 | catalog plugin은 fork별 분기 — Trino plugin은 PrestoDB와 호환 안 됨 |
| 사용성 | Coordinator UI + query plan + stage stats — Trino가 정보량 우위 |
| 신뢰성 | FTE는 task 단위 retry로 long-running query 무한 retry 방지 |
| 보안 | TLS + SSO + catalog 단위 RBAC — fork별 plugin 분리 결정 |
| 유지보수성 | Trino release cadence 월 1회 — 버전 pin + 분기 전략 명시 |
| 이식성 | catalog property로 동일 SQL이 객체 스토어/RDBMS/Kafka 무관 동작 |
| 확장성 | disaggregated coordinator/worker (Trino) — auto-scaling 가능 |

## Gotchas

### "Presto" 단독 표기를 무비판 채택
2020 fork 이후 "Presto" 단어는 ambiguous. 채용공고/docs/블로그 인용 시 fork 명시 — PrestoDB(Linux Foundation)인지 Trino인지. Netflix 채용공고의 "Presto/Trino" 표기는 슬래시 — 둘 다 받겠다는 의미 가능성.

### Resource Group이 메모리 한도 강제한다고 오해
Resource Group은 **admission control만** — 동시 실행 query 수만 제한. 메모리 OOM 방지 효과 없음. `query_max_memory`, `query_max_memory_per_node` 별도 설정 필요.

### spill-to-disk 의존
Trino는 spill을 legacy로 명시(deprecate 진행) — `trinodb/trino#22845`. 신규 batch 워크로드는 FTE+TASK retry로 설계. 18GB heap에서도 broadcast OOM 사례 다수.

### Iceberg connector를 fork 간 동일하다고 가정
Trino 480은 Iceberg v2 full(equality delete + branch/tag), PrestoDB 0.297은 매트릭스 후행. 같은 SQL이 다른 결과 가능 — connector docs를 fork별로 별도 확인.

### "Netflix=Trino" 단정 인용
1차 출처(Netflix tech blog 자체)에 명시 없음. Starburst 등 2차 출처만 명시 — 단언 시 출처 신뢰도 표시.

## Source

- https://trino.io/docs/current/connector/iceberg.html — Iceberg v2 full(position + equality delete), `FOR TIMESTAMP/VERSION AS OF`, branch/tag, 6 catalog 타입, 조회 2026-05-10
- https://trino.io/docs/current/admin/fault-tolerant-execution.html — `retry-policy=QUERY|TASK`, Exchange Manager 필수, 조회 2026-05-10
- https://trino.io/docs/current/admin/spill.html — spill-to-disk legacy 명시, 조회 2026-05-10
- https://trino.io/docs/current/release.html — Trino 480(2026-03-24), 479(2025-12-14), 478(2025-10-29) cadence, 조회 2026-05-10
- https://prestodb.io/docs/current/ — PrestoDB 0.297(2026-04-01) docs, 조회 2026-05-10
- https://prestodb.io/blog/2025/02/10/presto-native-engine-in-2025/ — Velox/C++ 방향성 (Presto Native), 조회 2026-05-10
- https://www.starburst.io/blog/prestodb-vs-prestosql/ — "Netflix, Lyft, Stripe, Salesforce, LinkedIn made the leap to Trino" (2차 출처, 편향 가능), 조회 2026-05-10
- https://www.nextplatform.com/2024/04/30/the-perfect-ai-storage-trino-from-facebook-and-iceberg-from-netflix/ — "Iceberg from Netflix" 사실 인용, 조회 2026-05-10
- https://github.com/trinodb/trino/issues/22845 — spill-to-disk 제거 논의, 조회 2026-05-10
