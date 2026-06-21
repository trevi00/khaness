---
name: swift-export-surface-design-and-generic-boundaries
description: Kotlin 2.1.x Swift export 표면 설계, generic/inheritance 경계, XCFramework vs Swift export 선택을 라인 코드로 강제.
keywords: kotlin multiplatform kmp swift-export xcframework spm swiftpm umbrella-framework iosMain appleMain commonMain hierarchy template direct-integration generic inheritance suspend inline operator final-class api-surface umbrella experimental cocoapods 멀티플랫폼 스위프트 익스포트 엄브렐라
intent: 만들어 추가해 노출해 구현해 설계해 마이그레이션 분리해
paths: shared/ shared/src/commonMain/ shared/src/iosMain/ shared/src/appleMain/ ios/ ios/Podfile ios/Podfile.lock build.gradle.kts settings.gradle.kts gradle.properties
patterns: applyDefaultHierarchyTemplate iosX64 iosArm64 iosSimulatorArm64 XCFramework binaries.framework binaryOption isStatic baseName commonMain iosMain appleMain expect actual @ObjCName @HiddenFromObjC @ShouldRefineInSwift swiftPackageDistribution umbrella swift-export experimental
requires:
phase: plan implement review debug migrate
tech-stack: kotlin
min_score: 2
---

# Kotlin 2.1.x — Swift Export Surface Design & Generic Boundaries

Swift export는 **여전히 experimental + direct-integration only**다. "Swift export로 가자"가 결정 자체가 아니라 — **(1) 어느 source-set 경계에 코드가 살고, (2) 어떤 배포 채널(direct integration vs XCFramework+SPM)을 쓰고, (3) generic/inheritance 제약에 API 표면을 맞췄는지**가 진짜 결정이다. 이 스킬은 그 세 축을 라인 단위로 강제한다.

## 의사결정 트리

### IF 새 KMP 프로젝트 시작 (Plan)
1. **`commonMain` = 모든 target에 컴파일** → 플랫폼 API 금지. Apple-specific은 `iosMain`/`appleMain`으로.
2. iOS-wide 공유 = `iosMain`. Apple 전체 (macOS/iOS/tvOS/watchOS) 공유 = `appleMain`. 더 좁은 `iosArm64Main`은 진짜 target-specific 사유 있을 때만.
3. `applyDefaultHierarchyTemplate()` 사용 — 손으로 짠 hierarchy는 2.1.x에서 deprecate 진행. 2.0→2.1 마이그레이션 시 이거부터.
4. 테스트도 동일: `commonTest` (kotlin.test) → `iosTest` → `androidUnitTest`.

### IF iOS 배포 채널 선택 (Plan)
1. **direct integration (Xcode가 Gradle 호출)** — iOS 팀이 Kotlin 툴체인 OK일 때. 가장 빠른 loop. **Swift export는 이것만 지원한다.**
2. **XCFramework + Swift Package** — iOS 팀이 versioned artifact만 소비. 운영적으로 안정. release 채널로 권장.
3. **CocoaPods** — 레거시 호환 필요 시. 신규 채택 비추.
4. **둘 다 유지** — 메인 워크플로가 remote(SPM)여도 local distribution 옵션을 살려두면 shared 코드 수정 시 빠른 검증 가능 (공식 권장).

### IF Swift export 채택 검토 (Plan)
1. **status check 먼저** — 2.1.x에서 experimental. API 안정성 계약으로 외부 SDK에 노출 금지.
2. **direct integration 안 쓰면** Swift export는 동작 안 함. SPM/CocoaPods 경로면 처음부터 ObjC 헤더 기반 (`-iosMain.framework`) 가정.
3. **API 표면이 Swift export 제약을 넘으면** XCFramework로 회귀. 제약: generic은 upper bound로 reduce / 일부 collection inheritance 미지원 / cross-language inheritance 없음 / `suspend`·`inline`·`operator` 제한.
4. 결정문은 `decisions.md`에 명시 — "현재 Swift export 채택, 외부 계약 아님. 제약 넘으면 XCFramework로 회귀."

### IF API 표면 설계 (Implement)
1. **final class + top-level function 우선** — Swift에서 subclass 불가가 기본 가정.
2. **generic-heavy API 회피** — Swift 측에서 upper bound로 reduce되어 쓸모 약해짐. T 대신 구체 타입 wrapper 제공.
3. **`suspend` 함수 노출** — Swift export 미지원/제한. 대안: `Result`/Flow wrapper or callback API + 별도 swift-side bridge.
4. **`inline`/`operator` 함수** — 제한. Swift 호출 가능한 일반 함수 추가.
5. **package 이름 명확** — `com.example.shared.cart` 같이 의도 드러나게. Swift module 네이밍에 영향.
6. **`@ObjCName`/`@HiddenFromObjC`/`@ShouldRefineInSwift`** — 표면 다듬기. 단 Swift export 모드에선 일부 의미가 달라짐, 모드별 검증.

### IF 멀티 모듈 → iOS 노출 (Plan)
1. **여러 KMP 모듈을 iOS에 별개 framework로 던지지 말 것** — dependency 중복 / 앱 size 부풀음 / cross-framework state 깨짐.
2. **umbrella module + umbrella framework** 한 개로 합쳐 iOS는 1 framework만 본다 (공식 권장).
3. Android는 feature module 직접 의존 vs umbrella 의존 — 한 repo에 한 정책. 문서화.

### IF 코드 리뷰 (Review)
- [ ] `commonMain`에 Apple/JVM/Android API 직접 사용 없음
- [ ] `iosMain`/`appleMain` 경계가 의도와 일치
- [ ] `applyDefaultHierarchyTemplate()` 사용
- [ ] Swift export 사용 시 direct integration 빌드인지 확인
- [ ] Swift 노출 class에 final 또는 sealed 적용
- [ ] generic API에 Swift-side reduce 영향 검토 완료
- [ ] suspend/inline/operator 노출 제약 확인
- [ ] 여러 KMP 모듈 → iOS = umbrella framework 사용
- [ ] release 채널 (direct integration vs XCFramework+SPM) 결정문 존재
- [ ] Swift export experimental 상태가 외부 계약에 영향 안 줌

## 핵심 패턴

### 기본 hierarchy (2.1.x)
```kotlin
// shared/build.gradle.kts
kotlin {
    iosX64()
    iosArm64()
    iosSimulatorArm64()
    androidTarget()
    jvm()

    applyDefaultHierarchyTemplate()    // commonMain → appleMain → iosMain 자동 생성

    sourceSets {
        commonMain.dependencies {
            // 플랫폼 API 금지. expect/actual 또는 multiplatform 라이브러리만.
        }
        iosMain.dependencies {
            // CoreFoundation, Foundation, UIKit interop OK
        }
    }
}
```

### XCFramework + 정적 링크 (release 안정 채널)
```kotlin
import org.jetbrains.kotlin.gradle.plugin.mpp.apple.XCFramework

kotlin {
    val frameworkName = "Shared"
    val xcf = XCFramework(frameworkName)

    listOf(iosX64(), iosArm64(), iosSimulatorArm64()).forEach { target ->
        target.binaries.framework {
            baseName = frameworkName
            binaryOption("bundleId", "com.example.shared")
            isStatic = true                    // SPM 친화. dynamic이 필요한 케이스만 false.
            xcf.add(this)
        }
    }
}
```

### Umbrella module (여러 feature 모듈 → iOS 1 framework)
```kotlin
// shared-umbrella/build.gradle.kts
kotlin {
    listOf(iosX64(), iosArm64(), iosSimulatorArm64()).forEach { it.binaries.framework { baseName = "SharedUmbrella" } }

    sourceSets {
        commonMain.dependencies {
            api(project(":feature-cart"))
            api(project(":feature-payment"))
            api(project(":feature-auth"))
        }
    }
}
```

### Swift-friendly API surface (Swift export 친화)
```kotlin
// 좋음 — final + top-level + 구체 타입
package com.example.shared.cart

public final class CartService(private val repo: CartRepository) {
    public fun loadCart(userId: String, callback: (Result<Cart>) -> Unit) { ... }
}

// 피하기 — Swift export 제약 충돌
public open class GenericRepo<T : Identifiable>          // generic + open → Swift에서 표면 약화
public suspend fun observeUpdates(): Flow<Cart>          // suspend + Flow → 직접 노출 어려움
public inline fun <reified T> decode(json: String): T    // inline + reified → 노출 안 됨
```

### Swift export 안 쓸 때 — 명시적 ObjC 표면 다듬기
```kotlin
@ObjCName(swiftName = "CartViewModel")
public class CartViewModelImpl(...) {

    @ShouldRefineInSwift
    public fun rawSubmit(payload: ByteArray): Boolean = ...

    @HiddenFromObjC
    internal fun debugDump(): String = ...
}
```

### Direct integration 빌드 스크립트 (Xcode → Gradle)
```bash
# Xcode "Run Script" build phase
cd "$SRCROOT/.."
./gradlew :shared:embedAndSignAppleFrameworkForXcode \
    -Pkotlin.native.cocoapods.archs=$ARCHS \
    -Pkotlin.native.cocoapods.configuration=$CONFIGURATION \
    -Pkotlin.native.cocoapods.platform=$PLATFORM_NAME
```

## Gotchas

### `commonMain`에 `import platform.Foundation.*`
컴파일은 iOS target만 통과. Android target 빌드 시 죽음. → `iosMain`으로 이동.

### Swift export로 generic Repository 노출 → Swift 측에서 `Any` 같은 표면
generic이 upper bound로 reduce. 구체 타입 wrapper (`CartRepository`, `OrderRepository`) 제공.

### Swift에서 Kotlin class subclass 시도
**cross-language inheritance 미지원.** delegate / composition / protocol 패턴으로 대체.

### Xcode 빌드는 통과인데 Kotlin 변경이 화면에 안 반영
direct integration의 stale framework. `./gradlew clean` + Xcode "Clean Build Folder" + DerivedData 삭제.

### Kotlin 2.1.20+ 업그레이드 후 K2 kapt가 default → 생성 코드 달라짐
연관 문제로 보일 수 있음. 별도 toolchain skill 참조.

### Multiplatform executable + Gradle 8.7 Application plugin
호환 깨짐. 2.1.20+의 Kotlin `executable {}` DSL로 교체.

### Xcode 16.3 업그레이드 후 Kotlin/Native 빌드 실패
2.1.21 이상 필요. patch line 먼저 확인.

### 여러 KMP 모듈을 iOS에 각각 framework로 노출
dependency 중복, 앱 size 부풀음, framework 간 state 깨짐. **umbrella module 1 개로 통합.**

### Swift export experimental인데 외부 SDK 계약으로 publish
breaking change 시 외부 소비자 전부 깨짐. 외부 계약은 XCFramework + 명시 버저닝 채널.

### `iosArm64Main`까지 쪼갬 — 이유 없음
디버깅 표면만 늘림. 진짜 target-specific 사유 (Swift code generation 차이 등) 없으면 `iosMain`만.

### `appleMain` 활성화 안 했는데 macOS target 추가
hierarchy 깨짐. `applyDefaultHierarchyTemplate()` 재확인.

### `isStatic = false` (dynamic framework) + 여러 framework
duplicate symbol / runtime crash. release 기본값 = `isStatic = true`.

### `kotlin.test` 안 쓰고 platform-specific test framework만
공통 테스트 코드 재사용 불가 → matrix 깨짐. commonTest = kotlin.test 베이스라인.

### Swift export 채택 결정만 하고 표면 설계 안 함
"experimental인데 우리도 쓰자"가 결정 아님. **API 제약을 표면에 반영했는가**가 결정.

## 검증 체크리스트

- commonMain에 platform-specific import 없음
- iosMain/appleMain 경계가 hierarchy template과 일치
- iOS 노출 framework가 1개 (multi-module이면 umbrella)
- 배포 채널 결정문 (direct integration vs XCFramework+SPM) 존재
- Swift export 사용 시 direct integration 빌드 확인
- 노출 class에 final + 구체 타입 우선
- generic API에 Swift-side reduce 시뮬레이션 완료
- suspend/inline/operator 노출 정책 확인
- Swift export experimental 상태가 외부 계약에 영향 없음
- Xcode upgrade 시 Kotlin/Native patch line 동기화 (Xcode 16.3 → 2.1.21+)

## 5축 자가 평가

- 검색성: kotlin / kmp / swift-export / xcframework / umbrella / 한·영 키워드 + applyDefaultHierarchyTemplate
- 의사결정 트리(IF/THEN): 6개 IF + 10개 리뷰 체크
- 코드 식별자: applyDefaultHierarchyTemplate, iosMain, appleMain, XCFramework, binaryOption, baseName, isStatic, @ObjCName, @HiddenFromObjC, @ShouldRefineInSwift, embedAndSignAppleFrameworkForXcode
- Gotcha-driven: 14개 흔한 실수 + 회피
- 검증 가능: 10개 체크리스트
