---
keywords: dart 3.11 cli run compile exe build aot jit pub global activate executables pubspec dart install bin tool 패키지 cli 빌드 실행파일
intent: dart cli 빌드 lane 분리 dart run compile exe build cli executables 노출 pub global activate publish 검증
paths: bin/ pubspec.yaml lib/src/cli/ build/ tool/
patterns: dart run dart compile exe dart build cli dart pub global activate executables: pubspec
requires: dart
phase: design implement release
tech-stack: dart
min_score: 3
---

# Dart 3.11.x CLI: run / compile exe / build cli + Packaging

> 핵심 원칙: **dev / standalone exe / asset-bundled CLI는 서로 다른 lane**이다. 한 패키지를 publish하기 전 세 lane(`dart run`, `dart compile exe`, `dart build cli`) + global activate를 모두 검증한다.

## 의사결정 트리

### IF 새 CLI 추가 (Design)
1. **entry point**: `bin/<name>.dart` (top-level `void main(List<String> args)`)
2. **executable 노출**: `pubspec.yaml`의 `executables:` 섹션
   ```yaml
   executables:
     mycli: bin/mycli.dart    # `dart pub global run pkg:mycli`
   ```
3. **package layout**:
   - `bin/` — entry point (얇게)
   - `lib/src/cli/` — 실제 명령 로직
   - `lib/<pkg>.dart` — public API re-export (라이브러리로도 쓰면)
4. **AOT vs JIT 결정**:
   - 개발 / 디버그 → `dart run` (JIT)
   - 빠른 cold start, 단일 binary 배포 → `dart compile exe`
   - native asset / build hook 결과물 포함 → `dart build cli`

### IF 검증 게이트 (release)
release 직전 다음 lane 모두 PASS 확인:
```powershell
# 1. 개발 lane
dart run bin/mycli.dart --help

# 2. AOT 단일 실행파일
dart compile exe bin/mycli.dart -o build/mycli.exe
./build/mycli.exe --help

# 3. asset-bundled CLI (build hook 사용 시)
dart build cli --target=bin/mycli.dart --output build_bundle
./build_bundle/mycli --help

# 4. 글로벌 활성화 검증 (publish 시뮬)
dart pub global activate --source path . --overwrite
dart pub global run mycli:mycli --help
dart pub global deactivate mycli
```

### IF 배포 형태 선택
| 형태 | 명령 | 사용 |
|---|---|---|
| pub.dev publish | `dart pub publish --dry-run` → tag → `dart pub publish` | 라이브러리 또는 CLI 둘 다 |
| 단일 실행파일 | `dart compile exe` → release 첨부 | 사용자 dart 미설치 |
| Asset bundle | `dart build cli` | native asset, 동적 라이브러리 동반 |
| Global install | 사용자가 `dart pub global activate <pkg>` | pub.dev에 publish된 CLI |

## pubspec 베이스라인

```yaml
name: mycli
description: A CLI for X
version: 0.1.0
homepage: https://github.com/me/mycli
repository: https://github.com/me/mycli

environment:
  sdk: ^3.11.0

dependencies:
  args: ^2.5.0          # CLI 파싱
  io: ^1.0.0            # stdin/out 헬퍼
  path: ^1.9.0

dev_dependencies:
  test: ^1.25.0
  lints: ^4.0.0

executables:
  mycli: bin/mycli.dart
```

## CLI entry 패턴

### 얇은 bin entry + 두꺼운 lib
```dart
// bin/mycli.dart
import 'dart:io';
import 'package:mycli/src/cli/runner.dart';

Future<void> main(List<String> args) async {
  final exitCode = await runMycli(args);
  exit(exitCode);
}
```

```dart
// lib/src/cli/runner.dart
import 'package:args/command_runner.dart';

class _GreetCommand extends Command<int> {
  @override
  String get name => 'greet';
  @override
  String get description => 'Greet someone';

  _GreetCommand() {
    argParser.addOption('name', abbr: 'n', mandatory: true);
  }

  @override
  Future<int> run() async {
    final name = argResults!['name'] as String;
    print('Hello, $name!');
    return 0;
  }
}

Future<int> runMycli(List<String> args) async {
  final runner = CommandRunner<int>('mycli', 'A CLI for X')
    ..addCommand(_GreetCommand());
  try {
    return await runner.run(args) ?? 0;
  } on UsageException catch (e) {
    stderr.writeln(e);
    return 64;
  }
}
```

**핵심**: `bin/`을 얇게 = 테스트 가능한 `runMycli(args)` 함수가 `lib/src/`에. test에서 `expect(await runMycli(['greet','-n','x']), 0)` 가능.

## 3 lane 비교

### `dart run` — 개발 / JIT
```bash
dart run bin/mycli.dart greet --name X
dart run :mycli greet --name X     # executables에 등록되어 있으면
```
- 빠른 iteration, 디버거 부착
- cold start 느림 (VM init), 배포에 부적합

### `dart compile exe` — AOT 단일 실행파일
```bash
dart compile exe bin/mycli.dart -o build/mycli.exe
./build/mycli.exe greet --name X
```
- 빠른 cold start, dart SDK 미설치 환경 OK
- 플랫폼별 빌드 필요 (Win/macOS/Linux 각각)
- build hook으로 만든 native asset 포함 안 됨

### `dart build cli` — asset bundle
```bash
dart build cli --target=bin/mycli.dart --output build_bundle
./build_bundle/mycli greet --name X
```
- AOT exe + 동반 dylib/so 등 asset
- native assets, build hook 결과물 포함
- 단일 binary가 아니라 디렉토리 형태

## Global activate / install

### 로컬 검증 (publish 전)
```bash
dart pub global activate --source path . --overwrite
dart pub global list
dart pub global run mycli:mycli --version
dart pub global deactivate mycli
```

### pub.dev에서 사용자 설치
```bash
dart pub global activate mycli       # pub.dev에서
dart pub global run mycli:mycli ...  # 항상 동작
mycli ...                             # PATH에 ~/.pub-cache/bin 있으면
```

### 새 `dart install` (3.11+)
```bash
dart install mycli   # global activate의 alternative
```
**주의**: 둘 다 같은 pub-cache. `dart pub global activate`는 source 종류(path/git/pub.dev) 선택 명시적이라 여전히 유용.

## 5축 품질 체크

| 축 | 체크 |
|---|---|
| 정확성 | `executables:`에 등록된 이름과 `bin/<name>.dart` 매칭되는가 |
| 안전성 | exit code가 명시적 (0 success, 64 usage error 등) |
| 성능 | 사용자 환경(cold start 빈도)에 맞는 lane 선택 (run vs exe) |
| 가독성 | bin은 얇고 lib/src/cli에 logic이 모여 있는가 |
| 검증성 | 3 lane + global activate 모두 release 직전 검증되는가 |

## Gotchas

### bin/에 logic 다 박음
테스트 불가능 + global activate 검증 어려움. `runX(args) → int` 함수를 `lib/src/cli/`에. bin은 그것만 호출.

### `dart compile exe`로 native asset 누락
build hook으로 생성된 .dll/.so는 `compile exe`에 안 들어감. `dart build cli`로 bundle.

### exit code 누락 → 0으로 끝남
실패 path도 `exit(0)` → CI에서 안 잡힘. usage error 64, runtime error 1, success 0 명시.

### `dart pub global activate --source path`로 검증 안 함
publish 후에야 노출 누락 발견. release 게이트에 path activation 필수.

### `executables:` 키 누락
`dart pub global run pkg:exe`만 동작, `dart pub global run pkg`는 안 됨. 사용자 confusion.

### top-level `main` 시그니처 잘못
`void main()` 인자 없으면 args 못 받음. `void main(List<String> args)` 필수. `Future<void>` 도 OK.

### `Platform.script` 대신 `Platform.executable`
컴파일된 exe와 dart run에서 결과 다름. 보통 `Directory.current` 또는 `Platform.script.toFilePath()`로 entry 위치 잡고, 명시적 인자 우선.

### Windows에서 `compile exe` 후 SmartScreen 경고
서명되지 않은 binary는 warning. publish용이면 codesign 단계 추가.

### `dart_test.yaml`의 `tags: cli:`로 격리 안 함
cli 통합 테스트가 unit 테스트와 같이 돌면 느림. `@Tags(['cli'])` 후 `dart test -t unit`으로 빠른 루프.

## 도구 사용 패턴 (Harness)
- 3 lane 게이트: `Bash("dart run :mycli --help && dart compile exe bin/mycli.dart -o /tmp/m.exe && /tmp/m.exe --help")`
- exec 등록 검증: `Read pubspec.yaml` → `executables:` 섹션 vs `bin/` glob
- bin 두께 측정: `Glob("bin/*.dart")` + 각 파일 line count → 50줄 이상이면 lib 분리 신호
- global activate: `Bash("dart pub global activate --source path . --overwrite && dart pub global run pkg:exe --help")`
- exit code 점검: `Grep("exit\\(", glob="bin/**/*.dart")` 와 `lib/src/cli/**/*.dart`
