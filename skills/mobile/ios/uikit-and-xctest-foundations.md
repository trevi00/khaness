---
name: uikit-and-xctest-foundations
description: iOS UIKit + Core Animation + Foundation + XCTest/XCUITest — UIViewController lifecycle, async test, accessibility identifier, SwiftUI interop
keywords: uikit uiviewcontroller core-animation calayer xctest xcuitest accessibility-identifier auto-layout uihostingcontroller foundation
intent: design-viewcontroller-lifecycle write-async-tests stabilize-xcuitest fix-retain-cycle bridge-swiftui-uikit
paths: ios/Sources ios/Tests
patterns: UIViewController NSLayoutConstraint CALayer XCTestCase XCUIApplication accessibilityIdentifier
requires: swift-concurrency-mainactor-and-cancellation-boundaries
phase: plan implement review debug
tech-stack: swift
min_score: 2
quality_axes_enforced: true
---

# UIKit + XCTest Foundations

> 핵심: UIKit은 **main thread 의존**, Core Animation은 **render server 별도 thread**, Foundation은 thread-agnostic. 이 3 lane 경계를 무시하면 dropped frame과 main-thread block이 동시 발생. XCUITest는 **accessibility identifier** 없으면 i18n에서 즉시 깨짐.

## 의사결정 트리

### IF UIViewController 설계 (Implement)
1. lifecycle 순서 — `loadView` → `viewDidLoad` (1회) → `viewWillAppear` → `viewDidAppear` → `viewWillDisappear` → `viewDidDisappear`
2. **`viewDidLoad`에서 1회 setup** — subview 추가, constraint, target/action
3. `viewWillAppear`마다 — 데이터 새로고침, observer 등록
4. `viewWillDisappear`/`deinit`에서 — observer 해제, timer invalidate (retain cycle 차단)

### IF Auto Layout 설계 (Implement)
1. anchor API 우선 — `subview.leadingAnchor.constraint(equalTo: view.leadingAnchor)`
2. `translatesAutoresizingMaskIntoConstraints = false` 명시 (코드로 추가하는 view)
3. priority — 충돌 시 `UILayoutPriority(750)` 등으로 명시. ambiguous → 런타임 로그 + 결정 비결정성
4. `hasAmbiguousLayout` debugger 호출로 검증

### IF Core Animation 사용 (Implement)
1. `CALayer` properties는 **암시적 animation** — `animationDuration` 안 줘도 0.25s default
2. off-main render — animation 자체는 render server. **CALayer property 변경은 main**
3. `CADisplayLink` — 60/120Hz tick. game loop / scroll-driven animation
4. `CABasicAnimation`은 view tree 안 갱신 — `model layer` 직접 set 또는 `CATransaction` 사용

### IF XCTest 작성 (Implement)
```swift
final class LoginVMTests: XCTestCase {
  func test_login_success() async throws {
    let vm = LoginViewModel(repo: FakeRepo(.success))
    try await vm.submit(email: "a@b", password: "pw")
    XCTAssertFalse(vm.isSubmitting)
  }
}
```
1. `async throws` test method (Xcode 13+, Swift 5.5+)
2. `setUp()` / `tearDown()` async 변종도 사용 가능
3. `XCTestExpectation` + `wait(for:timeout:)` — completion-handler 코드 호환
4. perf — `measure { ... }` block, baseline 비교

### IF XCUITest 작성 (Implement)
1. **모든 인터랙션 element에 `accessibilityIdentifier` 부여** — 절대 localized label 의존 X
2. `let app = XCUIApplication(); app.launch()`
3. query — `app.buttons["loginSubmit"].tap()`. id 기반
4. `XCUIElement.exists`로 비동기 등장 대기 (또는 `waitForExistence(timeout:)`)

### IF UIKit ↔ SwiftUI bridge (Implement)
1. UIKit 안에 SwiftUI view — `UIHostingController(rootView: MyView())`
2. SwiftUI 안에 UIKit — `UIViewControllerRepresentable` 또는 `UIViewRepresentable` 구현
3. lifecycle 차이 인식 — SwiftUI는 declarative, UIKit는 imperative

## 가이드

- delegate는 `weak var delegate: SomeDelegate?` — strong 사용 시 retain cycle.
- main thread block 검출은 Instruments → Time Profiler. `URLSession`/`DispatchQueue.global()`로 offload.
- async/await는 implicit MainActor 아님 — UI 갱신은 `@MainActor` 또는 `MainActor.run { ... }`.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | UIViewController lifecycle 순서 강제로 setup 1회 보장 |
| 성능 효율성 | CADisplayLink로 fps-aligned animation, render server off-main |
| 호환성 | UIHostingController로 SwiftUI 점진 도입 |
| 사용성 | accessibility identifier가 i18n 무관 안정 selector |
| 신뢰성 | weak delegate + observer 해제로 retain cycle 차단 |
| 보안 | URLSession + ATS (TLS 1.2+ 강제) |
| 유지보수성 | XCTestExpectation으로 async 코드 검증 표준화 |
| 이식성 | UIKit/SwiftUI bridge로 단계적 마이그레이션 |
| 확장성 | UIViewControllerRepresentable로 SwiftUI 신규 화면, UIKit 기존 화면 공존 |

## Gotchas

### `accessibilityIdentifier` 누락
XCUITest가 localized label에 의존하면 i18n 즉시 깨짐. 모든 testable element에 명시적 ID 부여.

### delegate를 strong reference로
`var delegate: SomeDelegate?` (weak 누락) → retain cycle, view 안 dealloc. `weak var delegate` 강제.

### Auto Layout ambiguous constraints
런타임 콘솔에 경고만 출력 — 동작은 비결정적. `hasAmbiguousLayout`으로 debugger에서 확인 + priority/contentHugging 명시.

### main thread block (URLSession sync)
synchronous data load 시 dropped frame. async/await + URLSession.shared.data로 offload.

### async/await test에서 `@MainActor` 누락
`async test_...` 안에서 UI assertion 시 thread mismatch 가능. `await MainActor.run { ... }` 또는 test class에 `@MainActor`.

### CABasicAnimation 후 view state 미갱신
animation은 presentation layer만 변경. model layer는 그대로 → 종료 후 원위치 점프. `layer.position = end; addAnimation` 순서 또는 `fillMode/.removedOnCompletion=false` + `CATransaction` 명시.

## Source

- https://developer.apple.com/documentation/uikit/uiviewcontroller — lifecycle methods (loadView/viewDidLoad/viewWillAppear/viewDidAppear/viewWillDisappear/viewDidDisappear), 조회 2026-05-10
- https://developer.apple.com/documentation/uikit/nslayoutconstraint — anchor API, priority, 조회 2026-05-10
- https://developer.apple.com/documentation/quartzcore/calayer — CALayer hierarchy + implicit animation, 조회 2026-05-10
- https://developer.apple.com/documentation/quartzcore/cadisplaylink — frame-aligned tick, 조회 2026-05-10
- https://developer.apple.com/documentation/xctest/xctestcase — `setUp`/`tearDown` (async), `async throws`, `XCTestExpectation`, `measure`, 조회 2026-05-10
- https://developer.apple.com/documentation/xctest/xcuiapplication — `launch()`, query API, 조회 2026-05-10
- https://developer.apple.com/documentation/swiftui/uihostingcontroller — SwiftUI ↔ UIKit bridge, 조회 2026-05-10
- https://developer.apple.com/videos/play/wwdc2015/406/ — UI Testing in Xcode (accessibility identifier 강조), 조회 2026-05-10
