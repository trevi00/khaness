---
name: feature-store-online-offline
description: Feast/Tecton/자체 구축 결정 — point-in-time correctness, online store(Redis/DynamoDB/Cassandra), train-serve skew 차단
keywords: feature-store feast tecton point-in-time training-serving-skew online-store offline-store palette
intent: choose-feature-store enforce-point-in-time prevent-train-serve-skew decide-online-store
paths:
patterns: feast tecton point-in-time entity_df feature-view online-store offline-store
requires: iceberg-table-format messaging-governance
phase: plan implement review
tech-stack: any
min_score: 2
---

# Feature Store (Online/Offline)

> 핵심: feature store의 첫 번째 책임은 **point-in-time correctness (PITC)** — training row가 label timestamp 시점 이전 feature value만 보도록. 이를 깨면 future-leak으로 production AUC가 offline AUC보다 항상 낮음. 두 번째는 train-serve skew 차단 — transformation 코드가 한 곳에서만 정의돼야.

## 의사결정 트리

### IF feature store 채택 결정 (Plan)
| 신호 | 권장 |
|---|---|
| 작은 팀 + OSS 자율 | **Feast** (Apache 2.0, 자체 운영) |
| 관리형 SaaS + 자동 transformation pipeline | **Tecton** (commercial, lock-in 감수) |
| 빅테크 규모 + 자체 컴퓨트 통합 | 자체 구축 (Uber Palette / Netflix 패턴) |
| 단일 프로젝트, feature 수 < 50 | feature store 채택 보류, 직접 SQL/Spark |

### IF online store 선택 (Plan)
| 요구사항 | 권장 |
|---|---|
| p99 < 5ms, 단일 region | Redis (단, Feast 통합은 #3596로 prod readiness 검증) |
| multi-region + AWS managed | DynamoDB |
| time-series 깊이 + cassandra 운영 경험 | Cassandra / ScyllaDB |
| GCP managed | Bigtable |

### IF offline store 선택 (Plan)
| 워크로드 | 권장 |
|---|---|
| BigQuery 중심 데이터 웨어하우스 | BigQuery (Feast 1st-class) |
| Snowflake 운영 | Snowflake (Feast 1st-class) |
| Iceberg lakehouse | Spark/Trino offline (Feast contrib, **Iceberg는 1st-class 아님 — Spark/Trino 경유**) |

### IF point-in-time join 구현 (Implement)
1. entity_df에 label timestamp 명시 컬럼 (`event_timestamp`)
2. feature view는 historical + latest 두 테이블 보유 (offline + online)
3. as-of join — `feature_ts <= event_ts AND event_ts < feature_ts + ttl`
4. 검증: training set의 feature value가 절대 미래 timestamp에서 오지 않음

### IF train-serve skew 차단 (Implement)
1. transformation 코드 **단일 정의** — Feast `FeatureTransformation` 또는 자체 라이브러리
2. training pipeline과 serving path 둘 다 같은 코드 import
3. CI에 skew detection — sample 100 row를 training/serving 양쪽에서 추출, hash 비교

## 가이드

- Feast minor 릴리스는 **non-backward-compatible** — production은 patch 버전까지 명시.
- streaming feature freshness는 Flink/Spark Structured Streaming + online store TTL 결정.
- Tecton 비교 자료는 vendor-authored — 1차 docs로 cross-check.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | PITC로 future-leak 차단, train AUC ≈ production AUC |
| 성능 효율성 | online store 선택이 p99 latency 직접 결정 |
| 호환성 | OSS Feast는 Spark/BigQuery/Snowflake 멀티 백엔드 |
| 사용성 | feature view 선언 1번으로 training+serving 동시 노출 |
| 신뢰성 | online store TTL + offline 백필 정책으로 staleness 통제 |
| 보안 | feature 단위 RBAC + PII 마스킹 정책 |
| 유지보수성 | transformation 단일 정의로 skew 차단 |
| 이식성 | Feast는 cloud 무관, online/offline 백엔드 교체 가능 |
| 확장성 | Uber Palette 사례 — 20,000+ feature 호스팅 |

## Gotchas

### Future leak (PITC 누락)
training row가 label 이후 feature value를 받음. offline AUC > production AUC인 가장 흔한 원인. as-of join 명시 필수.

### Train-serve skew (transformation 이중 정의)
training은 Spark에서, serving은 Python에서 별도 구현 → 미세한 차이가 model degradation. 단일 정의 + CI hash 비교.

### Feast minor 버전 backward 비호환
non-backward-compatible 릴리스 정책. production은 patch 버전까지 pin. 업그레이드 시 schema migration 명시.

### Iceberg를 Feast 1st-class로 가정
Feast docs offline store 카탈로그에 Iceberg 직접 항목 없음 — Spark/Trino 경유로만 사용. 직접 connector 기대 시 시간 낭비.

### Online store TTL 누락
Redis/DynamoDB에 TTL 없으면 stale feature가 무한 누적. cost 폭증 + 모델 성능 저하. 명시 정책 필수.

### Point-in-time join 비용 폭증
wide entity_df + 깊은 historical로 join 시 O(N×M). partition pruning + window 제한.

## Source

- https://docs.feast.dev/reference/online-stores — Redis/DynamoDB/Cassandra/Bigtable 등 online store 매트릭스, 조회 2026-05-10
- https://docs.feast.dev/reference/offline-stores — BigQuery/Snowflake/Redshift 1st-class; Spark/Trino contrib, 조회 2026-05-10
- https://docs.feast.dev/project/versioning-policy — Feast minor 릴리스 backward incompatible 정책, 조회 2026-05-10
- https://github.com/feast-dev/feast/issues/3596 — Redis online store production-ready 검증 이슈, 조회 2026-05-10
- https://docs.databricks.com/aws/en/machine-learning/feature-store/time-series — point-in-time feature join 정의, 조회 2026-05-10
- https://www.uber.com/blog/scaling-michelangelo/ — Palette 20,000+ feature, Hive(offline) + Cassandra(online), 조회 2026-05-10
- https://building.nubank.com/dealing-with-train-serve-skew-in-real-time-ml-models-a-short-guide/ — train-serve skew 진단/차단 패턴, 조회 2026-05-10
