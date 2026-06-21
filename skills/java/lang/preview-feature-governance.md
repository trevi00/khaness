---
name: preview-feature-governance
description: Java preview 기능을 "운영 정책"으로 다룬다 — 빌드/런타임 플래그·release pinning·코드 라벨링
keywords: preview enable-preview release jdk25 governance feature-flag
intent: gate-preview pin-release label-experimental separate-permanent-from-preview
paths: pom.xml build.gradle build.gradle.kts
patterns: javac java --enable-preview --release
requires: toolchain-boundaries
phase: plan implement review deploy
tech-stack: java
min_score: 2
---

# Preview Feature Governance

> Preview는 문법 옵션이 아니다 — 빌드·런타임·팀 정책 세 면에서 동시에 결정되는 운영 경계다.

## 의사결정 트리

### IF preview 기능 채택 검토 (Plan|Review)
1. 같은 목적을 영구(permanent) 기능으로 달성 가능한가? — Java 25의 영구 목록(compact source files, instance main, flexible constructor bodies, scoped values)을 먼저 사용
2. 정말 preview만 가능하면(예: `StructuredTaskScope`) 코드/빌드/문서에 명시적으로 라벨링
3. 빌드와 실행 양쪽에 `--enable-preview` 흐르는지 확인 — `javac --enable-preview --release 25`, `java --enable-preview`

### IF "로컬에서는 컴파일되는데 CI에서는 깨진다" (Debug)
1. 로컬 JDK·CI JDK 버전 일치 여부, `--enable-preview`가 양쪽 빌드 명령에 모두 있는지 확인
2. preview-dependent 클래스 파일은 해당 release에 묶임 — 21에서 빌드한 preview 산출물을 25 JVM에 그대로 옮길 수 없음
3. preview를 generic 예제에 섞지 않았는지 — "Java 25 example"로 보이지만 실제로 preview 의존인 케이스가 있음

### IF 마이그레이션 (Java 17/21 → 25) (Plan|Deploy)
1. 먼저 JDK 25로 실행만 시도 (Oracle migration guide의 "run-first") — 무조건 재컴파일하지 않는다
2. 비활성/제거된 VM 옵션 경고 확인 → 라이브러리·빌드도구·IDE 호환성 → `--release` 정착
3. preview 의존 코드를 별도 모듈/소스셋으로 격리 — 누가 preview를 쓰는지 빌드에서 보이게 한다

## 가이드

- code review에서 영구 기능과 preview 기능을 같은 PR에 섞지 않는다 — 분리해 리뷰해야 정책 결정이 보존됨.
- preview 정책은 README/CONTRIBUTING에 한 줄로 — "preview 사용 금지" 또는 "허용 영역: `experimental/*`".

## Gotchas

### "이미 컴파일됐으니 운영 가능"
- preview는 impermanent. 다음 JDK에서 시그니처/의미가 바뀔 수 있고 클래스파일 호환도 보장되지 않는다.

### preview를 baseline 템플릿에 silent 채택
- 신규 개발자가 무의식적으로 복사 → 점진적으로 코드베이스 전체가 preview 의존이 된다.

### `--source`/`--target` 만으로 preview 활성화 시도
- preview는 `--enable-preview` 단독 플래그. release 플래그와 별개로 명시되어야 함.

## Source

- `languages/java/25/04_usage/2026-04-19__oracle-docs__module-imports-compact-source-and-preview-boundaries__25.md`
- `languages/java/25/07_troubleshooting/2026-04-19__oracle-docs__preview-features-toolchains-and-migration-troubleshooting__25.md`
- `languages/java/25/08_know-how/2026-04-19__oracle-docs__preview-boundaries-release-flag-and-small-tooling-habits__25.md`
- `languages/java/25/05_patterns/2026-04-19__oracle-docs__scoped-values-structured-concurrency-and-preview-boundaries__25.md`
- `languages/java/25/10_migrations/2026-04-19__oracle-docs__migrating-from-21-to-25-and-preview-policy__25.md`
