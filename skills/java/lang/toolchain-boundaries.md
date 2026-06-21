---
name: toolchain-boundaries
description: Java 컴파일 타깃 플래그(--release/-source/-target)와 jdeps 의존성 표면을 단일 리뷰 단위로 다룬다
keywords: java toolchain release source target jdeps module-boundary internal-api
intent: review verify pin-target audit-dependency-surface
paths: pom.xml build.gradle build.gradle.kts settings.gradle.kts .mvn/jvm.config
patterns: javac jdeps maven gradle
requires:
phase: plan implement review deploy
tech-stack: java
min_score: 2
---

# Toolchain Boundaries (release / source-target / jdeps)

> Treat compile target, language level, and dependency surface as one review unit — not three separate flags.

## 의사결정 트리

### IF Java 버전 업그레이드를 검토 중 (Plan|Review)
1. 현재 빌드의 `--release`(또는 `-source`/`-target`) 값을 먼저 확정 — `mvn -X` / `gradle --info`로 실제 전달되는 플래그 확인
2. `--release` 단일 플래그로 통일 — Oracle 마이그레이션 가이드는 `-source`/`-target` 분리 사용보다 `--release`를 명시적으로 권고
3. `jdeps -jdkinternals <jar>`로 내부 API 사용처 식별. 정적 분석이라 reflection 경로는 못 잡으므로 통합 테스트 병행
4. 빌드 도구·IDE·주요 라이브러리가 모두 타깃 JDK 라인을 지원하는지 확인 — "내 머신에서 컴파일된다"는 버전 정책이 아님

### IF "왜 CI에서만 실패하는가?" 디버깅 (Debug|Review)
1. `java -version`이 아닌 전체 toolchain (Maven/Gradle 버전, IDE 버전, 컴파일 JDK ≠ 런타임 JDK 가능성) 비교
2. 동일 `--release` 플래그가 양쪽에 흐르는지 — 환경마다 다른 default가 깔리는지 확인
3. `jdeps`로 새로 추가된 의존성이 `jdk.internal.*` 같은 비공개 API를 끌어왔는지 점검

### IF 의존성 surface가 변경됨 (Implement|Review)
1. 언어 업그레이드와 동일한 멘탈 모델로 리뷰 — 새 라이브러리가 더 높은 bytecode를 요구하면 타깃을 깨거나, 내부 API를 끌어옴
2. `jdeps` 결과를 PR 첨부 — split-package, banned/unstable 의존성 등을 release-time이 아닌 PR 단계에서 차단

## Gotchas

### `--release`와 `-source`/`-target` 혼용
- 두 가지를 동시에 지정하면 빌드 도구마다 우선순위가 달라 silent drift 발생. `--release`로 단일화.

### "jdeps가 깨끗하니 안전하다"
- jdeps는 정적. reflection·`MethodHandles.Lookup`·`Unsafe`·서비스 로더는 못 봄. 실제 통합 테스트로 보완.

### 로컬 컴파일 성공 = 호환성 보장 (X)
- 로컬 JDK가 더 신형이면 신 API를 써도 컴파일은 통과. 빌드에 `--release` 명시가 없으면 운영 JDK에서만 깨짐.

## Source

- `languages/java/17/08_know-how/2026-04-26__local-java__treat-release-source-target-and-jdeps-surface-as-one-review-unit__17.md`
- `languages/java/17/06_templates/2026-04-26__local-java__java-toolchain-preview-policy-template-with-release-and-source-target-guard__17.md`
- `languages/java/25/06_templates/2026-04-26__local-java__java-jdeps-module-boundary-template-with-internal-package-and-unstable-dependency-guard__25.md`
- `languages/java/25/07_troubleshooting/2026-04-19__oracle-docs__preview-features-toolchains-and-migration-troubleshooting__25.md`
- `languages/java/25/08_know-how/2026-04-19__oracle-docs__preview-boundaries-release-flag-and-small-tooling-habits__25.md`
