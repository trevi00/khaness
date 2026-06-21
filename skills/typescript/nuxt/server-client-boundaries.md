---
keywords: nuxt 4 server client boundary ssr csr import.meta hydration nitro server route useFetch composable plugin lane review 서버 클라이언트 경계 하이드레이션
intent: nuxt4 server/client lane 리뷰 hydration 충돌 차단 import.meta 분기 server route vs composable plugin 책임 분배
paths: pages/ components/ composables/ server/ plugins/ nuxt.config.ts
patterns: import.meta.server import.meta.client process.server defineNuxtPlugin defineEventHandler useFetch server: false
requires: nuxt
phase: design implement review
tech-stack: typescript
min_score: 3
---

# Nuxt 4.x Server / Client / Plugin Lane Review

> 핵심 원칙: **server / client / 양쪽 lane은 명시적이어야 한다.** Nuxt는 코드를 양쪽에서 돌리는 게 default — 어느 쪽에서 실행될지 모르면 secret leak, hydration mismatch, 무거운 client bundle이 한꺼번에 생긴다.

## 의사결정 트리

### IF 새 코드 작성 시 lane 결정 (Design)
1. **이 코드는 어디서 실행되어야 하나?**
   - server only (DB, secret, Node API) → `server/` route 또는 `.server.ts` plugin
   - client only (browser API, 사용자 인터랙션) → `.client.ts` plugin 또는 컴포넌트 `onMounted`
   - 양쪽 (대부분 컴포넌트, composable) → `import.meta.server`/`import.meta.client` 분기
2. **데이터 패치 위치?**
   - SSR로 SEO 필요 → `useFetch`/`useAsyncData` (default 양쪽)
   - 개인화 + SEO 불필요 → `useFetch(..., { server: false })`
   - server에서 직접 DB/secret → server route + `useFetch('/api/...')`
3. **render에 영향?**
   - SSR HTML과 client hydration 결과가 같아야 함 → 분기 안에 시간/랜덤/window 함부로 X

### IF hydration mismatch 발생 (Review)
1. server 렌더 결과와 client 첫 렌더 결과가 다른 코드 찾기
2. 흔한 원인:
   - `Date.now()`, `Math.random()` — server/client 다른 값
   - `window.innerWidth` — server에서 unknown
   - localStorage 의존 초기 상태
3. 해결: `import.meta.client`로 client 전용 갈아내기 또는 `<ClientOnly>` 컴포넌트로 감싸기

### IF lane 책임 결정이 모호 (Design)
- 보안/시크릿: server route + composable wrapper
- 무거운 deps (PDF gen, image proc): server only
- 사용자 입력 + 즉시 반응: client (composable + onMounted)
- 데이터 + SEO: 양쪽 (useFetch)

## Lane별 entry point

| Lane | 위치 | 예시 |
|---|---|---|
| Server only | `server/api/`, `server/routes/`, `server/middleware/`, `*.server.ts` plugin | DB query, secret-bearing fetch, server-side cookies |
| Client only | `*.client.ts` plugin, `onMounted` 안 코드, `<ClientOnly>` 자식 | analytics, browser API, user-only state hydration |
| 양쪽 (universal) | `pages/`, `components/`, `composables/`, plugin without suffix | UI, useState, useFetch, hooks |

## 핵심 패턴

### Server route (Nitro)
```typescript
// server/api/users/[id].get.ts
export default defineEventHandler(async (event) => {
  const id = getRouterParam(event, "id");
  const config = useRuntimeConfig();              // private OK
  const user = await db.users.findUnique({ where: { id } });
  if (!user) throw createError({ statusCode: 404 });
  return user;
});
```

### Composable로 server route 감싸기
```typescript
// composables/useUser.ts
export function useUser(id: string) {
  return useFetch(`/api/users/${id}`, {
    key: `user-${id}`,
    default: () => null,
  });
}
```

```vue
<!-- pages/profile/[id].vue -->
<script setup lang="ts">
const route = useRoute();
const { data: user, error } = await useUser(route.params.id as string);
</script>
```

### Client-only 분기
```vue
<script setup lang="ts">
const width = ref(0);

onMounted(() => {
  // 이 시점은 항상 client
  width.value = window.innerWidth;
  window.addEventListener("resize", () => (width.value = window.innerWidth));
});
</script>

<template>
  <p>Width: {{ width }}</p>
</template>
```

### `<ClientOnly>` 래퍼
```vue
<template>
  <ClientOnly fallback-tag="div" fallback="Loading...">
    <CarbonChart :data="data" />  <!-- canvas 등 client-only -->
  </ClientOnly>
</template>
```

### `import.meta.server` / `import.meta.client` 분기
```typescript
// composables/useThing.ts
export function useThing() {
  if (import.meta.server) {
    // server context — useRequestEvent, headers 등 가능
  }
  if (import.meta.client) {
    // client context — window 접근 가능
  }
}
```

### server-only 코드 격리 (`server/utils/`)
```typescript
// server/utils/db.ts
import { drizzle } from "drizzle-orm/postgres-js";
export const db = drizzle(process.env.NUXT_DATABASE_URL!);
```
- `server/` 디렉토리 안의 코드는 client bundle에 절대 안 들어감
- composable에서 직접 import하면 안 됨 (server route 경유)

## Plugin lane 결정 표

| 시나리오 | mode | 이유 |
|---|---|---|
| Sentry 초기화 | universal (`*.ts`) | 양쪽 에러 모두 잡으려면 |
| Google Analytics | client (`*.client.ts`) | window.gtag 필요 |
| DB connection pool | server (`*.server.ts`) | secret + Node socket |
| Vue plugin install (i18n, pinia) | universal | hydration 동기화 필요 |
| Theme detection from localStorage | client | localStorage는 client only |
| Auth cookie 초기 read | universal | server에서 cookie 읽어 hydrate |

## Hydration 안전 패턴

### server/client에서 같은 값
```typescript
// ❌ Date.now() — server와 client 다름
const stamp = Date.now();

// ✅ useState로 한 번 결정
const stamp = useState("stamp", () => Date.now());  // server에서 정해서 payload로 전달
```

### server-rendered HTML과 client mount 동일하게
```vue
<!-- ❌ 첫 렌더에 분기 — mismatch 위험 -->
<div v-if="import.meta.client">{{ window.innerWidth }}</div>

<!-- ✅ ClientOnly로 server 단계 비움 -->
<ClientOnly>
  <div>{{ width }}</div>
</ClientOnly>
```

### useState로 SSR-safe 공유 state
```typescript
// composables/useUser.ts
export const useCurrentUser = () => useState<User | null>("currentUser", () => null);
```
- SSR에서 채우면 payload로 client 전달 → hydration matching

## 5축 품질 체크

| 축 | 체크 |
|---|---|
| 정확성 | secret이 `server/`나 `.server.ts` 안에서만 접근되는가 |
| 안전성 | hydration mismatch warning 0건인가 (브라우저 콘솔) |
| 성능 | 무거운 client bundle 가는 코드가 server-only로 옮겨졌는가 |
| 가독성 | `import.meta.server/client` 분기가 한 함수에 안 섞이게 분할됐는가 |
| 검증성 | `<ClientOnly>` 또는 명시적 lane 표시로 의도 보이는가 |

## Gotchas

### server-only utility를 composable에서 직접 import
`server/utils/db.ts`를 `composables/useUser.ts`에서 import → 빌드 실패 또는 client bundle leak. composable은 항상 `server/api/...`를 fetch.

### `process.server` / `process.client` 사용 (구버전 패턴)
Nuxt 4는 `import.meta.server` / `import.meta.client` 권장. `process.*` 는 deprecate.

### hydration mismatch를 ClientOnly로만 덮음
원인 안 고치고 ClientOnly로 가리면 server render 비우는 영역만 늘어남. 가능하면 server에서 동일 값 결정 → useState로 전달.

### `window` 사용 코드를 universal plugin에 넣음
SSR에서 깨짐. `*.client.ts` 분리 또는 `if (import.meta.client) { ... }` 가드.

### useFetch에 `server: false` 안 쓰고 개인화 데이터 fetch
SSR에서 user-specific data가 payload로 전송 → CDN 캐시 가능성 + 다른 사용자에게 leak. 인증 데이터는 항상 `server: false`.

### server route에서 client-side composable 호출
`useState` 등 client 의존 composable을 server route에서 호출 → `setup function called outside`. server route는 `defineEventHandler`만 사용.

### useState SSR-payload 큰 값 직렬화
큰 객체를 useState에 넣으면 payload 크기 폭증. selectively 가벼운 값만 server에서 결정, 무거운 데이터는 client lazy load.

### Pages SSR을 끄지 않고 인증 페이지에 SPA처럼 코드
`/account` 같은 페이지에 server fetch 없이 onMounted만 → SSR이 빈 HTML → SEO 영향 + 경험상 깜빡임. `routeRules: { '/account/**': { ssr: false } }`로 명시.

### plugin이 client에서만 inject
`*.client.ts` plugin이 `provide`하면 server에서 `useNuxtApp().$x`가 undefined. universal하게 만들거나 server에서도 fallback 제공.

## 도구 사용 패턴 (Harness)
- server-only leak: `Grep("from .{1,2}server/", glob="composables/**/*.ts")` (있으면 위험)
- universal에 window: `Grep("window\\.|document\\.", glob="composables/**/*.ts")` 후 가드 확인
- ClientOnly 사용처: `Grep("<ClientOnly", glob="**/*.vue")` → 의도 검토
- import.meta 분기 일관성: `Grep("import\\.meta\\.(server|client)", glob="**/*.{ts,vue}")`
- hydration mismatch 추적: 브라우저 콘솔 또는 `vue.config.devtools` 활성화 + DevTools warnings
