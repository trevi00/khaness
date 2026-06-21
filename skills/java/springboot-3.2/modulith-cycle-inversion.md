---
name: modulith-cycle-inversion
description: Spring Modulith cycle 검출 시 ApplicationEvent 기반 의존 역전 패턴 — facade 회피 + allowedDependencies/NamedInterface 명시
keywords: modulith cycle applicationevent namedinterface alloweddependencies
intent: 끊어 분리 역전 inversion 검출 수정
paths: src/main/java
patterns: ApplicationModule NamedInterface ApplicationEventPublisher
phase: design implement debug
tech-stack: java
min_score: 2
---

# Spring Modulith cycle inversion 패턴

> 핵심 원칙: 도메인 간 직접 호출이 cycle을 만들면 **공유 facade를 만들지 말고 (downstream 도메인의 NamedInterface 의존이 또 cycle을 만듦)** `ApplicationEvent`로 의존 방향을 한쪽 (publisher → listener)으로 단순화한다. 같은 트랜잭션 안에서 동기 publish/listen이면 listener throw 시 publisher도 함께 rollback된다.

## 의사결정 트리

### IF `ApplicationModules.verify()`가 cycle을 검출했을 때 (Debug)
1. 보고서에서 cycle 참여 도메인 목록 추출 (보통 2~3개)
2. 각 도메인 쌍별로 호출 방향 판단:
   - **양방향 호출** → ApplicationEvent inversion (한쪽이 publisher, 다른 쪽이 listener-only)
   - **단방향 + 호출 묶음** → 한쪽 도메인에 NamedInterface facade 노출만으로 해결 (cycle 아님)
3. publisher 측에 `ApplicationEventPublisher` 주입 + `publishEvent(new XxxEvent(...))`. listener 측은 `@EventListener` (또는 `@TransactionalEventListener(BEFORE_COMMIT)` — `AFTER_COMMIT`은 atomicity 깨짐, `outbox-atomicity` 스킬 참조).
4. cycle 끊긴 것 같으면 `./gradlew :<module>:test --tests *ApplicationModulesTest`로 재검증.

### IF Modulith 검증이 통과한 후 NamedInterface 노출 (Implement)
1. 외부 도메인이 import해야 하는 클래스만 `<domain>.api` 또는 `<domain>.<area>.api` 서브패키지에 두기.
2. 해당 서브패키지에 `package-info.java`로 `@NamedInterface("이름")` 선언.
3. 노출 클래스는 interface 또는 record. 구현체는 `<domain>.internal`에 두고 `@Component`로 등록.
4. exception이 wire surface면 별도 NamedInterface `"exception"` 노출 — 5 도메인 한꺼번에 노출하는 경우 hotfix commit으로 묶음 처리.

### IF allowedDependencies 좁히기 (Review)
- [ ] 각 `@ApplicationModule(allowedDependencies = {...})`에 정말 필요한 도메인만 명시
- [ ] testing 모듈은 `allowedDependencies = {}` (다른 도메인 import 0)
- [ ] auth 도메인의 JwtTokenProvider 같은 cross-cutting facade는 도메인별 `allowedDependencies`에 추가 명시 (그러지 않으면 internal class 노출됨)

## ApplicationEvent inversion 예시

### Before (cycle 발생)

```java
// order/internal/OrderService.java
@Service
class OrderService {
    private final NotificationFacade notification;   // notification 도메인 의존

    @Transactional
    public Order create(...) {
        Order o = orderRepository.save(...);
        notification.broadcastOrderCreated(o);   // notification → order 의존 발생 (cycle)
        return o;
    }
}

// notification/internal/NotificationService.java
@Service
class NotificationService {
    private final OrderFacade orderFacade;   // order 도메인 의존 — cycle!
    ...
}
```

### After (inversion)

```java
// order/event/OrderCreatedEvent.java  ← NamedInterface "event"
public record OrderCreatedEvent(UUID orderId, OffsetDateTime createdAt) {}

// order/internal/OrderService.java
@Service
class OrderService {
    private final ApplicationEventPublisher events;   // Spring 빈, 도메인 의존 0

    @Transactional
    public Order create(...) {
        Order o = orderRepository.save(...);
        events.publishEvent(new OrderCreatedEvent(o.getId(), o.getCreatedAt()));
        return o;
    }
}

// notification/internal/OrderEventListener.java
@Component
class OrderEventListener {
    private final WebSocketBroadcaster ws;

    @EventListener
    void on(OrderCreatedEvent e) {
        ws.broadcast(e);   // throw 시 OrderService 트랜잭션도 rollback (동기 publish 기본)
    }
}
```

**효과**:
- notification → order 의존 사라짐 (notification은 event class만 import)
- order → notification 의존 사라짐 (event publish만)
- listener throw가 publisher tx에 propagate → atomicity 유지

## NamedInterface 노출 표준

```
src/main/java/com/app/order/
├── api/                              ← NamedInterface "api"
│   ├── package-info.java             @org.springframework.modulith.NamedInterface("api")
│   ├── OrderFacade.java              public interface
│   └── OrderView.java                public record
├── event/                            ← NamedInterface "event"
│   ├── package-info.java             @NamedInterface("event")
│   └── OrderCreatedEvent.java
├── exception/                        ← NamedInterface "exception"
│   ├── package-info.java             @NamedInterface("exception")
│   └── OrderNotFoundException.java
├── internal/                         ← 외부 접근 금지 (Modulith가 enforce)
│   ├── OrderService.java
│   └── OrderRepository.java
└── web/                              ← 같은 모듈 안의 controller (외부 노출 X)
    └── OrderController.java
```

`package-info.java` 형식:
```java
@org.springframework.modulith.NamedInterface("api")
package com.app.order.api;
```

## Gotchas

### Facade로 cycle 해결 시도 → 더 깊은 cycle 생성
A도메인이 B도메인을 호출, B도 A를 호출 → "공통 C facade를 만들자"로 가면 A/B 모두 C 의존 + C가 결국 A/B internal을 사용 → A→C→A 3-hop cycle. 같은 함정 example_project Stage 15-2에서 발견 — facade 안티패턴.

### `@TransactionalEventListener(AFTER_COMMIT)`로 inversion하면 atomicity 깨짐
`AFTER_COMMIT`은 publisher 트랜잭션이 commit된 **후** listener 실행. listener fail해도 publisher rollback 안 됨 → 영구 이벤트 누락. cycle inversion에는 기본 `@EventListener` (동기 publish) 사용. outbox 경로면 publisher가 같은 tx에서 outbox INSERT (`outbox-atomicity` 스킬 참조).

### `allowedDependencies = {}` 비어있어도 Spring 인프라 빈은 OK
`ApplicationEventPublisher`, `ObjectMapper`, `Clock` 등 `org.springframework.*` 빈은 도메인 의존이 아니라 인프라 의존 → `allowedDependencies` 명시 불필요. 도메인 의존만 명시.

### testing 모듈에서 다른 도메인 import 1줄로 모든 cycle 검증 무효화
e2e용 SignalController에서 `OrderService` 직접 호출하면 testing → order 의존 추가됨. testing 모듈은 항상 `allowedDependencies = {}` + 실 호출은 HTTP REST로만.

### Modulith `@ApplicationModule(displayName="...")`의 검증 범위 오해
verify()는 `@ApplicationModule` 어노테이션이 붙은 `package-info.java`가 있는 패키지만 모듈로 인식. `package-info.java` 안 만들면 그 패키지는 "다른 모듈에서 마음대로 import 가능"으로 잡혀 cycle 검출이 약해짐. 새 도메인 추가 시 `package-info.java` 먼저.

### Modulith `Documenter`가 시각화하는 cycle은 메서드 호출만, event는 점선
event publish 기반 의존은 dependency graph에 **점선**으로 표시. cycle 검출에서 점선은 cycle로 안 셈 — 그래서 inversion이 통하는 것. NamedInterface 직접 import는 실선 → cycle.

### exception 클래스를 internal에 두면 GlobalExceptionHandler에서 import 불가
hq-server R-2 hotfix 학습: 5개 도메인의 exception을 동시에 `@NamedInterface("exception")`로 노출 + GlobalExceptionHandler는 `@RestControllerAdvice` 모듈에 두기. exception NamedInterface는 5축에서 안정/사용 게이트라 일괄 노출이 정당.
