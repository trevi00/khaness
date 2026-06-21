---
keywords: nextjs 15 authjs auth.js next-auth session jwt rbac middleware route handler server action edge node runtime secret env NEXT_PUBLIC 시크릿 환경변수 인증
intent: nextjs15 인증 설계 authjs v5 session 전략 runtime 선택 secret 노출 차단 middleware route handler server action 보호
paths: app/api/auth/ middleware.ts auth.config.ts auth.ts .env*
patterns: NextAuth() auth() middleware runtime export const runtime NEXT_PUBLIC_ env
requires: nextjs
phase: design implement review
tech-stack: typescript
min_score: 3
---

# Next.js 15 Auth.js, Runtime Choice + Secret Boundary

> 핵심 원칙: **인증은 surface별로 모델링**한다 — Server Component, Route Handler, Middleware, Server Action 각각의 entry point가 명시적이어야 한다. Session 전략(JWT/DB), runtime 선택(edge/node), env 노출 경계를 **한 리뷰 단위**로 본다.

## 의사결정 트리

### IF 새 인증 surface 추가 (Design)
1. **session 전략**:
   - JWT: edge runtime 호환, 무상태, 즉시 invalidation 어려움
   - DB session: 즉시 무효화 가능, edge에서 DB 어댑터 제약
   - 결정 기준: 즉시 로그아웃 / role 변경 즉시 반영 필요면 DB
2. **surface별 entry point**:
   - Server Component → `await auth()`
   - Server Action → `await auth()` 또는 callback에서
   - Route Handler → `await auth()` + Response 직접 반환
   - Middleware → `auth(req)` 또는 NextAuth 미들웨어 wrapper
3. **runtime 결정**:
   - middleware는 edge 강제 → DB adapter 못 쓰면 JWT 또는 분리
   - 무거운 의존성 (Node API, native modules) → `export const runtime = 'nodejs'`
4. **secret 경계**: 어떤 env가 client에 흘러가는가?

### IF env 변수 추가 (Implement)
1. **`NEXT_PUBLIC_*` 접두사 = 클라이언트 노출** — 절대 secret에 사용 금지
2. server-only secret: `STRIPE_SECRET_KEY`, `DATABASE_URL`, `AUTH_SECRET` 등 — 접두사 없음
3. 사용 위치: server component / route handler / server action / middleware (edge에서도 process.env로 접근)
4. Next.js는 `NEXT_PUBLIC_*`만 client bundle에 인라인. 그 외는 build 시점에 client에서 `undefined`

### IF 라우트 보호 (Review)
1. middleware로 route 그룹 단위 게이트
2. 세부 권한은 Server Component / Route Handler 레벨 `auth()` 호출
3. RBAC: session.user.role을 callback에서 채우고, 각 surface에서 enforce
4. 빌드 출력으로 클라이언트 번들에 secret 안 들어갔는지 검증

## Auth.js v5 베이스라인

```typescript
// auth.config.ts (edge-safe — middleware에서 import)
import type { NextAuthConfig } from "next-auth";

export const authConfig = {
  pages: { signIn: "/login" },
  providers: [], // Edge에서 못 도는 provider는 여기서 제외 (auth.ts에서 추가)
  callbacks: {
    authorized({ auth, request }) {
      const isLogged = !!auth?.user;
      const isOnDashboard = request.nextUrl.pathname.startsWith("/dashboard");
      if (isOnDashboard) return isLogged;
      return true;
    },
  },
} satisfies NextAuthConfig;
```

```typescript
// auth.ts (full config — Node runtime)
import NextAuth from "next-auth";
import GitHub from "next-auth/providers/github";
import Credentials from "next-auth/providers/credentials";
import { DrizzleAdapter } from "@auth/drizzle-adapter";
import { db } from "@/db";
import { authConfig } from "./auth.config";

export const { auth, handlers, signIn, signOut } = NextAuth({
  ...authConfig,
  adapter: DrizzleAdapter(db),  // DB session인 경우
  session: { strategy: "jwt" }, // 또는 "database"
  providers: [
    GitHub,
    Credentials({
      authorize: async (creds) => {
        // pw 검증 + user 반환
      },
    }),
  ],
  callbacks: {
    ...authConfig.callbacks,
    async jwt({ token, user }) {
      if (user) token.role = user.role;  // 가입 시점에 role 박기
      return token;
    },
    async session({ session, token }) {
      session.user.role = token.role as string;
      return session;
    },
  },
});
```

```typescript
// middleware.ts (edge runtime — authConfig만 사용)
import NextAuth from "next-auth";
import { authConfig } from "./auth.config";

export default NextAuth(authConfig).auth;

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
```

## Surface별 패턴

### Server Component
```tsx
// app/dashboard/page.tsx
import { auth } from "@/auth";
import { redirect } from "next/navigation";

export default async function DashboardPage() {
  const session = await auth();
  if (!session?.user) redirect("/login");
  if (session.user.role !== "admin") redirect("/no-access");
  return <div>Welcome {session.user.email}</div>;
}
```

### Server Action
```typescript
"use server";
import { auth } from "@/auth";

export async function deletePost(id: string) {
  const session = await auth();
  if (!session?.user || session.user.role !== "admin") {
    throw new Error("Unauthorized");
  }
  await db.posts.delete({ where: { id } });
}
```

### Route Handler
```typescript
// app/api/users/route.ts
import { auth } from "@/auth";
import { NextResponse } from "next/server";

export const runtime = "nodejs";  // DB 직접 접근 시

export async function GET() {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  return NextResponse.json({ users: await getUsers() });
}
```

## Runtime 선택

| Runtime | 장점 | 제약 |
|---|---|---|
| `nodejs` (default) | 모든 Node API, native module, DB driver | cold start 길고 비쌈 |
| `edge` | 빠른 cold start, 글로벌 분산 | Node API 제한, DB driver 호환 적음 (HTTP-based만) |

**규칙**:
- middleware → edge 강제 (Node 못 씀)
- DB 직접 접근 route → `runtime = 'nodejs'` 명시
- 헤비한 라이브러리 (jsonwebtoken, bcrypt 등) → node
- AI/LLM stream 라우트 → edge가 종종 유리

```typescript
// app/api/heavy/route.ts
export const runtime = "nodejs";  // 명시

// app/api/stream/route.ts
export const runtime = "edge";
```

## Secret 경계

### env 사용 규칙
```bash
# .env.local (절대 commit X)
DATABASE_URL=postgres://...
AUTH_SECRET=long-random-string
STRIPE_SECRET_KEY=sk_live_...

NEXT_PUBLIC_API_URL=https://api.example.com   # client 노출 OK
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_live_... # publishable만
```

### 클라이언트 누출 방지
```typescript
// ❌ 위험 — 'use client' 파일에서 process.env.SECRET 사용
"use client";
const key = process.env.STRIPE_SECRET_KEY;  // client에서 undefined → 동작 안 함

// ✅ secret은 server component / action / route handler에서만
async function pay(formData: FormData) {
  "use server";
  const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!);
  // ...
}
```

### 'server-only' 가드
```typescript
// lib/db.ts
import "server-only";  // client에서 import 시 빌드 에러
export const db = createClient(process.env.DATABASE_URL!);
```

## 5축 품질 체크

| 축 | 체크 |
|---|---|
| 정확성 | session 전략(JWT/DB)이 invalidation 요구사항과 맞는가 |
| 안전성 | secret env가 `NEXT_PUBLIC_*` 안 쓰고 server-only로 분리됐는가 |
| 성능 | runtime 선택이 워크로드(DB/AI/static)에 맞는가 |
| 가독성 | 각 surface에 auth() 호출 명시되어 있는가 (보호 안 된 라우트 식별 쉬움) |
| 검증성 | 빌드 출력 client bundle에 secret 문자열 안 보이는가 (`source-map-explorer`) |

## Gotchas

### `NEXT_PUBLIC_` 접두사를 secret에 사용
client bundle에 인라인됨. 빌드 후 .next/static/*.js에 그대로 박힘. `NEXT_PUBLIC`은 publishable key, public API URL만.

### middleware에서 DB adapter 사용
edge runtime에서 Node-only DB driver 깨짐. `auth.config.ts`(edge-safe) + `auth.ts`(full) 분리 패턴 사용. middleware는 config만 import.

### JWT session인데 즉시 로그아웃 기대
JWT는 만료 전엔 유효. 즉시 무효화 필요하면 DB session으로 전략 변경. 아니면 server-side block list 운영.

### role을 client에 의존
`session.user.role === 'admin' && <AdminUI />`만으론 보호 안 됨. server에서 enforce 필수. UI 토글은 UX, 권한은 server.

### `auth()` 호출 누락 라우트
민감 페이지에 `auth()` 빼먹으면 무방비. middleware로 route 그룹 단위 1차 게이트 + 페이지 레벨 2차 확인.

### `runtime = 'edge'` + bcrypt 같은 Node 라이브러리
빌드는 통과해도 런타임 깨짐. bcrypt는 node, edge에서는 Web Crypto API.

### server action에서 throw → cancel 안 함
React 19 form Action의 throw는 후속 Action skip. server action이 form action에 연결됐으면 catch + return error state.

### `process.env.X` 사용 시 build-time vs runtime 혼동
`NEXT_PUBLIC_*`은 build time에 인라인. 그 외 server env는 runtime read. Vercel 등에서 환경변수 바꾼 후 redeploy 필요.

### session callback에서 DB 호출 빈번
모든 RSC 렌더에 session() 호출 → DB 쿼리 폭발. JWT에 role 박아두고 session callback은 token에서 복사만.

### server-only 누출
secret 사용 utility를 client에서 import → 빌드 에러 안 나면 leak. `import "server-only"` 가드 + ESLint `no-restricted-imports`로 client → server-only 차단.

## 도구 사용 패턴 (Harness)
- secret 누출 검사: `Grep("NEXT_PUBLIC_.*(SECRET|KEY|TOKEN)", glob=".env*")` (false positive 검토)
- 보호 안 된 라우트: `Grep("export default.*function.*Page", glob="app/**/page.tsx")` 후 `auth()` 호출 여부
- runtime 명시 누락: `Grep("export const runtime", glob="app/api/**/*.ts")`
- middleware DB import: `Grep("from .*db|from .*prisma|from .*drizzle", path="middleware.ts")` (있으면 위험)
- client bundle 분석: `Bash("ANALYZE=true npx next build")` + secret 문자열 grep
