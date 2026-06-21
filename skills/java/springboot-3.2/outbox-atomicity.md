---
name: outbox-atomicity
description: Outbox 패턴에서 도메인 commit과 outbox INSERT가 같은 트랜잭션에 있어야 하는 이유 + AFTER_COMMIT 안티패턴 식별
keywords: outbox atomicity transactional aftercommit listener event
intent: 추가 분리 inversion 변경 보장
paths: src/main/java
patterns: TransactionalEventListener AFTER_COMMIT outbox
phase: design implement debug
tech-stack: java
requires: modulith-cycle-inversion
min_score: 2
---

# Outbox 트랜잭션 원자성 패턴

> 핵심 원칙: outbox는 "도메인 상태 변경"과 같은 RDBMS 트랜잭션 안에 있어야 그 의미를 갖는다. 도메인 commit 후 outbox INSERT 시도하는 모든 구조 (`AFTER_COMMIT` listener, `@Async` listener, scheduled side-channel) 는 **outbox 누락 시 영구 데이터 손실** 위험을 만든다. modulith cycle 끊기 위해 outbox을 listener로 빼고 싶은 유혹을 거부하라.

## 의사결정 트리

### IF 새 outbox 도입 (Design)
1. outbox 테이블 컬럼: `id`, `aggregate_type`, `aggregate_id`, `event_type`, `payload(JSON)`, `created_at`, `sent_at` (nullable), `status` (`PENDING/SENT/FAILED`), `retry_count`
2. 도메인 service에 `OutboxAppender` 빈 주입 (NamedInterface로 노출). service `@Transactional` 메서드 안에서 도메인 save + `outboxAppender.append(...)` 같은 줄에.
3. publisher (외부 시스템으로 전송하는 컴포넌트)는 별도 `@Scheduled` polling worker. PENDING → 전송 → SENT 마킹. **service와 publisher는 다른 트랜잭션.**
4. **DON'T**: `@TransactionalEventListener(phase = AFTER_COMMIT)`로 outbox 분리. 이유 §Gotchas.

### IF 기존 코드에서 atomicity 위반 의심 (Debug)
1. outbox INSERT가 service tx 바깥에 있는지 grep:
   - `@TransactionalEventListener` 사용 + `outbox.append`
   - `@Async` + `outbox.append`
   - `@Scheduled` polling으로 도메인 테이블 읽어서 outbox 채우는 backfill 패턴 (가장 위험)
2. 발견되면 **service same-tx로 회수** — listener는 broadcast/notify만 남기기.
3. 회귀 테스트: service 메서드 + intentional listener throw → 도메인 row와 outbox row가 **동시에 rollback**되는지 검증.

### IF outbox 패턴 검수 (Review)
- [ ] 도메인 save + outbox append가 같은 `@Transactional` 메서드 안에 있다
- [ ] AFTER_COMMIT 사용처는 broadcast/notify 같은 fire-and-forget 사이드 효과만
- [ ] publisher worker가 outbox.status 갱신 시 `@Transactional` 부착 + `OPTIMISTIC_LOCK` 또는 `WHERE status='PENDING'` guard
- [ ] outbox payload는 immutable record로 직렬화 (consumer 측 schema evolution 고려)

## R-2.1 회수 패턴 (example_project 학습)

### Before (AFTER_COMMIT 안티패턴 — atomicity 위반)

```java
// order/internal/OrderService.java
@Service
class OrderService {
    @Transactional
    public Order create(...) {
        Order o = orderRepository.save(...);
        events.publishEvent(new OrderCreatedEvent(o.getId()));
        return o;
        // tx commit 시점에 OrderCreatedEvent fired → listener가 outbox INSERT 시도
    }
}

// notification/internal/OrderEventListener.java
@Component
class OrderEventListener {
    private final OutboxAppender outbox;

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    void on(OrderCreatedEvent e) {
        outbox.append("order.created", e);   // 별도 tx — INSERT fail해도 order는 이미 commit됨!
    }
}
```

**문제**: order 테이블에 row가 commit된 **다음** outbox INSERT가 시도됨. 그 사이 DB connection 끊김 / outbox table full / appender code throw 모두 영구 누락. consumer는 "주문 #N 접수됨" 통지 영원히 못 받음.

### After (service same-tx 회수)

```java
// order/internal/OrderService.java
@Service
class OrderService {
    private final OutboxAppender outbox;
    private final ApplicationEventPublisher events;

    @Transactional
    public Order create(...) {
        Order o = orderRepository.save(...);
        outbox.append("order.created", new OrderCreatedPayload(o.getId(), ...));   // same tx
        events.publishEvent(new OrderCreatedEvent(o.getId()));   // listener는 broadcast만
        return o;
    }
}

// notification/internal/OrderEventListener.java
@Component
class OrderEventListener {
    private final WebSocketBroadcaster ws;

    @EventListener   // 기본 동기 publish — broadcast만
    void on(OrderCreatedEvent e) {
        ws.broadcast(e);   // throw해도 outbox는 이미 same tx에서 안전
    }
}
```

**효과**: order INSERT, outbox INSERT, listener broadcast 시도가 **하나의 트랜잭션**. 어디서든 fail하면 모두 rollback → 일관성 유지.

## Scheduler/Poller `@Transactional` 함정

R-2.2 학습: `@Scheduled` 메서드는 default로 **@Transactional 없음**. 메서드 안에서 entity를 `findById`로 가져와 setter 호출만 하면 detached 상태에서 변경 → flush 안 됨.

```java
@Component
class HeartbeatScheduler {
    @Scheduled(fixedDelay = 30_000)
    @Transactional   // 빼먹으면 license.updateStatus가 영구 silent loss
    void poll() {
        License lic = licenseRepository.findActive();
        lic.updateStatus(SUSPENDED, "..." );   // tx 없이는 더티 체킹 안 됨
    }
}
```

scheduler/poller에서 entity 변경하면 무조건 `@Transactional` 부착. read-only면 `@Transactional(readOnly = true)`.

## Gotchas

### "Modulith cycle 끊으려면 outbox를 listener로 빼야 한다"는 거짓 명제
cycle은 ApplicationEvent inversion으로 끊는다 (`modulith-cycle-inversion` 스킬). outbox는 도메인 same-tx에 둔다. 두 문제는 분리.

### `@Transactional(propagation = REQUIRES_NEW)`로 outbox 분리
새 tx에서 outbox INSERT → 도메인 tx가 rollback되어도 outbox row는 commit됨 → 발생 안 한 이벤트가 publish됨. atomicity 정반대 방향으로 깨짐.

### outbox publisher worker가 이벤트를 두 번 보내는 함정
worker가 PENDING row 가져와서 외부 전송 후 SENT 마킹 → 마킹 전에 worker crash → 다음 cycle에서 같은 row 다시 PENDING으로 보임 → 중복 전송. 외부 시스템에 `event_id` (idempotency key) 전달 + consumer 측에서 dedup 책임. 또는 worker에 `PESSIMISTIC_LOCK` + `processed_at` 컬럼.

### outbox payload에 JPA entity 직접 넣기
lazy collection이 직렬화 시점에 LazyInitializationException 또는 의도치 않은 전체 그래프 직렬화. payload는 항상 immutable record / DTO. entity는 절대 outbox에 넣지 않음.

### outbox INSERT 실패가 service tx를 fail시키는 게 "맞다"
사용자 입장에서 "주문 접수 200 OK 받았는데 통지가 안 온" 상태는 outbox 누락 시 영구 미감지. INSERT fail로 사용자가 500 받고 retry하는 게 "조용한 누락"보다 1000배 낫다 — 5축 안정 게이트.

### `@TransactionalEventListener(BEFORE_COMMIT)`로는 회피 가능하지만 권장 X
`BEFORE_COMMIT` listener throw는 tx rollback. 동작은 맞지만 의도가 불명확 (event listener의 본래 역할은 "이미 일어난 일에 반응"). same-tx에 직접 호출이 가독성 + 디버깅성 우월.

### testing에서 outbox row count로 atomicity 검증
happy path: service 호출 → order + outbox 둘 다 1개씩 증가. rollback path: service 안에서 의도적 throw (e.g. validation fail) → order 0 + outbox 0. catchup queue 검증 X (AFTER_COMMIT listener는 다른 tx라 catchup 시점이 들쭉날쭉).
