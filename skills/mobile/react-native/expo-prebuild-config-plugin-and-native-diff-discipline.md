---
name: expo-prebuild-config-plugin-and-native-diff-discipline
description: Expo prebuild + config plugin + native diff(EAS/CNG) 경계를 라인 코드로 강제하는 베이스라인.
keywords: expo react-native prebuild config plugin eas build managed bare cng continuous-native-generation app.json app.config.ts info.plist androidmanifest entitlements native-diff ota update runtimeversion 익스포 빌드 네이티브 동기화
intent: 만들어 추가해 구성해 마이그레이션 빌드해 검증해
paths: app.json app.config.ts app.config.js plugins/ ios/ android/ eas.json package.json
patterns: expo expo-config-plugin withInfoPlist withAndroidManifest withGradleProperties withDangerousMod prebuild eas build runtimeVersion newArchEnabled jsEngine hermes ios.bundleIdentifier android.package
requires:
phase: plan implement migrate review debug
tech-stack: react-native
min_score: 2
---

# Expo Prebuild, Config Plugin, Native Diff Discipline

Expo 0.76.x+ 시대의 React Native는 **CNG(Continuous Native Generation) + config plugin**을 통한 native code 생성이 표준이다. 이 흐름을 깨면 ① iOS/Android 한쪽만 동작 ② OTA로 native 변경이 배포 ③ Xcode/Gradle 직수정이 prebuild에서 사라짐 같은 사고가 난다. 이 스킬은 prebuild·plugin·native diff 세 경계를 라인 단위로 잡는다.

## 의사결정 트리

### IF 새 프로젝트 / 워크플로 결정 (Plan)
1. **CNG (Continuous Native Generation)** — `app.config.ts` + config plugins로 모든 native 설정. `npx expo prebuild`로 ios/android 폴더 생성. 기본 권장.
2. **Bare workflow** (전통적 직편집) — ios/android 폴더 직접 관리. CNG 안 씀. 마이그레이션 어려운 기존 RN 앱.
3. **CNG + 일부 native 직편집** — `npx expo prebuild`로 생성 후 ios/android를 git에 커밋. 하지만 다음 prebuild 때 덮어씌워질 수 있음 — 안티패턴. 직편집 필요하면 config plugin으로 표현.
4. 결제 SDK / 결제 앱 Intent / Apple Pay 같은 도메인 특화 native는 **반드시 config plugin**으로 표현.

### IF 새 native 설정 추가 (Implement)
1. **iOS Info.plist / Entitlements** → `withInfoPlist` / `withEntitlementsPlist` 모듈 (config-plugins).
2. **Android Manifest / Gradle** → `withAndroidManifest` / `withGradleProperties` / `withAppBuildGradle`.
3. **여러 단계 변환 + 위험** → `withDangerousMod` (마지막 수단). 후속 plugin이 실행되지 않으니 신중.
4. **표준화된 권한**: `app.config.ts`의 `ios.infoPlist`, `android.permissions` 사용.
5. plugin은 한 파일당 하나의 책임. 여러 변환 묶지 말 것.

### IF 빌드 경로 (Implement)
1. **EAS Build** (권장): `eas.json`에 profile 정의 (development, preview, production). `eas build --profile production`.
2. local prebuild + 로컬 Xcode/Gradle 빌드 가능하지만 환경 일관성 떨어짐.
3. profile별 환경변수: `eas.json`의 `env` + `EXPO_PUBLIC_*` (런타임 노출) vs 비 prefix (build-time only).
4. iOS 인증서 / Android 키스토어 → EAS Credentials 또는 자체 관리.

### IF runtimeVersion 정책 (Migrate / Implement)
1. **`runtimeVersion`은 native binary의 식별자** — JS 번들과 native가 호환되는지 결정.
2. native 변경 (plugin 추가, SDK 업데이트, Expo SDK upgrade) → **runtimeVersion bump 필수**. 안 하면 OTA로 호환 안 되는 JS 배포.
3. JS-only 변경 → runtimeVersion 그대로 → OTA 안전.
4. policy 옵션: `"appVersion"`(version 따라감), `"sdkVersion"`(Expo SDK 따라감), `"fingerprint"`(자동 — 권장), 직접 문자열.
5. fingerprint 사용 시 plugin이 자동 hash — 새 plugin 추가하면 자동 새 buildable.

### IF native diff 검증 (Review / Debug)
1. **prebuild 결과는 git에 커밋 안 하기** — `.gitignore`에 `ios/`, `android/`. CNG 신뢰.
2. 또는 **prebuild 결과 커밋** + 매 prebuild마다 `git diff` 검토. 직편집 추적 가능. 단 충돌 비용.
3. CI에서 `npx expo prebuild --clean` 실행 후 git status가 clean한지 검증 — 직편집 조기 발견.
4. native folder를 커밋하는 경우 `bare` workflow로 마이그레이션 검토.

### IF 코드 리뷰 (Review)
- [ ] native 설정이 모두 config plugin 또는 app.config.ts로 표현
- [ ] ios/, android/ 폴더가 직편집 안 되거나 직편집이 plugin으로 추출됨
- [ ] runtimeVersion 정책이 명시 (fingerprint 권장)
- [ ] EAS build profile별 환경변수가 명확
- [ ] EXPO_PUBLIC_* 가 secret이 아닌 정보만
- [ ] new architecture / Hermes 정책이 app.config에 명시
- [ ] plugin 코드에 dangerousMod 남발 없음

## 핵심 패턴

### app.config.ts 표준
```ts
import { ExpoConfig } from 'expo/config';

const config: ExpoConfig = {
  name: 'MyApp',
  slug: 'myapp',
  version: '1.4.0',
  scheme: 'myapp',
  jsEngine: 'hermes',
  newArchEnabled: true,
  runtimeVersion: { policy: 'fingerprint' },
  updates: {
    url: 'https://u.expo.dev/<project-id>',
    requestHeaders: { 'expo-channel-name': 'production' },
  },
  ios: {
    bundleIdentifier: 'com.acme.myapp',
    supportsTablet: true,
    infoPlist: {
      NSCameraUsageDescription: '결제 서명에 사용됩니다.',
      LSApplicationQueriesSchemes: ['example_gateway'],
    },
  },
  android: {
    package: 'com.acme.myapp',
    permissions: ['android.permission.CAMERA'],
  },
  plugins: [
    './plugins/withPaymentIntent',
    ['expo-build-properties', {
      android: { compileSdkVersion: 35, minSdkVersion: 24 },
      ios: { deploymentTarget: '15.1' },
    }],
  ],
};
export default config;
```

### Custom config plugin (iOS Info.plist)
```ts
// plugins/withPaymentIntent.ts
import { ConfigPlugin, withInfoPlist, withAndroidManifest } from '@expo/config-plugins';

const withPaymentIntent: ConfigPlugin = (config) => {
  config = withInfoPlist(config, (cfg) => {
    cfg.modResults.LSApplicationQueriesSchemes = [
      ...(cfg.modResults.LSApplicationQueriesSchemes ?? []),
      'example_gateway',
    ];
    return cfg;
  });
  config = withAndroidManifest(config, (cfg) => {
    const queries = cfg.modResults.manifest['queries'] ??= [{}];
    queries[0]['package'] ??= [];
    queries[0]['package'].push({ $: { 'android:name': 'com.example_gateway.app' } });
    return cfg;
  });
  return config;
};
export default withPaymentIntent;
```

### eas.json 프로파일
```json
{
  "cli": { "version": ">= 13.0.0" },
  "build": {
    "development": {
      "developmentClient": true,
      "distribution": "internal",
      "env": { "EXPO_PUBLIC_API_BASE": "https://dev.api/" }
    },
    "preview": {
      "distribution": "internal",
      "channel": "preview",
      "env": { "EXPO_PUBLIC_API_BASE": "https://staging.api/" }
    },
    "production": {
      "channel": "production",
      "env": { "EXPO_PUBLIC_API_BASE": "https://api.acme.com/" }
    }
  },
  "submit": { "production": {} }
}
```

### CI guard — prebuild diff 검사
```yaml
# .github/workflows/native-diff.yml
- name: prebuild and verify clean
  run: |
    npx expo prebuild --clean
    if [[ -n "$(git status --porcelain ios android)" ]]; then
      echo "Direct edits detected in ios/android — extract to plugin"
      git status
      exit 1
    fi
```

## Gotchas

### `ios/`, `android/` 직편집 후 다음 prebuild에서 사라짐
직편집은 매 prebuild에 의해 덮어씌워짐. **plugin으로 추출** 또는 native folder를 git에 커밋 + bare 전환.

### runtimeVersion 안 올리고 native plugin 추가 → OTA 사고
JS-only OTA로 native 호환 안 되는 코드 배포 → 런타임 crash. **plugin policy fingerprint** 또는 수동 bump.

### `EXPO_PUBLIC_API_KEY` 같은 secret 노출
`EXPO_PUBLIC_*`는 클라이언트 번들에 포함됨. **API key, OAuth secret 절대 금지**. server-side 또는 EAS Secrets.

### `withDangerousMod` 남용
이 plugin 이후 다른 plugin이 무력화될 수 있음. 정말 필요한 마지막 수단.

### Expo SDK upgrade 후 plugin 호환성 무시
config-plugins API는 SDK major마다 변경 가능. plugin compatibility matrix 확인.

### `newArchEnabled: true`인데 라이브러리가 new arch 미지원
빌드 성공해도 런타임 crash 또는 UI 깨짐. 모든 native 라이브러리의 new arch 지원 확인.

### `jsEngine: 'jsc'` 잔존
0.74+ 기본 Hermes. JSC는 deprecated path. 명시적으로 hermes로.

### URL scheme / Universal Link 진입에 auth 게이트 부재
deep link 진입 시 로그인 우회 가능. linking 설정 + 진입 후 auth check.

### `app.json` vs `app.config.ts` 혼재
`app.json`만 있으면 정적, `app.config.ts`가 있으면 동적 — 둘 다 있으면 ts가 우선이지만 혼란. 한쪽만 사용.

### iOS bundleIdentifier / Android package 변경 후 prebuild만 함
EAS Build credential 재발급 필요 + 스토어 등록 ID 충돌. 이름 변경은 신중.

### EAS Build profile 누락
production만 정의하고 dev/preview 없음 → 디버깅 build 어려움. 최소 3개 profile.

### plugin이 사이드이펙트 (외부 파일 다운로드 등) 수행
빌드 재현성 깨짐 + CI 캐시 무효. plugin은 순수 변환만.

## 검증 체크리스트

- 모든 native 설정이 plugin 또는 app.config로 표현
- ios/android 직편집이 CI에서 검출됨
- runtimeVersion 정책 명시 (fingerprint 권장)
- EAS build profile별 환경변수 분리
- EXPO_PUBLIC_* 에 secret 없음
- new architecture / Hermes 정책 명시
- dangerousMod 사용처가 의도적이고 최소
- Expo SDK 와 plugin 버전 호환성 확인

## 5축 자가 평가

- 검색성: expo / prebuild / config plugin / cng / eas / runtime version / 한·영
- 의사결정 트리(IF/THEN): 5개 IF + 7개 리뷰 체크
- 코드 식별자: app.config.ts, withInfoPlist, withAndroidManifest, withGradleProperties, withDangerousMod, runtimeVersion, fingerprint, jsEngine, newArchEnabled, EXPO_PUBLIC_, eas.json, expo-build-properties
- Gotcha-driven: 12개 흔한 실수 + 회피
- 검증 가능: 8개 체크리스트 + CI guard 스니펫
