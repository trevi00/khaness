---
keywords: dart 3.11 test package:test matcher async expectLater completion throwsA fake_async coverage tags timeout dart_test.yaml 테스트 매처 비동기 커버리지
intent: dart 테스트 작성 비동기 매처 fake_async coverage tag timeout dart_test.yaml 셋업
paths: test/ dart_test.yaml pubspec.yaml
patterns: test group expect expectLater completion throwsA fake_async @Tags timeout: dart test --coverage
requires: dart
phase: implement review
tech-stack: dart
min_score: 3
---

# Dart 3.11.x Testing: package:test, Async Matchers, Coverage

> 핵심 원칙: **테스트는 public 동작에 매기고, 시간 의존은 결정론적 도구로 대체한다.** wall-clock에 의존한 sleep, 플레이키 timing, lib/src 직접 import는 안정성을 깎는다.

## 의사결정 트리

### IF 새 unit test (Implement)
1. **public surface 우선**: `test/` 안에서 `package:<pkg>/<pkg>.dart`만 import
2. **그룹화**: `group('add', () { test('returns sum', ...) })` 행동 단위
3. **단일 책임 assert**: 한 test에 한 가지 동작만
4. **결정론적**: timer, random, current time → fake로 대체

### IF 비동기 코드 (Implement)
- Future 결과 → `expectLater(fut, completion(matcher))`
- 예외 → `expectLater(fut, throwsA(...))` 또는 `expect(() async { ... }, throwsA(...))`
- timer / Future.delayed → `package:fake_async`
- Stream → `expectLater(stream, emitsInOrder([...]))`

### IF 커버리지 / 태그 (Review)
1. CI에서 `dart test --coverage=coverage`
2. 의미 있는 branch에 갭이 있나 → 추가 테스트
3. fast/slow 분리: `@Tags(['integration'])` 후 `dart test -t unit` (빠른 루프)
4. timeout 명시: `dart_test.yaml`에 tag별 timeout

## 기본 셋업

```yaml
# pubspec.yaml
dev_dependencies:
  test: ^1.25.0
  fake_async: ^1.3.0
  coverage: ^1.7.0
```

```yaml
# dart_test.yaml
tags:
  unit:
    timeout: 30s
  integration:
    timeout: 2m

reporter: expanded

paths:
  - test/
```

```dart
// test/calculator_test.dart
import 'package:mycli/mycli.dart';
import 'package:test/test.dart';

void main() {
  group('Calculator', () {
    late Calculator calc;

    setUp(() {
      calc = Calculator();
    });

    test('add returns sum', () {
      expect(calc.add(1, 2), 3);
    });

    test('add handles negatives', () {
      expect(calc.add(-1, -2), -3);
    });

    test('divide throws on zero', () {
      expect(() => calc.divide(1, 0), throwsA(isA<ArgumentError>()));
    });
  });
}
```

## Async 패턴

### Future 결과
```dart
test('fetchUser returns user', () async {
  final user = await api.fetchUser('id1');
  expect(user.id, 'id1');
});

// 또는 expectLater
test('fetchUser completes with user', () {
  expect(api.fetchUser('id1'), completion(isA<User>()));
});
```

### 예외
```dart
test('throws on invalid id', () {
  expect(api.fetchUser(''), throwsA(isA<ArgumentError>()));
});

// async 함수
test('throws on network error', () async {
  await expectLater(
    () async => await api.fetchUser('bad'),
    throwsA(isA<NetworkException>().having((e) => e.statusCode, 'status', 500)),
  );
});
```

### Stream
```dart
test('emits values in order', () {
  final stream = Stream.fromIterable([1, 2, 3]);
  expect(stream, emitsInOrder([1, 2, 3, emitsDone]));
});
```

### 시간 의존 — fake_async
```dart
import 'package:fake_async/fake_async.dart';

test('debounces with 200ms wait', () {
  fakeAsync((async) {
    final results = <String>[];
    final debouncer = Debouncer(const Duration(milliseconds: 200));

    debouncer.run(() => results.add('a'));
    async.elapse(const Duration(milliseconds: 100));
    debouncer.run(() => results.add('b'));   // reset
    async.elapse(const Duration(milliseconds: 200));

    expect(results, ['b']);
  });
});
```

## Custom matcher

```dart
Matcher hasField<T>(String name, dynamic value) =>
    isA<T>().having((it) => (it as dynamic), name, value);

test('user has expected fields', () {
  final u = User(id: 'x', name: 'A');
  expect(u, hasField<User>('id', 'x'));
});

// 또는 inline having
test('user props', () {
  final u = User(id: 'x', name: 'A');
  expect(
    u,
    isA<User>()
        .having((it) => it.id, 'id', 'x')
        .having((it) => it.name, 'name', 'A'),
  );
});
```

## Tags + Timeout

```dart
// test/integration/api_test.dart
@Tags(['integration'])
library;

import 'package:test/test.dart';

void main() {
  test('hits real API', () async {
    // ...
  }, timeout: const Timeout(Duration(seconds: 30)));
}
```

```bash
# 빠른 루프
dart test -t unit

# 통합만
dart test -t integration

# 통합 제외
dart test -x integration
```

## Coverage

```bash
# coverage 수집
dart pub global activate coverage
dart test --coverage=coverage
dart pub global run coverage:format_coverage \
  --lcov --in=coverage --out=coverage/lcov.info \
  --packages=.dart_tool/package_config.json --report-on=lib

# 보기 (선택)
genhtml -o coverage/html coverage/lcov.info
```

```yaml
# .github/workflows/dart.yml
- run: dart test --coverage=coverage
- run: dart pub global activate coverage
- run: dart pub global run coverage:format_coverage --lcov --in=coverage --out=coverage/lcov.info --packages=.dart_tool/package_config.json --report-on=lib
- uses: codecov/codecov-action@v4
  with: { files: coverage/lcov.info }
```

## 5축 품질 체크

| 축 | 체크 |
|---|---|
| 정확성 | public API에 assert 거는가 (`lib/src/` 직접 X) |
| 안전성 | async에 `expectLater` + 적절한 matcher 쓰는가 |
| 성능 | wall-clock sleep 없이 fake_async로 결정론적인가 |
| 가독성 | group/test 이름이 행동을 설명하는가 (`returns sum` vs `test1`) |
| 검증성 | CI에서 coverage 수집되고 의미있는 branch 커버하는가 |

## Gotchas

### `Future.delayed` real time wait
test가 wall-clock으로 기다림 → 느림 + 플레이키. fake_async로 대체.

### async test에 `await` 누락
expectation 실행 전 test 종료 → false negative. 항상 `await expectLater(...)` 또는 `expect(future, completion(...))`.

### `lib/src/` 직접 import
internal 변경 시 테스트 깨짐 → 리팩토링 비용. 가능한 한 public API 통해.

### `expect(() => fn(), throwsA(...))`에서 async fn
sync expect로 async 예외 못 잡음. `expectLater(() async => fn(), throwsA(...))` 또는 `expect(fn(), throwsA(...))` (Future 직접).

### `setUp`을 group 밖에 한 번
모든 group이 공유. group 내부에 두면 그 group만. 의도에 맞게.

### `@Tags`를 file-level `library;` 없이
`@Tags`는 library annotation. `library;` 선언 + 그 위에 `@Tags(['x'])`. 안 그러면 적용 안 됨.

### Stream test에서 `emitsDone` 누락
finite stream인데 done 매처 안 넣으면 leak 의심 못 잡음. `emitsInOrder([..., emitsDone])`.

### coverage가 lib 밖까지 측정
`--report-on=lib`로 한정. 안 그러면 test/ 자기 자신도 포함 → 의미 없는 100%.

### plugin / IO 의존 unit에 mock 없음
실제 file system / network 의존하면 CI 환경 차이로 깨짐. abstract하고 fake 주입.

### `print` 디버그 로그를 commit
`avoid_print` lint 키고 logger 도입. 테스트에서 print하면 reporter 꼬임.

## 도구 사용 패턴 (Harness)
- 빠른 루프: `Bash("dart test -t unit -r expanded")`
- coverage: `Bash("dart test --coverage=coverage")`
- async wait 탐지: `Grep("Future\\.delayed|sleep\\(", glob="test/**/*.dart")`
- lib/src import: `Grep("import 'package:[^/]+/src/", glob="test/**/*.dart")` (있으면 의존 지나침)
- tag 분포: `Grep("@Tags\\(", glob="test/**/*.dart")`
- 매처 다양성: `Grep("expect(Later)?\\(", glob="test/**/*.dart")` 호출 수 확인
