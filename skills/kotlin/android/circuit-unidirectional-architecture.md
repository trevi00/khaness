---
name: circuit-unidirectional-architecture
description: Slack Circuit 0.33+ 단방향 아키텍처 — Screen/Presenter/Ui 분리, Navigator, Compose-runtime 기반 state 관리
keywords: circuit slack screen presenter ui navigator unidirectional udf compose-runtime molecule eventSink
intent: design-screen wire-presenter-ui handle-navigation-result test-presenter migrate-to-jakarta-inject
paths: app/src/main/kotlin
patterns: CircuitContent NavigableCircuitContent Screen Presenter Ui Navigator goTo eventSink
requires: coroutines-flow-viewmodel-and-compose-state-boundaries
phase: plan implement review debug
tech-stack: kotlin
min_score: 2
quality_axes_enforced: true
---

# Slack Circuit — Unidirectional Architecture (0.33+)

> 핵심: Circuit는 Compose 위에서 Screen/Presenter/Ui 3 추상화로 단방향 흐름 강제. **Presenter와 Ui는 직접 접근 불가**, state emit + event 통신만. Compose runtime 기반(Presenter도 compose) — `LaunchedEffect` key 안정성 결정적.

## 의사결정 트리

### IF Circuit 채택 결정 (Plan)
| 신호 | 권장 |
|---|---|
| Compose-first + 단방향 강제 | **Circuit 0.33+** |
| KMP/CMP 공유 가능 | Circuit (Kotlin 2.3.0 + CMP 1.10) |
| MVVM with ViewModel + StateFlow 충분 | 기존 패턴 유지 |
| MVI/Reducer 명시적 분리 필요 | Orbit / MVI-kotlin |

### IF Screen + Presenter + Ui 작성 (Implement)
1. Screen — `@Parcelize data object/class XScreen : Screen` (key)
2. State + Event — sealed로 분리:
```kotlin
data class XState(
  val items: List<Item>,
  val eventSink: (XEvent) -> Unit
) : CircuitUiState
sealed interface XEvent : CircuitUiEvent {
  data class Click(val id: String) : XEvent
}
```
3. Presenter — `present()` 안에서 `LaunchedEffect(stableKey) { ... }`. **stable key**(Screen object, ID) 사용, state 전체 캡처 금지
4. Ui — Compose 함수, eventSink 호출만. business logic 0

### IF Navigation 결정 (Implement)
1. `goTo(screen)` / `pop()` — 단순 push/pop
2. `pop(result = ...)` — 결과 전달 (0.31.0+에서 `AnsweringResultNavigator` / `rememberAnsweringNavigator` 사용)
3. `forward()` / `backward()` (0.33.0+) — 양방향 navigation
4. 0.30 이전 result 패턴 사용 시 **NavigableCircuitContent 외부에서 깨짐** — 마이그레이션 필수

### IF Presenter 테스트 (Implement)
```kotlin
@Test fun loads() = runTest {
  presenter.test {
    awaitItem().eventSink(XEvent.Click("1"))
    awaitItem().items shouldHaveSize 1
  }
}
```
- `awaitItem()`은 **distinct-until-changed** — 동일 state 두 번 emit 시 hang
- `FakeNavigator`로 navigator 호출 검증
- intermediate transition 명시적 assert

### IF KSP1 / kotlinx-immutable 마이그레이션 (Plan)
1. **KSP1 dropped (0.32.0)** — KSP2로 이전 필수
2. **jakarta.inject 전환 (0.32.0)** — `javax.inject.Inject` import는 generated factory에서 깨짐. Hilt 모듈 전수 점검
3. **kotlinx-immutable dropped (0.31.0)** — `ImmutableList` 의존 state는 `@Immutable` data class로 또는 stable collection 직접 제공

## 가이드

- minSdk 23 floor (0.31.0+). 그 이하 프로젝트는 채택 불가.
- CircuitX 확장 — `circuitx-overlays`, `circuitx-gesture-navigation`, `circuitx-effects`.
- Presenter는 Compose runtime이지 UI 아님 — 실수로 Composable UI 호출 금지.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | Presenter ↔ Ui 직접 접근 차단으로 단방향 강제 |
| 성능 효율성 | stable LaunchedEffect key로 불필요한 recomposition 차단 |
| 호환성 | Compose Multiplatform 지원 (Android/iOS/desktop) |
| 사용성 | sealed Event + eventSink로 Ui→Presenter 통신 1방향 |
| 신뢰성 | distinct-until-changed `awaitItem()`으로 테스트 결정성 |
| 보안 | Screen `@Parcelize`로 process death 후 복원 안전 |
| 유지보수성 | Screen/Presenter/Ui 3-파일 분리로 책임 명확 |
| 이식성 | KMP shared module로 iOS/Web 재사용 |
| 확장성 | CircuitX 모듈로 Overlay/GestureNav/Effects 추가 |

## Gotchas

### 0.31.0 result 전달 패턴 깨짐
NavigableCircuitContent **외부**에서 result 받던 코드는 0.31.0에서 동작 안 함. `AnsweringResultNavigator` / `rememberAnsweringNavigator`로 전환.

### Presenter `LaunchedEffect`에 state 전체를 key로 captures
state 변경마다 effect 재시작 → 무한 루프 또는 cancellation 폭주. stable key(Screen, ID)만 capture.

### `awaitItem()` 동일 state 두 번 emit 시 hang
distinct-until-changed 기본. test에서 동일 state 다시 emit하면 timeout. intermediate transition을 다른 state로 명시.

### KSP1 + javax.inject 사용 (0.32.0+에서 깨짐)
0.32.0이 KSP1 drop + jakarta.inject 전환. `javax.inject.Inject`로 import한 generated factory는 컴파일 fail. Hilt 모듈 전수 점검 후 업그레이드.

### kotlinx-immutable `ImmutableList` 의존
0.31.0에서 dependency drop — state class에서 `ImmutableList` 사용 시 stability 깨짐. `@Immutable` data class 또는 ImmutableList를 직접 제공.

## Source

- https://slackhq.github.io/circuit/ — "Circuit is a simple, lightweight, and extensible framework for building Kotlin applications that's Compose from the ground up"; "A Presenter and a Ui cannot directly access each other. They can only communicate through state and event emissions", 조회 2026-05-10
- https://slackhq.github.io/circuit/navigation/ — `goTo(screen)` / `pop()` / `forward()` / `backward()` semantics, 조회 2026-05-10
- https://slackhq.github.io/circuit/testing/ — `Presenter.test`, `FakeNavigator`, `CircuitReceiveTurbine` distinct-until-changed, 조회 2026-05-10
- https://github.com/slackhq/circuit/releases — 0.33.1 (2026-02-20), 0.33.0 forward/backward, 0.32.0 jakarta.inject + KSP1 drop, 조회 2026-05-10
- https://github.com/slackhq/circuit — Compose-driven architecture 설명 + topics(android/kotlin/architecture/udf/mvi/compose), 조회 2026-05-10
