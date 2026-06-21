---
name: transport-reliability
description: Network transport as an explicit contract — protocol choice, deadlines, retry/backoff, connection pool, and fallback path made reviewable instead of inheriting library defaults.
keywords: transport network protocol http http2 http3 grpc websocket tcp tls deadline timeout connect-timeout read-timeout idle-timeout retry backoff jitter circuit-breaker bulkhead connection-pool keepalive dns-resolution ttl fallback degraded-mode partial-failure hedged-request load-balancer client-side-balancing service-discovery
intent: 네트워크설계해 timeout정해 retry정책정해 connection-pool설정해 circuit-breaker걸어 fallback설계해 protocol선택해 grpc설계해 websocket설계해 dns튜닝해
paths: src/client src/http src/rpc src/grpc clients/ network/ transport/ httpclient/ resilience/ resilience4j/ polly/
patterns: okhttp httpclient retrofit grpc-java grpc-go tonic reqwest axios fetch undici hyper requests aiohttp httpx resilience4j polly hystrix sentinel envoy istio linkerd
requires: idempotency monitoring sre-operations rollback-readiness
phase: plan implement review
tech-stack: any
min_score: 2
---

# Transport Reliability

라이브러리 기본값(무한 timeout, no retry, lazy DNS)은 production에서 거의 항상 틀림. 모든 outbound 호출은 **명시적 계약** — 5축: protocol, deadline, retry, pool, fallback.

## 의사결정 트리

### IF 새 외부 호출 추가 (Plan)
1. **protocol 선택**:
   - request/response stateless: HTTP/1.1 또는 HTTP/2 (multiplex 필요 시 H2)
   - 양방향 streaming: gRPC + HTTP/2, 또는 WebSocket
   - low-latency RPC + schema 강제: gRPC
   - 브라우저 호환 + 단순 push: SSE
2. SLA 명시 — p50/p99 latency, error budget, 호출 빈도
3. **deadline budget 분배** — 상위 deadline에서 child 호출 budget을 빼서 전달 (deadline propagation)
4. idempotent 여부 — 안전한 retry 가능한가 (POST는 idempotency-key)
5. **→ idempotency 스킬: idempotency-key 패턴 참고**

### IF Deadline / Timeout 설정 (Implement)
1. **3종 timeout 모두 설정**:
   - connect timeout: TCP/TLS handshake (보통 1-3초)
   - read timeout: 응답 대기 (요청별 SLA + α)
   - idle timeout: keep-alive 연결 회수 (pool 관리)
2. infinite timeout 금지 — 라이브러리 기본이 무한이면 명시적 cap
3. deadline 전파 — gRPC `deadline`, HTTP `Deadline` header, context.WithDeadline
4. timeout < 호출자 deadline (caller가 끊기 전에 cleanup 시간 확보)

### IF Retry 정책 (Implement)
1. **idempotent만 retry** — 비idempotent는 idempotency-key 또는 retry 금지
2. backoff = exponential + jitter — `min(cap, base * 2^n) + random(0, jitter)`
3. retry budget — 시간 budget 안에서 N회 (보통 2-3회), 무한 retry 금지
4. retry-after 존중 — 서버가 보낸 헤더로 backoff 조정
5. retryable 분류 — 5xx / network timeout → retry / 4xx → no retry / 429 → backoff 증가
6. **circuit breaker** — 연속 실패 시 일정 시간 fail-fast (downstream 보호)

### IF Connection Pool / Keepalive (Implement)
1. pool max size — host당, 전체. 예상 concurrency × safety
2. idle timeout — server keepalive보다 짧게 (서버가 끊은 stale 연결 잡기)
3. connection validation — 가져올 때 health check (옵션)
4. DNS TTL 존중 — 캐시된 IP 영원 사용 금지 (host failover 시 stuck)
5. HTTP/2는 pool 1개로 multiplex — 옛 HTTP/1.1 thinking 안 됨

### IF Fallback / Degraded Mode (Implement)
1. cached value — 마지막 성공 응답을 N분 사용 (stale-while-revalidate)
2. default value — empty list, 0, "unknown" 등 안전한 default
3. partial response — 일부 필드 빠진 응답 + 클라이언트가 처리
4. circuit open 시 즉시 fallback — 호출 자체 안 함
5. **graceful degradation 명시** — UX 차이를 product 합의

### IF 운영 회고 (Review)
- [ ] timeout/retry 정책이 라이브러리 기본인가, 명시적인가
- [ ] error rate / p99 가 SLA 안인가
- [ ] retry rate — 너무 높으면 downstream 부담 가중
- [ ] circuit open 빈도 / 지속 시간
- [ ] pool exhausted 알림 / 대기 시간
- [ ] DNS resolution 실패 비율

## 5축 체크리스트

```
[Protocol]
□ stateless/stream/RPC 요구에 맞는 프로토콜
□ TLS 검증 (cert pinning은 신중히)
□ HTTP/2 또는 HTTP/3 활용 가능성

[Deadline]
□ connect / read / idle 3종 timeout 명시
□ deadline 전파 (caller → callee)
□ 무한 timeout 없음

[Retry / Resilience]
□ idempotent만 retry
□ exponential backoff + jitter + cap
□ retry budget (시간 또는 횟수)
□ circuit breaker (consecutive failure 또는 error rate)

[Connection Pool]
□ max size per host / total
□ idle timeout < server keepalive
□ DNS TTL 존중
□ stale connection 검증

[Fallback]
□ degraded mode 정의
□ cached / default / partial 중 선택
□ circuit open 시 즉시 fallback
□ UX 합의된 차이
```

## 가이드

### Deadline Propagation
A → B → C 호출 chain에서 A가 5s deadline이면 B는 4s, C는 3s 식으로 전파. gRPC는 metadata로 자동 전파(`grpc-timeout`). HTTP는 직접 header 또는 framework 설정. propagation 없으면 A는 끊겼는데 B/C는 계속 일하는 좀비 호출.

### Retry vs Hedged Request
- **Retry**: 실패 후 재시도. 추가 latency.
- **Hedged**: 일정 시간 후 응답 없으면 같은 요청을 다시 보내고 먼저 도착하는 것 사용. tail latency 단축. 단 idempotent + 추가 부하 감수.

### Circuit Breaker State Machine
- **Closed**: 정상. 실패 카운트 누적.
- **Open**: 임계 초과. 모든 호출 즉시 실패(fail-fast).
- **Half-Open**: 일정 시간 후 일부 호출 허용. 성공이면 Closed, 실패면 Open으로.
임계: consecutive N개 또는 N초 안 error rate %.

### HTTP/2 Connection Reuse
HTTP/1.1은 pool 여러 connection으로 concurrency. HTTP/2는 1개 connection에 multiplex. pool max=1로도 충분 — 옛 HTTP/1.1 sizing 그대로 두면 자원 낭비. 단 stream concurrency limit(server max_streams)은 별개.

### DNS TTL과 Failover
JVM 등 일부 런타임은 DNS 결과를 영원 캐시(default `networkaddress.cache.ttl=-1`). host가 다른 IP로 failover 됐는데 영원 옛 IP 호출 → 장애. TTL 30-60s로 명시 또는 매 connection마다 resolve.

### gRPC Deadline의 default
gRPC client default deadline은 보통 무한 — production에선 항상 명시. server는 deadline 받아서 자기 쿼리/호출에도 전파. 안 그러면 client가 끊겼는데 server DB 쿼리 계속 도는 좀비.

## Gotchas

### Default infinite timeout
많은 클라이언트(특히 옛 Java HttpURLConnection, 일부 SDK)가 default 무한 timeout. 한 번 stuck 호출이 thread/connection 영원 점유 → pool exhaust. 명시적 timeout 강제.

### POST를 자동 retry
HTTP 라이브러리 일부는 POST도 retry — 결제/주문 중복. retry는 idempotent method(GET/PUT/DELETE) 또는 명시적 idempotency-key 가진 POST만.

### Backoff 없이 즉시 retry
실패 → 즉시 retry → 더 실패 → server overload 가속. exponential + jitter 필수. jitter 없으면 thundering herd(모든 client 동시에 retry).

### Circuit breaker가 너무 sensitive
임계가 낮으면 transient blip마다 open → user 영향. 보통 consecutive 5-10 또는 error rate 50% over 10s. tuning이 필요.

### Pool size를 무제한
pool unbounded면 갑자기 traffic 폭증 시 connection 수만 → server가 못 받음 → 모두 실패. max + queue로 backpressure.

### Idle connection이 server에서 끊김
LB / server가 idle 60s에 끊는데 client pool은 5분 보관 → 다음 사용 때 broken pipe. server keepalive 확인 + client idle timeout < server.

### DNS caching forever
한 번 resolve된 IP를 process 평생 사용 → host migration / failover 시 stuck. JVM `networkaddress.cache.ttl=30`, OS-level은 stub resolver TTL 존중.

### Retry storm during outage
downstream이 느려서 모두 timeout → 모두 retry → 더 느려짐 → 영원 storm. circuit breaker + retry budget으로 차단.

### Deadline 전파 안 함
client가 5s deadline에 끊기지만 server는 모르고 계속 처리 → DB lock / resource 점유. 모든 호출에 deadline 전파.

### TLS handshake가 매 호출
keepalive / pool이 동작 안 해서 매 요청마다 TLS handshake → latency / CPU 폭증. pool reuse 검증 (요청 수와 connection 수 비율 확인).

### Same connection across regions
multi-region failover 후에도 옛 region 연결 사용 → cross-region latency. 정기 connection cycling 또는 TTL 기반 refresh.

### Hedged request 둘 다 처리
hedged 보낸 요청이 둘 다 server에 도착 → 비idempotent면 중복. hedged는 항상 idempotent + cancel 신호 또는 idempotency-key.

### Fallback이 silent failure
default value 반환하지만 metric / log 없으면 calling-side에선 잘 도는 것처럼 보임 — 실제 downstream 다운 중. fallback도 metric으로 가시화.

## 도구 사용 패턴 (Harness)
- timeout 설정 검사: `Grep`으로 `connectTimeout`, `readTimeout`, `WithTimeout` 검색
- retry 정책: `Grep`으로 `retry`, `backoff`, `RetryPolicy` 검색
- circuit breaker 상태: 라이브러리별 metric (resilience4j, polly, hystrix 대시보드)
- DNS TTL: JVM `networkaddress.cache.ttl`, OS resolver 설정
- pool 상태: HTTP client metric(`pool.active`, `pool.pending`, `pool.idle`)

## 에러 복구 패턴 (Harness)
- "p99 latency spike" → server는 정상이지만 client pool exhausted 가능성, pool 설정과 sharing 패턴 확인
- "broken pipe / connection reset 빈발" → idle timeout mismatch, client idle을 server keepalive보다 짧게
- "circuit open 자주" → 임계 너무 낮음 또는 진짜 server 문제, error breakdown 분석
- "DNS resolution intermittent fail" → resolver fallback 추가, hosts 파일 emergency override 절차
- "retry rate 폭증" → downstream 상태 + circuit breaker 기동 여부, retry budget 적용

## Related (신규 그래프 cross-ref)

transport-reliability가 결합되는 신규 노드:
- `_common/service-resilience-patterns.md` — resilience4j 2.59 (Hystrix maintenance mode 대체) circuit breaker / bulkhead / retry / time-limiter
- `_common/edge-gateway-routing.md` — Envoy retry budget (`budget_percent`, `min_retry_concurrency`) — retry storm 차단 표준
- `_common/load-shedding-prioritized.md` — 503 + Retry-After (criticality tier별)로 retry 폭주 차단
- `infra/network-tcp-bgp-dns-tls.md` — TCP BBR vs cubic, TLS 1.3 1-RTT, RPKI invalid 거부, MTU/PMTUD black hole
- `systems/realtime-media-transport.md` — UDP/QUIC head-of-line blocking 차단, GCC congestion control, B-frame disable
- `java/lang/grpc-service-contracts.md` — gRPC keepalive (server PERMIT_KEEPALIVE_TIME 5min), deadline propagation
