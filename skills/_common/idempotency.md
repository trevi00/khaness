---
name: idempotency
description: Idempotency as a cross-domain pattern — HTTP retry replay, message consumer redelivery, and pipeline backfill rerun unified by key + dedup window + side-effect isolation.
keywords: idempotency 멱등성 idempotent retry replay redelivery backfill rerun dedup deduplication idempotency-key request-id event-id transactional-outbox upsert merge unique-constraint exactly-once at-least-once side-effect dedup-window deterministic
intent: 멱등성구현해 idempotency-key받아 dedup해 upsert해 retry해도안전하게 redelivery안전하게 backfill안전하게 멱등컨슈머만들어
paths: src/api src/handlers src/consumer src/jobs api/ workers/ pipelines/ batch/ middleware/
patterns: idempotency-key request-id stripe-idempotency upsert merge on-conflict insert-or-update unique-constraint dedup-table outbox-pattern transactional-outbox event-id message-id correlation-id
requires: api-contracts messaging-governance data-pipeline-governance db-design
phase: implement review
tech-stack: any
min_score: 2
---

# Idempotency

같은 입력으로 N회 실행해도 결과 1회. **HTTP retry, message redelivery, backfill rerun** 3가지 도메인이 같은 패턴: key + dedup window + side-effect isolation.

## 의사결정 트리

### IF HTTP API에 idempotency 추가 (Implement)
1. 어떤 method — POST/DELETE/PATCH (GET은 본질적으로 idempotent, PUT은 자연스럽게 idempotent)
2. **Idempotency-Key 헤더 받음** — client가 UUID 생성. 같은 key 재요청 시 cached 결과 반환
3. dedup 저장소 — Redis(빠름, TTL) 또는 DB 테이블(internal POST에 좋음)
4. window — 보통 24h. 너무 짧으면 client 재시도 안전 X, 너무 길면 storage 비용
5. response cache — status code + body를 같이 저장. retry 시 정확히 같은 응답
6. **→ api-contracts 스킬: Idempotency-Key 헤더를 contract에 명시**

### IF Message Consumer 멱등 (Implement)
1. event 자체에 unique ID — message ID, event ID, 또는 business key
2. 처리 시작 전 dedup table 검사 — 이미 처리된 ID면 skip + ack
3. 처리 + dedup table 기록 + ack를 transaction으로
4. 또는 **transactional outbox** 또는 **dedup window** + business key
5. **→ messaging-governance 스킬: at-least-once 환경에서 필수**

### IF Pipeline / Backfill 멱등 (Implement)
1. partition key — 일/시간 단위로 나뉘는 단위
2. write 방식 — APPEND이면 dedup 후처리, MERGE(upsert)면 자연 멱등
3. rerun ledger — 어느 partition을 누가 언제 reprocess했는가
4. side-effect 격리 — 같은 partition 재실행 시 이메일 중복 발송 X (이메일은 ledger 기반)
5. **→ data-pipeline-governance 스킬: backfill 멱등성 패턴**

### IF Side-effect 멱등화 (Implement)
1. 외부 호출(이메일, SMS, 결제) — 자체 idempotency-key 또는 우리가 dedup
2. payment provider는 보통 idempotency-key 지원(Stripe 등) — 같은 key 재호출 = 1회 결제
3. notification은 dedup table — `(notification_type, target, dedup_window)` unique
4. webhook 발송도 dedup — 같은 event ID로 N회 발송해도 receiver 1회 처리

### IF 멱등성 회고 (Review)
- [ ] 모든 mutating endpoint가 retry-safe (Idempotency-Key 또는 자연 idempotent)
- [ ] consumer redelivery 시 중복 side-effect 없음
- [ ] backfill rerun 시 결과 같음 (count, sum 같은 invariant)
- [ ] dedup table 사이즈 / TTL 정상
- [ ] 외부 결제/notification에 dedup key 사용

## 패턴별 체크리스트

```
[HTTP Idempotency-Key]
□ POST/DELETE/PATCH에 헤더 받음
□ key + status + body 캐시 (24h)
□ key는 client UUID, server 생성 X
□ 같은 key + 다른 body 시 409 Conflict

[Consumer Dedup]
□ event ID 또는 business key 추출
□ dedup table 검사 → 처리 → 기록 → ack가 atomic
□ TTL은 retention보다 길게
□ outbox 패턴 또는 dedup window

[Pipeline Backfill]
□ MERGE(upsert) 또는 APPEND + 후처리 dedup
□ partition 단위 ledger
□ side-effect는 ledger 기반 분기

[Side-effect Isolation]
□ payment에 idempotency key
□ notification dedup table
□ webhook event ID dedup
```

## 가이드

### Idempotency-Key vs PUT
PUT은 "이 리소스를 X로 설정" — 자연 idempotent (마지막 PUT 결과 = 최종 상태). POST는 "create" — natural하지 않으므로 explicit Idempotency-Key 필요.

### Stripe-style Idempotency 설계
- key는 client가 생성 (UUID v4)
- 24h 동안 같은 key + 같은 body → cached 응답
- 24h 동안 같은 key + 다른 body → 409 conflict (오용)
- 24h 후 같은 key → 새 요청으로 처리
- key 길이 ≤ 255자, 충돌 위험 없음

### Transactional Outbox 패턴
DB write + 메시지 발행을 atomic하게:
1. 같은 transaction 안에서 비즈 row + outbox row 둘 다 INSERT
2. 별도 publisher process가 outbox poll → broker로 publish → ack 후 outbox row 삭제
3. publisher crash 시 outbox에 남아 다음 cycle에서 재발행 → consumer가 dedup
이중 write(DB OK + publish 실패) 문제 해결.

### Upsert(MERGE) vs INSERT + dedup
- **Upsert**: PK 충돌 시 update. backfill 시 자연 idempotent. UNIQUE INDEX 비용.
- **INSERT + dedup**: 일단 INSERT 후 dedup 후처리. 빠름. 하지만 대용량에서 비용.
- 일반: state 테이블은 upsert, fact 테이블은 INSERT + dedup column.

### 멱등성과 monotonicity
counter 같은 monotonic 연산은 멱등 어려움(`counter += 1` N회 = N). 대신 "이 event가 카운트되었는가"를 dedup하고 카운터는 distinct event 수로 계산.

## Gotchas

### 자체 소유 상태컬럼 SSOT 멱등은 read-check가 아니라 atomic CAS pre-claim
idempotency-key/dedup table이 없는 **자체 상태컬럼**(예: `order_status_flag='5'`) 멱등을 read-then-write(조회 후 검사)로 닫으면, 조회~쓰기 윈도우(외부 왕복 수초)에 **이중 외부호출**(UpdateOrder·PG 중복)을 못 막는 TOCTOU. → **원자적 CAS**: `UPDATE ... SET flag=? WHERE pid=? AND flag NOT IN(종결값)` 후 **영향행=1 확인**을, PG/외부 호출 **직전 pre-claim 지점**에 둔다. 취소 다경로(운영자/timeout/inbound) 공통 단일 안전점. (poslink #61 [HIGH] — read-check로 못 닫음)

### Idempotency-Key를 server가 생성
client가 보내야 의미. server가 생성하면 client는 retry할 때 어느 key 쓸지 모름 → idempotency 효과 없음. client가 retry policy + key 생성 책임.

### dedup table TTL이 retention보다 짧음
broker가 7일 보관인데 dedup table TTL이 24h면 5일째 redelivery 시 dedup 못 함 → 중복 처리. TTL ≥ retention + margin.

### 처리 + dedup 기록이 atomic 아님
처리 → DB commit → dedup 기록인데 두 번째 단계에서 crash → 다음 redelivery 시 dedup 못 찾고 재처리. 같은 transaction에 묶거나 outbox.

### Idempotency 캐시가 in-memory
서버 재시작 또는 multi-instance 환경에서 캐시 분실 → 같은 key 재처리. Redis나 DB 같은 shared store 필수.

### "같은 key 다른 body" — 무시하고 처리
client bug로 같은 key에 다른 payload 보냈을 때 silent하게 새 처리하면 idempotency 의미 없음. 409 Conflict로 명확히.

### 자연 idempotent 가정 — 실은 아님
"DELETE는 idempotent" — 처음엔 200 OK, 두 번째는 404? client 입장에선 다른 응답. 실제 멱등은 같은 입력 → 같은 출력. DELETE는 N회 모두 200 또는 204 (이미 없어도 OK).

### 외부 결제 retry — Idempotency-Key 누락
PG사에 idempotency-key 없이 retry하면 중복 결제. PG가 제공하는 mechanism(Stripe `Idempotency-Key`, PayPal `PayPal-Request-Id`) 의무.

### Pipeline rerun이 email 재발송
backfill 시 email/notification trigger도 재실행되면 사용자가 같은 email 5번 받음. side-effect는 ledger("이미 보낸 partition X로는 보내지 않음") 또는 별도 처리 lane.

### Counter을 update — race
`UPDATE counter SET value = value + 1`는 commutative지만 retry 시 +1이 +2 됨. distinct event ID 기반으로 카운트 또는 idempotent set 사용.

### Webhook 재발송 — receiver가 dedup 안 함
sender가 5초 timeout 후 retry하면 receiver는 같은 event 2번 받음. webhook payload에 event ID 포함하고 receiver가 dedup해야 안전.

### Dedup window 만료 후 재요청
24h dedup window인데 25h 후 client가 같은 key로 retry → 새 처리. 의도라면 OK, 실수라면 더 긴 window 필요. business 의미에 맞춰.

### Rerun ledger 없음 — 동시 backfill
두 사람이 동시 같은 partition 재처리 → 결과 divergence. ledger에 row 추가 + 동시 실행 락(파티션 단위 advisory lock).

## 도구 사용 패턴 (Harness)
- dedup table 검색: `Grep`으로 `idempotency_keys`, `processed_events`, `dedup_table` 패턴
- middleware 검토: `Grep`으로 `Idempotency-Key` 헤더 처리 코드
- DB 스키마: `Read`로 unique constraint, on-conflict 절 검사
- broker dedup: `Grep`으로 event ID extraction 로직

## 에러 복구 패턴 (Harness)
- 중복 결제 incident → idempotency-key 전달 여부, retry 로직 + key 생성 위치 점검
- consumer redelivery 시 중복 side-effect → dedup transaction atomicity 검토
- backfill 후 metric 2배 → MERGE vs APPEND 확인, dedup 후처리 누락 점검
- Idempotency-Key 401/400 응답 → header 이름 / 형식 / 길이 / dedup table connectivity

## Related (신규 그래프 cross-ref)

idempotency는 다음 신규 노드들의 전제 조건:
- `_common/webhook-delivery-and-signing.md` — webhook receiver는 event_id 기반 dedup 필수 (HMAC 검증 ≠ idempotency)
- `_common/dlq-reprocessing-wal.md` — DLQ replay 시 같은 message 두 번 처리 방지
- `_common/durable-execution.md` — Temporal activity input의 idempotency-key가 retry 안전성 핵심
- `_common/api-migration-replay-traffic.md` — replay traffic 시 dual-backend 처리에 dedup 필수
- `_common/load-shedding-prioritized.md` — 503 + Retry-After 후 caller retry가 idempotent해야 안전
- `java/lang/grpc-service-contracts.md` — gRPC unary call retry는 자연스레 idempotent 가정 — 명시적 보장 필요
