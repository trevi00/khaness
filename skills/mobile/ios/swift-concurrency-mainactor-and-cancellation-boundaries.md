---
name: swift-concurrency-mainactor-and-cancellation-boundaries
description: Swift Concurrency(async/await)에서 actor 격리, @MainActor 경계, Task 취소 계약을 라인 코드로 강제.
keywords: swift concurrency async await task taskgroup mainactor actor sendable cancellation isolation structured-concurrency continuation withCheckedContinuation TaskCancelledError ios swiftui scene 동시성 메인액터 취소
intent: 만들어 추가해 구현해 호출해 격리해 수정해
paths: Sources/ App/ ios/Runner/ Tests/
patterns: async await Task TaskGroup MainActor actor Sendable nonisolated AsyncSequence AsyncStream withTaskCancellationHandler Task.checkCancellation withCheckedThrowingContinuation @StateObject @Observable @Environment Scene SceneDelegate
requires:
phase: plan implement review debug
tech-stack: ios
min_score: 2
---

# Swift Concurrency — MainActor & Cancellation Boundaries

Swift Concurrency는 **actor 격리(isolation)**, **@MainActor 경계**, **Task 취소(cancellation)** 세 축의 계약 구조다. UI 멈춤, race, "왜 결과가 화면에 안 반영되지?" 버그의 90%는 이 세 축 중 하나의 경계가 모호해서 발생한다. 이 스킬은 그 경계를 라인 단위로 강제한다.

## 의사결정 트리

### IF UI 코드 작성 (Plan / Implement)
1. **모든 ViewModel/UI 클래스는 `@MainActor`**. SwiftUI `View`의 body는 자동 MainActor — 그 안에서 호출되는 ViewModel 메서드도 MainActor로 격리해야 hop 비용 + race 방지.
2. UIKit ViewController도 `@MainActor` 명시. (대부분 자동 추론되지만 명시가 안전.)
3. Background 작업 → `Task.detached` 또는 `nonisolated` actor 메서드. 결과를 UI에 반영하려면 명시적 `await MainActor.run { ... }` 또는 `@MainActor` 메서드 호출.

### IF actor 정의 (Implement)
1. **mutable 상태 + 멀티 task 접근** → `actor` 사용. 자동 직렬화로 race 방지.
2. **immutable 함수만** → 일반 `struct`/`class`. actor 오버헤드 불필요.
3. **UI 노출용** → `@MainActor` class. actor와 다름 — actor는 isolation, MainActor는 main thread 강제.
4. actor의 nonisolated 메서드는 mutable state 접근 금지 (compile error). pure 함수만.

### IF Task 시작 (Implement)
1. **lifetime이 명확한 곳에서만 시작** — SwiftUI의 `.task { ... }` modifier가 view lifetime에 묶여 가장 안전.
2. **결과가 await로 받아야 하면 `Task { ... }`**, 결과 무시 가능하면 `Task.detached` (parent context 안 상속).
3. **UI 코드에서 `Task.detached` 신중히** — MainActor 격리 깨짐, 경고 다수.
4. parent task가 cancel되면 자식 자동 cancel — 구조적 동시성. detached는 이걸 깨므로 신중.

### IF 취소 처리 (Implement)
1. **장기 루프**: `try Task.checkCancellation()` 호출 — cancel 시 throw.
2. **suspend point 없는 CPU loop** → 취소 무시됨. `await Task.yield()` 또는 명시적 checkCancellation 삽입.
3. **콜백 기반 API 래핑** → `withTaskCancellationHandler { ... } onCancel: { ... }`.
4. **CancellationError catch 후 재throw** — Swift는 Kotlin과 달리 `try`로 명시적이라 흡수 위험은 적지만 `catch { }`에서 일반 처리하면 cancel 의미 잃음.

### IF callback API → async 브리지 (Implement)
1. `withCheckedContinuation` (no throws) / `withCheckedThrowingContinuation` (throws).
2. **continuation은 정확히 1번만 resume** — 0번 = leak (영원히 대기), 2번 = crash.
3. cancellation 지원하려면 `withTaskCancellationHandler`로 감싸 cancel 시 콜백 invalidate.

### IF Sendable 경계 (Implement)
1. actor 또는 task 경계로 넘기는 타입은 `Sendable` 필수.
2. struct + immutable property → 자동 Sendable.
3. class는 `final class ... : Sendable` + immutable property 또는 `@unchecked Sendable` (수동 동기화 책임).
4. closure는 `@Sendable` — capture가 모두 Sendable이어야 함.

### IF Scene/Lifecycle 경계 (Implement, iOS 13+)
1. SceneDelegate 또는 SwiftUI `Scene`에서 lifecycle 작업 시작/정리.
2. `.task(id:) { }` modifier — id 변경 시 task 재시작. id가 안정적인지 확인.
3. background → foreground 전환 시 `@Environment(\.scenePhase)` 관찰.
4. URL scheme / Universal Link 진입 시 auth 게이트 통과 후 navigation.

### IF 코드 리뷰 (Review)
- [ ] ViewModel/UI 클래스에 @MainActor 명시
- [ ] actor 사용 시 mutable state 접근이 격리 안에 있음
- [ ] Task 시작 위치가 lifetime 명확 (`.task` modifier 또는 명시 owner)
- [ ] 장기 루프에 `try Task.checkCancellation()` 또는 `Task.yield()`
- [ ] continuation은 정확히 1번 resume — 모든 분기 검증
- [ ] task 경계로 넘기는 타입이 Sendable
- [ ] `Task.detached`가 정말 필요해서 사용했는가
- [ ] async 함수 안에서 강제 동기 작업(Thread.sleep, DispatchSemaphore) 없음

## 핵심 패턴

### MainActor ViewModel + Task
```swift
@MainActor
final class CartViewModel: ObservableObject {
    @Published private(set) var state: CartState = .loading
    private let repo: CartRepository
    private var task: Task<Void, Never>?

    init(repo: CartRepository) { self.repo = repo }

    func load() {
        task?.cancel()
        task = Task {
            do {
                let cart = try await repo.fetchCart()      // suspend
                self.state = .ready(cart)                  // MainActor 격리
            } catch is CancellationError {
                // 정상 — view 떠남
            } catch {
                self.state = .error(error.localizedDescription)
            }
        }
    }

    deinit { task?.cancel() }
}
```

### SwiftUI `.task` modifier (가장 안전한 lifetime)
```swift
struct CartView: View {
    @StateObject private var viewModel: CartViewModel

    var body: some View {
        content
            .task {                                        // view 등장~사라짐 까지
                await viewModel.observeUpdates()
            }
            .task(id: viewModel.cartId) {                  // cartId 변경 시 재시작
                await viewModel.refresh()
            }
    }
}
```

### Actor — 동시 접근 직렬화
```swift
actor CartCache {
    private var entries: [String: Cart] = [:]

    func store(_ cart: Cart, for key: String) {
        entries[key] = cart
    }

    func cart(for key: String) -> Cart? {
        entries[key]
    }

    nonisolated func cacheKey(for userId: String) -> String {
        "cart:\(userId)"                                   // pure — actor 격리 불필요
    }
}
```

### Task 취소 + checkCancellation
```swift
func processLargeFile(at url: URL) async throws -> Result {
    var lines: [String] = []
    for try await line in url.lines {
        try Task.checkCancellation()                       // cancel 시 throw
        lines.append(transform(line))
    }
    return Result(lines: lines)
}
```

### Continuation으로 callback 브리지
```swift
func locationOnce() async throws -> CLLocation {
    try await withCheckedThrowingContinuation { (cont: CheckedContinuation<CLLocation, Error>) in
        let manager = CLLocationManager()
        let delegate = LocationOnceDelegate { result in
            switch result {
            case .success(let loc): cont.resume(returning: loc)
            case .failure(let err): cont.resume(throwing: err)
            }
        }
        manager.delegate = delegate
        manager.requestLocation()
    }
}
```

### withTaskCancellationHandler (취소 시 cleanup)
```swift
func streamPayments() async throws -> [Payment] {
    let handle = api.openPaymentStream()
    return try await withTaskCancellationHandler {
        try await handle.collect()
    } onCancel: {
        handle.close()                                     // cancel 시 즉시 정리
    }
}
```

### TaskGroup — 병렬 결과 합산
```swift
func loadDashboard() async throws -> Dashboard {
    try await withThrowingTaskGroup(of: Section.self) { group in
        group.addTask { try await loadOrders() }
        group.addTask { try await loadStats() }
        var sections: [Section] = []
        for try await section in group {
            sections.append(section)
        }
        return Dashboard(sections: sections)
    }
}
```

## Gotchas

### `@MainActor` 누락된 ViewModel
SwiftUI `View.body`에서 호출하면 자동 hop이 추가되거나 (성능) 컴파일 경고. 모든 UI-facing 클래스에 `@MainActor` 명시.

### `Task { }` 안에서 self capture로 retain cycle
ViewModel deinit 안 됨 → 누수. `[weak self]` capture 또는 view lifetime에 묶인 `.task` modifier 사용.

### `Task.detached` 무지성 사용
parent context 무시 → cancellation 안 전파, MainActor 격리 깨짐. **결과를 UI에 반영하면 detached 쓰지 말 것.**

### `try Task.checkCancellation()` 누락
cancel 호출해도 루프 영원히 진행. CPU loop / 긴 데이터 변환에 명시적 check.

### continuation resume 누락
`withCheckedContinuation` 안의 callback에서 모든 분기에 resume — error 분기에 resume 빼먹으면 영원히 await 대기.

### continuation 2회 resume → crash
같은 callback이 두 번 호출될 수 있는 API → continuation도 두 번 resume → fatal. flag로 1회 보장 또는 `Unsafe*Continuation` 회피.

### actor 메서드를 외부에서 sync 호출 시도
`actor.method()` → 항상 `await` 필요. await 빠뜨리면 컴파일 에러.

### `nonisolated` 메서드에서 actor 상태 접근
컴파일 에러. nonisolated는 immutable / 외부 입력만 사용.

### Sendable 위반 경고 무시
class를 task 경계로 넘기면 race 가능. final class + immutable property 또는 actor로 감쌈.

### `DispatchQueue.main.async`를 async 함수 안에서 사용
Swift Concurrency 모델 깨짐 — `await MainActor.run { ... }` 또는 `@MainActor` 메서드.

### `Thread.sleep`을 async 함수에서 사용
스레드 블로킹 → 다른 task가 그 스레드 못 씀. `try await Task.sleep(for: .seconds(1))`.

### `.task { }` modifier 안에서 무한 루프 + 취소 미고려
view 사라져 task가 cancel돼도 루프가 안 끝남. `try Task.checkCancellation()` 또는 자연스러운 await.

### URL scheme / Universal Link 진입 → auth 우회
받은 URL을 검증 없이 deep navigation → 권한 우회. auth gate 통과 후 화면 결정. 받은 파라미터는 untrusted.

## 검증 체크리스트

- ViewModel/UI 클래스에 @MainActor 명시
- 모든 mutable state가 actor 또는 MainActor 안
- Task 시작 위치가 lifetime 명확
- 장기 loop에 checkCancellation 또는 yield
- continuation 모든 분기에서 정확히 1회 resume
- task 경계 type이 Sendable 적합
- Task.detached 사용처가 의도적
- async 함수에 동기 블로킹 (Thread.sleep, semaphore) 없음
- URL scheme/Universal Link 진입에 auth gate

## 5축 자가 평가

- 검색성: swift / concurrency / async / await / actor / mainactor / 한·영 키워드
- 의사결정 트리(IF/THEN): 7개 IF + 8개 리뷰 체크
- 코드 식별자: @MainActor, actor, nonisolated, Sendable, Task, TaskGroup, withTaskCancellationHandler, Task.checkCancellation, withCheckedThrowingContinuation, AsyncSequence, .task(id:), @StateObject, @Environment(\.scenePhase)
- Gotcha-driven: 13개 흔한 실수 + 회피
- 검증 가능: 9개 체크리스트
