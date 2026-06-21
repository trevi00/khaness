---
name: fabric-turbomodule-jsi-and-native-module-compat-review
description: React Native New Architecture(Fabric/TurboModule/JSI) 호환성 리뷰를 라인 코드로 강제하는 베이스라인.
keywords: react-native new architecture fabric turbomodule jsi codegen hermes bridgeless interop layer concurrent renderer fallback compat 0.76 신아키텍처 호환성 네이티브모듈 리뷰
intent: 검증해 마이그레이션 호환 추가해 빌드해 디버그
paths: package.json android/app/build.gradle ios/Podfile metro.config.js react-native.config.js
patterns: newArchEnabled bridgeless RCTAppDelegate UIManagerType.Fabric TurboModule HostObject jsi::Runtime codegenConfig nativeModulesProvider unstable_enablePackagerExperiments react-native-config interop_layer
requires:
phase: plan migrate review debug
tech-stack: react-native
min_score: 2
---

# React Native New Architecture — Fabric, TurboModule, JSI Compat Review

React Native 0.76+ 부터 **New Architecture가 기본**(default ON)이다. 이 환경에서 가장 자주 발생하는 사고는 **native 라이브러리가 New Arch 미지원**이라 런타임 crash, **codegen 설정 mismatch**로 빌드 실패, **interop layer fallback** 의존으로 성능 저하. 이 스킬은 그 호환성 검토를 라인 단위로 강제한다.

## 의사결정 트리

### IF 새 RN 0.76+ 프로젝트 / 라이브러리 추가 (Plan)
1. **모든 native 라이브러리에 New Arch 지원 확인** — package.json/README의 Fabric/TurboModule 표시.
2. 미지원 라이브러리 → ① 대체 라이브러리 ② upstream PR ③ interop layer (성능 비용) ④ fork+패치.
3. **JS-only 라이브러리는 영향 없음** (단, Reanimated/Gesture Handler 등 native 사용 라이브러리는 New Arch 지원 버전 필수).
4. 직접 native module 작성 → 처음부터 TurboModule + Codegen으로.

### IF 호환성 매트릭스 작성 (Migrate)
1. 의존성 분류: **JS-only / Old Arch only / New Arch supported / interop fallback**.
2. 핵심 후보군 점검: react-native-reanimated, react-native-gesture-handler, react-native-screens, react-native-safe-area-context, react-native-svg, react-native-vector-icons (각각 New Arch 버전 명시).
3. 결제/카메라/지도/광고 SDK는 native heavy — 가장 먼저 검증.
4. 호환 매트릭스 문서화 — `docs/native-arch-compat.md` 같은 파일에 라이브러리·버전·상태.

### IF Codegen 설정 (Implement, custom native module)
1. `package.json`에 `codegenConfig` 명시 — `name`, `type` (`modules`/`components`/`all`), `jsSrcsDir`.
2. JS spec 파일 (`*Spec.ts`) — `TurboModuleRegistry.getEnforcing<Spec>(...)`. spec이 generated native interface의 source of truth.
3. iOS Podfile에 `use_react_native!` (자동 codegen 호출).
4. Android `build.gradle`의 `react { codegenDir }` 설정.

### IF interop layer (legacy bridge fallback) (Migrate)
1. 일부 lib가 Old Arch 전제일 때 RN의 interop layer가 자동 변환 시도. 동작은 하지만 **bridge cost 부담**.
2. interop layer 의존 표시: 빌드 로그에 `interop_layer` / `bridge call`.
3. 성능 회귀 보이면 해당 라이브러리 제거/교체 우선.
4. interop은 영구 해법이 아님 — 향후 RN release에서 제거 가능성.

### IF Hermes / bridgeless 검증 (Implement)
1. `jsEngine: 'hermes'` 명시 — JSC 폴백 비권장.
2. bridgeless mode (RN 0.74+) — 0.76 default. 일부 legacy native 코드 호환 안 됨.
3. **금지**: `react-native.config.js`로 강제 unlink된 라이브러리. autolinking 사용.
4. iOS `RCTAppDelegate` — bridgeless 진입점.

### IF 디버깅 (Debug)
1. 빌드 실패: codegen output 확인 (`ios/build/generated/ios/`, `android/app/build/generated/source/codegen/`).
2. 런타임 crash + "TurboModule not found": JS spec과 native impl mismatch — 메서드 시그니처 비교.
3. UI 깨짐 + Fabric 컴포넌트 미반영: shadow tree mount 실패 — 해당 컴포넌트가 New Arch view manager 구현했는지.
4. release 빌드만 깨짐: ProGuard / dead code elimination이 codegen된 클래스 제거 → keep rules 추가.

### IF 코드 리뷰 (Review)
- [ ] `newArchEnabled: true` 명시
- [ ] 모든 native 의존성의 New Arch 지원 매트릭스 문서
- [ ] Custom native module이 TurboModule + Codegen으로 작성됨
- [ ] codegenConfig가 package.json에 명시
- [ ] Hermes 명시 (`jsEngine: 'hermes'`)
- [ ] interop layer 의존이 의도적이고 단기 계획
- [ ] iOS Podfile / Android build.gradle 모두 New Arch 활성화
- [ ] CI에서 release build이 New Arch로 통과

## 핵심 패턴

### 0.76+ 표준 설정
```jsonc
// package.json
{
  "name": "myapp",
  "dependencies": {
    "react-native": "0.76.5",
    "react": "18.3.1"
  },
  "codegenConfig": {
    "name": "MyAppSpec",
    "type": "modules",
    "jsSrcsDir": "specs"
  }
}
```

### TurboModule JS spec
```ts
// specs/NativePayment.ts
import type { TurboModule } from 'react-native';
import { TurboModuleRegistry } from 'react-native';

export interface Spec extends TurboModule {
  pay(amount: number, orderId: string): Promise<{
    approvedAt: string;
    transactionId: string;
  }>;
  isAvailable(): boolean;
}

export default TurboModuleRegistry.getEnforcing<Spec>('Payment');
```

### Android TurboModule impl (Kotlin)
```kotlin
class PaymentModule(reactContext: ReactApplicationContext)
    : NativePaymentSpec(reactContext) {        // codegen된 추상 클래스 상속

    override fun pay(amount: Double, orderId: String, promise: Promise) {
        try {
            val result = example_gatewayClient.pay(amount.toLong(), orderId)
            promise.resolve(Arguments.createMap().apply {
                putString("approvedAt", result.approvedAt)
                putString("transactionId", result.transactionId)
            })
        } catch (e: Exception) {
            promise.reject("EXAMPLE_APP_ERROR", e.message, e)
        }
    }

    override fun isAvailable(): Boolean = example_gatewayClient.isInstalled()

    override fun getName(): String = NAME
    companion object { const val NAME = "Payment" }
}
```

### iOS TurboModule impl (Swift)
```swift
@objc(PaymentModule)
final class PaymentModule: NSObject, NativePaymentSpec {
    func pay(_ amount: Double,
             orderId: String,
             resolve: @escaping RCTPromiseResolveBlock,
             reject: @escaping RCTPromiseRejectBlock) {
        Task {
            do {
                let r = try await PaymentClient.shared.pay(amount: Int(amount), orderId: orderId)
                resolve(["approvedAt": r.approvedAt, "transactionId": r.transactionId])
            } catch {
                reject("EXAMPLE_APP_ERROR", error.localizedDescription, error)
            }
        }
    }

    func isAvailable() -> Bool { PaymentClient.shared.isInstalled }
}
```

### iOS Podfile (bridgeless)
```ruby
use_react_native!(
  :path => config[:reactNativePath],
  :hermes_enabled => true,
  :fabric_enabled => true,
  :new_arch_enabled => true,
  :app_path => "#{Pod::Config.instance.installation_root}/.."
)
```

### 호환성 매트릭스 예
```md
| Library                          | Version  | New Arch | Notes |
|----------------------------------|----------|----------|-------|
| react-native-reanimated          | 3.16.x   | ✅       | Fabric supported |
| react-native-gesture-handler     | 2.20.x   | ✅       | TurboModule |
| react-native-screens             | 4.0.x    | ✅       |       |
| react-native-svg                 | 15.x     | ✅       |       |
| react-native-example_gateway (internal)  | 1.4.0    | ✅       | TurboModule |
| legacy-tracker-sdk               | 0.9.x    | ⚠️ interop | replace by Q3 |
```

### Android keep rules (ProGuard)
```proguard
# Codegen-generated TurboModule classes
-keep class com.facebook.react.turbomodule.core.interfaces.** { *; }
-keep class com.myapp.spec.** { *; }
-keep,allowobfuscation,allowshrinking class com.facebook.react.bridge.NativeModule { *; }
```

## Gotchas

### `newArchEnabled: false` 잔존 + 라이브러리 New Arch 강제
0.76 default true인데 명시적 false로 두면 일부 lib가 강제 enable이라 빌드 깨짐. **명시적 true로 통일.**

### Codegen output을 git에 커밋
재현 불가능한 diff 생기고 빌드마다 회귀. `.gitignore`로 generated 디렉토리 제외.

### TurboModule JS spec 변경 후 빌드 안 함
codegen이 spec → native interface를 다시 만들어야 함. `pod install` (iOS), `./gradlew clean` (Android).

### 메서드 시그니처 mismatch (spec vs impl)
JS에서 number, native에서 Int → 32bit overflow. **spec의 number는 Double**. `Int.MAX_VALUE` 넘으면 BigInt 또는 string.

### Promise resolve/reject 누락
모든 분기에서 정확히 1번 호출 — 안 하면 JS Promise 영원히 pending. error path 검증.

### release build 만 crash (ProGuard)
codegen된 classes가 obfuscated/제거 → keep rules 추가.

### interop layer 영구 의존
"동작하니까 둔다" 하면 다음 RN release에서 깨짐. 매 release notes의 deprecation 확인.

### react-native.config.js로 manual link
autolinking 시대에 manual link 잔존 → 충돌. 0.60+ 이후 autolinking 사용.

### `react-native-screens` 미사용 + Native Stack
React Navigation v6+의 Native Stack은 screens 의존. 미설치 시 ID-only 화면 → Fabric에서 깨짐.

### Reanimated 버전 mismatch
Reanimated 3.16+ 가 New Arch 풀 지원. 구버전 사용 시 worklet crash.

### iOS minimum deployment 너무 낮음
New Arch는 iOS 13+ 필요 (RN 0.74+ 기준). 12 이하면 Fabric 안 됨.

### Android compileSdk / minSdk
RN 0.76은 compileSdk 35 / minSdk 24+. 미만이면 빌드 깨짐 — `expo-build-properties` 또는 직접 build.gradle.

### 새 native module 호출이 main thread 블로킹
TurboModule는 동기 호출 가능 — 무거운 작업을 sync로 노출하면 JS thread 멈춤. async + Promise.

## 검증 체크리스트

- newArchEnabled true 명시
- 모든 native 의존성 New Arch 지원 매트릭스 문서
- Custom native module이 TurboModule + Codegen
- codegenConfig package.json에 명시
- jsEngine hermes 명시
- interop layer 의존이 단기 계획
- ProGuard keep rules 추가
- iOS deployment / Android sdk 최소 버전 충족
- release build이 New Arch로 CI 통과

## 5축 자가 평가

- 검색성: react-native / new architecture / fabric / turbomodule / jsi / interop / 한·영
- 의사결정 트리(IF/THEN): 6개 IF + 8개 리뷰 체크
- 코드 식별자: newArchEnabled, fabric_enabled, codegenConfig, TurboModuleRegistry.getEnforcing, NativePaymentSpec, RCTPromiseResolveBlock, use_react_native!, jsEngine, react-native-reanimated, react-native-screens, jsi::Runtime, HostObject
- Gotcha-driven: 13개 호환성 실수 + 회피
- 검증 가능: 9개 체크리스트 + 매트릭스 + ProGuard 스니펫
