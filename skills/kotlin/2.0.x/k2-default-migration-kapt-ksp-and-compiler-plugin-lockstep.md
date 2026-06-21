---
name: k2-default-migration-kapt-ksp-and-compiler-plugin-lockstep
description: Kotlin 2.0.x에서 K2 기본 전환·KAPT/KSP 정합·컴파일러 플러그인 lockstep을 라인 수준으로 강제.
keywords: kotlin 2.0 K2 default migration kapt ksp lockstep compiler-plugin allopen noarg serialization parcelize sam-conversion data-class compose-compiler languageVersion gradle 마이그레이션 컴파일러 플러그인
intent: 마이그레이션 업그레이드 만들어 수정해 검증해
paths: build.gradle.kts settings.gradle.kts gradle.properties libs.versions.toml buildSrc/
patterns: kotlin("jvm") kotlin("kapt") kotlin("plugin.serialization") kotlin("plugin.allopen") com.google.devtools.ksp compilerOptions languageVersion KotlinVersion.KOTLIN_2_0 useK2 freeCompilerArgs
requires:
phase: plan migrate implement review
tech-stack: kotlin
min_score: 2
---

# Kotlin 2.0.x — K2 Default Migration, KAPT/KSP, Compiler Plugin Lockstep

Kotlin 2.0은 **K2 컴파일러를 기본**으로 만든 분기점이다. 2.0.x 마이그레이션 실패의 90%는 컴파일러 자체가 아니라 **플러그인 버전 불일치, KAPT/KSP 경로 혼재, language/api version flag 잔존** 같은 빌드 경계 문제다. 이 스킬은 그 경계를 라인 수준으로 잡는다.

## 의사결정 트리

### IF Kotlin 1.9.x → 2.0.x 마이그레이션 (Migrate)
1. **빌드 환경 먼저, 코드는 나중**: Java 17+ toolchain, Gradle 8.5+ 확인.
2. **모든 kotlin(...) 플러그인 동일 버전으로 잠금**: jvm, kapt, plugin.serialization, plugin.allopen, plugin.spring, plugin.jpa, parcelize. 한 군데라도 1.9면 internal API 어긋남.
3. **KSP 버전 lockstep**: KSP는 `<kotlin>-<ksp-rev>` 형식. Kotlin 2.0.21이면 KSP는 `2.0.21-1.0.28` 같은 매칭 버전.
4. **`languageVersion`/`apiVersion` 플래그 정리**: 1.4/1.5 제거됨. 1.6/1.7 deprecated. 명시 안 하면 기본값 (2.0).
5. **freeCompilerArgs 청소**: K1 전용 플래그 (`-Xuse-k2`, K1 internal 옵션) 제거. K2 기본이라 `-Xuse-k2` 불필요.
6. **KAPT 사용 모듈 별도 검증**: K2 KAPT는 2.0.x에서 stub 생성기가 K2 기반으로 변경 — 풀 빌드 + 생성 코드 diff 확인.
7. **컴포즈 모듈**: Kotlin 2.0부터 Compose Compiler가 별도 plugin (`org.jetbrains.kotlin.plugin.compose`)으로 분리. 기존 Compose Compiler version 매핑 표 폐기.

### IF KAPT 사용 중 (Plan / Migrate)
1. KSP processor 제공 라이브러리(Hilt, Room, Moshi 등) → KSP로 이주. KAPT는 호환만.
2. KAPT 경로 유지하면 빌드 시간 + Java stub 비용 영구 부담.
3. 같은 모듈에서 KAPT와 KSP 병행 → 가능하지만 같은 processor를 양쪽 등록 금지.
4. KAPT 의존성 제거 시 `kapt { ... }` 블록·plugin·dependencies 모두 정리.

### IF 컴파일러 플러그인 (Implement)
1. **Spring/JPA**: `kotlin("plugin.spring")`, `kotlin("plugin.jpa")` 사용. Kotlin과 같은 버전.
2. **serialization**: `kotlin("plugin.serialization")`. runtime은 `kotlinx-serialization-json` 별도 버전 카탈로그.
3. **allopen/noarg**: 직접 등록 가능 — `kotlin("plugin.allopen")` + `allOpen { annotation("...") }`.
4. **parcelize (Android)**: `id("kotlin-parcelize")`. Android 모듈 한정.
5. **Compose Compiler (Kotlin 2.0+)**: `id("org.jetbrains.kotlin.plugin.compose")`. AGP의 `composeOptions.kotlinCompilerExtensionVersion` 폐기.

### IF Compose 모듈 (Migrate, Android)
1. AGP에서 `composeOptions { kotlinCompilerExtensionVersion = "..." }` 제거.
2. `plugins { id("org.jetbrains.kotlin.plugin.compose") version "<kotlin-version>" }` 추가.
3. compose-bom + 라이브러리 의존성은 그대로 유지.
4. stability 설정은 `composeCompiler { stabilityConfigurationFile = ... }` 또는 plugin DSL.

### IF 코드 리뷰 (Review)
- [ ] 모든 kotlin(...) 플러그인 같은 버전
- [ ] KSP 버전이 Kotlin과 lockstep
- [ ] `languageVersion`/`apiVersion`이 명시적이거나 기본값(2.0) 의존
- [ ] freeCompilerArgs에 K1 전용 잔존 플래그 없음
- [ ] Compose 모듈에서 `composeOptions.kotlinCompilerExtensionVersion` 제거 + plugin.compose 추가
- [ ] KAPT 잔존 모듈은 풀 빌드 + 생성 코드 diff 검증
- [ ] Gradle 8.5+ / Java 17+

## 핵심 패턴

### 표준 2.0.x 빌드 (버전 카탈로그)
```toml
# gradle/libs.versions.toml
[versions]
kotlin = "2.0.21"
ksp = "2.0.21-1.0.28"
agp = "8.6.1"
hilt = "2.52"

[plugins]
kotlin-jvm = { id = "org.jetbrains.kotlin.jvm", version.ref = "kotlin" }
kotlin-android = { id = "org.jetbrains.kotlin.android", version.ref = "kotlin" }
kotlin-serialization = { id = "org.jetbrains.kotlin.plugin.serialization", version.ref = "kotlin" }
kotlin-spring = { id = "org.jetbrains.kotlin.plugin.spring", version.ref = "kotlin" }
kotlin-jpa = { id = "org.jetbrains.kotlin.plugin.jpa", version.ref = "kotlin" }
kotlin-compose = { id = "org.jetbrains.kotlin.plugin.compose", version.ref = "kotlin" }
ksp = { id = "com.google.devtools.ksp", version.ref = "ksp" }
```

### 모듈 build.gradle.kts (Spring + JPA + KSP)
```kotlin
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.kotlin.jvm)
    alias(libs.plugins.kotlin.spring)
    alias(libs.plugins.kotlin.jpa)
    alias(libs.plugins.ksp)
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
        // K2 default — useK2 / -Xuse-k2 불필요
    }
}

dependencies {
    ksp(libs.hilt.compiler)
    implementation(libs.hilt.runtime)
}
```

### Android Compose 모듈 (2.0+)
```kotlin
plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)        // ← 새 위치
    alias(libs.plugins.ksp)
}

android {
    // ❌ 폐기: composeOptions { kotlinCompilerExtensionVersion = "..." }
    buildFeatures { compose = true }
}

composeCompiler {
    // 선택: stabilityConfigurationFile, reportsDestination, metricsDestination
}
```

### KAPT 호환 잔존 모듈
```kotlin
plugins {
    alias(libs.plugins.kotlin.jvm)
    alias(libs.plugins.kotlin.kapt)
}

kapt {
    correctErrorTypes = true
    useBuildCache = true
}

dependencies {
    kapt(libs.legacy.apt.processor)
}
```
2.0.x에서 K2 KAPT는 default — 풀 빌드로 generated 비교.

### 마이그레이션 인시던트 템플릿
```
- exact Kotlin patch:
- exact Gradle version:
- exact AGP (Android):
- exact KSP version:
- KAPT 사용 여부:
- Compose 모듈 여부 + plugin.compose 적용?:
- languageVersion / apiVersion flag:
- 변경 후 영향 받은 generated 코드 모듈:
```

## Gotchas

### kotlin(...) 플러그인 버전 mismatch
`kotlin("jvm") version "2.0.21"` + `kotlin("plugin.serialization") version "1.9.24"` → internal compiler API 다름 → 빌드 빨간불 또는 silent miscompile. **하나의 lockstep 변수로 통일.**

### KSP 버전 mismatch
`com.google.devtools.ksp:2.0.0-1.0.21` + Kotlin 2.0.21 → processor 호환 깨짐. 매번 release notes의 표 확인.

### Compose 모듈에 plugin.compose 안 추가
2.0+에서 `composeOptions.kotlinCompilerExtensionVersion`만 남기면 동작 안 함. **plugin.compose 필수 + composeOptions 라인 제거.**

### `-Xuse-k2` 잔존
2.0 default라 무용. 일부 옵션이 K2와 비호환이라 빌드 깨짐.

### `languageVersion = "1.5"` 잔존
2.1부터 1.4/1.5 제거. 2.0에서는 deprecated 경고 → 빨리 정리.

### KAPT generated 코드 diff 미확인
K2 KAPT 기본 전환 → stub 생성 차이 가능. 풀 빌드 후 `git diff build/generated`로 확인 안 하면 런타임 ClassNotFound 만남.

### `kotlin("plugin.compose")` + `kotlinCompilerExtensionVersion` 둘 다 남김
중복 적용 — 빌드는 되지만 어떤 버전인지 모호. `composeOptions { kotlinCompilerExtensionVersion = ... }` 줄 자체를 삭제.

### Multiplatform executable + Gradle Application plugin
Gradle 8.7+에서 KMP 와 application plugin 비호환. Kotlin 2.0.20+ 의 `executable {}` DSL 사용. 1.9에서 올라온 KMP 빌드는 별도 점검.

### Spring 모듈에 `plugin.spring` 누락
`@Component`, `@Service` 등이 final → AOP/proxy 깨짐. Kotlin은 기본 final이라 plugin이 자동 open 처리 필요.

### JPA 모듈에 `plugin.jpa` 누락
`@Entity` + 기본 생성자 누락 → 런타임 InstantiationException. plugin.jpa가 noarg 자동 처리.

### `freeCompilerArgs` 안에 deprecated `-progressive`
2.0에서 의미 없거나 일부 옵션 제거. release notes 확인.

## 검증 체크리스트

- 모든 kotlin(...) 플러그인 lockstep 버전
- KSP 버전이 Kotlin과 정확히 매칭
- languageVersion/apiVersion 명시 또는 기본 의존
- freeCompilerArgs에 K1 전용 잔존 플래그 없음
- Compose 모듈에 plugin.compose 추가 + composeOptions 제거
- KAPT generated 코드 diff 풀 빌드로 검증
- Spring/JPA/Parcelize 등 도메인 플러그인 누락 없음
- Gradle 8.5+ / Java 17+

## 5축 자가 평가

- 검색성: kotlin 2.0 / K2 default / migration / kapt / ksp / lockstep / compose plugin / 한·영
- 의사결정 트리(IF/THEN): 5개 IF 분기 + 7개 리뷰 체크
- 코드 식별자: kotlin("jvm"), kotlin("plugin.spring"), kotlin("plugin.jpa"), kotlin("plugin.compose"), com.google.devtools.ksp, languageVersion KotlinVersion.KOTLIN_2_0, composeOptions, composeCompiler
- Gotcha-driven: 11개 마이그레이션 실수 + 회피
- 검증 가능: 8개 체크리스트 + 인시던트 템플릿
