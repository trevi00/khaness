---
name: gradle-nebula-multi-project
description: Gradle 8.14+ multi-project — Kotlin DSL, version catalog, custom plugin, Nebula 패턴, configuration cache
keywords: gradle nebula kotlin-dsl version-catalog custom-plugin convention-plugin configuration-cache build-cache toolchain
intent: design-multi-project author-custom-plugin enable-configuration-cache lock-dependencies migrate-groovy-to-kotlin
paths: build.gradle.kts settings.gradle.kts buildSrc build-logic gradle/libs.versions.toml
patterns: Plugin<Project> includeBuild libs.versions.toml java-gradle-plugin
requires: api-contracts virtual-threads
phase: plan implement review debug
tech-stack: java
min_score: 2
quality_axes_enforced: true
---

# Gradle + Nebula Multi-Project (8.14+)

> 핵심: Gradle 8.2+ Kotlin DSL이 default. Multi-project 구조는 **`buildSrc` (auto-included) 또는 `build-logic` (composite build)** 둘 중 하나에 convention plugin 두기. Nebula는 Netflix가 만든 plugin 모음 (publishing/dependency-lock/info/release).

## 의사결정 트리

### IF Gradle 신규 프로젝트 (Plan)
1. version pin — Gradle 8.14.3 (current series). 9.0 milestone — JDK 17+ 필수
2. DSL — **Kotlin DSL** (default since 8.2). Groovy DSL은 legacy 유지보수만
3. JDK toolchain — `java { toolchain { languageVersion = JavaLanguageVersion.of(21) } }` 명시 (host JDK drift 차단)
4. version catalog — `gradle/libs.versions.toml` 생성 → `libs.springBoot`, `libs.kotlin` 등 type-safe accessor

### IF Multi-project 구조 (Implement)
```
settings.gradle.kts:
  rootProject.name = "myapp"
  include("app", "core", "data")
  includeBuild("../shared-lib")   // composite build

gradle/libs.versions.toml:
  [versions]
  spring = "3.5.0"
  [libraries]
  spring-boot = { module = "org.springframework.boot:spring-boot-starter", version.ref = "spring" }
  [plugins]
  spring-boot = { id = "org.springframework.boot", version.ref = "spring" }
```

### IF Custom plugin 작성 (Implement)
선택지 2가지:
1. **`buildSrc/`** — auto-included, root buildscript classloader 공유. 작은 프로젝트에 적합
2. **`build-logic/` (composite build)** — included build, classloader 격리. 공유성/재사용 우선이면 권장

```kotlin
// build-logic/src/main/kotlin/conventions/JavaConventionsPlugin.kt
class JavaConventionsPlugin : Plugin<Project> {
    override fun apply(project: Project) {
        project.plugins.apply("java")
        project.tasks.withType<Test> { useJUnitPlatform() }
    }
}
```
사용처: `plugins { id("conventions.java") }`.

### IF Nebula 도입 결정 (Plan)
| 신호 | Nebula plugin |
|---|---|
| Maven publishing 표준화 | `nebula-publishing-plugin` |
| 모든 의존성 lockfile (재현성) | `gradle-dependency-lock-plugin` (`generateLock`/`saveLock`) |
| JAR에 SCM/CI manifest 주입 | `gradle-info-plugin` |
| 자동 버전 + tag | `nebula.release` |

### IF Configuration cache 활성 (Implement)
1. `org.gradle.configuration-cache=true` in `gradle.properties`
2. **task action에서 `Project` 접근 금지** — `Provider`/`@Input` properties로
3. `System.getenv` / 절대경로 / timestamp는 `@Internal` 또는 normalize
4. 기존 plugin 호환성 — `--no-configuration-cache`로 점진 전환

## 가이드

- build cache 안정성 — `@Input` 정확하게 표시, `@InputFiles` 경로 normalization
- Kotlin DSL 빌드 시간 — IDE 첫 동기화 느림. `kotlin-dsl` plugin 활성으로 빠른 type inference
- plugin 발행 — `java-gradle-plugin` + `gradlePlugin { plugins { create(...) } }` 블록

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | toolchain 명시로 host JDK 드리프트 차단 |
| 성능 효율성 | configuration cache + build cache로 재실행 시간 ↓ |
| 호환성 | version catalog로 모든 모듈 동일 의존성 버전 |
| 사용성 | convention plugin 1줄로 모듈 boilerplate 제거 |
| 신뢰성 | dependency-lock-plugin lockfile로 빌드 재현성 |
| 보안 | nebula-publishing POM hardening + 서명 |
| 유지보수성 | composite build + Kotlin DSL로 type-safe refactor |
| 이식성 | toolchain auto-download로 CI runner JDK 무관 |
| 확장성 | custom plugin으로 도메인 convention 추가 |

## Gotchas

### Configuration cache + Project 접근
task action에서 `project.someProperty` 직접 접근 → cache miss + 경고. `Provider`로 wrap, `@Input` annotation 사용.

### buildSrc + 절대경로 input
buildSrc compile 결과가 절대경로 의존 → CI 머신 변경 시 cache 무효. `@Input` 대신 `@Internal` 또는 path normalization.

### 의존성 lockfile 없이 운영
같은 commit이 다른 시점에 빌드되면 transitive dependency 다른 버전. `gradle-dependency-lock-plugin` 또는 Gradle 자체 lockfile 활성.

### plugin classloader conflict
`buildSrc`와 root `buildscript`가 classloader 공유 — Kotlin/Gradle metadata 버전 mismatch 시 NoSuchMethodError. composite build로 격리.

### Cyclic project dependency
Gradle configuration phase에서 fail. api/implementation split 또는 abstraction module 추가.

### Gradle 9.x로 업그레이드 후 JDK 11 사용
9.x는 JDK 17+ 필수. CI runner / 로컬 JDK 동시 업그레이드.

## Source

- https://docs.gradle.org/current/userguide/userguide.html — Gradle 8.x current series, 조회 2026-05-10
- https://docs.gradle.org/current/userguide/multi_project_builds.html — settings.gradle, includeBuild, 조회 2026-05-10
- https://docs.gradle.org/current/userguide/platforms.html — version catalog `libs.versions.toml`, 조회 2026-05-10
- https://docs.gradle.org/current/userguide/custom_plugins.html — Plugin<Project> 패턴, 조회 2026-05-10
- https://docs.gradle.org/current/userguide/configuration_cache.html — task action 제약, 조회 2026-05-10
- https://docs.gradle.org/current/userguide/toolchains.html — `java { toolchain { ... } }` 명시, 조회 2026-05-10
- https://github.com/nebula-plugins — Netflix Nebula plugin org (publishing/dependency-lock/info/release), 조회 2026-05-10
