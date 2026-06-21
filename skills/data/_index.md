---
name: data-platform-domain
description: 산업 표준 대규모 데이터 플랫폼 도메인 (Iceberg/Spark/Flink/Kafka/Presto/Druid) 진입점
keywords: data-platform iceberg spark flink kafka presto trino druid lakehouse
intent: design-data-pipeline tune-storage-layout govern-schema
paths:
patterns: spark.sql flink.streaming iceberg kafka.consumer
requires: db-design messaging-governance
phase: plan implement review
tech-stack: any
min_score: 1
---

# Data Platform 도메인 진입점

> 채용 시장(Netflix Data Engineer L5, Personalization Data Engineering 등)에서
> 일관되게 등장하는 lakehouse / streaming / OLAP 스택. RDBMS 스키마 결정은
> `_common/db-design.md`에서 다루고, 본 트리는 batch/stream + 분산 storage 결정.

## 매칭 룰

- 프롬프트에 `iceberg|spark|flink|kafka|presto|trino|druid|lakehouse` → 본 트리 우선
- `_common/db-design.md`보다 구체적인 분기에서 발동
- `_common/messaging-governance.md`와 양방향 cross-ref (kafka 노드)

## 9축 적용 정책

본 트리 산하 모든 스킬은 9축 게이트 강제 (`scripts/validators/skill_quality_axes.py`).
`MANDATORY_PREFIXES = ("data/", "infra/", "ml/")` 화이트리스트 적용.

게이트:
- G1 정확성  · `## Source` 절 ≥ 1 인용
- G2 성능    · ≤ 250 lines AND ≤ 8192 bytes
- G3 호환성  · frontmatter `requires:` ≥ 1
- G4 사용성  · 5 표준 절 (의사결정 트리/가이드/Gotchas/9축/Source)
- G5 신뢰성  · Gotchas ≥ 3개
