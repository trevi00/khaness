---
keywords: nuxt 4 vue useFetch useAsyncData routeRules cache prerender ssr swr isr nitro runtimeConfig payload plugin client server mode publicRuntimeConfig privateRuntimeConfig nuxtApp
intent: 라우트설계해 데이터로딩 캐시정책 plugin등록 runtime config 분리 secret관리 payload예산 점검
paths: pages/ app.vue server/ plugins/ nuxt.config.ts
patterns: useFetch useAsyncData useState useRuntimeConfig defineNuxtRouteMiddleware nitro routeRules definePayloadPlugin
requires: nuxt
phase: design implement review
tech-stack: typescript
min_score: 3
---

# Nuxt 4.x Route Data + Payload + Route Rules + Cache Surface

> 핵심 원칙: **route는 delivery policy 단위**다. 데이터 로딩, route rule(cache), runtime config 노출, plugin mode, payload 크기는 한 라우트의 review 단위에서 같이 결정한다.

## 의사결정 트리

### IF 새 라우트 추가 (Design)
1. **인증 필요?** → `routeRules`에서 `cache` 끄거나 `headers`로 `Cache-Control: private, no-store`
2. **공개 + 정적성 강함?** → `prerender: true` 또는 `isr: <초>` / `swr: <초>`
3. **퍼블릭 API 호출?** → `useFetch` 키 명시 + payload 크기 검토
4. **클라이언트에서만 실행?** → `useFetch(..., { server: false })` 또는 client-only plugin
5. **개인화 데이터?** → `useFetch(..., { server: false })` + 인증 키 `useRuntimeConfig().XXX`로 server-only

### IF 데이터 로딩 작성 (Implement)
```
한 번만 가져오고 캐시 OK → useAsyncData(key, fn)
HTTP fetch 직접 → useFetch(url) (내부적으로 useAsyncData 사용)
SSR 없이 client만 → { server: false }
파라미터 변경 시 재요청 → watch + refresh 또는 query를 url에 포함
```

**키는 명시**: 자동 생성 키는 동일 endpoint 호출 충돌 → 직접 명시 권장.

### IF runtime config 분리 (Review)
```ts
// nuxt.config.ts
export default defineNuxtConfig({
  runtimeConfig: {
    // private — server only, 노출 안 됨
    apiSecret: process.env.API_SECRET,
    // public — client 노출됨 (NUXT_PUBLIC_*)
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE,
    },
  },
});
```

- secret을 `public:` 안에 넣으면 client bundle에 박힘 → 차단
- env 변수 prefix `NUXT_*` (private), `NUXT_PUBLIC_*` (public) 매핑 정확히

### IF plugin 추가 (Design)
1. **mode 결정**: `client` / `server` / 양쪽
2. browser-only API (window/document) 사용? → `.client.ts` 접미어
3. server-only secret 접근? → `.server.ts` 접미어
4. injection 키는 명시: `nuxtApp.provide('myService', service)` → `useNuxtApp().$myService` 타입 안전

## 핵심 패턴

### 데이터 로딩 (server-side)
```vue
<!-- pages/products/[id].vue -->
<script setup lang="ts">
const route = useRoute();
const { data: product, error } = await useFetch(`/api/products/${route.params.id}`, {
  key: `product-${route.params.id}`,        // 명시 키
  default: () => null,
  // server-only secret이 필요하면 server endpoint 경유
});

if (error.value) {
  throw createError({ statusCode: 404, statusMessage: 'Not found' });
}
</script>
```

### 클라이언트 전용 데이터 (개인화)
```vue
<script setup lang="ts">
const { $auth } = useNuxtApp();
const { data: cart } = await useFetch('/api/cart', {
  server: false,           // SSR 안 함 → payload에 포함 안 됨
  key: 'user-cart',
  headers: { Authorization: `Bearer ${$auth.token.value}` },
});
</script>
```

### Route rules — delivery policy
```ts
// nuxt.config.ts
export default defineNuxtConfig({
  routeRules: {
    '/': { prerender: true },                            // 빌드 시 정적 생성
    '/blog/**': { isr: 3600 },                           // 1시간 ISR
    '/api/**': { cors: true, headers: { 'cache-control': 's-maxage=60' } },
    '/admin/**': { ssr: true, cache: false },            // 캐시 절대 X
    '/account/**': { ssr: false },                       // SPA fallback
    '/news/**': { swr: 600 },                            // stale-while-revalidate 10분
  },
});
```

### Plugin (server-only)
```ts
// plugins/db.server.ts
export default defineNuxtPlugin(() => {
  const config = useRuntimeConfig();
  const db = createDbClient(config.dbUrl);  // private only

  return {
    provide: { db },
  };
});
```

### Plugin (client-only, browser API)
```ts
// plugins/analytics.client.ts
export default defineNuxtPlugin(() => {
  if (typeof window === 'undefined') return;
  // window.gtag(...) etc.
});
```

### Server route (Nitro)
```ts
// server/api/products/[id].get.ts
export default defineEventHandler(async (event) => {
  const id = getRouterParam(event, 'id');
  const config = useRuntimeConfig();        // server에서 private 접근 가능
  const product = await fetch(`${config.apiBase}/products/${id}`, {
    headers: { 'X-API-Key': config.apiSecret },
  });
  return product.json();
});
```

## Payload 예산 + 키 정책

### Payload size 점검
- `useAsyncData`/`useFetch` 결과는 SSR payload에 직렬화되어 client로 전달됨
- 큰 collection (수천 개)을 server에서 fetch하면 HTML 폭증 → `server: false` 검토 또는 page에서 paginate
- DevTools `Payload` 탭으로 전송 크기 체크

### 키 충돌
같은 endpoint를 다른 컴포넌트에서 호출 → 키 명시 안 하면 한쪽 결과 덮어씀.
```ts
useFetch('/api/products', { key: 'products-list-page' });
useFetch('/api/products', { key: 'products-recommend-widget' });
```

## 5축 품질 체크

| 축 | 체크 |
|---|---|
| 정확성 | routeRules가 라우트 성격(인증/정적/SWR)과 일치하는가 |
| 안전성 | `runtimeConfig.public`에 secret이 섞여있지 않은가 / 인증 라우트가 `cache: false`인가 |
| 성능 | payload 크기 측정 후 `server: false` 또는 paginate 검토했는가 |
| 가독성 | plugin mode가 파일명 접미어(`.client/.server`)로 명확한가 |
| 검증성 | 키 명시로 같은 endpoint 호출이 충돌하지 않는가 |

## Gotchas

### `useFetch` 키 미명시로 캐시 충돌
같은 URL을 다른 컨텍스트에서 호출 시 결과가 섞임. 항상 `key` 옵션 명시.

### `routeRules` 와일드카드 우선순위 함정
`/admin/**` 가 `/admin/users` 에 적용되지만 더 구체적 규칙이 없으면 cache 정책이 의도와 어긋날 수 있음. 정확한 prefix + 더 구체적 규칙 병기.

### secret을 `runtimeConfig.public` 에 둠
`NUXT_PUBLIC_API_KEY`로 노출 → client bundle에 박힘. private은 prefix 없이 `runtimeConfig.apiSecret`처럼 정의.

### client-only plugin이 server에서 실행됨
`.client.ts` 접미어 누락 시 SSR에서 `window` 접근 → hydration 깨짐. 접미어로 mode 강제.

### `useState` 와 `useFetch` 혼용
`useState`는 SSR-friendly 공유 reactive state, `useFetch`는 데이터 로딩. 같은 상태에 둘 다 쓰면 동기화 깨짐.

### 인증 페이지가 prerender됨
실수로 `prerender: true`가 매칭되면 빌드 시점 데이터로 박힘. 인증/대시보드는 `ssr: false` 또는 `cache: false`.

### Payload에 거대 collection
SSR fetch 결과가 1MB+ → HTML 비대화 + Hydration 시간 증가. 첫 화면에 필요한 만큼만 server fetch, 나머지는 client paginate.

## 도구 사용 패턴 (Harness)
- secret 노출 감사: `Grep("public:", path="nuxt.config.ts", -A=10)` → SECRET 류 키 점검
- routeRules 점검: `Read nuxt.config.ts` → 인증 라우트 cache 정책 확인
- plugin mode: `Glob("plugins/*.{client,server}.ts")` 와 mode 없는 plugin 비교
- 키 누락 useFetch: `Grep("useFetch\\([^,]*\\)", glob="**/*.vue")` → key 옵션 없는 호출 탐지
