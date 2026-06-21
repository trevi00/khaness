---
keywords: nextjs next 15 app router server component client component use client rsc rendering ppr streaming suspense edge runtime node runtime cache no-store fetch revalidate dynamic static cookies headers searchParams secret env
intent: 라우팅설계해 서버컴포넌트 클라이언트분리 캐시정책 런타임선택 보안경계 Next.js 마이그레이션
paths: app/ middleware.ts next.config.ts
patterns: 'use client' 'use server' fetch cache: 'no-store' revalidate: dynamic = 'force-dynamic' export const runtime cookies() headers()
requires: nextjs
phase: design implement review
tech-stack: typescript
min_score: 3
---

# Next.js 15 App Router + Server/Client Split + Rendering Surface

> 핵심 원칙: **대부분의 Next.js 버그는 boundary 버그다.** 라우터 boundary, server-client boundary, cache boundary, runtime boundary가 모두 한 라우트의 design 단위에서 같이 결정되어야 한다.

## 의사결정 트리

### IF 새 라우트 추가 (Design)
1. **인증 필요?** → 기본 동적(`dynamic = 'force-dynamic'` or `cache: 'no-store'`). 정적 캐시 함정 차단
2. **개인화 데이터?** → server component에서 `cookies()`/`headers()` 호출 → 자동 동적 진입
3. **공개 콘텐츠 + 자주 안 바뀜?** → 정적 + ISR (`revalidate: <초>`) 또는 `next: { tags: [...] }` + 온디맨드 invalidate
4. **edge에서 가능한 작업?** → Node API 미사용 + DB 드라이버 호환 확인 → `runtime: 'edge'` 검토
5. **모든 라우트마다 caching mode를 명시 검토** — 침묵 default에 의존하지 말 것

### IF Server vs Client 컴포넌트 결정 (Implement)
```
이벤트 핸들러/브라우저 API/state hook 필요?
├─ 예 → 'use client' (가능한 leaf로 좁히기)
└─ 아니오 → server component (default)

Server에서 client로 props 전달 시:
- 직렬화 가능한 값만 (function/Date/class instance ❌)
- secret/server-only env는 절대 props로 ❌
```

**Rule of thumb**: `'use client'`는 페이지 전체가 아니라 **interactivity가 필요한 leaf**에. shell은 server로 둬서 payload 줄임.

### IF 14 → 15 마이그레이션 (Migrate)
1. **async request APIs**: `cookies()`, `headers()`, `draftMode()`, `params`, `searchParams` 모두 await 필요
   ```ts
   // 14
   const { id } = params;
   // 15
   const { id } = await params;
   ```
2. **fetch cache default 변경**: 14는 cache by default, 15는 `no-store` default → 명시적으로 `{ cache: 'force-cache' }` 추가 검토
3. codemod 자동 적용: `npx @next/codemod@latest upgrade`
4. **route별 review** — codemod로 안 잡히는 cache 가정 잔존 가능

## 핵심 패턴

### Server component default + client leaf
```tsx
// app/products/[id]/page.tsx — server component (default)
import { AddToCartButton } from "./AddToCartButton";

export default async function ProductPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;  // 15: await 필수
  const product = await db.product.findUnique({ where: { id } });
  if (!product) notFound();

  return (
    <article>
      <h1>{product.name}</h1>
      <p>{product.description}</p>
      <AddToCartButton productId={product.id} />  {/* client leaf */}
    </article>
  );
}
```

```tsx
// app/products/[id]/AddToCartButton.tsx
"use client";
import { useTransition } from "react";

export function AddToCartButton({ productId }: { productId: string }) {
  const [pending, start] = useTransition();
  return (
    <button
      disabled={pending}
      onClick={() => start(async () => { await fetch(`/api/cart`, { method: "POST", body: JSON.stringify({ productId }) }); })}
    >
      카트 담기
    </button>
  );
}
```

### Cache mode 명시
```tsx
// 인증 필요 라우트 — 절대 캐시 안 함
export const dynamic = 'force-dynamic';

// 또는 fetch 단위
const data = await fetch(url, { cache: 'no-store' });

// ISR — 60초마다 재생성
const data = await fetch(url, { next: { revalidate: 60 } });

// 태그 기반 invalidation
const data = await fetch(url, { next: { tags: ['products'] } });
// 이후 server action 등에서 revalidateTag('products');
```

### Runtime 명시
```tsx
// app/api/edge-route/route.ts
export const runtime = 'edge';  // V8 isolate, Node API 제한

// app/api/heavy/route.ts
export const runtime = 'nodejs';  // default, full Node API
```

### Server Action — mutation boundary
```tsx
// app/products/actions.ts
"use server";
import { revalidateTag } from 'next/cache';

export async function updateProduct(formData: FormData) {
  const id = formData.get('id') as string;
  await db.product.update({ where: { id }, data: { /* ... */ } });
  revalidateTag('products');
}
```

### Secret env 격리
```tsx
// ❌ NEXT_PUBLIC_API_KEY = "sk-..." — 클라이언트 번들에 노출
// ✅ API_KEY = "sk-..." — 서버에서만 process.env.API_KEY 접근 가능

// 클라이언트로 env를 props 전달 시 NEXT_PUBLIC_ prefix만 안전
// secret을 client component prop으로 넘기면 RSC payload에 포함됨 → 노출
```

## 렌더링 표면(Rendering Surface) 결정 매트릭스

| 라우트 성격 | 권장 |
|---|---|
| 마케팅 정적 페이지 | static (default) + 빌드 시 생성 |
| 자주 갱신되는 공개 페이지 | ISR `revalidate: <초>` |
| 사용자 대시보드 | dynamic + `cookies()` 사용 |
| 인증된 프로필/주문 | `dynamic = 'force-dynamic'` 또는 `no-store` |
| API 게이트웨이 (지연 민감) | edge runtime + streaming |
| heavy DB 조작 / Node-only lib | nodejs runtime (default) |
| 부분 정적 + 부분 동적 | PPR (실험적, 15에선 production 비권장) |

## 5축 품질 체크

| 축 | 체크 |
|---|---|
| 정확성 | 각 라우트의 cache mode와 runtime이 코드에 명시되어 있는가 |
| 안전성 | 인증 라우트가 정적 캐시되지 않는가 / secret env가 client에 노출되지 않는가 |
| 성능 | `'use client'`가 leaf로 좁혀져 RSC payload가 작은가 |
| 가독성 | server/client 분리가 파일 단위로 명확한가 (혼합 컴포넌트 없음) |
| 검증성 | hydration mismatch 없이 빌드/렌더 통과하는가 |

## Gotchas

### 인증 라우트가 정적으로 캐시됨
session 토큰 검사 없는 fetch → 14의 cache default + 15에서도 명시 안 하면 위험. 인증 페이지는 항상 `dynamic = 'force-dynamic'` 명시.

### `'use client'` 페이지 단위 남발
페이지 컴포넌트 최상단에 `'use client'`를 박으면 RSC 이점 전부 소실. interactivity가 필요한 leaf만 client로.

### server에서 client로 함수/Date/Map 전달
직렬화 불가 → 런타임 에러. plain JSON-safe 객체로 변환 후 전달.

### `cookies()`/`headers()` 동기 호출 잔존
15에서 await 안 하면 타입 에러 + 런타임 깨짐. codemod 후에도 수동 검증.

### fetch cache 기본값 변경 (14→15)
14는 cache by default, 15는 no-store default. 마이그 후 비용/지연 폭증 가능. 자주 안 바뀌는 데이터는 `force-cache` 또는 `revalidate` 명시.

### middleware에서 db / heavy lib import
middleware는 edge runtime → Node-only 모듈 깨짐. middleware는 light 인증/리다이렉트만.

### NEXT_PUBLIC_ 접두어 secret
클라이언트 번들에 그대로 박힘. API key/DB url/JWT secret 절대 NEXT_PUBLIC_ 사용 금지.

### PPR을 production에 도입
Next.js 15에서 PPR은 experimental + production 비권장. 평가 단계로만 취급.

## 도구 사용 패턴 (Harness)
- 인증 라우트 cache 검증: `Grep("dynamic|force-dynamic|no-store", path="app/(auth)")`
- client 경계 점검: `Grep("'use client'", glob="app/**/*.tsx")`
- secret 노출 검사: `Grep("NEXT_PUBLIC_.*KEY|SECRET|TOKEN", path="src,app")`
- 14→15 잔존: `Grep("params\\.id|searchParams\\.", glob="app/**/*.tsx")` (await 누락)
- runtime 명시 누락: `Grep("export const runtime", path="app/api")` 결과 빈약 시 검토
