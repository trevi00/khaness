---
name: distributed-cache-decisions
description: Cassandra / EVCache / Redis / DynamoDB 결정 — 일관성 모델, eviction policy, hot partition, cache stampede 차단
keywords: cassandra evcache redis dynomite dynamodb memcached cache eviction hot-partition consistency stampede thundering-herd
intent: choose-cache-store decide-consistency-model handle-hot-partition prevent-stampede tune-eviction
paths:
patterns: LOCAL_QUORUM maxmemory-policy ConsistentRead ALL_KEYS partition-key
requires: db-design service-resilience-patterns
phase: plan implement review debug
tech-stack: any
min_score: 2
quality_axes_enforced: true
---

# Distributed Cache Decisions (Cassandra / EVCache / Redis / DynamoDB)

> 핵심: 4 종류 store는 일관성/지속성/접근 패턴이 모두 다름. **Cassandra는 "per-operation tradeoff"**, EVCache는 AP, Redis는 단일 노드(또는 cluster), DynamoDB는 managed AP+option strong read. 가장 흔한 사고는 **hot partition** — Cassandra/DynamoDB 둘 다 partition key 분포 안 보고 설계해 throughput cliff.

## 의사결정 트리

### IF cache/store 선택 (Plan)
| 신호 | 권장 |
|---|---|
| wide-column + tunable consistency + multi-DC | **Cassandra** (LOCAL_QUORUM default) |
| 단순 key→object + 다중 AZ replication + 운영 단순 | **EVCache** (Netflix OSS, memcached 위) |
| data structure (List/Set/Sorted Set/Hash/Stream) | **Redis** |
| AWS managed + on-demand scale | **DynamoDB** |
| 검색/full-text | (cache 아님) **Elasticsearch** — 별도 결정 |

### IF Cassandra 사용 (Implement)
1. partition key — high-cardinality. 단일 partition row 수 < 100MB 권장 (hot partition 차단)
2. clustering key — partition 내 정렬. range scan 패턴 결정
3. consistency — read/write 각각 LOCAL_QUORUM default. eventual로 낮추면 stale 위험
4. compaction — STCS (write-heavy) vs LCS (read-heavy) vs TWCS (time-series)

### IF Redis 사용 (Implement)
1. eviction policy 결정 — `maxmemory-policy`:
   - `allkeys-lru` (default), `allkeys-lfu`, `volatile-lru`, `volatile-ttl`, `noeviction` 등 9종
   - **`volatile-xxx`**는 TTL 없는 키는 eviction 안 함 — 모든 키에 TTL 없으면 `noeviction`처럼 동작 → OOM crash
2. persistence — AOF (durability) vs RDB (faster restart). 둘 다 가능
3. cluster mode — 16384 hash slot. cross-slot transaction 불가
4. memory budget — `maxmemory` 명시 + alert at 75%

### IF DynamoDB 사용 (Implement)
1. partition key — 균등 분포. **단일 partition 한도: 3000 RCU / 1000 WCU**
2. read consistency — eventually consistent (default, 1 RCU) vs strongly consistent (`ConsistentRead=true`, 2 RCU)
3. **`ConsistentRead`는 GSI/Stream에서 미지원** — 모르고 설계 시 silent inconsistency
4. on-demand vs provisioned — peak/평균 비율 4× 미만이면 provisioned가 저렴

### IF EVCache 사용 (Implement)
1. zone-affinity — read는 같은 AZ에서, write는 모든 AZ 동시
2. ChannelGroup으로 client 구성, replica = AZ 수
3. memcached protocol — 단순 GET/SET/CAS만. 복잡 data structure는 Redis로

### IF cache stampede / thundering herd (Debug)
1. single-flight — 같은 key fetch 진행 중이면 후속 요청은 첫 결과 wait
2. jittered TTL — exact 만료 시각 분산 (TTL ± 10% random)
3. probabilistic early refresh — TTL 90% 도달 시점부터 random하게 미리 갱신
4. negative cache — miss 결과도 짧은 TTL (downstream 폭주 차단)

## 가이드

- Cassandra hot partition 진단 — `nodetool tablestats` partition size 분포.
- Redis stampede 차단 — Redlock은 lock 자체 stampede 위험. single-flight 우선.
- DynamoDB adaptive capacity는 partition cap 자동 우회 안 함 — burst 흡수만.
- Dynomite는 redis 자체가 아니라 redis 위 multi-DC replication shim — vanilla Redis Cluster와 실패 모드 다름.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | Cassandra LOCAL_QUORUM이 latency-availability tradeoff 명시 |
| 성능 효율성 | Redis in-memory + EVCache zone-local read로 latency ↓ |
| 호환성 | DynamoDB SDK 모든 언어, Cassandra CQL 표준 |
| 사용성 | partition key 결정 트리로 hot partition 사전 차단 |
| 신뢰성 | EVCache multi-AZ replication, Redis AOF persistence |
| 보안 | Redis ACL/AUTH, DynamoDB IAM, Cassandra mTLS + RBAC |
| 유지보수성 | eviction policy 9종 매트릭스로 운영 결정 표준화 |
| 이식성 | memcached protocol(EVCache) + RESP(Redis) + CQL은 cloud 무관 |
| 확장성 | Cassandra add-node + DynamoDB on-demand로 horizontal scale |

## Gotchas

### Cassandra hot partition (단일 row 수 폭증)
partition key 설계 시 cardinality 안 보면 1개 partition에 row 수만/수억 누적 → throughput cliff + GC pressure. design 시 row 수 추정 + bucketing.

### Redis `volatile-lru`인데 TTL 없는 키 다수
`volatile-xxx`는 TTL 없는 키 무시 → `noeviction`처럼 동작 → OOM crash. 모든 키에 TTL 부여 또는 `allkeys-lru` 사용.

### DynamoDB hot partition (3000 RCU / 1000 WCU 한도)
single partition key가 hot이면 throughput throttle. partition key에 random suffix(write sharding) 또는 GSI 분산.

### `ConsistentRead`를 GSI/Stream에서 시도
지원 안 됨 — silent eventually consistent. 설계 시 명시적 인지.

### Cache stampede 무방어
TTL 만료 시각 동일 → 동시 요청이 모두 downstream으로 → cascade 장애. jittered TTL + single-flight 둘 다 적용.

### EVCache를 Redis 대체로 가정
EVCache는 memcached 프로토콜 — List/Set/Hash/Sorted Set 같은 data structure 없음. Redis 패턴 코드를 그대로 옮기면 동작 안 함.

### Dynomite는 vanilla Redis 아님
Netflix Dynomite는 Dynamo-style multi-DC replication을 redis/memcached 위에 얹은 shim. Redis Cluster와 동작/실패 모드 다름.

## Source

- https://cassandra.apache.org/doc/latest/cassandra/architecture/dynamo.html — "per-operation tradeoff between consistency and availability through Consistency Levels", 조회 2026-05-10
- https://redis.io/docs/latest/develop/reference/eviction/ — `maxmemory-policy` 9 values; "volatile-xxx policies behave like noeviction if no keys have an associated expiration", 조회 2026-05-10
- https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-partition-key-design.html — "Every partition ... maximum capacity of 3,000 read units per second and 1,000 write units per second", 조회 2026-05-10
- https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html — `ConsistentRead` not supported on GSI/Stream, 조회 2026-05-10
- https://github.com/Netflix/EVCache — "memcached & spymemcached based caching solution" multi-AZ, 조회 2026-05-10
- https://github.com/Netflix/EVCache/wiki/Overview — "All the reads ... same zone whereas the writes are done on all the zones", 조회 2026-05-10
