---
keywords: flutter 3 test unit widget integration plugin native xctest junit gradle integration_test WidgetTester pumpAndSettle 테스트 매트릭스 위젯 통합
intent: flutter 테스트 lane 분리 unit/widget/integration/plugin native 매트릭스 설계 fake repository 경계 결정
paths: test/ test/unit/ test/widget/ integration_test/ example/integration_test/ example/android/ example/ios/
patterns: WidgetTester pumpWidget pumpAndSettle IntegrationTestWidgetsFlutterBinding gradlew testDebugUnitTest xcodebuild test
requires: flutter
phase: implement review
tech-stack: flutter
min_score: 3
---

# Flutter 3.x Testing Matrix: Unit / Widget / Integration / Plugin / Native

> 핵심 원칙: **테스트는 layer별 책임으로 분리**한다. unit = pure logic, widget = rendered behavior, integration = full app on device, plugin = native boundary 추가. 한 lane이 다른 lane을 덮으려고 하면 비싸지고 플레이키해짐.

## 의사결정 트리

### IF 새 코드 작성 (Implement)
1. **무엇을 검증?**
   - 함수/클래스 순수 로직 → **unit test** (`test/unit/`)
   - Widget 입력→출력, finder 어설션 → **widget test** (`test/widget/`)
   - 화면 흐름 + 실제 디바이스/플랫폼 → **integration test** (`integration_test/`)
2. **fake 어디서?**
   - Repository를 fake → ViewModel unit/widget test에 주입
   - HTTP/storage를 fake → repository test에 주입
3. **plugin 작성 중?** → 아래 plugin 매트릭스 추가

### IF 위젯 테스트가 점점 무거워짐 (Review)
1. App-wide widget tree mount → 사실상 integration test로 변질 → 분리
2. Real repository / network 사용 → 약한 boundary → fake로 교체
3. `pumpAndSettle` 무한 wait → 명시적 `pump(duration)` 또는 mock timer

### IF plugin 테스트 (Implement)
1. **Dart unit/widget**: native 안 로드, platform 호출은 mock
2. **Dart integration** (`example/integration_test/`): Dart + native 같이, native UI dialog는 못 함
3. **Native unit**:
   - Android: `cd example/android && ./gradlew testDebugUnitTest`
   - iOS: `cd example/ios && xcodebuild test ...`
4. example app 한 번 빌드 후 native test (generated build files 필요)

## 테스트 layout

```
lib/
├── src/...
test/
├── unit/
│   └── view_models/
│       └── login_view_model_test.dart
├── widget/
│   └── screens/
│       └── login_screen_test.dart
└── helpers/
    └── fakes.dart
integration_test/
└── app_test.dart
```

### Plugin 추가
```
plugins/my_plugin/
├── lib/...
├── test/                   ← Dart unit/widget
├── example/
│   ├── lib/
│   ├── integration_test/   ← Dart + native bridge
│   ├── android/
│   │   └── app/src/test/   ← JUnit native
│   └── ios/
│       └── RunnerTests/    ← XCTest native
```

## 패턴

### Unit (Flutter binding 없이)
```dart
// test/unit/view_models/login_view_model_test.dart
import 'package:test/test.dart';
import 'package:my_app/src/features/auth/view_model/login_view_model.dart';
import '../../helpers/fakes.dart';

void main() {
  group('LoginViewModel', () {
    test('submit success sets isSubmitting back to false', () async {
      final repo = FakeAuthRepository(success: true);
      final vm = LoginViewModel(repo);

      final ok = await vm.submit(email: 'a@b.c', password: 'pw');

      expect(ok, true);
      expect(vm.isSubmitting, false);
      expect(vm.errorMessage, null);
    });

    test('submit failure sets errorMessage', () async {
      final repo = FakeAuthRepository(error: AuthException('bad creds'));
      final vm = LoginViewModel(repo);

      final ok = await vm.submit(email: 'a@b.c', password: 'pw');

      expect(ok, false);
      expect(vm.errorMessage, 'bad creds');
    });
  });
}
```
**규칙**: Flutter UI 패키지 import 안 함 (binding 안 만들면 더 빠름).

### Widget (rendered behavior)
```dart
// test/widget/screens/login_screen_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:my_app/src/features/auth/view/login_screen.dart';
import '../../helpers/fakes.dart';

void main() {
  testWidgets('shows error when submit fails', (tester) async {
    await tester.pumpWidget(
      Provider<AuthRepository>.value(
        value: FakeAuthRepository(error: AuthException('bad')),
        child: const MaterialApp(home: LoginScreen()),
      ),
    );

    await tester.enterText(find.byKey(const Key('email')), 'a@b.c');
    await tester.enterText(find.byKey(const Key('password')), 'pw');
    await tester.tap(find.byKey(const Key('submit')));
    await tester.pump(); // 1프레임 — 로딩 상태
    await tester.pumpAndSettle();

    expect(find.text('bad'), findsOneWidget);
  });
}
```
**규칙**: real repository 안 씀. Provider로 fake 주입. `pumpAndSettle`은 deterministic 흐름에서만 (animation 무한 시 hang).

### Integration (full app, real device)
```dart
// integration_test/app_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:my_app/main.dart' as app;

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('login flow', (tester) async {
    app.main();
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('email')), 'demo@x');
    await tester.enterText(find.byKey(const Key('password')), 'demo');
    await tester.tap(find.byKey(const Key('submit')));
    await tester.pumpAndSettle();

    expect(find.text('Welcome'), findsOneWidget);
  });
}
```
실행:
```bash
flutter test integration_test/app_test.dart
flutter test integration_test/app_test.dart --device-id=<id>
```

### Plugin native (Android JUnit)
```bash
cd example
flutter build apk --debug         # generated platform build files 보장
cd android
./gradlew :app:testDebugUnitTest
```

### Plugin native (iOS XCTest)
```bash
cd example
flutter build ios --debug --no-codesign
cd ios
xcodebuild test \
  -workspace Runner.xcworkspace \
  -scheme Runner \
  -configuration Debug \
  -destination 'platform=iOS Simulator,name=iPhone 15'
```

## Plugin 테스트 매트릭스

| Layer | 위치 | 검증 | 한계 |
|---|---|---|---|
| Dart unit/widget | `test/` | Dart API/로직 | platform 호출은 mock |
| Dart integration | `example/integration_test/` | Dart + native 연동 | native dialog/UI 자동화 X |
| Android native | `example/android/...` | JUnit, Kotlin host code | dart side는 검증 안 함 |
| iOS native | `example/ios/...` | XCTest, Swift host code | 위와 동일 |

## 5축 품질 체크

| 축 | 체크 |
|---|---|
| 정확성 | unit/widget/integration이 의도한 layer를 검증하는가 (overrun X) |
| 안전성 | widget test가 real repository/network 안 쓰는가 |
| 성능 | unit이 Flutter binding 없이 빠르게 도는가 |
| 가독성 | folder layout (test/unit · test/widget · integration_test) 일관적인가 |
| 검증성 | critical 사용자 흐름이 integration_test에 있는가 (sign-in, purchase) |

## Gotchas

### widget test가 사실상 integration test
전체 앱 트리 mount + real services → 느리고 플레이키. 작은 위젯 트리 + fake repo로 줄이기.

### unit test에 Flutter binding 무의식 사용
`TestWidgetsFlutterBinding.ensureInitialized()`를 모든 테스트에 박으면 unit이 widget test 비용. pure 로직은 Flutter import 없이.

### `pumpAndSettle` 무한 hang
무한 animation, periodic timer 있으면 settle 안 됨. 그 경우 `pump(Duration)` 명시적 사용 또는 fake timer.

### plugin native test를 example app build 전 시도
generated platform build files 없어서 실패. `flutter build` 먼저.

### integration test를 unit test 폴더에
`flutter test`가 모두 함께 도는데 device 필요한 게 섞이면 CI 깨짐. `integration_test/` 분리, 명령도 분리.

### fake 대신 mockito everywhere
verify 검증 위주가 되면 implementation detail에 의존. fake 클래스로 행동 기반 테스트가 더 견고.

### golden test를 처음부터 너무 많이
golden은 시각 회귀에 강하지만 maintenance 비용. critical screen만, OS/font에 민감한 점 의식.

### `findsOneWidget` 대신 `findsWidgets`로 모호하게
정확히 한 개여야 하는데 복수 매칭 시 silent pass. 의도대로 `findsOneWidget`/`findsNothing` 사용.

### plugin Dart integration test에서 native dialog 기대
docs 명시: 안 됨. native UI 검증은 native test로.

### widget에 `key` 없는 selector를 text 기반으로
i18n / 재사용 시 깨짐. 안정 selector를 `Key('submit')` 또는 semantic finder로.

## 도구 사용 패턴 (Harness)
- 빠른 unit only: `Bash("flutter test test/unit")`
- widget only: `Bash("flutter test test/widget")`
- integration: `Bash("flutter test integration_test/")`
- plugin native (Android): `Bash("cd example/android && ./gradlew :app:testDebugUnitTest")`
- plugin native (iOS): `Bash("cd example/ios && xcodebuild test -workspace Runner.xcworkspace -scheme Runner")`
- pumpAndSettle 위험 탐지: `Grep("pumpAndSettle\\(\\)", glob="test/**/*.dart")` — animation 있으면 hang 의심

## Related (신규 그래프 cross-ref)

testing-matrix가 결합되는 신규 노드:
- `kotlin/android/paparazzi-screenshot-tests.md` — Android Compose JVM 스크린샷 (Flutter golden test의 native 변종) — RTL pseudolocale 패턴 동일
- `java/lang/testcontainers-junit-integration.md` — JVM integration test (Flutter integration_test와 동일 lane 구분 정신)
- `_common/test-driven-development.md` — TDD red-green-refactor (사후 테스트 anti-pattern)
- `_common/experimentation-and-ab-testing.md` — production stochastic 검증 (test deterministic의 보완 axis)
