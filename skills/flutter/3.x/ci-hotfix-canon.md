---
name: flutter-ci-hotfix-canon
description: Flutter 3.x를 GitHub Actions에서 처음 굴릴 때 누적되는 13+가지 함정 카탈로그 — gradlew exec bit, build_runner, custom_lint AOT, dart format 버전 차이, strict raw type, Stream timeout 시그니처 등
keywords: flutter github-actions gradlew build_runner custom_lint dart-format inference_failure
intent: 빌드 검증 통과 실행 fix
paths: .github/workflows pubspec.yaml analysis_options.yaml
patterns: flutter pub dart build_runner custom_lint
phase: implement debug deploy
tech-stack: flutter
min_score: 2
---

# Flutter 3.x CI hotfix canon

> 핵심 원칙: Flutter CI는 **로컬 환경의 우연한 잘 됨**에 의존하지 않는다. Windows 개발 + Linux/macOS CI runner 사이의 모든 환경 차이 (filesystem, line ending, exec bit, Dart 버전, runner 가용성, network 의존) 가 한 번씩 깨진다. 본 카탈로그는 example_project Stage 17 (13 hotfix) + I-5 + V-3에서 누적된 학습. 새 Flutter 프로젝트 시작 시 이 카탈로그를 첫 commit에 반영하면 cold-start cost가 0에 수렴.

## 의사결정 트리

### IF 새 Flutter 프로젝트 CI 첫 설정 (Design)
1. `.github/workflows/flutter.yml`을 ubuntu-22.04 기반으로 작성. macOS/Windows runner는 큐 22min+ 가능 → analyze/test 단계는 OS 무관이므로 ubuntu만 쓴다.
2. 첫 commit 전 `git update-index --chmod=+x gradlew`로 exec bit 박기 (Windows에서 만든 wrapper는 666 이라 Linux runner에서 exit 126).
3. `pubspec.yaml`에 `custom_lint` / `riverpod_lint` 추가 X (IDE assist 용도면 dev dep도 X — CI AOT fail 함정).
4. workflow에 `dart run build_runner build --delete-conflicting-outputs` 단계 명시. `*.freezed.dart` / `*.g.dart`은 `.gitignore`에 (commit 안 함).
5. `dart format`은 `--output=none --set-exit-if-changed`보다 advisory (continue-on-error) — 로컬 Dart 버전과 CI Flutter stable Dart 버전이 종종 다름.
6. `dart analyze --fatal-warnings` 까지만. `--fatal-infos`는 `withOpacity` deprecated 같은 minor info에 매번 fail.

### IF CI가 깨졌을 때 (Debug)
1. 가장 흔한 5건부터 확인:
   - exit 126 → gradlew exec bit
   - `Could not find a file named ".freezed.dart"` → build_runner 단계 누락
   - `inference_failure_*` warning → 명시 type argument 누락 (§strict raw type)
   - `analyzer_plugin AOT failed` → custom_lint/riverpod_lint dev dep 충돌
   - `dart format` exit 1 → 로컬 Dart 버전과 CI 버전 차이
2. 운영 분기 (Stream/Future/Dio) 시그니처 변경은 SDK bump마다 추적 — `Stream<T>.timeout` `onTimeout` 시그니처는 Dart 3.0 전후 다름.

### IF 외부 actions push 시 권한 fail (Deploy)
- `gh auth refresh -s workflow -h github.com` + `gh auth setup-git`. `.github/workflows/**` push에는 OAuth `workflow` scope 필수.

## 함정 카탈로그 (example_project 누적 학습)

> 5축 (응집/결합/확장/안정/사용) 게이트 — 모두 안정/사용 축 위반 사례.

### 환경 / 실행 권한

| # | 함정 | 원인 | 해결 |
|---|---|---|---|
| 1 | `gradlew` exit 126 (Linux runner) | Windows에서 commit하면 exec bit 누락 (filesystem mode bit 666) | `git update-index --chmod=+x gradlew && git commit -m "fix: gradlew exec bit"` 한 번이면 영구 해결 |
| 2 | `gradle/wrapper-validation` ETIMEDOUT | services.gradle.org Cloudflare 외부 의존 — 지역/시점에 따라 fail | `continue-on-error: true` (supply-chain 검증은 advisory로) |
| 3 | macOS/Windows runner queue 22min+ | GitHub Actions에서 분당 가용 분량 부족 | `runs-on: ubuntu-22.04`. analyze/test/build은 OS 무관 |

### Toolchain / 의존 충돌

| # | 함정 | 원인 | 해결 |
|---|---|---|---|
| 4 | `freezed ^2.5.7` ↔ `custom_lint ^0.6.4` 충돌 | analyzer 버전 graph 불일치 | `custom_lint ^0.7.1`로 시도 → 그래도 analyzer_plugin AOT fail → IDE-assist용은 dev dep도 제거 |
| 5 | `*.freezed.dart` / `*.g.dart` 부재로 빌드 fail | build_runner 산출물을 commit 안 함 + CI에서 생성 안 함 | workflow에 `dart run build_runner build --delete-conflicting-outputs` 단계 추가. `.gitignore`에 codegen 산출물 명시 |
| 6 | `dart format --set-exit-if-changed` 무한 fail | 로컬 Dart ≠ CI Flutter stable Dart (포맷 미세 차이) | `dart format --output=none ... continue-on-error: true` (advisory). 또는 `flutter --version` lock으로 환경 통일 |
| 7 | `dart analyze --fatal-infos` 너무 strict | `withOpacity` deprecated 같은 minor info | `--fatal-warnings`만 유지 |

### Strict types (2-Strike 충족 — Stage 17 14건 + I-5 3건)

| # | 함정 | 원인 | 해결 |
|---|---|---|---|
| 8 | `Dio.post/get/fetch` + `MaterialPageRoute` type inference 14건 | analyzer `strict_raw_type` / `inference_failure_on_function_invocation` | `<Map<String, dynamic>>` / `<void>` 등 명시 type argument |
| 9 | I-5에서 `<Map>[]` 재발 3건 | Map raw type literal | `<Map<String, dynamic>>[]` 명시. dart `strict-raw-types: true` analyzer 옵션 활성화 |

### API 시그니처

| # | 함정 | 원인 | 해결 |
|---|---|---|---|
| 10 | `Stream<T>.timeout(onTimeout)` 시그니처 mismatch | Dart 3.0 후 `onTimeout`이 `(EventSink<T> sink) → void` | `(sink) => sink.close()` 또는 `(sink) => sink.add(fallback)` |

### Trigger / Workflow

| # | 함정 | 원인 | 해결 |
|---|---|---|---|
| 11 | OAuth `workflow` scope 없어 `.github/workflows/**` push 거부 | gh auth token 권한 부족 | `gh auth refresh -s workflow -h github.com` + `gh auth setup-git` |
| 12 | 빈 commit이 path filter trigger 안 함 | head commit에 변경 파일 없음 | 실제 변경 commit으로 trigger 또는 `gh workflow run <name>.yml` dispatch |
| 13 | feature 브랜치 push에 CI 0건 trigger | workflow가 `on: push: branches: [master]` 만 | feature branch에서도 검증 필요하면 `pull_request:` trigger 추가 |

## 표준 workflow 템플릿

```yaml
# .github/workflows/flutter.yml
name: CI — Flutter

on:
  push:
    branches: [master]
    paths:
      - 'apps/**/lib/**'
      - 'apps/**/test/**'
      - 'apps/**/pubspec.yaml'
      - '.github/workflows/flutter.yml'
  pull_request:
    paths-ignore:
      - '**/*.md'

jobs:
  analyze-and-test:
    runs-on: ubuntu-22.04
    strategy:
      matrix:
        app: [phone, admin]
    defaults:
      run:
        working-directory: apps/${{ matrix.app }}
    steps:
      - uses: actions/checkout@v4
      - uses: subosito/flutter-action@v2
        with:
          flutter-version: '3.41.7'   # 명시 — channel 'stable' 추적 X
          cache: true
      - run: flutter pub get
      - run: dart run build_runner build --delete-conflicting-outputs
      - run: dart analyze --fatal-warnings   # --fatal-infos X
      - run: dart format --output=none --set-exit-if-changed .
        continue-on-error: true   # advisory — Dart 버전 차이 회피
      - name: Run tests
        run: flutter test --reporter=expanded
        if: ${{ hashFiles('test/**/*_test.dart') != '' }}
```

## Gotchas

### `flutter-version: stable` 추적은 PR-by-PR 불안정성
stable channel은 주기적으로 새 Dart 버전 + 신규 lint rule 활성화. CI가 갑자기 fail. 명시 버전 `3.41.7` 박는다.

### `actions/cache` pub cache가 lock file 변경 즉시 무효화
pubspec.lock 변경 PR마다 cache rebuild → 시간 절약 0. `cache: true` (flutter-action 내장) + 매번 fresh `pub get`이 결과적으로 빠른 경우 많음.

### Patrol 도구는 Windows Desktop 미지원
admin app처럼 Windows desktop이 타겟이면 Patrol 대신 `integration_test` built-in 사용. iOS/Android는 Patrol.

### `flutter test integration_test/`를 unit test와 같이 돌리면 느려짐
integration_test는 emulator/desktop runner 필요 → workflow 분리. unit test는 PR마다, integration은 nightly 또는 manual dispatch.

### Flutter desktop CI 시도 시 ninja-build/libgtk-3-dev 누락
Linux desktop runner에서 `flutter build linux` 또는 `flutter run -d linux`는 native 빌드 도구 필요:
```yaml
- run: sudo apt-get install -y ninja-build libgtk-3-dev
- run: flutter config --enable-linux-desktop
- run: xvfb-run flutter test ...   # headless display
```

### `withOpacity` deprecated → `withValues(alpha: ...)` migration
Flutter 3.27+에서 `Color.withOpacity(0.5)` deprecated. info-level warning이라 `--fatal-infos`면 fail. Migration:
```dart
color.withValues(alpha: 0.5)   // 신규
color.withOpacity(0.5)         // deprecated, info warning
```

### `*.freezed.dart` / `*.g.dart`를 git에 commit하지 않으면 IDE에서 import 에러
로컬 개발자가 처음 clone 후 `flutter pub get` → IDE 즉시 빨간 줄. 해결: `flutter pub get` 후 자동 build_runner를 실행하는 git hook 또는 README 명시. 운영 환경에는 commit하지 말고 CI에서만 생성.

### `build_runner build` 시 `--delete-conflicting-outputs` 누락
이전 빌드 산출물이 남아있으면 `Conflicting outputs` error로 fail. 항상 `--delete-conflicting-outputs` 또는 `flutter clean` 먼저.

### pubspec `dependency_overrides`로 임시 fix하면 잊어버림
custom_lint version conflict 임시 해결로 `dependency_overrides` 쓰면 TODO 잊고 잔류 → 다음 의존 bump에서 cascade 깨짐. 항상 commit message에 "TODO: remove override after X resolved" 명시.
