---
keywords: 셋업 setup 초기설정 init 프로젝트생성 vite 빌드 build 린트 lint eslint prettier husky 패키지 package pnpm npm tsconfig typescript 환경변수 env docker dockerfile nginx proxy 프록시
intent: 셋업해 프로젝트만들어 초기설정해 린트설정해 환경변수해
paths: vite.config.ts tsconfig.json eslint.config.js .prettierrc package.json Dockerfile docker-compose.yml .env
patterns: vite eslint prettier husky lint-staged pnpm tsconfig docker nginx
requires: frontend fsd
phase: plan implement
min_score: 3
---

# React + TypeScript 프로젝트 셋업 가이드

> 스택: Vite 6 + React 18 + TypeScript + pnpm + ESLint flat config + Prettier + Tailwind CSS v4
> FSD 아키텍처 기반 폴더 구조

## 의사결정 트리

### IF 새 프로젝트 생성 (Plan)
1. `pnpm create vite@latest {name} -- --template react-ts`
2. FSD 폴더 구조 생성 (fsd.md 참조)
3. tsconfig paths 설정 (@app, @pages, @widgets, @features, @entities, @shared)
4. ESLint flat config + Prettier + Tailwind 설정
5. Husky + lint-staged 설정
6. 환경변수 (.env) + Zod 검증 설정
7. Axios 인스턴스 + JWT 인터셉터 설정
8. Docker 멀티스테이지 빌드 설정

### IF 백엔드 API 연결 (Implement)
1. `.env.development`에 `VITE_API_BASE_URL=http://localhost:8080`
2. vite.config.ts에 `/api` 프록시 설정
3. `shared/api/apiClient.ts`에 Axios 인스턴스 + 인터셉터

## 핵심 설정 파일

### vite.config.ts
```typescript
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react-swc'
import tsconfigPaths from 'vite-tsconfig-paths'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react(), tsconfigPaths(), tailwindcss()],
    server: {
      port: 3000,
      proxy: {
        '/api': {
          target: env.VITE_API_BASE_URL || 'http://localhost:8080',
          changeOrigin: true,
        },
      },
    },
    build: {
      target: 'es2020',
      rollupOptions: {
        output: {
          manualChunks: { vendor: ['react', 'react-dom'], router: ['react-router-dom'] },
        },
      },
    },
  }
})
```

### tsconfig.app.json (핵심 옵션)
```json
{
  "compilerOptions": {
    "target": "ES2020",
    "jsx": "react-jsx",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"],
      "@app/*": ["src/app/*"],
      "@pages/*": ["src/pages/*"],
      "@widgets/*": ["src/widgets/*"],
      "@features/*": ["src/features/*"],
      "@entities/*": ["src/entities/*"],
      "@shared/*": ["src/shared/*"]
    }
  }
}
```

### 환경변수 타입 + Zod 검증
```typescript
// src/shared/config/env.ts
import { z } from 'zod'
const envSchema = z.object({
  VITE_API_BASE_URL: z.string().url(),
  VITE_APP_TITLE: z.string().min(1),
  VITE_APP_ENV: z.enum(['development', 'staging', 'production']).default('development'),
})
const parsed = envSchema.safeParse(import.meta.env)
if (!parsed.success) throw new Error('Invalid env: ' + JSON.stringify(parsed.error.flatten()))
export const env = parsed.data
```

### Axios + JWT 인터셉터 (핵심)
```typescript
// shared/api/apiClient.ts
// Access Token: 메모리 저장 (XSS 안전)
// Refresh Token: httpOnly 쿠키 (서버 rotation)
// 401 시: 큐잉 → 토큰 갱신 → 일괄 재시도
// 갱신 실패: 로그인 페이지 리다이렉트
```

| 항목 | 값 |
|------|---|
| Access Token | Authorization 헤더 (Bearer), 메모리 저장, 30분 |
| Refresh Token | httpOnly 쿠키, 7일, 서버 rotation |
| 동시 요청 | failedQueue로 큐잉 → 갱신 완료 후 일괄 재시도 |

### 초기 의존성
```bash
# 프로덕션
pnpm add react react-dom react-router-dom axios zod

# 개발
pnpm add -D typescript @types/react @types/react-dom \
  @vitejs/plugin-react-swc vite vite-tsconfig-paths \
  eslint @eslint/js typescript-eslint \
  eslint-plugin-react eslint-plugin-react-hooks eslint-plugin-react-refresh \
  eslint-plugin-jsx-a11y eslint-plugin-import-x eslint-config-prettier \
  prettier prettier-plugin-tailwindcss \
  husky lint-staged \
  tailwindcss @tailwindcss/vite
```

### Docker (프론트엔드 + nginx)
```dockerfile
# Stage 1: Build
FROM node:20-alpine AS builder
RUN corepack enable && corepack prepare pnpm@latest --activate
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

# Stage 2: Serve
FROM nginx:1.27-alpine
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
```

nginx.conf: `/api/` → `proxy_pass http://backend:8080`, SPA fallback `try_files $uri /index.html`

## 패키지 매니저: pnpm 추천

| 항목 | npm | pnpm |
|------|-----|------|
| 속도 | 기준 | 3-4x 빠름 |
| 디스크 | 기준 | -75% (content-addressable store) |
| Phantom dep | 허용 | 차단 (strict isolation) |

## Gotchas

### moduleResolution: "bundler" 필수
Vite/SWC 환경에서 `node`를 쓰면 경로 해석 실패. 반드시 `bundler`.

### VITE_ 접두사 필수
환경변수에 `VITE_` 접두사 없으면 클라이언트에서 접근 불가.

### eslint-config-prettier 순서
반드시 ESLint config 배열의 **마지막**에 위치해야 포매팅 규칙 충돌 방지.

### pre-commit에 tsc 제외
`tsc --noEmit`은 전체 프로젝트 대상이라 느림. pre-commit에서 제외하고 CI에서 수행.

## 도구 사용 패턴 (Harness)
- 프로젝트 생성: `Bash(pnpm create vite@latest)`
- 설정 파일 작성: `Write`로 vite.config.ts, tsconfig.json 등 생성
- 의존성 설치: `Bash(pnpm add ...)` — 서버 종료 없이 실행
- 환경변수 확인: `Read(.env.development)` + `Grep(VITE_)`
