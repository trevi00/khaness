---
name: entitlements-universal-links-keychain-and-privacy-surface-review
description: iOS entitlements, Universal Links, URL scheme, Keychain, App Privacy / NS*UsageDescription, Scene 진입을 권한·보안 surface로 라인 코드로 강제.
keywords: ios entitlements universal-links associated-domains apple-app-site-association aasa url-scheme deep-link auth-gate keychain ksecattraccessible kSecAttrAccessibleAfterFirstUnlock kSecClassGenericPassword nsphotolibraryusagedescription nslocationwheninuseusagedescription nsfaceiduidescription privacy-info app-privacy purpose-strings scene-restoration sceneconfiguration nsuseractivity userActivity continueUserActivity backstage-state-restoration ats nsapptransportsecurity 엔타이틀먼트 유니버설링크 키체인 프라이버시
intent: 만들어 추가해 검증해 리뷰 설계해 디버그 잠금
paths: ios/Runner/Info.plist ios/Runner/Runner.entitlements ios/Runner/PrivacyInfo.xcprivacy .well-known/apple-app-site-association ios/Runner/AppDelegate.swift ios/Runner/SceneDelegate.swift ios/Runner.xcodeproj
patterns: associated-domains com.apple.developer.associated-domains applinks: webcredentials: appgroups CFBundleURLSchemes CFBundleURLTypes LSApplicationQueriesSchemes NSAppTransportSecurity NSExceptionDomains NSCameraUsageDescription NSPhotoLibraryUsageDescription NSLocationWhenInUseUsageDescription NSFaceIDUsageDescription NSUserTrackingUsageDescription NSContactsUsageDescription PrivacyInfo.xcprivacy NSPrivacyTracking NSPrivacyAccessedAPITypes kSecClassGenericPassword kSecAttrService kSecAttrAccount kSecAttrAccessible kSecAttrAccessControl SecAccessControlCreateWithFlags UISceneConfigurations UIApplicationSceneManifest application(_:continue:) scene(_:openURLContexts:) NSUserActivity webpageURL UIApplication.OpenURLOptionsKey
requires:
phase: plan implement review debug
tech-stack: ios
min_score: 2
---

# iOS — Entitlements, Universal Links, Keychain & Privacy Surface Review

iOS의 Info.plist / .entitlements / PrivacyInfo.xcprivacy / AASA / Keychain 설정은 **단순 메타가 아니라 권한·보안·배포 계약**이다. 사고의 전형 패턴: (1) 더 이상 사용 안 하는 capability/usage string이 잔존 → App Store 거부, (2) URL scheme/Universal Link로 인증 bypass, (3) Keychain accessibility 잘못 설정으로 첫 잠금해제 전 데이터 노출, (4) NSAppTransportSecurity 광범위 예외, (5) PrivacyInfo.xcprivacy 누락된 API access. 이 스킬은 그 surface를 라인 단위로 강제한다.

## 의사결정 트리

### IF entitlements 추가 (Plan)
1. **product 사유 명시 후 추가** — "왜 이 capability가 필요한가"를 PR 설명에 명시. 안 그러면 잔존하다가 App Review 사유 됨.
2. **Associated Domains** (`applinks:`/`webcredentials:`/`activitycontinuation:`) — Universal Link, Shared Web Credentials, Handoff 각각 별도. 필요한 것만.
3. **App Groups** (`group.com.example.app`) — Widget/Share Extension과 main app 데이터 공유. 미사용 group은 즉시 제거.
4. **Push Notification, In-App Purchase, Sign in with Apple, Keychain Sharing** — 사용 시작 전엔 추가 금지. App Store 심사 표면.

### IF Universal Link 채택 (Plan)
1. **Associated Domains에 `applinks:example.com`**. wildcard 가능하나 좁게.
2. **AASA 파일** `https://example.com/.well-known/apple-app-site-association` — `application/json` MIME, **redirect 없이 200**, **SSL 인증서 valid**. CDN cache 정책 검증.
3. **paths 명시** — `"paths": ["/orders/*", "/cart/*"]`. wildcard `["*"]`는 운영 체크 어려워짐.
4. **AppID 형식** `TEAMID.com.example.app` — TEAMID 정확히. 잘못되면 link 동작 안 함.

### IF deep link / URL scheme 처리 (Implement)
1. **모든 진입점은 untrusted input 가정** — query/fragment 검증 + 화이트리스트.
2. **auth gate를 진입점에서 강제** — 미로그인 + 보호된 화면 deep link → 로그인 화면 후 원래 destination으로 복귀.
3. **modal stacking 정책** — deep link로 진입 시 기존 modal 정리 / 유지 정책 명시. 흐름이 잠기는 incident 1순위.
4. **scene restoration vs deep link 충돌** — restoration은 이전 화면 복구, deep link는 새 destination. 우선순위 결정 후 코드화.

### IF Keychain 사용 (Implement)
1. **`kSecAttrAccessible` 명시** — default를 신뢰하지 말 것. 권장: `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` (백업 안 됨, device 잠금해제 후만).
2. **biometric 보호 데이터** → `SecAccessControlCreateWithFlags` + `.biometryCurrentSet` 또는 `.userPresence`. Face/Touch ID 등록 변경 시 invalidate.
3. **`kSecAttrService` + `kSecAttrAccount`** 명확. 같은 키 두 번 add 시 `errSecDuplicateItem` — update flow 별도.
4. **Keychain Sharing group 사용 시 entitlements + access group 정확히 매칭**.
5. **삭제 — `SecItemDelete`** 명시. logout 시 호출 안 하면 다음 사용자 세션에 누수.

### IF NSAppTransportSecurity (Plan)
1. **default ATS 유지** — `NSAllowsArbitraryLoads = true` 절대 금지.
2. **불가피한 도메인만** `NSExceptionDomains`에 named exception. 사유를 PR + Info.plist 옆 주석에 명시.
3. **production 빌드에서 dev exception 잔존** 금지. xcconfig로 환경 분리.

### IF Privacy / Usage Descriptions (Plan)
1. **사용하는 capability에만 NS*UsageDescription** — 미사용 string 잔존은 App Review 사유 + 사용자 의심.
2. **사용자 친화 문구** — "왜 이 권한이 필요한가"를 사용자 시각으로. 개발용 placeholder 금지.
3. **PrivacyInfo.xcprivacy** (Privacy Manifest) — Apple이 요구하는 reason API access (UserDefaults, file timestamp 등) + tracking + collected data type. 누락 시 App Store 경고/거부.
4. **third-party SDK도 자체 PrivacyInfo 포함 확인** — 없으면 import 금지 또는 vendor에 요청.

### IF Scene / lifecycle (Implement)
1. **UIApplicationSceneManifest** — multi-window/iPad 지원 시 명시. 단일 scene이어도 명시 안 하면 restoration 동작 모호.
2. **`scene(_:continue:)`** — Universal Link / Handoff 진입. validated URL인지 검증 후 navigate.
3. **`NSUserActivity` 기반 restoration** — `userActivity?.webpageURL` 검증.
4. **modal pathway** — deep link 진입 시 기존 modal 처리 정책 명시.

### IF 코드 리뷰 (Review)
- [ ] 새 entitlement에 product 사유 PR 명시
- [ ] 사용 안 하는 capability/entitlement 즉시 제거
- [ ] Associated Domains의 applinks/webcredentials/activitycontinuation 각각 사유
- [ ] AASA 파일 200 + JSON MIME + redirect 없음 검증 (curl/링크 검사)
- [ ] AASA paths 화이트리스트 (wildcard 회피)
- [ ] 모든 deep link 진입에 auth gate
- [ ] modal stacking 정책 명시
- [ ] Keychain `kSecAttrAccessible` 명시 (default 의존 금지)
- [ ] biometric 보호 데이터에 SecAccessControl flags
- [ ] logout 시 SecItemDelete
- [ ] NSAllowsArbitraryLoads = true 없음
- [ ] NS*UsageDescription 사용자 친화 문구 + 미사용 제거
- [ ] PrivacyInfo.xcprivacy 존재 + reason API 명시
- [ ] third-party SDK PrivacyInfo 포함 확인
- [ ] UIApplicationSceneManifest 명시

## 핵심 패턴

### Runner.entitlements 좁게
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "https://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.developer.associated-domains</key>
    <array>
        <string>applinks:example.com</string>
        <string>webcredentials:example.com</string>
    </array>
    <key>com.apple.security.application-groups</key>
    <array>
        <string>group.com.example.app.shared</string>
    </array>
    <key>keychain-access-groups</key>
    <array>
        <string>$(AppIdentifierPrefix)com.example.app</string>
    </array>
</dict>
</plist>
```

### AASA — 좁은 paths
```json
{
  "applinks": {
    "details": [
      {
        "appIDs": ["ABCDE12345.com.example.app"],
        "components": [
          { "/": "/orders/*", "comment": "order detail deep link" },
          { "/": "/cart",      "comment": "cart entry" }
        ]
      }
    ]
  },
  "webcredentials": {
    "apps": ["ABCDE12345.com.example.app"]
  }
}
```

### Universal Link 진입 + auth gate
```swift
@MainActor
final class DeepLinkRouter {
    private let auth: AuthSession
    private let nav: AppNavigator

    func handle(_ url: URL) {
        guard let dest = parse(url) else { return }     // 화이트리스트 검증

        if dest.requiresAuth && !auth.isLoggedIn {
            nav.presentLogin(then: dest)                // 인증 후 destination 복귀
            return
        }
        nav.navigate(to: dest)
    }

    private func parse(_ url: URL) -> Destination? {
        guard url.host == "example.com" else { return nil }
        let comps = url.pathComponents
        switch comps.first(where: { !$0.isEmpty }) {
        case "orders":
            guard comps.count >= 2, let id = Int(comps[2]) else { return nil }
            return .order(id: id)
        case "cart":
            return .cart
        default:
            return nil
        }
    }
}
```

### SceneDelegate continueUserActivity
```swift
func scene(_ scene: UIScene, continue userActivity: NSUserActivity) {
    guard userActivity.activityType == NSUserActivityTypeBrowsingWeb,
          let url = userActivity.webpageURL else { return }
    DeepLinkRouter.shared.handle(url)
}

func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
    URLContexts.forEach { DeepLinkRouter.shared.handle($0.url) }
}
```

### Keychain 안전 wrapper
```swift
enum KeychainError: Error { case status(OSStatus), notFound, encoding }

struct KeychainStore {
    let service: String

    func setToken(_ token: String, account: String, biometry: Bool = false) throws {
        let data = Data(token.utf8)
        var query: [String: Any] = [
            kSecClass as String:        kSecClassGenericPassword,
            kSecAttrService as String:  service,
            kSecAttrAccount as String:  account,
        ]
        if biometry {
            var err: Unmanaged<CFError>?
            guard let access = SecAccessControlCreateWithFlags(
                nil,
                kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
                .biometryCurrentSet, &err
            ) else { throw KeychainError.status(errSecAuthFailed) }
            query[kSecAttrAccessControl as String] = access
        } else {
            query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        }

        SecItemDelete(query as CFDictionary)              // upsert
        query[kSecValueData as String] = data
        let status = SecItemAdd(query as CFDictionary, nil)
        guard status == errSecSuccess else { throw KeychainError.status(status) }
    }

    func token(account: String) throws -> String {
        let query: [String: Any] = [
            kSecClass as String:        kSecClassGenericPassword,
            kSecAttrService as String:  service,
            kSecAttrAccount as String:  account,
            kSecReturnData as String:   true,
            kSecMatchLimit as String:   kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess, let data = item as? Data,
              let str = String(data: data, encoding: .utf8) else {
            throw KeychainError.notFound
        }
        return str
    }

    func delete(account: String) {
        let query: [String: Any] = [
            kSecClass as String:        kSecClassGenericPassword,
            kSecAttrService as String:  service,
            kSecAttrAccount as String:  account,
        ]
        SecItemDelete(query as CFDictionary)              // logout 시 호출
    }
}
```

### Info.plist — 사용 권한만 명시
```xml
<key>NSCameraUsageDescription</key>
<string>주문 영수증 촬영을 위해 카메라가 필요합니다.</string>
<key>NSPhotoLibraryUsageDescription</key>
<string>업로드할 영수증을 사진 보관함에서 선택하기 위해 필요합니다.</string>
<key>NSFaceIDUsageDescription</key>
<string>로그인을 보호하기 위해 Face ID를 사용합니다.</string>
<!-- 사용 안 하는 항목은 절대 두지 말 것. App Review 사유. -->
```

### NSAppTransportSecurity — exception 좁게
```xml
<key>NSAppTransportSecurity</key>
<dict>
    <!-- NSAllowsArbitraryLoads는 추가 금지 -->
    <key>NSExceptionDomains</key>
    <dict>
        <key>legacy-internal.example.com</key>
        <dict>
            <key>NSIncludesSubdomains</key><false/>
            <key>NSExceptionAllowsInsecureHTTPLoads</key><true/>
            <!-- 사유: 내부 레거시 시스템 마이그레이션 중. 2026 Q3에 제거. -->
        </dict>
    </dict>
</dict>
```

### PrivacyInfo.xcprivacy
```xml
<dict>
    <key>NSPrivacyTracking</key><false/>
    <key>NSPrivacyTrackingDomains</key><array/>
    <key>NSPrivacyCollectedDataTypes</key>
    <array>
        <dict>
            <key>NSPrivacyCollectedDataType</key>
            <string>NSPrivacyCollectedDataTypeEmailAddress</string>
            <key>NSPrivacyCollectedDataTypeLinked</key><true/>
            <key>NSPrivacyCollectedDataTypeTracking</key><false/>
            <key>NSPrivacyCollectedDataTypePurposes</key>
            <array><string>NSPrivacyCollectedDataTypePurposeAppFunctionality</string></array>
        </dict>
    </array>
    <key>NSPrivacyAccessedAPITypes</key>
    <array>
        <dict>
            <key>NSPrivacyAccessedAPIType</key>
            <string>NSPrivacyAccessedAPICategoryUserDefaults</string>
            <key>NSPrivacyAccessedAPITypeReasons</key>
            <array><string>CA92.1</string></array>
        </dict>
    </array>
</dict>
```

### AASA 검증 스크립트
```bash
# 200 + json MIME + redirect 없음 확인
URL="https://example.com/.well-known/apple-app-site-association"
curl -sI "$URL" | head -1                                 # HTTP/2 200
curl -sI "$URL" | grep -i 'content-type'                  # application/json
curl -sI "$URL" | grep -i 'location' && echo "REDIRECT — fix"
curl -s "$URL" | jq '.applinks.details[].appIDs'          # appID 형식 검증
```

## Gotchas

### 더 이상 사용 안 하는 entitlement 잔존 (Push, IAP, Apple Sign In...)
App Review 사유 — Apple이 capability vs 실제 사용 비교. 즉시 제거.

### `NSAllowsArbitraryLoads = true` 잔존
production binary에 들어가면 보안 사고 + App Review reject. xcconfig로 dev/prod 분리.

### `NSCameraUsageDescription` 등을 사용 안 하는데 명시
사용자가 권한 prompt 보고 의심. 미사용은 즉시 제거.

### usage description 문구가 placeholder ("camera permission needed")
App Review 거부. 사용자 시각의 사유.

### AASA 200이 아닌 redirect 또는 wrong content-type
Universal Link 동작 안 함. 매 배포마다 검증.

### AASA `paths: ["*"]` wildcard 운영
의도 안 한 경로도 deep link → security/UX 사고. 좁은 paths.

### Keychain `kSecAttrAccessible` 미명시 → default `kSecAttrAccessibleWhenUnlocked`
device 잠금해제 후만 접근 가능 — backup에 포함됨. 의도와 다를 수 있음. 명시 필수.

### Keychain item을 device 간 backup하고 싶지 않은데 `ThisDeviceOnly` 미사용
iCloud Keychain backup으로 이동. 토큰은 `ThisDeviceOnly` 권장.

### biometric 보호 데이터에 access control 미사용
Face/Touch ID 변경/제거 후에도 그대로 접근 가능. `.biometryCurrentSet` flag.

### logout 시 `SecItemDelete` 누락
다음 사용자가 같은 device 사용 시 이전 세션 토큰 잔존. 명시 호출.

### Universal Link 진입에 auth gate 없음
미로그인 상태에서 보호 화면 노출. router가 첫 검증.

### deep link로 진입 시 기존 modal stack 안 정리
화면 잠김 / back 동작 깨짐. 정책 (dismiss vs stay) 결정 후 일관 적용.

### URL scheme 진입 파라미터 검증 없이 navigate
URL injection — 외부 앱이 임의 진입. 화이트리스트 + 타입 검증.

### scene restoration이 deep link보다 우선해서 deep link 무시
restoration vs deep link 우선순위 명시. 보통 deep link 우선.

### `UIApplicationSceneManifest` 미명시
multi-window/iPad에서 동작 모호. 명시.

### third-party SDK가 PrivacyInfo.xcprivacy 미포함
앱 전체 PrivacyInfo가 불완전. App Store 경고. SDK vendor에 요구 또는 교체.

### `NSPrivacyAccessedAPITypes`에 reason code 누락
Apple이 명시한 category(UserDefaults, file timestamp, system boot, disk space, active keyboards)는 reason code 필수.

### App Group identifier가 entitlements와 main bundle 다름
shared container 접근 실패 — silent. 정확히 매칭.

## 검증 체크리스트

- 모든 entitlement에 product 사유 (PR/문서)
- 미사용 capability/entitlement 제거
- Associated Domains이 applinks/webcredentials/activitycontinuation 명시적 분리
- AASA: 200 + JSON MIME + no redirect + 좁은 paths (curl 검증)
- 모든 deep link 진입에 auth gate
- modal stacking 정책 코드화
- Keychain kSecAttrAccessible 명시 + ThisDeviceOnly 토큰 정책
- biometric 데이터에 SecAccessControl
- logout flow에 SecItemDelete
- NSAllowsArbitraryLoads = true 없음 (production)
- NS*UsageDescription 사용자 친화 + 미사용 제거
- PrivacyInfo.xcprivacy 존재 + reason API + tracking 정책
- third-party SDK PrivacyInfo 포함
- UIApplicationSceneManifest 명시
- App Group identifier가 entitlements/main bundle 일치

## 5축 자가 평가

- 검색성: ios / entitlements / universal-links / aasa / keychain / privacy / 한·영 키워드
- 의사결정 트리(IF/THEN): 8개 IF + 15개 리뷰 체크
- 코드 식별자: com.apple.developer.associated-domains, applinks:, webcredentials:, NSCameraUsageDescription, NSAppTransportSecurity, NSExceptionDomains, kSecAttrAccessible, kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly, SecAccessControlCreateWithFlags, SecItemDelete, NSPrivacyAccessedAPITypes, NSPrivacyCollectedDataTypes, UIApplicationSceneManifest, scene(_:continue:)
- Gotcha-driven: 17개 흔한 실수 + 회피
- 검증 가능: 15개 체크리스트 + AASA curl 스크립트
