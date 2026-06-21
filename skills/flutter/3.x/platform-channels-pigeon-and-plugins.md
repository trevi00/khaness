---
keywords: flutter 3 method channel pigeon platform channel federated plugin TaskQueue main thread Android iOS Kotlin Swift endorsed default_package implements 플랫폼 채널 피전 페더레이티드
intent: flutter 네이티브 boundary 설계 MethodChannel vs Pigeon 결정 federated plugin endorsement default_package threading TaskQueue 패턴
paths: lib/src/services/ android/ ios/ pigeons/ plugins/
patterns: MethodChannel invokeMethod Pigeon @HostApi @FlutterApi BasicMessageChannel TaskQueue setMethodCallHandler default_package implements
requires: flutter
phase: design implement review
tech-stack: flutter
min_score: 3
---

# Flutter 3.x Platform Channels, Pigeon + Federated Plugins

> 핵심 원칙: **native 통합은 boundary 설계 문제다.** payload 작고 1-2 method면 `MethodChannel`, 계약이 길게 살고 type 안전 필요면 `Pigeon`. plugin이 여러 platform owner면 federated 분리.

## 의사결정 트리

### IF native API 호출 필요 (Design)
1. **payload 크기 / 메서드 수**:
   - primitive 1-2개, method 1-2개 → `MethodChannel`
   - nested type, optional 많음, 양방향 콜백 → `Pigeon`
2. **threading**:
   - platform → Flutter 호출은 **main thread 강제**
   - native handler를 background로 → host에서 `TaskQueue` 명시
3. **scope**: 한 channel당 한 integration concern (battery, files, analytics 따로)
4. **이름**: 도메인 prefix로 unique (`com.example.app/battery`)

### IF channel boundary가 큼 (Implement)
**Pigeon 전환 신호**:
- argument map 파싱이 review noise
- Android/iOS host가 같은 API contract 유지해야 함
- callback direction이 양방향
- field 추가/제거가 잦음

### IF plugin이 여러 platform owner (Design — Federated)
1. **package 분리**:
   - app-facing (`my_plugin`) — 사용자가 import
   - platform interface (`my_plugin_platform_interface`)
   - platform impls (`my_plugin_android`, `my_plugin_ios`, ...)
2. **endorsement**:
   - first-party 정식 지원 → endorsed (`default_package`로 자동 선택)
   - vendor-specific / experimental → non-endorsed (사용자가 명시 추가)
3. native 코드 owner를 package boundary로 reflect

## MethodChannel 기본

### Dart side
```dart
import 'package:flutter/services.dart';

class DeviceService {
  static const _channel = MethodChannel('com.example.app/device');

  Future<int?> getBatteryLevel() async {
    try {
      return await _channel.invokeMethod<int>('getBatteryLevel');
    } on PlatformException catch (e) {
      throw DeviceException(e.code, e.message);
    }
  }
}
```

### Android (Kotlin) host
```kotlin
class DevicePlugin : FlutterPlugin, MethodCallHandler {
  private lateinit var channel: MethodChannel

  override fun onAttachedToEngine(binding: FlutterPlugin.FlutterPluginBinding) {
    val taskQueue = binding.binaryMessenger.makeBackgroundTaskQueue()
    channel = MethodChannel(
      binding.binaryMessenger,
      "com.example.app/device",
      StandardMethodCodec.INSTANCE,
      taskQueue,        // background thread로 handler 처리
    )
    channel.setMethodCallHandler(this)
  }

  override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
    when (call.method) {
      "getBatteryLevel" -> result.success(getBatteryLevelImpl())
      else -> result.notImplemented()
    }
  }

  override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {
    channel.setMethodCallHandler(null)
  }
}
```

### iOS (Swift) host
```swift
public class DevicePlugin: NSObject, FlutterPlugin {
  public static func register(with registrar: FlutterPluginRegistrar) {
    let channel = FlutterMethodChannel(
      name: "com.example.app/device",
      binaryMessenger: registrar.messenger()
    )
    let instance = DevicePlugin()
    registrar.addMethodCallDelegate(instance, channel: channel)
  }

  public func handle(_ call: FlutterMethodCall, result: @escaping FlutterResult) {
    switch call.method {
    case "getBatteryLevel":
      result(getBatteryLevelImpl())
    default:
      result(FlutterMethodNotImplemented)
    }
  }
}
```

## Pigeon — type-safe contract

### 정의 (`pigeons/messages.dart`)
```dart
import 'package:pigeon/pigeon.dart';

@ConfigurePigeon(PigeonOptions(
  dartOut: 'lib/src/messages.g.dart',
  kotlinOut: 'android/src/main/kotlin/.../Messages.g.kt',
  kotlinOptions: KotlinOptions(package: 'com.example.app'),
  swiftOut: 'ios/Classes/Messages.g.swift',
))
class DeviceInfo {
  String? model;
  int? batteryLevel;
  bool? charging;
}

@HostApi()
abstract class DeviceHostApi {
  @async
  DeviceInfo getDeviceInfo();
  void setBrightness(double level);
}

@FlutterApi()
abstract class DeviceFlutterApi {
  void onBatteryChanged(int level);
}
```

### 생성
```bash
dart run pigeon --input pigeons/messages.dart
```

### 사용
```dart
// Dart
final api = DeviceHostApi();
final info = await api.getDeviceInfo();    // type-safe
```

```kotlin
// Android
class DeviceHostImpl : DeviceHostApi {
  override fun getDeviceInfo(callback: (Result<DeviceInfo>) -> Unit) {
    val info = DeviceInfo(
      model = Build.MODEL,
      batteryLevel = batteryLevel(),
      charging = isCharging(),
    )
    callback(Result.success(info))
  }
  override fun setBrightness(level: Double) { /* ... */ }
}
```

## Federated plugin layout

```
my_plugin/                        ← app-facing
├── lib/my_plugin.dart
├── pubspec.yaml
│   dependencies:
│     my_plugin_platform_interface: ^1.0.0
│     my_plugin_android:            ^1.0.0   # endorsed
│     my_plugin_ios:                ^1.0.0   # endorsed
│   flutter:
│     plugin:
│       platforms:
│         android: { default_package: my_plugin_android }
│         ios:     { default_package: my_plugin_ios }

my_plugin_platform_interface/     ← shared API contract
├── lib/my_plugin_platform_interface.dart
└── lib/method_channel_my_plugin.dart

my_plugin_android/                ← Android impl
├── pubspec.yaml
│   flutter:
│     plugin:
│       implements: my_plugin
│       platforms:
│         android: { package: ..., pluginClass: ..., dartPluginClass: ... }
└── android/...

my_plugin_ios/                    ← iOS impl
├── pubspec.yaml
│   flutter:
│     plugin:
│       implements: my_plugin
│       platforms:
│         ios: { pluginClass: ..., dartPluginClass: ... }
└── ios/...
```

### Endorsement rule
- **endorsed**: app-facing pubspec에서 `default_package`로 명시 → 사용자 자동 선택
- **non-endorsed**: 사용자가 자기 앱 pubspec에 따로 `my_plugin_vendor: ...` 추가

## Threading 규칙

| 방향 | 스레드 |
|---|---|
| Flutter → host (invokeMethod) | host main thread (default), background는 `TaskQueue` 등록 시 |
| host → Flutter (invokeMethod from host) | **반드시 host main thread**에서 호출 |
| 메시지 자체 | async by design |

```kotlin
// Kotlin: background thread로 handler
val taskQueue = binding.binaryMessenger.makeBackgroundTaskQueue()
val channel = MethodChannel(binding.binaryMessenger, name, StandardMethodCodec.INSTANCE, taskQueue)

// host → Flutter는 main thread로
Handler(Looper.getMainLooper()).post {
  channel.invokeMethod("onEvent", payload)
}
```

## 5축 품질 체크

| 축 | 체크 |
|---|---|
| 정확성 | channel name이 unique + 도메인 prefix인가 |
| 안전성 | host → Flutter 호출이 main thread인가 |
| 성능 | 무거운 native 처리가 TaskQueue로 background 분리됐는가 |
| 가독성 | 큰 contract면 Pigeon 전환했는가 (loose map 파싱 X) |
| 검증성 | Dart unit + integration test + native unit test 모두 있는가 |

## Gotchas

### channel name 충돌
`battery`만 쓰면 다른 plugin과 충돌. 항상 `com.example.app/battery` 도메인 prefix.

### host → Flutter 호출이 background thread에서
Flutter 측 receiver가 깨짐. 항상 main thread post로 wrap.

### Pigeon 생성 코드를 직접 수정
다음 generation에 사라짐. `*.g.dart`/`*.g.kt`는 read-only로 취급, 변경은 `pigeons/messages.dart` 통해.

### MethodChannel argument key 오타
silent fail 또는 `notImplemented`. Pigeon으로 바꾸면 컴파일 시점에 잡힘.

### federated plugin에서 `implements:` 누락
platform impl이 자동 매칭 안 됨. pubspec의 `flutter.plugin.implements: my_plugin` 필수.

### `default_package` 없이 endorsed처럼 작동 기대
사용자 앱에서 별도 추가해야 함. UX 망가짐. endorsed면 default_package 명시.

### TaskQueue 없이 무거운 native 처리
main thread 블로킹 → ANR. `makeBackgroundTaskQueue()` + 무거운 작업 거기로.

### plugin Dart-only test로 native 검증한 셈치기
Dart unit/widget은 native 안 로드. integration test 또는 native test 필수.

### 큰 nested map을 MethodChannel로 주고받기
review noise + 양 host 사이 type drift. Pigeon으로.

### Flutter side가 native 구현 detail을 안다
`getInternalAndroidServiceImpl()` 같은 leaky 이름. Flutter API는 capability 단위 (`getBatteryLevel`).

## 도구 사용 패턴 (Harness)
- channel name 검사: `Grep("MethodChannel\\(['\"]([^'\"]+)", glob="**/*.{dart,kt,swift}")` → 도메인 prefix 확인
- generated 수정 방지: `Grep("Pigeon.+autogenerated", glob="**/*.g.{dart,kt,swift}")` 후 git history 점검
- TaskQueue 사용처: `Grep("makeBackgroundTaskQueue", glob="**/*.kt")` — 무거운 plugin은 가져야
- federated implements: `Grep("implements:", glob="**/pubspec.yaml")` — platform impl이 명시했나
- Pigeon 전환 신호: `Grep("invokeMethod\\(['\"][^'\"]+['\"]\\s*,\\s*\\{", glob="**/*.dart")` — large arg map 호출
