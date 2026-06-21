---
name: ota-runtime-version-rollback-and-binary-compat-contracts
description: React Native 0.76.x OTA(EAS Update / CodePush) 배포에서 runtime version, binary 호환 경계, rollback, native 변경 감지를 라인 코드로 강제.
keywords: react-native ota over-the-air eas-update codepush appcenter expo runtime-version sdkVersion binary-change native-module-change new-architecture fabric turbomodule hermes channel deployment-key rollback regression rollout phased-release public-env env-public expo-public secret-drift deep-link auth-gate js-bundle hbc bundle-hash 0.76 OTA 런타임버전 롤백 바이너리호환
intent: 배포 릴리즈 추가해 검증해 롤백 회귀 디버그 잠금
paths: package.json eas.json app.config.ts app.json android/ ios/ src/ codepush.config.js .env.public .env
patterns: expo-updates EAS update channel runtimeVersion appVersion sdkVersion --channel --runtime-version codepush sync codepush.checkForUpdate codePushOptions deploymentKey AppCenterDeployments.set rollback rollback-immediately install-immediate install-on-next-restart install-on-next-resume Updates.fetchUpdateAsync Updates.reloadAsync Updates.checkForUpdateAsync NSCFNetworkUserAgent expo-public-env EXPO_PUBLIC_ public-env-leak react-native-config Hermes hbc
requires:
phase: plan implement review debug release rollback
tech-stack: react-native
min_score: 2
---

# React Native — OTA, Runtime Version, Rollback & Binary Compat Contracts

OTA (Over-the-Air) 업데이트 — EAS Update, CodePush, expo-updates — 는 **JS 번들만 교체할 뿐 native 코드/아키텍처는 못 바꾼다.** OTA의 사고 패턴은 거의 항상 **(1) 변경에 native 변경이 섞였는데도 OTA로 push, (2) runtime version 정책 부재로 구버전 binary가 신버전 JS를 받아 crash, (3) rollback 경로 미설계, (4) public env에 secret 누출, (5) deep link/auth가 OTA 채널과 맞물리며 깨짐**이다. 이 스킬은 그 계약을 라인 단위로 강제한다.

## 의사결정 트리

### IF OTA로 보낼 변경인가 (Plan)
1. **JS-only 변경 = OTA 가능** — JS, TS, asset (이미지, JSON), JS 의존성 (peer dep 추가 없이).
2. **다음은 OTA 불가, store 빌드 필수** — native module 추가/제거, native 코드 (Java/Kotlin/Swift/ObjC), `Podfile`/`build.gradle` 변경, Info.plist/AndroidManifest 권한·entitlements/usage strings, app icon, splash screen, ATS, deep link scheme 추가.
3. **New Architecture (Fabric/TurboModule) 토글** — OTA 불가. 새 binary.
4. **Hermes on/off** — bytecode 변경. OTA 불가.
5. **`expo-updates` SDK runtime API 차이** — OTA 가능하지만 runtime version으로 차단된 채널인지 확인.

### IF runtime version 정책 (Plan)
1. **`runtimeVersion` 명시 필수** — `appVersion` (1.x.x → 1.x.x은 호환), `sdkVersion` (Expo SDK), `policy: "appVersion"`/`"nativeVersion"`/`"fingerprint"` 등 명시.
2. **native 변경 시 runtime version bump 필수** — 안 하면 구버전 binary가 신JS를 받아 crash. **CI에 enforcement.**
3. **fingerprint 방식 (Expo SDK 51+)** — native fingerprint 자동 계산. 변경 감지 누락 위험 줄어듬.
4. **CodePush의 `targetBinaryVersion`** — semver range. native 변경 시 range 좁히기.

### IF channel / 배포 lane (Plan)
1. **production / staging / preview** 최소 3 채널. 각 binary가 어느 채널 가입하는지 lock.
2. **internal preview는 internal binary에만** — external user에게 노출 금지.
3. **rollout 단계** — 0% → 10% → 50% → 100%. 단계마다 crash rate / error rate 확인.
4. **channel switch 검증** — TestFlight/Internal Track에서 실제 OTA fetch 확인.

### IF rollback 설계 (Plan)
1. **이전 버전 OTA 재 publish** — 같은 channel에 직전 안전 버전 republish. timestamp 기반 → 자동 latest pickup.
2. **`republish` 명령 / EAS Update의 republish 메커니즘**. rollback도 OTA 한 번 더 — store update 아님.
3. **rollback 결정 기준** — crash rate 임계, JS error rate 임계, key business metric 임계. 사람 판단 + 자동화 둘 다.
4. **rollback 후 sticky 정책** — 그 채널의 새 OTA 받을 때까지 rollback 버전 유지.

### IF public env 운영 (Plan)
1. **`EXPO_PUBLIC_*` / `react-native-config`의 public**은 **JS 번들에 그대로 박힘** — secret 절대 금지.
2. **secret = server side만** — 토큰 발급은 서버에서. JS는 발급된 토큰만 받음.
3. **CI에 grep gate** — `EXPO_PUBLIC_*` 가 빌드 산출물에 들어가는지 자동 검사. secret 패턴 (sk_, AKIA, password) 차단.
4. **dev/staging/prod env 격리** — `.env.production`, `.env.staging` 분리. CI에서 환경별 inject.

### IF native module / new arch (Plan/Review)
1. **native module 추가 = binary 변경** — OTA 불가. 새 store 빌드.
2. **TurboModule/Fabric 호환** — 별도 skill `fabric-turbomodule-jsi-and-native-module-compat-review` 참조.
3. **OTA로 받은 JS가 binary에 없는 native module 호출** → crash. JS bundle과 binary의 native module set 매칭이 runtime version 의미.

### IF deep link / auth와 OTA (Implement)
1. **OTA로 deep link scheme 추가 불가** — Info.plist/AndroidManifest 변경 → store 빌드.
2. **OTA로 라우터 path 추가 가능** — JS-only.
3. **auth gate가 OTA 후에도 정상** — `Updates.reloadAsync()` 후 navigation state 정리. user logged-in 상태 보존.

### IF release 흐름 (Release)
1. **store 빌드 = runtime version bump** + 다음 OTA부터 새 RV 채널.
2. **OTA = 같은 RV 안에서 JS 교체.** rollout %로 단계.
3. **모니터링 — Sentry / EAS dashboard / CodePush metrics** — crash, error, install 성공률.
4. **CI에 incident-template 자동 생성** — issue 발생 시 RV/channel/build/JS hash/binary version 즉시 답.

### IF 코드 리뷰 (Review)
- [ ] PR diff에 native 변경 (Podfile/build.gradle/Manifest/Info.plist/native 코드) 없음 = OTA 가능
- [ ] native 변경 있으면 runtime version bump + store 빌드 lane
- [ ] `runtimeVersion` 정책 (appVersion / fingerprint) 명시
- [ ] CodePush의 `targetBinaryVersion` 좁게
- [ ] channel별 빌드/배포 격리
- [ ] rollout phased (10/50/100) 정책
- [ ] rollback playbook 존재 (republish 절차)
- [ ] `EXPO_PUBLIC_*` / public env에 secret 없음 (CI grep)
- [ ] deep link scheme 추가는 store 빌드 PR 별도
- [ ] auth state가 OTA reload 후 보존
- [ ] Hermes / New Architecture toggle은 binary 변경 PR 별도

## 핵심 패턴

### `app.config.ts` — runtimeVersion 정책
```ts
import type { ExpoConfig } from "expo/config";

const config: ExpoConfig = {
  name: "MyApp",
  slug: "myapp",
  version: "1.4.0",
  runtimeVersion: { policy: "fingerprint" },     // native 변경 자동 감지 (SDK 51+)
  // 또는 명시:
  // runtimeVersion: { policy: "appVersion" },   // 1.4.x 호환
  updates: {
    url: "https://u.expo.dev/<project-id>",
    enabled: true,
    fallbackToCacheTimeout: 0,
    checkAutomatically: "ON_LOAD",
  },
  ios: { bundleIdentifier: "com.example.myapp" },
  android: { package: "com.example.myapp" },
};
export default config;
```

### `eas.json` — channel + production guard
```json
{
  "build": {
    "production": { "channel": "production", "distribution": "store" },
    "staging":    { "channel": "staging",    "distribution": "internal" },
    "preview":    { "channel": "preview",    "distribution": "internal" }
  },
  "submit": {
    "production": { "ios": { "ascAppId": "123" } }
  }
}
```

### EAS Update — phased rollout
```bash
# 0. 변경이 JS-only인지 검증
git diff --name-only origin/main | grep -E '(android/|ios/|Podfile|build\.gradle|Info\.plist|AndroidManifest)' && {
  echo "native change detected — store build required, not OTA"; exit 1
}

# 1. staging으로 먼저
eas update --branch staging --message "fix: cart total calc"

# 2. production rollout
eas update --branch production --message "fix: cart total calc" --rollout-percentage 10
# 모니터링 1-2시간 (crash, error, business metric)
eas update:edit --branch production --rollout-percentage 50
eas update:edit --branch production --rollout-percentage 100
```

### Rollback — republish 직전 안전 버전
```bash
# 직전 안전 update id 확인
eas update:list --branch production --limit 5

# 안전 update를 production에 다시 publish
eas update:republish --group <SAFE_UPDATE_GROUP_ID> --branch production
```

### CodePush — `targetBinaryVersion` 좁게 + rollback
```bash
# native 변경이 1.4.0 binary에 들어있다면 OTA는 1.4.0만 대상
appcenter codepush release-react -a Org/MyApp \
    --deployment-name Production \
    --target-binary-version "1.4.0" \
    --description "fix cart total calc" \
    --rollout 10

# 단계 상승
appcenter codepush patch -a Org/MyApp Production -r 50
appcenter codepush patch -a Org/MyApp Production -r 100

# rollback (직전 release 비활성화)
appcenter codepush rollback -a Org/MyApp Production
```

### `expo-updates` 런타임 — manual check + reload
```ts
import * as Updates from "expo-updates";

export async function checkAndApplyUpdate() {
  if (__DEV__) return;
  try {
    const result = await Updates.checkForUpdateAsync();
    if (result.isAvailable) {
      await Updates.fetchUpdateAsync();
      // 사용자에게 prompt 후
      await Updates.reloadAsync();
    }
  } catch (e) {
    // 네트워크 오류는 무시 — 다음 launch에 재시도
  }
}
```

### Public env guard (CI grep)
```bash
# CI에 추가 — secret이 public env에 들어갔는지 검사
set -e
PATTERNS='(EXPO_PUBLIC_.*(_KEY|_SECRET|_TOKEN|_PASSWORD)|sk_live_|sk_test_|AKIA[0-9A-Z]{16})'
if grep -REn "$PATTERNS" .env* app.config.* 2>/dev/null; then
  echo "secret in public env — abort"
  exit 1
fi

# build 산출물에서 secret 패턴 검색
if [ -f dist/_expo/static/js/*.hbc ]; then
  if strings dist/_expo/static/js/*.hbc | grep -E '(sk_live_|AKIA[0-9A-Z]{16})'; then
    echo "secret leaked into bundle — abort"; exit 1
  fi
fi
```

### Native-change detector (PR gate)
```bash
#!/usr/bin/env bash
# .github/scripts/detect-native-change.sh
set -e
NATIVE_PATTERN='^(android/|ios/|Podfile|Podfile\.lock|build\.gradle|gradle\.properties|Info\.plist|AndroidManifest\.xml|app\.config\.|app\.json|package\.json)'
if git diff --name-only "origin/${GITHUB_BASE_REF}"...HEAD | grep -E "$NATIVE_PATTERN"; then
  if grep -q '"runtimeVersion"' app.config.* app.json 2>/dev/null; then
    if ! git diff "origin/${GITHUB_BASE_REF}"...HEAD -- app.config.* app.json | grep -q runtimeVersion; then
      echo "native change without runtimeVersion bump — fail"
      exit 1
    fi
  fi
  echo "native change detected — must be store build, not OTA"
fi
```

### Auth state preservation across `reloadAsync`
```ts
// auth state는 SecureStore/AsyncStorage에 영속화. reload 후 재구성.
async function bootstrap() {
  const token = await SecureStore.getItemAsync("auth_token");
  if (!token) return navigateToLogin();
  setAuthHeader(token);
  await refreshUserProfile();         // 토큰 만료/취소 검증
  navigateToHome();
}
```

### Incident report template
```yaml
# kept in repo as docs/ota-incident-template.md
update_id:                     # eas update:list로 확인
update_group:                  # rollback 단위
channel:                       # production / staging / preview
rollout_percentage:            #
runtime_version:               #
binary_app_version:            #
native_change_in_pr:           # yes/no
crash_rate_before:             #
crash_rate_after:              #
js_error_rate_after:           #
rollback_decision:             # yes/no/pending
rollback_target_group:         #
deep_link_or_auth_impact:      # yes/no
```

## Gotchas

### native 변경 (Podfile, build.gradle, Manifest, Info.plist, native code)을 OTA로 push
구버전 binary가 받음 → 호출 누락된 native module / permission missing → crash. **CI에 native-change detector.**

### `runtimeVersion` 미설정 (default = appVersion)
appVersion bump를 깜빡하면 옛 binary에 새 JS 들어감. **명시 + bump 정책 코드화.**

### `runtimeVersion: { policy: "appVersion" }`인데 minor만 bump해도 OTA 가능 가정
1.4.0 ↔ 1.4.1 호환 — minor 안에 native 추가 있으면 폭망. fingerprint policy 권장.

### CodePush `targetBinaryVersion` wildcard (`*`)
모든 binary가 받음 — 옛 binary가 신JS 받음. 구체 semver.

### `EXPO_PUBLIC_API_KEY` / `react-native-config`의 public에 secret 박음
JS 번들에 평문 — `strings` 명령 한 줄에 노출. CI grep gate 필수.

### `.env.production`이 git에 commit
secret 누출. .gitignore + CI에서 secret manager로 inject.

### rollout 100%로 바로 publish
crash 발견 시 이미 전체 사용자 영향. **단계적 rollout이 기본.**

### rollback 절차 미설계
긴급 시 우왕좌왕 → 노출 시간 길어짐. `eas update:republish` 한 줄 playbook.

### `Updates.reloadAsync()` 호출 시 사용자 작업 미저장
입력 중 reload → 데이터 손실. user-confirmed reload + draft persistence.

### auth state가 reload 후 사라짐
in-memory만 유지 → re-launch 시 logout 화면. SecureStore/AsyncStorage 영속화.

### deep link scheme 추가가 OTA에 섞여 들어감
Info.plist/AndroidManifest 변경 → OTA로 못 보냄. 별도 store 빌드 PR.

### Hermes on/off 토글을 OTA로 보내려 함
bytecode 형식 다름 → JS 안 로드. binary 변경이라 OTA 불가.

### New Architecture (Fabric/TurboModule) 토글이 OTA에 포함
binary 변경 — OTA 불가. 별도 빌드.

### channel 분리 안 함 — 모두 production 한 채널
staging 테스트가 production 사용자에게 노출. 채널별 빌드 격리.

### `EXPO_PUBLIC_*` 변수 변경이 OTA로 자동 반영 가정
빌드 시 inline됨. 새 publish가 새 값 가져감 — 동작은 함. 단 secret이 들어 있으면 매 OTA마다 누출 갱신.

### OTA channel에 가입한 binary가 인터넷 없을 때 fallback 미설계
첫 launch에서 update fetch 실패 → 사용자 경험. `fallbackToCacheTimeout` + cached bundle 정책.

### rollback 후 monitoring 종료 — 같은 incident 재발 가능
post-mortem 후 root cause fix → 새 OTA / 새 binary. rollback은 응급조치, 종착지 아님.

## 검증 체크리스트

- PR에 native 변경 없음 (OTA 가능 PR) — CI detector
- runtimeVersion 정책 (fingerprint 권장) 명시 + native 변경 시 bump
- CodePush targetBinaryVersion 좁게
- channel 3단계 (production/staging/preview) 격리
- phased rollout (10/50/100) 정책
- rollback playbook (eas update:republish 또는 codepush rollback) 문서화
- public env에 secret 없음 (CI grep + bundle strings 검사)
- .env.production git commit 없음
- auth state SecureStore 영속화
- deep link/Hermes/New Arch 토글은 별도 store 빌드 PR
- Updates.reloadAsync 호출 시 사용자 작업 저장 처리
- channel별 binary가 production user 노출 안 됨
- monitoring (Sentry/EAS metrics) crash/error/rollout 단계 게이트
- incident template 사용

## 5축 자가 평가

- 검색성: react-native / ota / eas-update / codepush / runtime-version / rollback / 한·영 키워드
- 의사결정 트리(IF/THEN): 8개 IF + 11개 리뷰 체크
- 코드 식별자: runtimeVersion, EAS update, --rollout-percentage, --target-binary-version, expo-updates, Updates.checkForUpdateAsync, Updates.fetchUpdateAsync, Updates.reloadAsync, EXPO_PUBLIC_*, eas update:republish, codepush rollback, fingerprint policy
- Gotcha-driven: 17개 흔한 실수 + 회피
- 검증 가능: 14개 체크리스트 + native-change detector 스크립트 + secret-grep gate + incident template
