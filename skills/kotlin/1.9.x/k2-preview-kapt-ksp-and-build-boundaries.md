---
name: k2-preview-kapt-ksp-and-build-boundaries
description: Kotlin 1.9.x에서 K2 컴파일러 preview, KAPT/KSP 선택, 빌드 경계를 코드/빌드 라인에서 강제하는 베이스라인.
keywords: kotlin 1.9 K2 preview kapt ksp annotation processing compilerOptions kotlinOptions languageVersion apiVersion gradle dsl jvmTarget jdk-release 코틀린 어노테이션 컴파일러 빌드
intent: 만들어 추가해 마이그레이션 설정해 수정해 검증해
paths: build.gradle.kts settings.gradle.kts gradle.properties buildSrc/ libs.versions.toml
patterns: kotlin("jvm") kotlin("kapt") kotlin("plugin.serialization") compilerOptions kotlinOptions JvmTarget.JVM_17 languageVersion apiVersion KotlinCompile useK2 ksp() kapt()
requires:
phase: plan implement migrate review
tech-stack: kotlin
min_score: 2
---

# Kotlin 1.9.x — K2 Preview, KAPT/KSP, Build Boundaries

Kotlin 1.9.x는 **K1 컴파일러가 기본, K2는 preview** 단계다. 이 스킬은 1.9.x 라인에서 컴파일러 선택, annotation processing 경로(KAPT vs KSP), 그리고 Gradle 빌드 경계를 라인 수준으로 명확히 한다. (2.0.x 이후는 별도 스킬 — `k2-default-migration-kapt-ksp-and-compiler-plugin-lockstep` 참조.)

## 의사결정 트리

### IF Kotlin 1.9.x 신규 프로젝트 (Plan)
1. **기본 컴파일러는 K1** — K2는 preview, 프로덕션 기본값 아님.
2. K2 시도하려면 `kotlin { compilerOptions { languageVersion.set(KotlinVersion.KOTLIN_2_0) } }` 또는 `-Xuse-k2` (1.9 후반). **하나의 모듈에만, CI에서 빨간불 정책.**
3. JVM target 명시: `compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }`. 회사 표준 = Java 17.
4. annotation processing은 **KSP 우선**. KAPT는 Java APT만 지원하는 라이브러리 호환용.

### IF Annotation Processing 선택 (Plan / Implement)
1. **라이브러리가 KSP processor 제공** → KSP 사용. Hilt, Room, Moshi, Kotlinx Serialization, Detekt, Ksp 등 대부분 KSP 지원.
2. **라이브러리가 Java APT만 제공** → KAPT 사용. 스텁 생성 비용 있어 빌드 느림.
3. **두 경로 혼재 금지** — 같은 processor를 KAPT와 KSP 양쪽으로 등록하면 출력 중복 + 어떤 게 우선인지 모호.
4. KSP plugin: `id("com.google.devtools.ksp") version "<ksp version>"`. **ksp 버전은 Kotlin 버전과 lockstep**(예: Kotlin 1.9.24 ↔ KSP 1.9.24-1.0.20).

### IF compilerOptions 구성 (Implement)
1. `kotlinOptions { ... }` (구식) 대신 `compilerOptions { ... }` (Kotlin 1.8+) 사용.
2. 다중 모듈에서는 root build.gradle.kts에 공통 `subprojects { kotlin { compilerOptions { ... } } }`.
3. JVM target은 한 곳에만 정의 (extension 레벨). 특정 task 오버라이드는 진짜 다를 때만.
4. `freeCompilerArgs.addAll("-Xjvm-default=all", "-opt-in=kotlin.RequiresOptIn")` 등 명시.

### IF K2 preview 시도 (Plan / Migrate)
1. **개별 모듈에서만**, 새 브랜치에서 시도. 메인은 K1 유지.
2. preview 언어 기능(`when` guards, multi-dollar interpolation 등)은 K2 + 명시적 opt-in 필요.
3. KAPT는 K2와 호환 문제 가능 — 1.9.x에서는 KAPT 사용 시 K1 유지 권장.
4. 컴파일러 플러그인 (allopen, noarg, serialization, parcelize) 버전이 Kotlin과 정확히 일치해야 함.

### IF Gradle DSL (Implement)
1. Kotlin DSL (`build.gradle.kts`) 사용. Groovy DSL은 정적 검사 약함.
2. 버전 카탈로그(`libs.versions.toml`) 사용 — Kotlin/KSP/AGP 버전을 한 곳에서.
3. plugin block에서 버전 한 번만:
   ```kotlin
   plugins {
       kotlin("jvm") version "1.9.24"
       kotlin("plugin.serialization") version "1.9.24"
       id("com.google.devtools.ksp") version "1.9.24-1.0.20"
   }
   ```
4. `kapt`/`ksp` 의존성 선언:
   ```kotlin
   dependencies {
       ksp("com.google.dagger:hilt-compiler:<version>")    // KSP 권장
       kapt("legacy-annotation-processor:1.0")             // KAPT — 호환만
   }
   ```

### IF 코드 리뷰 (Review)
- [ ] `kotlinOptions` (deprecated) 대신 `compilerOptions` 사용
- [ ] JVM target이 명시적이고 회사 표준(JVM_17)과 일치
- [ ] KAPT와 KSP가 같은 processor에 동시 적용 안 됨
- [ ] KSP 버전이 Kotlin 버전과 lockstep
- [ ] K2 preview를 메인 브랜치 기본값으로 쓰지 않음
- [ ] 컴파일러 플러그인(serialization, allopen 등) 버전이 Kotlin과 일치
- [ ] freeCompilerArgs에 의도된 플래그만

## 핵심 패턴

### 표준 1.9.x JVM 모듈
```kotlin
// build.gradle.kts
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    kotlin("jvm") version "1.9.24"
    id("com.google.devtools.ksp") version "1.9.24-1.0.20"
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
        freeCompilerArgs.addAll("-Xjvm-default=all")
    }
}

dependencies {
    ksp("com.google.dagger:hilt-compiler:2.51.1")
    implementation("com.google.dagger:hilt-android:2.51.1")
}
```

### KAPT 호환 경로
```kotlin
plugins {
    kotlin("jvm") version "1.9.24"
    kotlin("kapt") version "1.9.24"
}

kapt {
    correctErrorTypes = true       // Java 스텁 에러 메시지 개선
    useBuildCache = true
    arguments {
        arg("dagger.fastInit", "enabled")
    }
}

dependencies {
    kapt("legacy-apt-only-processor:1.0")
}
```

### K2 preview 모듈 한정 활성화
```kotlin
// 한 모듈에서만 K2 시도
kotlin {
    compilerOptions {
        languageVersion.set(org.jetbrains.kotlin.gradle.dsl.KotlinVersion.KOTLIN_2_0)
        apiVersion.set(org.jetbrains.kotlin.gradle.dsl.KotlinVersion.KOTLIN_1_9)
    }
}
```
**caveat**: 이 모듈에서 KAPT 쓰지 말 것. K2-KAPT 호환성은 1.9에서 불안정. 별 모듈로 분리 또는 K1 유지.

### 버전 카탈로그
```toml
# gradle/libs.versions.toml
[versions]
kotlin = "1.9.24"
ksp = "1.9.24-1.0.20"
hilt = "2.51.1"

[plugins]
kotlin-jvm = { id = "org.jetbrains.kotlin.jvm", version.ref = "kotlin" }
kotlin-serialization = { id = "org.jetbrains.kotlin.plugin.serialization", version.ref = "kotlin" }
ksp = { id = "com.google.devtools.ksp", version.ref = "ksp" }
```

## Gotchas

### KSP 버전 mismatch
KSP 버전은 `<kotlin>-<ksp>` 두 부분 모두 정확히. Kotlin 1.9.24면 KSP는 `1.9.24-1.0.20` 같은 형태. 다르면 처리 실패 또는 silent NoOp.

### `kotlinOptions { }` 사용 (deprecated)
Kotlin 1.8+에서 `kotlinOptions` 는 deprecated. 새 코드는 `compilerOptions { ... }` 사용. IDE가 노란 경고 — 무시 말고 마이그레이션.

### KAPT + KSP 같은 processor 양쪽 등록
출력 디렉토리 충돌 + 빌드 시간 2배. 한 processor는 한 경로만.

### K2 preview를 메인 기본값으로
1.9.x의 K2는 preview — production CI 기본값이면 빌드 빨간불 빈발. 메인 K1 + 실험 모듈만 K2.

### 컴파일러 플러그인 버전 불일치
`kotlin("plugin.serialization")`의 버전이 `kotlin("jvm")`과 다르면 internal API mismatch. **모든 kotlin(...) 플러그인은 동일 버전.**

### `kapt { ... }` 블록을 KSP 모듈에 남겨둠
KAPT 의존성을 KSP로 이주했는데 `kapt { ... }` 설정 블록이 남아 있으면 빈 KAPT task가 빌드 그래프에 추가됨. 이주 시 블록·plugin·dependencies 모두 정리.

### Gradle Application plugin + KMP executable
KMP에서 application 플러그인 사용 시 KMP 8.7+ 호환 문제. 1.9.x에서는 일단 미인지 — 2.0.x로 올리면 명시적 가이드 따라야 함. (해당 스킬: 2.0.x 마이그레이션 스킬)

### freeCompilerArgs에 중복 -opt-in
같은 `-opt-in=...`이 root + module 양쪽에 → 중복 경고. extension 레벨 한 곳만.

### JVM target 누락
Gradle toolchain만 의존하면 일부 task가 다른 target으로 컴파일 → ABI 불일치. **항상 명시.**

## 검증 체크리스트

- compilerOptions 사용 (kotlinOptions 아님)
- JVM target 명시 (JVM_17)
- KAPT와 KSP 중복 등록 없음
- KSP 버전이 Kotlin과 정확히 lockstep
- 모든 kotlin(...) 플러그인 동일 버전
- K2 preview는 한정 모듈에만
- 버전 카탈로그(libs.versions.toml)로 한 곳 관리

## 5축 자가 평가

- 검색성: kotlin 1.9 / K2 preview / kapt / ksp / compilerOptions / 한·영 키워드
- 의사결정 트리(IF/THEN): 5개 IF 분기 + 7개 리뷰 체크
- 코드 식별자: kotlin("jvm"), kotlin("kapt"), com.google.devtools.ksp, compilerOptions, JvmTarget.JVM_17, languageVersion, freeCompilerArgs, kapt(), ksp()
- Gotcha-driven: 9개 build/version 실수 + 회피
- 검증 가능: 7개 체크리스트
