---
keywords: nuxt 4 plugin client server mode runtimeConfig public private secret env NUXT_ NUXT_PUBLIC nuxtApp provide injection 플러그인 모드 시크릿 환경변수
intent: nuxt4 plugin mode 결정 runtimeConfig private/public 분리 secret 노출 차단 injection key 명시
paths: plugins/ nuxt.config.ts .env app.vue
patterns: defineNuxtPlugin .client.ts .server.ts useRuntimeConfig provide useNuxtApp NUXT_PUBLIC_
requires: nuxt
phase: design implement review
tech-stack: typescript
min_score: 3
---

# Nuxt 4.x Plugins, Runtime Config + Secret Boundary

> 핵심 원칙: **plugin mode와 runtimeConfig 분리는 함께 검토할 한 묶음의 boundary**다. plugin이 어디서 실행되는지(`.client`/`.server`/양쪽), 어떤 config를 읽는지(`public`/`private`), env가 어떤 prefix로 들어오는지(`NUXT_*`/`NUXT_PUBLIC_*`)는 같은 리뷰에서 본다.

## 의사결정 트리

### IF 새 plugin 추가 (Design)
1. **mode 결정**:
   - browser API (`window`, `document`, `localStorage`) 사용? → `.client.ts`
   - server-only secret 또는 Node API? → `.server.ts`
   - 양쪽 동작 (init, error handler 등)? → suffix 없음 (`.ts`)
2. **순서 의존?** → 파일명 접두어 또는 `nuxt.config.ts`의 `plugins` 배열 순서
3. **inject 필요?** → `provide` 키 명시 + 타입 보강
4. **runtimeConfig 접근?** → public만 client, private은 server 전용

### IF env 변수 추가 (Implement)
1. **노출 정책**:
   - server-only secret → `runtimeConfig.X`, env: `NUXT_X` (or `process.env.X` mapped)
   - client에서도 필요 → `runtimeConfig.public.X`, env: `NUXT_PUBLIC_X`
2. **secret을 public에 두지 않음** — client bundle에 박혀 leak
3. **mapping 정확히**: `NUXT_API_SECRET` → `runtimeConfig.apiSecret`, `NUXT_PUBLIC_API_BASE` → `runtimeConfig.public.apiBase`

### IF runtimeConfig drift 의심 (Review)
1. `nuxt.config.ts`에서 `runtimeConfig` 객체 확인 → public 안에 secret 키 있는지
2. `.env*` 파일에서 `NUXT_PUBLIC_*` 접두어 가진 secret 의심 키 검사
3. client bundle 빌드 후 secret 문자열 검색
4. plugin이 잘못된 mode에서 secret 접근하는지 확인

## Plugin 패턴

### server-only (DB / secret API)
```typescript
// plugins/db.server.ts
export default defineNuxtPlugin(() => {
  const config = useRuntimeConfig();
  const db = createDbClient(config.databaseUrl);  // private only

  return {
    provide: { db },
  };
});
```

### client-only (browser API)
```typescript
// plugins/analytics.client.ts
export default defineNuxtPlugin((nuxtApp) => {
  // window.gtag, navigator API 등 안전하게 사용
  const config = useRuntimeConfig();
  const ga = config.public.googleAnalyticsId;
  if (!ga) return;
  // ...
});
```

### 양쪽 (init, hook, error handler)
```typescript
// plugins/error-tracker.ts (suffix 없음 → 양쪽)
export default defineNuxtPlugin((nuxtApp) => {
  nuxtApp.hook("vue:error", (error) => {
    console.error("[vue]", error);
    // server / client 모두에서 호출됨
  });
});
```

### Injection key + 타입 보강
```typescript
// plugins/myService.ts
export default defineNuxtPlugin(() => {
  const myService = { greet: (name: string) => `Hi ${name}` };
  return { provide: { myService } };
});

// types/nuxt.d.ts
declare module "#app" {
  interface NuxtApp {
    $myService: { greet: (name: string) => string };
  }
}
declare module "vue" {
  interface ComponentCustomProperties {
    $myService: { greet: (name: string) => string };
  }
}
```

```vue
<script setup lang="ts">
const { $myService } = useNuxtApp();  // 타입 안전
$myService.greet("Nuxt");
</script>
```

## runtimeConfig 베이스라인

```typescript
// nuxt.config.ts
export default defineNuxtConfig({
  runtimeConfig: {
    // server-only — client bundle에 안 들어감
    apiSecret: "",                  // env: NUXT_API_SECRET
    databaseUrl: "",                // env: NUXT_DATABASE_URL
    authSecret: "",                 // env: NUXT_AUTH_SECRET

    public: {
      // client에 노출 OK
      apiBase: "/api",              // env: NUXT_PUBLIC_API_BASE
      siteUrl: "",                  // env: NUXT_PUBLIC_SITE_URL
      googleAnalyticsId: "",        // env: NUXT_PUBLIC_GA_ID
    },
  },
});
```

```bash
# .env.local
NUXT_API_SECRET=top-secret
NUXT_DATABASE_URL=postgres://...
NUXT_AUTH_SECRET=jwt-signing-key

NUXT_PUBLIC_API_BASE=https://api.example.com
NUXT_PUBLIC_SITE_URL=https://example.com
```

### 사용 시 분기
```typescript
// server only
const { apiSecret, databaseUrl } = useRuntimeConfig();

// 양쪽 OK
const { public: { apiBase } } = useRuntimeConfig();
```

## Plugin mode 매트릭스

| 파일명 | 실행 위치 | 사용 |
|---|---|---|
| `xxx.ts` | server + client | hook, error handler, 공통 init |
| `xxx.client.ts` | client only | browser API, analytics, DOM access |
| `xxx.server.ts` | server only | DB, server secret, Node API |
| `xxx.client.ts` + `xxx.server.ts` | 같이 두면 mode별 다른 구현 | universal API surface |

### 로딩 순서
- 파일명 알파벳 순 (또는 number prefix `01-`, `02-`)
- 또는 `nuxt.config.ts`의 `plugins` 배열에 명시
- 의존성 있는 plugin은 `app:created` hook 안에서 초기화

## Secret 누출 차단 규칙

### 절대 안 됨
```typescript
// ❌ secret을 public에
runtimeConfig: {
  public: {
    apiSecret: process.env.API_SECRET,  // client bundle leak!
  },
}
```

```typescript
// ❌ client plugin에서 server-only config 접근
// plugins/foo.client.ts
const { apiSecret } = useRuntimeConfig();  // undefined — client에는 없음
```

### OK
```typescript
// ✅ secret은 server route 또는 .server.ts plugin에서만
// server/api/secure.ts
export default defineEventHandler(async () => {
  const { apiSecret } = useRuntimeConfig();
  return await fetch(externalApi, { headers: { "X-Key": apiSecret } });
});
```

```typescript
// ✅ client는 server route 경유
// pages/data.vue
const { data } = await useFetch("/api/secure");
```

## 5축 품질 체크

| 축 | 체크 |
|---|---|
| 정확성 | plugin이 사용하는 API가 mode와 맞는가 (browser API ↔ .client) |
| 안전성 | secret이 `public:`이나 `NUXT_PUBLIC_*`에 안 들어갔는가 |
| 성능 | 양쪽 plugin이 client에서 무거운 로직 안 도는가 |
| 가독성 | plugin 파일명 접미어로 mode 한눈에 보이는가 |
| 검증성 | injection 키 타입 보강이 `#app` declaration에 있는가 |

## Gotchas

### `.client.ts` 접미어 누락
SSR에서 `window` 접근 → hydration 깨짐 / 빌드 실패. browser API 한 줄이라도 쓰면 무조건 `.client.ts`.

### secret을 `runtimeConfig.public`에
빌드 출력 client bundle에 그대로 박힘. `.nuxt/dist/client/*.js` grep으로 secret 문자열 검색해서 검증.

### `NUXT_PUBLIC_*`을 server-only 의도로 사용
prefix가 매핑 결정. server에서만 쓰고 싶어도 `NUXT_PUBLIC_*`이면 client bundle에 들어감. server-only는 prefix 없이 `NUXT_X`.

### plugin 순서 의존을 파일명에 안 박음
순서가 우연히 맞아 동작하다가 새 plugin 추가 시 깨짐. number prefix (`01-init.ts`) 또는 hook 안에서 초기화.

### `useRuntimeConfig()`를 server endpoint 밖에서 secret 읽으려 시도
client에서 `apiSecret`은 `undefined`. 항상 `server/api/*` 또는 `.server.ts` 에서.

### inject 키 타입 보강 누락
`useNuxtApp().$myService` 사용처에서 타입 `any`. `declare module "#app"`로 보강 안 하면 IDE 도움 잃음.

### 양쪽 plugin이 client-only 라이브러리 import
`xxx.ts`에서 browser-only 라이브러리 import → SSR 빌드 실패. `import.meta.client` 분기로 가드 또는 별도 파일.

### env 파일 commit
`.env.local`은 `.gitignore`에. CI는 secrets manager. `.env.example`로 키 목록만 공유.

### `useState` + plugin 초기값 충돌
plugin에서 `useState` 초기 값 setter → 컴포넌트의 `useState` 사용처와 충돌. plugin은 inject로 service 제공, state는 store/composable에.

## 도구 사용 패턴 (Harness)
- secret in public 검사: `Grep("public:\\s*\\{", path="nuxt.config.ts", -A=20)` → SECRET/KEY/TOKEN 류 키 매칭
- env prefix 검증: `Grep("NUXT_PUBLIC_(SECRET|KEY|TOKEN|PASSWORD)", glob=".env*")`
- plugin mode 분류: `Bash("ls plugins/")` → `.client.ts` / `.server.ts` 분포
- mode 누락 plugin: `Grep("window\\.|document\\.|localStorage", path="plugins/")` 후 파일명 접미어 확인
- inject 타입 보강: `Grep("declare module .#app.", glob="**/*.d.ts")`
- client bundle leak: `Bash("npx nuxt build && grep -r 'secret-string' .output/public/")` (실제 secret 일부)
