---
keywords: dart 3.11 analyze fix format doc pub package quality gate ci analysis_options pubspec lints
intent: dart품질게이트 analyze fix format doc 검증 ci 셋업 lint 강화 publish 준비
paths: pubspec.yaml analysis_options.yaml lib/ test/ tool/
patterns: dart analyze dart fix --dry-run dart format --set-exit-if-changed dart doc --dry-run dart test
requires: dart
phase: implement review release
tech-stack: dart
min_score: 3
---

# Dart 3.11.x Package Quality Gates: analyze / fix / format / doc

> 핵심 원칙: **품질 게이트는 boring + repeatable**. 단일 SDK CLI(`dart`)로 정의되어, 로컬과 CI에서 동일하게 돌아가는 게 가장 가치 있다. 커스텀 래퍼는 plain SDK 흐름이 진짜 반복으로 부족할 때만.

## 의사결정 트리

### IF 새 Dart 패키지 시작 (Design)
1. `pubspec.yaml`에 `sdk: ^3.11.0` (또는 팀 SDK constraint)
2. `lints` 패키지 추가 → `analysis_options.yaml`에서 `package:lints/recommended.yaml` 또는 `package:flutter_lints/flutter.yaml` (Flutter 패키지면)
3. `dev_dependencies`에 `package:test`
4. 폴더: `lib/<pkg>.dart` (public entry) + `lib/src/` (private) + `test/`
5. CI에 quality gate 한 줄로 박기 — 같은 명령을 로컬에서도 돌리도록

### IF 품질 게이트 한 번 실행 (Implement)
**순서**: analyze → fix --dry-run → format --set-exit-if-changed → (필요 시) doc --dry-run → test

```powershell
# 1. 의존성
dart pub get --offline

# 2. 정적 분석 (가장 먼저 — 구조적 이슈를 자동 fix 전에 봐야 진단이 깨끗함)
dart analyze --fatal-infos --fatal-warnings

# 3. 자동 fix 가능한지 미리보기 (mutating은 의도적으로만)
dart fix --dry-run

# 4. 포맷 검증 (CI에서 changed 시 실패)
dart format --output=none --set-exit-if-changed bin lib test tool

# 5. (public API 패키지) 문서 빌드 dry-run
dart doc --dry-run .

# 6. 테스트
dart test --coverage=coverage --reporter=expanded
```

### IF CI 워크플로 (release)
```yaml
# .github/workflows/dart.yml
jobs:
  qa:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dart-lang/setup-dart@v1
        with: { sdk: 3.11.x }
      - run: dart pub get
      - run: dart analyze --fatal-infos --fatal-warnings
      - run: dart fix --dry-run     # 진단용 — 실패시키지는 않음 (또는 정책에 따라)
      - run: dart format --output=none --set-exit-if-changed .
      - run: dart test --reporter=github
      - run: dart doc --dry-run .   # 패키지 publish 전 게이트
      # publish 전에만:
      # - run: dart pub publish --dry-run
```

### IF publish 직전 (Release)
1. `pubspec.yaml`의 `version`, `description`, `homepage`, `repository` 점검
2. `CHANGELOG.md` 갱신
3. `dart pub publish --dry-run` → 경고 0건
4. `dart doc --dry-run .` → 빠진 doc-comment 점검
5. tag → publish

## analysis_options.yaml 베이스라인

```yaml
include: package:lints/recommended.yaml

analyzer:
  language:
    strict-casts: true
    strict-inference: true
    strict-raw-types: true
  errors:
    # info를 warning 이상으로 격상하고 싶은 항목
    todo: ignore
    missing_required_param: error
    missing_return: error
  exclude:
    - "**/*.g.dart"
    - "**/*.freezed.dart"
    - "build/**"

linter:
  rules:
    - prefer_const_constructors
    - prefer_const_literals_to_create_immutables
    - avoid_print
    - require_trailing_commas
    - sort_pub_dependencies
    - public_member_api_docs   # 공개 API 패키지에서만
```

## 패키지 레이아웃 표준

```
my_pkg/
├── pubspec.yaml
├── analysis_options.yaml
├── CHANGELOG.md
├── README.md
├── LICENSE
├── lib/
│   ├── my_pkg.dart           ← public entry (re-export only 권장)
│   └── src/
│       ├── core.dart         ← private impl
│       └── ...
├── test/
│   ├── my_pkg_test.dart      ← public 동작 검증
│   └── src/
│       └── core_test.dart
├── tool/                     ← 빌드/유지보수 스크립트
└── example/                  ← (publish 패키지) 사용 예
```

**원칙**: `lib/<name>.dart`는 가능한 얇게 — `export 'src/...';` 만. 사용자는 이 파일만 import해야 함. `lib/src/`는 private.

## Test layout

```dart
// test/my_pkg_test.dart
import 'package:my_pkg/my_pkg.dart';
import 'package:test/test.dart';

void main() {
  group('add', () {
    test('returns sum', () {
      expect(add(1, 2), 3);
    });

    test('handles zero', () {
      expect(add(0, 0), 0);
    });
  });
}
```

- `dart test` 단일 명령
- 비동기는 `expectLater(future, completion(...))`
- 테스트 태그(`@Tags(['integration'])`)로 fast/slow 분리 가능: `dart test -t fast`

## 5축 품질 체크

| 축 | 체크 |
|---|---|
| 정확성 | `dart analyze --fatal-infos --fatal-warnings`가 통과하는가 |
| 안전성 | strict-casts/strict-inference로 `dynamic` 누수 차단되는가 |
| 성능 | `prefer_const_constructors` 적용으로 alloc 감소했는가 |
| 가독성 | `dart format` 결과가 commit되어 diff가 깨끗한가 |
| 검증성 | CI가 로컬 명령과 동일 순서로 실행되는가 (drift 없음) |

## Gotchas

### `dart fix` 자동 적용을 CI에서 시키면 위험
`dart fix --apply`는 mutating. CI는 `--dry-run`으로 진단만. 적용은 개발자가 의식해서.

### `dart format`을 CI에서 빼면 diff가 더러움
포맷이 PR마다 차이나면 review 시간 낭비. `--set-exit-if-changed`로 PR을 강제 fail.

### `analysis_options.yaml`을 IDE만 읽고 CI는 안 읽음
`dart analyze` 명령은 자동으로 옵션 파일 읽음. 다만 옵션 파일이 없으면 default lint만 적용 → 약한 게이트. 반드시 체크인.

### `lib/src/` 내부를 직접 import하는 사용자
`lib/<name>.dart`만 export하면 사용자는 `package:my_pkg/my_pkg.dart`만 쓰게 됨. private import 막으려면 lints의 `implementation_imports` 활성화.

### `public_member_api_docs` 룰을 internal 패키지에 적용
internal/throwaway 패키지는 doc 강제가 noise. publish 패키지에서만 켜기.

### Flutter 패키지에 `package:lints` 적용
Flutter는 `package:flutter_lints` 따로 사용. Dart-only 패키지만 `package:lints`.

### `dart pub publish --dry-run`을 안 돌림
publish 직전 누락된 README/license/version constraint를 잡아줌. tag 전에 필수.

## 도구 사용 패턴 (Harness)
- 게이트 한 번에: `Bash("dart analyze && dart format --output=none --set-exit-if-changed . && dart test")`
- analysis 옵션 점검: `Read analysis_options.yaml`
- public surface: `Read lib/<pkg>.dart` → src/만 export하는지 확인
- publish 준비: `Bash("dart pub publish --dry-run")`
