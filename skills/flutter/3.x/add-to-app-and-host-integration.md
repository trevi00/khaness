---
keywords: flutter 3 add-to-app android ios FlutterEngine FlutterFragment FlutterActivity FlutterViewController cached engine pre-warm Java 17 module 호스트 통합 임베딩
intent: flutter add-to-app 호스트앱 임베딩 설계 cached engine pre-warm android FlutterFragment ios FlutterViewController boundary
paths: my_flutter_module/ android/app/ ios/Runner/ .android/ .ios/
patterns: FlutterEngine FlutterEngineCache FlutterFragment FlutterActivity FlutterViewController FlutterEngine() flutter create -t module
requires: flutter
phase: design implement review
tech-stack: flutter
min_score: 3
---

# Flutter 3.x Add-to-App + Host Integration

> 핵심 원칙: **Flutter는 module boundary**다 — 호스트 앱이 navigation/lifecycle/permission을 owns, Flutter는 Dart UI runtime을 owns. cached pre-warmed engine은 first-frame 지연을 줄이는 default.

## 의사결정 트리

### IF native 앱에 Flutter 추가 (Design)
1. **module 형태**:
   - Gradle subproject (Android) / CocoaPods module (iOS)
   - 또는 AAR/xcframework artifact 빌드해서 host에 배포
2. **host 책임**: app launch, signing, native nav, permission, 인증
3. **Flutter 책임**: Dart UI tree, Flutter runtime, asset
4. **engine 전략**:
   - 짧게 1회 등장 → on-demand engine
   - 자주 노출 / 다중 화면 / Dart state persist → **cached pre-warmed engine**
5. **boundary 명시**: 어느 화면이 Flutter? native 라우팅 표에 명시

### IF Android (Implement)
1. project Java 17+ (3.x docs 명시)
2. `flutter.androidPackage`가 host app package와 달라야 함
3. embedding 단위:
   - 전체 화면 → `FlutterActivity`
   - 기존 activity 안 일부 → `FlutterFragment`
4. `.android/` 자동 생성 — VCS 제외
5. cached engine: `FlutterEngineCache`로 pre-warm

### IF iOS (Implement)
1. CocoaPods로 module 통합 또는 xcframework
2. `.ios/` 자동 생성 — 직접 수정 X
3. embedding 단위: `FlutterViewController` (UIKit) / `FlutterViewControllerRepresentable` (SwiftUI)
4. long-lived `FlutterEngine` 보관 — AppDelegate 또는 singleton

### IF host nav과 Flutter route 섞임 (Review)
1. native ↔ Flutter 경계가 platform channel로 명시되었나
2. Flutter 안에서 host로 돌아가는 path (deep link, finish) 존재
3. engine cache lifetime이 명시 (영구 vs scoped)

## Module 생성

```bash
# host 디렉토리 옆에 module 생성
cd /path/to/host_repo
flutter create --template=module --org com.example my_flutter
```

## Android 통합

### Gradle 추가 (settings.gradle)
```gradle
include ':app'
setBinding(new Binding([gradle: this]))
evaluate(new File(
  settingsDir.parentFile,
  'my_flutter/.android/include_flutter.groovy'
))
```

### app `build.gradle`
```gradle
android {
  compileOptions {
    sourceCompatibility JavaVersion.VERSION_17
    targetCompatibility JavaVersion.VERSION_17
  }
  kotlinOptions { jvmTarget = '17' }
}

dependencies {
  implementation project(':flutter')
}
```

### Engine pre-warm + cache
```kotlin
// MyApplication.kt
class MyApplication : Application() {
  override fun onCreate() {
    super.onCreate()
    val engine = FlutterEngine(this)
    engine.dartExecutor.executeDartEntrypoint(
      DartExecutor.DartEntrypoint.createDefault()
    )
    FlutterEngineCache.getInstance().put("main_engine", engine)
  }
}
```

### FlutterActivity (전체 화면)
```kotlin
val intent = FlutterActivity
  .withCachedEngine("main_engine")
  .build(this)
startActivity(intent)
```

### FlutterFragment (부분 임베딩)
```kotlin
class HostActivity : FragmentActivity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    setContentView(R.layout.host)

    val fragment = FlutterFragment
      .withCachedEngine("main_engine")
      .renderMode(RenderMode.surface)
      .transparencyMode(TransparencyMode.opaque)
      .build<FlutterFragment>()

    supportFragmentManager.beginTransaction()
      .replace(R.id.flutter_container, fragment)
      .commit()
  }
}
```

## iOS 통합

### Podfile (host)
```ruby
flutter_application_path = '../my_flutter'
load File.join(flutter_application_path, '.ios', 'Flutter', 'podhelper.rb')

target 'HostApp' do
  use_frameworks!
  install_all_flutter_pods(flutter_application_path)
end
```

### Engine pre-warm (AppDelegate)
```swift
import Flutter
import UIKit
import FlutterPluginRegistrant

@UIApplicationMain
class AppDelegate: FlutterAppDelegate {
  lazy var flutterEngine = FlutterEngine(name: "main_engine")

  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    flutterEngine.run()
    GeneratedPluginRegistrant.register(with: self.flutterEngine)
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }
}
```

### FlutterViewController 노출 (UIKit)
```swift
class HostViewController: UIViewController {
  @IBAction func openFlutter() {
    let appDelegate = UIApplication.shared.delegate as! AppDelegate
    let flutterVC = FlutterViewController(
      engine: appDelegate.flutterEngine,
      nibName: nil, bundle: nil
    )
    present(flutterVC, animated: true)
  }
}
```

### SwiftUI host
```swift
struct FlutterScreen: UIViewControllerRepresentable {
  let engine: FlutterEngine
  func makeUIViewController(context: Context) -> FlutterViewController {
    FlutterViewController(engine: engine, nibName: nil, bundle: nil)
  }
  func updateUIViewController(_ vc: FlutterViewController, context: Context) {}
}
```

## Engine lifetime 선택

| 패턴 | 사용 |
|---|---|
| App-scope cached (default) | 자주 노출, Dart state 유지 |
| 짧은 dialog/scoped | 일회성, 메모리 우선 |
| 다중 engine (FlutterEngineGroup) | 여러 화면 동시 + 메모리 절약 |

## 5축 품질 체크

| 축 | 체크 |
|---|---|
| 정확성 | host nav과 Flutter route 경계가 platform channel로 명시되는가 |
| 안전성 | `.android`/`.ios` 자동 생성 디렉토리가 VCS에서 제외되었는가 |
| 성능 | first-frame 지연 줄이려 cached pre-warmed engine 사용하는가 |
| 가독성 | host가 Flutter implementation detail 안 알고 module API만 쓰는가 |
| 검증성 | engine cache key 일관 / module 빌드가 host CI에서 도는가 |

## Gotchas

### `flutter.androidPackage`가 host app package와 같음
빌드 충돌. module 생성 시 `--org`을 host와 다르게 지정.

### `.android/`, `.ios/` 직접 수정
docs 명시: 자동 생성. 다음 build에 덮임. host는 native side에서 wrapping만.

### engine pre-warm 안 하고 cold open
첫 화면 blank period 길어짐. `FlutterEngineCache.put` (Android) 또는 AppDelegate에서 `engine.run()` (iOS).

### Java 17 미만 host
3.x docs 명시: Java 17+. 기존 host 업그레이드 필요.

### 다중 FlutterActivity 동시 실행 메모리
각각 engine 생성하면 메모리 폭증. cached engine 재사용 또는 `FlutterEngineGroup`.

### iOS Podfile에 `use_frameworks!` 누락
Flutter는 dynamic framework로 통합 → static linking 시 깨짐.

### route 동기화 누락
host에서 다른 native 화면으로 이동했는데 Flutter는 여전히 이전 route. platform channel로 양방향 sync.

### `GeneratedPluginRegistrant` 누락 (iOS)
plugins (firebase, ...) 가 register 안 됨 → 런타임 에러. AppDelegate에서 `register(with: engine)`.

### deep link가 host만 받고 Flutter에 전달 안 됨
host가 Flutter로 어떤 route 열지 platform channel 또는 initial route arg로.

### 호스트 lifecycle와 Flutter binding 동기화 누락
background→foreground에서 stale state. AppLifecycleState 관찰 + restoration scope.

## 도구 사용 패턴 (Harness)
- module 생성 점검: `Read pubspec.yaml` → `module:` 섹션
- Java 17 검증 (Android): `Grep("VERSION_17|jvmTarget", glob="**/build.gradle")`
- engine cache 사용: `Grep("FlutterEngineCache|withCachedEngine", glob="**/*.kt")`
- iOS engine pre-warm: `Grep("FlutterEngine\\(name:", glob="**/*.swift")` — AppDelegate에 있어야
- `.android` VCS 점검: `Read .gitignore` → `.android/` `.ios/` 포함
