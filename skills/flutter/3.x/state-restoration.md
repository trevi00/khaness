---
keywords: flutter 3 state restoration restorationScopeId restorationId RestorableProperty restorablePush RootRestorationScope MaterialApp android process death iOS NSCoder 상태 복원 라우트
intent: flutter 상태복원 설계 restorationScopeId restorationId 부착 restorable navigation 적용 ephemeral state 한정
paths: lib/ ios/Runner/ android/app/src/main/
patterns: restorationScopeId restorationId RestorationMixin RestorableInt restorablePush MaterialApp.restorationScopeId
restorationBucket
requires: flutter
phase: design implement review
tech-stack: flutter
min_score: 3
---

# Flutter 3.x State Restoration: Scope, Route Replay + Restorable Navigation

> 핵심 원칙: **상태 복원은 storage 호출이 아니라 scope 설계 문제다.** `restorationScopeId`는 새 bucket을 만들고, `restorationId`는 surrounding bucket에 저장한다. ephemeral UI state만 — 영구 데이터는 별도 storage.

## 의사결정 트리

### IF 상태 복원 도입 (Design)
1. **target 결정**: 어떤 사용자 흐름이 process death 후 살아나야 하나?
   - 폼 입력 (email/text field) — 흔함
   - 스크롤 위치 — 흔함
   - 탭 인덱스 / 라우트 스택 — 흔함
   - 영구 비즈니스 데이터 → **여기에 두지 말 것** (Hive/Isar/SQLite)
2. **app-level scope**: `MaterialApp.restorationScopeId = 'root'`
3. **navigation**: `Navigator.push` → `Navigator.restorablePush`
4. **widget-level**: 지원되는 widget(`TextField`, `ScrollView`)에 `restorationId` 부여
5. **custom state**: `RestorationMixin` + `RestorableProperty` 변종

### IF iOS도 지원 (Implement)
1. iOS는 추가 Xcode 설정 필요 — `Application Supports State Restoration` Info.plist
2. AppDelegate에서 application:shouldSaveApplicationState/shouldRestoreApplicationState true 반환
3. 디바이스에서 실제 process death 시뮬 후 검증

### IF 복원 안 됨 / 부분만 됨 (Review)
1. root scope (MaterialApp restorationScopeId) 빠졌나
2. Navigator.push → restorablePush로 안 바꿨나
3. RestorationMixin 구현체가 `restorationId` getter 반환하나
4. iOS: Xcode 설정 누락

## App-level scope 셋업

```dart
// main.dart
import 'package:flutter/material.dart';

void main() => runApp(const MyApp());

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      restorationScopeId: 'root',          // 핵심 — 이 한 줄로 시작
      home: const HomePage(),
      onGenerateRoute: (settings) {
        // restorablePushNamed로 push할 때 여기서 같이 매칭
        return MaterialPageRoute(builder: (_) => routeFor(settings.name!));
      },
    );
  }
}
```

## Navigator 변환

### push → restorablePush
```dart
// 변경 전
Navigator.of(context).push(MaterialPageRoute(builder: (_) => DetailPage(id)));

// 변경 후
Navigator.of(context).restorablePush(_detailRouteBuilder, arguments: id);

// top-level 또는 static
Route<void> _detailRouteBuilder(BuildContext context, Object? id) {
  return MaterialPageRoute(builder: (_) => DetailPage(id as String));
}
```

**규칙**: route builder는 top-level 또는 static (closure 캡처 불가 — restoration 후 다시 호출 가능해야).

### named 라우트
```dart
Navigator.of(context).restorablePushNamed('/details', arguments: id);
```

## Widget restorationId

### 기본 widget
```dart
TextField(
  restorationId: 'email_field',           // surrounding bucket에 저장
  controller: emailController,
)

ScrollView(
  restorationId: 'feed_scroll',
)

NestedScrollView(
  restorationId: 'profile_scroll',
)
```

### 새 scope 만들기 (자식 trees가 자기 bucket 가짐)
```dart
class FeatureSection extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return UnmanagedRestorationScope(
      bucket: RestorationScope.of(context),
      child: const RestorationScope(
        restorationId: 'feature_x',  // 새 bucket → 자식들의 restorationId가 여기로
        child: FeatureWidget(),
      ),
    );
  }
}
```

## Custom state — RestorationMixin

```dart
class CounterPage extends StatefulWidget {
  const CounterPage({super.key});
  @override
  State<CounterPage> createState() => _CounterPageState();
}

class _CounterPageState extends State<CounterPage> with RestorationMixin {
  final _count = RestorableInt(0);
  final _username = RestorableString('');

  @override
  String get restorationId => 'counter_page';      // 필수 getter

  @override
  void restoreState(RestorationBucket? oldBucket, bool initialRestore) {
    registerForRestoration(_count, 'count');
    registerForRestoration(_username, 'username');
  }

  @override
  void dispose() {
    _count.dispose();
    _username.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Column(
    children: [
      Text('${_count.value}'),
      ElevatedButton(
        onPressed: () => setState(() => _count.value++),
        child: const Text('+'),
      ),
    ],
  );
}
```

### Restorable* 종류
- `RestorableInt`, `RestorableDouble`, `RestorableString`, `RestorableBool`
- `RestorableEnum<T>`
- `RestorableDateTime`
- `RestorableTextEditingController`
- 커스텀: `RestorableValue<T>` 상속

## iOS 추가 셋업

```xml
<!-- ios/Runner/Info.plist -->
<key>UIApplicationSupportsStateRestoration</key>
<true/>
```

```swift
// ios/Runner/AppDelegate.swift
override func application(
  _ application: UIApplication,
  shouldSaveSecureApplicationState coder: NSCoder
) -> Bool { return true }

override func application(
  _ application: UIApplication,
  shouldRestoreSecureApplicationState coder: NSCoder
) -> Bool { return true }
```

## 디바이스 테스트

### Android
```bash
# 1. 앱 띄우고 상태 만들기 (입력, 스크롤, navigation)
# 2. "Don't keep activities" 옵션 ON (개발자 옵션)
# 3. Home 누르고 다시 앱 열기 → 복원 확인
adb shell settings put global always_finish_activities 1
adb shell settings put global always_finish_activities 0      # 테스트 후 OFF
```

### iOS
```
1. 앱 시뮬에서 띄우고 상태 만들기
2. Xcode에서 stop (process kill 시뮬)
3. 다시 launch → 복원 확인
```

**docs 경고**: 테스트 후 device 설정 정상화 잊지 말기.

## 5축 품질 체크

| 축 | 체크 |
|---|---|
| 정확성 | root scope (`MaterialApp.restorationScopeId`)가 설정됐는가 |
| 안전성 | 영구 비즈니스 데이터가 restoration에 안 섞여있는가 (storage 분리) |
| 성능 | restoration bucket이 큰 객체 직렬화 안 하는가 (작은 ephemeral state만) |
| 가독성 | restorationId가 의미 있는 이름인가 (id 같은 generic X) |
| 검증성 | 디바이스 process death 시나리오로 실제 검증됐는가 |

## Gotchas

### `MaterialApp.restorationScopeId` 누락
root scope 없으면 자식의 모든 restorationId가 동작 안 함. 빈 문자열 아니라 의미 있는 값 (`'root'`).

### `Navigator.push`를 그대로 둠
restorablePush로 안 바꾸면 process death 후 라우트 스택이 sign-in 페이지로 리셋. critical 흐름엔 변환 필수.

### route builder가 closure 캡처
```dart
// ❌
Navigator.restorablePush(context, (ctx, args) {
  return DetailPage(externalState);     // closure capture 위험
});

// ✅ top-level
Route<void> _detailRoute(BuildContext c, Object? args) =>
    MaterialPageRoute(builder: (_) => DetailPage(args as String));
```

### iOS Info.plist 누락
Android에선 동작, iOS에선 안 됨. plist key 추가 + AppDelegate.

### 영구 데이터를 RestorableProperty에 담음
restoration bucket은 작아야 함 (TransactionTooLargeException 등). 영구 데이터는 SQLite/Hive/Isar로.

### `dispose()`에서 RestorableProperty 정리 누락
listener 누수. `_count.dispose()` 항상 호출.

### restorationId가 generic (`'id'`, `'state'`)
debugging / 충돌 회피 어려움. 도메인 이름 (`'cart_screen_quantity'`).

### bucket 안에 매우 큰 객체 직렬화
`TransactionTooLargeException` (Android binder 1MB cap). 큰 객체 분해 또는 영구 storage.

### TestWidgetsFlutterBinding 안에서만 검증
실제 process death와 다름. 디바이스에서 "Don't keep activities" 또는 process kill로 검증.

### `RootRestorationScope`를 매번 사용
대부분은 `MaterialApp.restorationScopeId`로 충분. RootRestorationScope는 MaterialApp/CupertinoApp 위에 무언가 있어야 할 때만.

## 도구 사용 패턴 (Harness)
- root scope 검사: `Grep("restorationScopeId", path="lib/main.dart")`
- restorable navigation 변환: `Grep("Navigator\\..*\\.push\\(", glob="lib/**/*.dart")` — restorablePush로 변환 대상
- RestorationMixin 사용처: `Grep("with RestorationMixin", glob="lib/**/*.dart")`
- iOS plist 검증: `Grep("UIApplicationSupportsStateRestoration", path="ios/Runner/Info.plist")`
- bucket 크기 위험 탐지: `Grep("RestorableValue<List|RestorableValue<Map", glob="lib/**/*.dart")` (큰 collection 의심)
