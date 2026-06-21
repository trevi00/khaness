---
keywords: nextjs 15 app router cache fetch revalidate dynamic static no-store ISR PPR streaming suspense server client boundary 캐시 라우트 무효화 데이터
intent: nextjs15 캐시 정책 설계 fetch revalidate ISR dynamic 명시 boundary 분리 무효화 전략
paths: app/ src/app/ src/lib/data/
patterns: fetch cache revalidate revalidatePath revalidateTag dynamic = 'force-dynamic' export const dynamic Suspense
requires: nextjs
phase: design implement review
tech-stack: typescript
min_score: 3
---

# Next.js 15 Cache, Data Fetching + Route Boundaries

> 핵심 원칙: **캐시·런타임·서버/클라이언트 경계는 한 묶음으로 리뷰**해야 한다. Next.js 15는 default가 더 dynamic 친화 — `fetch` 자동 캐시는 **opt-in**으로 바뀌었다. cache 정책을 명시하지 않으면 stale/leak 위험이 같이 따라온다.

## 의사결정 트리

### IF 새 라우트 데이터 패치 추가 (Design)
1. **데이터 신선도 요구**:
   - 정적 (build time) → `fetch(url, { cache: 'force-cache' })` 또는 default + page-level static
   - 주기적 갱신 → `fetch(url, { next: { revalidate: 60 } })`
   - 항상 최신 → `fetch(url, { cache: 'no-store' })` + `export const dynamic = 'force-dynamic'`
   - 사용자별 (auth) → 항상 dynamic, no-store
2. **route-level 의도 명시**:
   - `export const dynamic = 'force-dynamic'` (사용자 종속)
   - `export const revalidate = 60` (ISR)
   - `export const fetchCache = 'force-no-store'` (전체 fetch 강제)
3. **streaming 필요?** Suspense + loading.tsx로 shell 먼저 보내기

### IF mutation 후 데이터 갱신 (Implement)
1. server action / route handler에서:
   - `revalidatePath('/posts')` — 특정 경로 cache invalidate
   - `revalidateTag('posts')` — fetch에 `next.tags`로 묶은 그룹 invalidate
2. 클라이언트는 router.refresh()로 RSC payload 재요청 (수동 케이스)
3. 잘못된 곳에 cache invalidate → drift 발생

### IF 캐시 동작이 의심됨 (Review)
1. 이 fetch는 무슨 cache 모드? (default는 15에서 no-store에 가까워짐)
2. route segment에 `dynamic`/`revalidate` 명시되어 있나?
3. cookies/headers 호출이 있나? → 자동 dynamic
4. 빌드 출력에서 ƒ (dynamic) / ○ (static) 확인

## Cache 모델 (Next.js 15)

| Layer | 역할 | 제어 |
|---|---|---|
| **Request Memoization** | 같은 render 내 동일 fetch 중복 제거 | 자동 (per-request) |
| **Data Cache** | fetch 결과 영구 캐시 | `cache: 'force-cache' \| 'no-store'`, `next.revalidate`, `next.tags` |
| **Full Route Cache** | route HTML/RSC payload 빌드 시점 저장 | route segment config (`dynamic`, `revalidate`) |
| **Router Cache** | 클라이언트 in-memory navigation cache | `staleTimes` (next.config) |

**15 변경**: GET Route Handler default는 더 이상 자동 캐시 안 됨. 명시 필요.

## 패턴

### Static (build time)
```tsx
// app/blog/[slug]/page.tsx
export async function generateStaticParams() {
  const posts = await getAllPosts();
  return posts.map(p => ({ slug: p.slug }));
}

export default async function PostPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const post = await fetch(`https://api/posts/${slug}`, { cache: 'force-cache' }).then(r => r.json());
  return <Article post={post} />;
}
```

### ISR (시간 기반 재검증)
```tsx
// app/products/page.tsx
export const revalidate = 300;  // 5분마다

export default async function ProductsPage() {
  const products = await fetch('https://api/products', {
    next: { revalidate: 300, tags: ['products'] },  // tag로 on-demand invalidate 가능
  }).then(r => r.json());
  return <List products={products} />;
}
```

### Dynamic (사용자 종속)
```tsx
// app/dashboard/page.tsx
import { cookies } from 'next/headers';

export const dynamic = 'force-dynamic';

export default async function Dashboard() {
  const session = (await cookies()).get('session')?.value;       // → 자동 dynamic 트리거
  const data = await fetch(`https://api/me`, {
    cache: 'no-store',
    headers: { Authorization: `Bearer ${session}` },
  }).then(r => r.json());
  return <UserDashboard data={data} />;
}
```

### Streaming + Suspense
```tsx
// app/dashboard/page.tsx
import { Suspense } from 'react';

export default function Dashboard() {
  return (
    <>
      <Header />
      <Suspense fallback={<StatsSkeleton />}>
        <SlowStats />
      </Suspense>
      <Suspense fallback={<FeedSkeleton />}>
        <Feed />
      </Suspense>
    </>
  );
}
```
shell이 먼저 흐르고 각 island가 들어옴 → TTFB ↓.

### On-demand invalidation (Server Action)
```tsx
'use server';
import { revalidatePath, revalidateTag } from 'next/cache';

export async function createPost(formData: FormData) {
  await db.posts.create({ title: String(formData.get('title')) });
  revalidateTag('posts');           // 같은 tag 가진 모든 fetch
  revalidatePath('/admin/posts');   // 특정 경로
}
```

## Route segment config 매트릭스

| 옵션 | 의미 | 자주 쓰는 값 |
|---|---|---|
| `dynamic` | 라우트 동적/정적 | `'auto' \| 'force-dynamic' \| 'error' \| 'force-static'` |
| `revalidate` | ISR 주기(초) | `false \| 0 \| number` |
| `fetchCache` | fetch default | `'auto' \| 'default-cache' \| 'force-no-store'` |
| `runtime` | 실행 환경 | `'nodejs' \| 'edge'` |
| `dynamicParams` | 동적 segment 허용 | `true \| false` |

## PPR (Partial Prerendering) — 평가 단계
- Next.js 15에서 **여전히 experimental**, production 비추천 (docs 명시)
- experimental flag 켜고 평가만, default로 채택 X
- 안정될 때까지 ISR + Suspense 조합으로 충분

## 5축 품질 체크

| 축 | 체크 |
|---|---|
| 정확성 | 사용자 종속 데이터에 `cache: 'no-store'` 또는 `force-dynamic` 명시했는가 |
| 안전성 | auth 라우트가 정적 캐시로 빌드되지 않는가 (`cookies()`/`headers()` 호출) |
| 성능 | 정적/ISR 가능한 페이지에 default dynamic 안 가는가 |
| 가독성 | 라우트 상단 segment config로 의도 한눈에 보이는가 |
| 검증성 | mutation 후 `revalidatePath`/`revalidateTag`로 drift 잡히는가 |

## Gotchas

### auth 라우트가 stale public cache로 서빙됨
`cookies()`/`headers()` 안 부르고 fetch만 하면 캐시 가능. session 데이터를 로컬 기억하면 다른 사용자에게 leak. 항상 `dynamic = 'force-dynamic'` + `no-store` 명시.

### Next.js 15에서 default cache 변경 모름
GET Route Handler 자동 캐시 제거됨. 14 코드를 그대로 가져오면 의도치 않게 매 요청 fetch. cache 정책을 코드에 박아두기.

### `revalidatePath`를 잘못된 경로로 호출
`revalidatePath('/posts/123')`이 `/posts/[id]`를 잡는지 확인. dynamic segment는 패턴 매칭. tag 기반(`revalidateTag`)이 더 안전한 경우 많음.

### server component에서 client-only API 호출
`window`, `localStorage` 호출 → 빌드 또는 prerender 실패. `'use client'` 컴포넌트로 분리 + Suspense fallback.

### `'use client'`를 페이지 최상위에
client boundary가 위로 올라가면 자식 전부 client → RSC 이점 잃고 번들 폭증. 가능한 한 leaf 위치로 푸시.

### fetch에 `next.tags` 안 박아서 on-demand invalidation 불가
`revalidateTag` 쓰려면 fetch에 `tags` 등록 필수. 미리 박아두는 습관.

### route-level `revalidate`와 fetch-level 충돌
fetch가 더 짧은 수치면 fetch가 이김. 의도 명확히 — segment-level은 fallback, fetch-level이 실제 정책이라고 통일.

### dynamic API 호출 누락한 채 force-static
`force-static` + `cookies()` 호출 → 빌드 에러 또는 잘못된 prerender. `dynamic = 'error'`로 정적이 깨질 때 빌드 실패시키는 strict mode 사용 가능.

### staleTimes 무지로 client navigation에서 stale UI
client router cache는 별개. `next.config.experimental.staleTimes`로 dynamic/static prefetch TTL 조절. mutation 후 `router.refresh()`로 강제 갱신.

## 도구 사용 패턴 (Harness)
- 캐시 모드 누락: `Grep("fetch\\(", glob="app/**/*.{ts,tsx}")` 후 `cache:` / `next:` 옵션 점검
- dynamic 명시 검증: `Grep("export const dynamic", glob="app/**/page.tsx")`
- auth + cache 조합: `Grep("cookies\\(\\)|headers\\(\\)", glob="app/**/page.tsx")` 후 같은 파일 cache 모드
- 빌드 출력 분석: `Bash("npx next build")` → ƒ/○ 표 확인 (○가 사용자 데이터 라우트면 위험)
- revalidate 일관성: `Grep("revalidateTag\\('([^']+)'", glob="**/*.ts")` 와 `Grep("tags:\\s*\\[", glob="**/*.ts")` 매칭
