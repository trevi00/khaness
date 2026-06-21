---
name: toolchain-lockstep-ksp-kapt-compose-and-native-release-review
description: Kotlin 2.1.x 툴체인 lockstep — Kotlin/Gradle/AGP/KSP/KAPT/Compose/Native/Xcode 버전 정합성과 K2 default 변화 리뷰를 라인 코드로 강제.
keywords: kotlin 2.1 2.1.20 2.1.21 toolchain lockstep gradle agp ksp kapt k2 compose-compiler kotlin-native xcode 16.3 application-plugin executable-dsl preview-flag language-version 1.6 1.7 minor-line patch-release migration whatsnew compatibility-guide 툴체인 정합성 마이그레이션
intent: 업그레이드 마이그레이션 추가해 적용해 검증해 디버그 잠금
paths: build.gradle.kts settings.gradle.kts gradle/libs.versions.toml gradle.properties gradle/wrapper/gradle-wrapper.properties .github/workflows/ ci/ buildSrc/
patterns: kotlin("multiplatform") kotlin-android com.google.devtools.ksp kotlin-kapt org.jetbrains.kotlin.plugin.compose kotlin.compiler.kapt.useK2 kotlin.experimental.tryK2 -Xskip-prerelease-check languageVersion apiVersion KotlinVersion executable jvmToolchain compose-compiler-extension applyDefaultHierarchyTemplate
requires:
phase: plan migrate review debug
tech-stack: kotlin
min_score: 2
---

# Kotlin 2.1.x — Toolchain Lockstep & K2/KAPT/Compose/Native Release Review

Kotlin 2.1.x에서 빌드가 깨지는 원인의 90%는 비즈니스 코드가 아니라 **(1) Kotlin patch line × Gradle × AGP × KSP × Compose compiler × Xcode의 lockstep 깨짐**, **(2) preview feature flag 누락**, **(3) K2 kapt default 전환 (2.1.20+)에 따른 생성 코드 변동**이다. 이 스킬은 그 정합성을 라인 단위로 강제한다.

## 의사결정 트리

### IF 새 프로젝트 / 버전 잠금 (Plan)
1. **Kotlin patch line 한 곳에 핀** — `gradle/libs.versions.toml`에 `kotlin = "2.1.21"` 같이 한 줄. `kotlin-multiplatform`, `kotlin-android`, `kotlin-kapt`, `kotlin-plugin-compose` 모두 같은 version 참조.
2. **Java toolchain 17+** — Kotlin 2.1은 JDK 17 이상에서 컴파일. CI/local 동일하게 `jvmToolchain(17)` 명시.
3. **Gradle 호환 매트릭스 검증** — Kotlin 2.1.21 권장 Gradle 8.x 라인. wrapper version 명시.
4. **AGP 호환** — Android 프로젝트면 AGP × Kotlin × KSP 3-way 매트릭스를 docs에서 확인 후 핀.
5. **KSP version 매칭** — KSP는 Kotlin patch에 잠금 (`com.google.devtools.ksp:2.1.21-1.0.X`). KSP 단독 업그레이드 금지.
6. **Compose compiler** — Kotlin 2.0+부터 `org.jetbrains.kotlin.plugin.compose` 별도 plugin. Kotlin version 따라간다.

### IF Kotlin 2.0 → 2.1 마이그레이션 (Migrate)
1. **patch line 결정 먼저** — `2.1.21` (이 KB bucket 기준 권장). `2.1.20`은 K2 kapt default + KMP executable DSL 도입 분기점.
2. **language version flag 정리** — `1.4`/`1.5`는 제거됨. `1.6`/`1.7`은 deprecated. `languageVersion = "2.0"` 또는 미설정으로.
3. **JDK 17+ CI 확인** — `actions/setup-java`에 17 명시.
4. **kapt 잔존 모듈 식별** — 가능하면 KSP로 이전. 못 옮기면 K2 kapt 모드로 full clean build + 생성 코드 diff 검증.
5. **KMP executable 모듈** — Gradle 8.7+ Application plugin 호환 깨짐. Kotlin `executable {}` DSL로 교체.
6. **preview flag opt-in 정책 문서화** — `when` guard, multi-dollar interpolation, non-local break/continue 등.
7. **Native — Xcode 버전 매칭** — Xcode 16.3 사용 시 Kotlin 2.1.21+ 필수.

### IF KSP vs KAPT 선택 (Plan)
1. **신규 처리기 = KSP 우선** — Hilt, Room, Moshi codegen, Dagger 모두 KSP 지원. 빌드 속도 +생성 정확도.
2. **KSP 미지원 처리기만 kapt 유지** — 그 모듈은 격리. K2 kapt default 가정.
3. **kapt + K2 — full clean build 후 생성 결과 비교** — silent 변동 가능 (annotation 인식 차이, parameter name 보존, nullability inference).
4. `kotlin.compiler.kapt.useK2` flag로 명시 제어 가능 — 호환 문제 시 임시 false로 재현.

### IF Compose compiler 사용 (Plan)
1. **Kotlin 2.0+** → `org.jetbrains.kotlin.plugin.compose` plugin 별도 적용. AGP의 composeOptions kotlinCompilerExtensionVersion 더 이상 필요 없음.
2. **Stability config**, **strong skipping**, **compiler reports** 옵션은 plugin DSL의 `composeCompiler { ... }` 블록.
3. Kotlin patch 업그레이드 시 Compose plugin은 자동으로 같은 version. **AGP의 옛날 composeOptions 잔존 라인 제거 필수.**

### IF preview feature 사용 (Implement)
1. `-Xenable-preview-flag` 또는 `languageFeature = "+Feature"` 컴파일 옵션 — 모든 모듈/CI에 동일하게.
2. **shared 코드는 preview 사용 회피 권장** — 한 명 로컬에선 통과, CI에서 깨지는 원인 1위.
3. opt-in 정책을 `decisions.md`에 명시: 어떤 preview 어디까지 허용.

### IF Native (KMP iOS) 빌드 깨짐 (Debug)
1. **patch line 먼저** — Xcode 16.3 = Kotlin 2.1.21+. Xcode upgrade가 먼저면 Kotlin 안 따라감.
2. **stale framework** — `./gradlew clean` + Xcode "Clean Build Folder" + DerivedData 삭제 (`~/Library/Developer/Xcode/DerivedData`).
3. **direct integration script의 archs/configuration/platform** 인자 일치 확인.
4. **KMP executable** + Gradle 8.7 → Application plugin 호환 깨짐. Kotlin `executable {}`로.

### IF CI 실패 트리아지 (Debug)
1. **Incident template 작성** — exact Kotlin patch / exact Gradle / preview features 사용 / kapt or KSP / KMP executable / Xcode version.
2. **로컬 통과 + CI 실패** → preview flag 또는 toolchain 차이 1순위 의심.
3. **patch upgrade 후 생성 코드 변동** → K2 kapt default 가정 후 실증.
4. **생성 코드 / annotation 처리만 의심** — 비즈니스 코드 디버그 전에 toolchain 가설 우선 소거.

### IF 코드 리뷰 (Review)
- [ ] `libs.versions.toml`에 kotlin/gradle/agp/ksp/compose 한곳에 핀
- [ ] KSP version이 Kotlin patch에 매칭 (`X-1.0.Y` 패턴)
- [ ] JDK 17+ toolchain 명시
- [ ] AGP의 옛날 `composeOptions` 라인 제거
- [ ] kapt 모듈 식별 + K2 kapt 가정 + clean build 검증
- [ ] preview feature 사용처 opt-in 명시
- [ ] KMP executable이 Gradle Application plugin 잔존 안 함
- [ ] language version `1.4`/`1.5` 잔존 없음
- [ ] Xcode version과 Kotlin patch 매칭
- [ ] CI에 incident template 활용 트리아지 가이드

## 핵심 패턴

### `libs.versions.toml` lockstep (단일 진실)
```toml
[versions]
kotlin = "2.1.21"
gradle = "8.10.2"
agp = "8.7.2"
ksp = "2.1.21-1.0.27"            # kotlin patch에 매칭
compose-compiler = "2.1.21"       # = kotlin
hilt = "2.52"
room = "2.7.0"

[plugins]
kotlin-multiplatform = { id = "org.jetbrains.kotlin.multiplatform", version.ref = "kotlin" }
kotlin-android       = { id = "org.jetbrains.kotlin.android",       version.ref = "kotlin" }
kotlin-kapt          = { id = "org.jetbrains.kotlin.kapt",          version.ref = "kotlin" }
kotlin-plugin-compose= { id = "org.jetbrains.kotlin.plugin.compose",version.ref = "kotlin" }
ksp                  = { id = "com.google.devtools.ksp",            version.ref = "ksp" }
android-application  = { id = "com.android.application",            version.ref = "agp" }
android-library      = { id = "com.android.library",                version.ref = "agp" }
```

### JDK toolchain 명시
```kotlin
// build.gradle.kts (root or module)
kotlin {
    jvmToolchain(17)
}

// 또는 KMP
kotlin {
    jvmToolchain {
        languageVersion.set(JavaLanguageVersion.of(17))
        vendor.set(JvmVendorSpec.AZUL)
    }
}
```

### Compose compiler plugin (Kotlin 2.0+)
```kotlin
// app/build.gradle.kts
plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.plugin.compose)    // ← 별도 plugin (AGP composeOptions 아님)
}

composeCompiler {
    enableStrongSkippingMode.set(true)
    reportsDestination.set(layout.buildDirectory.dir("compose_compiler"))
    stabilityConfigurationFile.set(rootProject.file("compose_stability.txt"))
}

android {
    buildFeatures { compose = true }
    // composeOptions { kotlinCompilerExtensionVersion = "..." }   ← 삭제. plugin이 처리.
}
```

### KSP migration (kapt → KSP)
```kotlin
plugins {
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.ksp)
    // alias(libs.plugins.kotlin.kapt)              ← 가능하면 제거
}

dependencies {
    ksp(libs.hilt.compiler)                          // kapt(libs.hilt.compiler) → ksp
    ksp(libs.room.compiler)                          // kapt(libs.room.compiler) → ksp
    ksp(libs.moshi.codegen)
}
```

### K2 kapt 명시 제어 (호환 의심 시)
```properties
# gradle.properties — 2.1.20+에서 K2 kapt가 default
kotlin.compiler.kapt.useK2=true   # default
# kotlin.compiler.kapt.useK2=false # 호환 문제 디버그용 임시
```

### KMP executable (Gradle 8.7+)
```kotlin
kotlin {
    jvm {
        // Gradle Application plugin 의존 제거
        // application { mainClass.set("com.example.MainKt") }   ← 이거 안 됨
        binaries {
            executable {                              // Kotlin 2.1.20+ DSL
                mainClass.set("com.example.MainKt")
            }
        }
    }
}
```

### Native — Xcode 정렬 build script
```bash
# Xcode "Run Script" build phase
set -e
EXPECTED_KOTLIN_MIN="2.1.21"
echo "Xcode: ${XCODE_VERSION_ACTUAL}, Kotlin pinned to ${EXPECTED_KOTLIN_MIN}+"
cd "$SRCROOT/.."
./gradlew :shared:embedAndSignAppleFrameworkForXcode \
    -Pkotlin.native.cocoapods.archs=$ARCHS \
    -Pkotlin.native.cocoapods.configuration=$CONFIGURATION \
    -Pkotlin.native.cocoapods.platform=$PLATFORM_NAME
```

### Preview feature opt-in (모듈 일관)
```kotlin
// build-logic의 conventions plugin
tasks.withType<org.jetbrains.kotlin.gradle.tasks.KotlinCompilationTask<*>>().configureEach {
    compilerOptions {
        // 팀 정책에 명시된 preview만
        freeCompilerArgs.addAll(
            "-Xwhen-guards",
            "-Xmulti-dollar-interpolation",
        )
    }
}
```

### Incident report template
```yaml
# kept in repo as docs/build-incident-template.md
exact_kotlin_patch:    # e.g. 2.1.21
exact_gradle:          # e.g. 8.10.2
exact_agp:             # e.g. 8.7.2
exact_ksp:             # e.g. 2.1.21-1.0.27
preview_features_used: # yes/no, which
annotation_path:       # kapt | ksp | both
kmp_executable:        # yes/no
xcode_version:         # e.g. 16.3
ci_or_local:           # both? only one?
clean_build_done:      # yes/no
gradle_clean_done:     # yes/no
xcode_clean_done:      # yes/no (DerivedData)
```

## Gotchas

### `libs.versions.toml`에 kotlin은 핀했는데 `kotlin-kapt` plugin은 다른 version
sub-plugin 버전 mismatch — 컴파일 단계에서 cryptic error. 항상 `version.ref = "kotlin"`.

### KSP version을 Kotlin과 다르게 핀
`2.1.21-1.0.27` 같은 패턴 — 앞이 Kotlin patch와 정확히 일치해야 함. 단독 KSP 업그레이드 금지.

### AGP `composeOptions { kotlinCompilerExtensionVersion = ... }` 잔존
Kotlin 2.0+에선 무시 또는 충돌. plugin DSL의 `composeCompiler { ... }`가 우선.

### `kapt`로 빌드 통과인데 patch upgrade 후 생성 코드 미세 변동
2.1.20+에서 K2 kapt가 default. annotation 인식, parameter name, nullability inference 미세 차이. **clean build + diff 비교 필수.**

### Multiplatform executable 빌드가 갑자기 안 됨
Gradle 8.7+에서 Application plugin 호환 깨짐. Kotlin `executable {}` DSL로 교체.

### `languageVersion = "1.5"` 또는 `1.4` 잔존
2.1에서 제거됨. CI에서 cryptic 실패. flag 정리.

### preview syntax (`when` with guard)를 한 명만 사용 → 다른 모듈에서 컴파일 실패
preview flag가 모듈마다 따로 설정. **build-logic conventions plugin에 모듈 공통으로 강제.**

### Xcode 16.3로 업그레이드했는데 Kotlin 2.1.20에 머무름
Xcode 16.3 지원은 2.1.21부터. Kotlin/Native 빌드 cryptic 실패 → patch line 먼저 의심.

### direct integration 빌드에서 Kotlin 변경 안 반영
stale framework. `./gradlew clean` + Xcode Clean Build Folder + DerivedData 삭제 — 셋 다.

### CI에서만 깨지고 로컬은 통과
preview flag 차이 / JDK 차이 / Gradle wrapper 차이 / Xcode 차이 — Incident template로 격자식 비교.

### kapt processor 1개 때문에 전체 모듈 K2 kapt 가정 회피
그 processor만 격리 모듈로 분리. 전체 모듈 K2 kapt 거부 → 빌드 속도 손실 + 미래 호환 부채.

### Compose strong skipping mode 켜고 stability config 비워둠
external lib의 unstable 타입이 무한 recompose 유발. `stabilityConfigurationFile` 명시 + Compose compiler reports로 검증.

### `kotlinOptions { jvmTarget = "1.8" }` (deprecated 표면 잔존)
Kotlin 2.0+ → `compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }`. 또는 `jvmToolchain(17)` 한 줄.

### KSP / kapt 처리기 dependency만 업그레이드, plugin은 그대로
runtime은 새 처리기, plugin은 옛날 protocol — symbol 인식 깨짐. 처리기와 plugin 같은 line 매칭.

## 검증 체크리스트

- libs.versions.toml에 kotlin/gradle/agp/ksp/compose 단일 핀
- KSP version이 Kotlin patch에 매칭 (`X-1.0.Y`)
- jvmToolchain(17) 또는 동급 명시
- AGP composeOptions 옛날 라인 제거 + composeCompiler {} plugin DSL 사용
- kapt 모듈 K2 kapt 가정 + clean build + 생성 코드 diff 검증
- preview feature opt-in 정책 conventions plugin에 코드화
- KMP executable이 Kotlin executable {} DSL 사용
- language version 1.4/1.5 잔존 없음, 1.6/1.7 deprecation 인지
- Xcode version 16.3 사용 시 Kotlin 2.1.21+
- CI 실패 트리아지에 incident template 활용

## 5축 자가 평가

- 검색성: kotlin / 2.1 / toolchain / lockstep / ksp / kapt / k2 / compose / native / xcode / 한·영 키워드
- 의사결정 트리(IF/THEN): 8개 IF + 10개 리뷰 체크
- 코드 식별자: libs.versions.toml, jvmToolchain, kotlin.compiler.kapt.useK2, composeCompiler, executable {}, embedAndSignAppleFrameworkForXcode, KotlinCompilationTask, freeCompilerArgs, applyDefaultHierarchyTemplate
- Gotcha-driven: 14개 흔한 실수 + 회피
- 검증 가능: 10개 체크리스트 + incident template
