---
name: dart-strict-types-and-codegen
description: Dart strict-raw-types / inference_failure 2-Strike 학습 + freezed/json_serializable codegen 산출물 git 관리 — Dio·MaterialPageRoute·Map literal 명시 type argument 패턴
keywords: dart strict-raw-types inference_failure freezed json_serializable codegen gitignore
intent: 명시 추가 fix 검증
paths: lib/ analysis_options.yaml pubspec.yaml
patterns: Dio Map List Future Stream MaterialPageRoute freezed g.dart
phase: implement debug
tech-stack: flutter
min_score: 2
---

# Dart strict types + codegen 위생

> 핵심 원칙: Dart의 strict 모드는 generic 함수/literal에 `<T>` 명시를 요구한다. `<Map>`은 `<Map<dynamic, dynamic>>`이라 strict_raw_types에 걸리고, `Dio.post(...)` 같은 inferred call은 inference_failure에 걸린다. codegen 산출물 (`*.freezed.dart`, `*.g.dart`) 은 빌드 결과이므로 git에 commit하지 않고 CI/로컬에서 매번 생성한다.

## 의사결정 트리

### IF 새 Dart 프로젝트 (Design)
1. `analysis_options.yaml`에 strict 옵션 활성화:
   ```yaml
   include: package:flutter_lints/flutter.yaml
   analyzer:
     language:
       strict-casts: true
       strict-inference: true
       strict-raw-types: true
   ```
2. `.gitignore`에 codegen 산출물:
   ```gitignore
   # Codegen — regenerate locally / in CI
   *.freezed.dart
   *.g.dart
   *.gr.dart
   *.config.dart
   # build_runner cache
   .dart_tool/
   ```
3. CI workflow에 `dart run build_runner build --delete-conflicting-outputs` 단계 명시.

### IF strict_raw_type / inference_failure warning이 떴을 때 (Implement)
1. `<Map>` / `<List>` / `<Set>` literal → 항상 type argument 명시:
   - `<Map<String, dynamic>>[]` (Map element list)
   - `<String, dynamic>{}` (Map literal)
   - `<int>[]` (List literal)
2. Dio `post/get/put/delete/fetch` → response 타입 명시:
   ```dart
   final res = await dio.post<Map<String, dynamic>>('/path', data: ...);
   ```
3. `MaterialPageRoute` / `PageRouteBuilder` → return 타입 명시:
   ```dart
   await Navigator.of(context).push<void>(MaterialPageRoute<void>(builder: ...));
   ```
4. `Future.then` / `Stream.map` callback → 명시:
   ```dart
   future.then<R>((value) => ...)
   ```

### IF 새 freezed/json_serializable 모델 추가 (Implement)
1. 모델 파일 작성 후 즉시:
   ```bash
   dart run build_runner build --delete-conflicting-outputs
   ```
2. 생성된 `*.freezed.dart` / `*.g.dart`는 commit X — `.gitignore` 매칭 확인 (`git status`).
3. IDE에서 빨간 줄 보이면 `flutter pub get` → build_runner 다시.
4. CI workflow가 build_runner 단계를 갖는지 확인 (없으면 추가).

### IF Review
- [ ] `analysis_options.yaml`에 strict-raw-types/strict-inference 활성화됨
- [ ] `*.freezed.dart` / `*.g.dart`이 `git status`에 untracked 또는 ignored로만 나옴 (tracked 0건)
- [ ] CI workflow에 build_runner 단계가 analyze보다 먼저 실행됨

## 2-Strike 학습 (example_project)

| 사건 | 발생량 | 위치 |
|---|---|---|
| Stage 17 hotfix | 14건 | phone Dio + MaterialPageRoute (commit 622c841, 99f89ad) |
| I-5 hotfix | 3건 | integration_test `<Map>[]` (commit 1e52968) |

2회 발생 → 2-Strike Rule 적용. `strict-raw-types: true`를 default로 박고, 신규 코드 작성 시 `Dio.post<R>(...)` / `<Map<String, dynamic>>[]` / `<void>` 형식 정착.

## 표준 패턴 예시

### Dio HTTP client

```dart
// X (inference_failure_on_function_invocation)
final res = await dio.post('/api/v1/orders', data: payload);

// O — response 타입 명시
final res = await dio.post<Map<String, dynamic>>('/api/v1/orders', data: payload);

// O — void response
await dio.post<void>('/api/v1/log', data: payload);
```

### Map / List literal

```dart
// X (strict_raw_type)
final list = <Map>[];
final cache = {};   // Map<dynamic, dynamic>

// O
final list = <Map<String, dynamic>>[];
final cache = <String, int>{};
```

### Navigator routes

```dart
// X (inference_failure)
Navigator.push(context, MaterialPageRoute(builder: ...));

// O
Navigator.push<void>(context, MaterialPageRoute<void>(builder: ...));

// O — result 반환 시 명시
final result = await Navigator.push<bool>(
  context,
  MaterialPageRoute<bool>(builder: ...),
);
```

### Stream timeout (Dart 3.0+)

```dart
// X (시그니처 mismatch — Dart 3.0 이전 형식)
stream.timeout(
  const Duration(seconds: 5),
  onTimeout: () => Stream.empty(),   // function 리턴 X
);

// O (Dart 3.0+)
stream.timeout(
  const Duration(seconds: 5),
  onTimeout: (sink) => sink.close(),
  // 또는 sink.add(fallback) / sink.addError(TimeoutException(...))
);
```

## codegen 산출물 git 관리 의사결정

### Commit하지 않는 이유

1. **재현성**: 어떤 머신/Dart 버전에서도 `build_runner build`로 동일 결과 — drift 0
2. **PR diff 잡음**: codegen 산출물이 diff에 끼면 review 신호 대 잡음 비율 떨어짐
3. **merge conflict 빈발**: 자동 생성 코드는 위치/순서가 freezed 버전마다 미세 변경
4. **공간**: 큰 프로젝트에서 *.freezed.dart 누적 수십 MB

### Commit하는 예외 케이스

- CI에 build_runner 단계를 둘 수 없는 환경 (예: Pub Workspaces 미지원 toolchain)
- 외부 contributor에게 build_runner 실행을 요구하지 못하는 OSS 패키지 (rare)
- 위 두 경우 모두 README에 명시 + pre-commit hook으로 staleness 검증

## Gotchas

### `.freezed.dart` / `.g.dart`이 untracked로 보이지만 의도와 다름
`.gitignore` 규칙이 wildcard로 매칭하는지 `git check-ignore -v lib/foo.freezed.dart`로 확인. ignore 안 되면 commit으로 들어가는 사고 — example_project R-8 시연 후 발견된 6개 untracked가 이 케이스.

### `dart run build_runner watch` 로컬에서 켜놓고 IDE 끄기
watch 모드는 background process. IDE 종료해도 안 죽음 → 다음 세션에서 file lock으로 build fail. `flutter pub run build_runner clean` + 명시 종료.

### json_serializable `@JsonKey(name: 'snake_case')`와 global `@JsonNaming` 충돌
global naming이 snake_case라도 `@JsonKey(name: '...')` 명시는 override. wire 표기 일관성을 위해 한 가지만 선택 — 보통 `@JsonKey`로 명시 (검색 가능성 우위).

### strict-casts vs strict-inference
`strict-casts: true`는 implicit downcast 금지 — `Object → String`을 `value as String` 명시 요구. `strict-inference: true`는 inferred `dynamic` 금지. 둘 다 켜야 strict 모드의 가치가 살아남.

### `--no-fatal-warnings` 잠시 우회로 분기 만들기
PR에서 strict warning이 너무 많이 떠서 `--no-fatal-warnings`로 임시 우회 → 머지 후 그대로 잔류 → 다음 PR에서 1000건 누적. 우회는 commit 단위 + 명시 expiration TODO.

### freezed `@Default`와 `required` 충돌
freezed 클래스에서 `@Default(0)` 박은 field에 `required` 함께 명시하면 codegen fail (silent — 단순 warning). default가 있으면 required 빼기.

### codegen 산출물의 import path 변경 (drift, build_runner version bump)
`build_runner` minor bump 후 `*.g.dart`의 import path 형식이 바뀌어서 기존 hand-written code의 import가 깨지는 경우 있음. bump 후 항상 `flutter clean && flutter pub get && build_runner build` 전체 재생성.

### IDE가 보는 산출물과 CI가 생성한 산출물 mismatch
로컬에서 옛 *.freezed.dart을 git에 commit한 적이 있고, .gitignore 추가 후에도 file은 working tree에 남아있어 IDE가 그걸 본다. CI는 fresh runner라 새 freezed 버전으로 생성 → drift. 해결: `git rm --cached **/*.freezed.dart **/*.g.dart` + `flutter clean`.
