---
keywords: 프론트 프론트엔드 frontend 프런트 UI ui 화면 페이지 컴포넌트 component 레이아웃 layout 스타일 style CSS css 반응형 responsive 폼 form 버튼 button 모달 modal 네비게이션 nav 라우팅 routing 상태관리 state 리액트 React 타입스크립트 TypeScript Vite vite 번들 청크 chunk 스플리팅
intent: UI만들어 컴포넌트추가해 화면꾸며 레이아웃배치해 스타일링해 프론트해 프론트만들어 화면만들어 UI해
paths: src/components src/pages src/views src/layouts src/styles src/hooks src/store src/assets src/api src/types components/ pages/ views/ public/ static/ styles/ css/ e2e/
patterns: react vue svelte next nuxt astro tailwind styled-components emotion chakra shadcn radix zustand redux pinia vite webpack tanstack-query react-query monaco-editor recharts playwright
requires: testing security
phase: plan implement review
min_score: 3
---

# Frontend Development Guide

## 의사결정 트리

### IF 새 프로젝트 시작 (Plan)
1. 프레임워크와 스타일링은 프로젝트 요구사항에 맞게 선택
2. 상태 관리: 서버 상태와 클라이언트 상태 분리
3. `.claude/plan.md`에 컴포넌트 트리 설계 작성

### IF 새 페이지 추가 (Implement)
1. 페이지 컴포넌트 생성 + lazy loading 적용
2. 인증 필요 시 ProtectedRoute 감싸기
3. API 모듈 생성 (도메인별)
4. 로딩/에러/빈 상태 처리
5. 반응형 디자인
6. **→ testing 스킬: E2E 테스트 작성**

### IF 새 컴포넌트 작성 (Implement)
1. Props 타입 인터페이스 정의
2. 분류: UI(재사용) / Feature(도메인) / Layout / Page
3. 로딩 상태 → Skeleton 컴포넌트
4. 접근성 (aria-label, role, 키보드)

### IF 폼 구현 (Implement)
1. 클라이언트 + 서버 유효성 검사
2. 제출 중 버튼 비활성화 (중복 제출 방지)
3. 성공/실패 피드백
4. **→ security 스킬: XSS, CSRF 방지 확인**

### IF 성능 문제 (Review)
1. 코드 스플리팅 + 매뉴얼 청크 분리 확인
2. 번들 사이즈 분석
3. 불필요한 리렌더링 확인
4. 이미지 최적화 (WebP, lazy loading)

## 디렉토리 구조 (권장)
```
src/
├── api/           # API 모듈 (도메인별)
├── store/         # 전역 상태
├── hooks/         # 커스텀 훅
├── types/         # TypeScript 타입
├── components/
│   ├── ui/        # 재사용 UI (Button, Card, Modal)
│   ├── layout/    # 페이지 골격
│   └── [feature]/ # 도메인별 컴포넌트
└── pages/         # 라우트 진입점 (lazy loading)
```

## 새 기술 도입 시 리서치 체크리스트

새 라이브러리/프레임워크를 프로젝트에 추가할 때 **구현 전에** 반드시 수행:

1. **버전 확인**: `npm info <pkg> version`으로 최신 stable 확인. pipeline.md 명세와 현재 버전이 다를 수 있음
2. **공식 문서 조회**: context7 MCP → `resolve-library-id` → `query-docs`로 설치/설정 방법 확인
3. **Breaking Changes 검색**: WebSearch로 "v{N} migration guide" / "v{N} breaking changes" 검색
4. **의존성 호환성**: 기존 패키지(React, Vite 등)와 버전 호환 확인
5. **플러그인/확장 호환**: 사용할 플러그인이 현재 메이저 버전을 지원하는지 확인
6. **Known Gotchas 수집**: WebSearch로 "{pkg} v{N} gotchas / common issues" 검색 → 스킬에 기록
7. **최소 POC**: 설정 파일 1개 + 컴포넌트 1개로 빌드 확인 후 전체 적용

> **교훈 (Phase 18)**: PMD 4회, Checkstyle 3회, SpotBugs 2회 실패 — 감으로 설정했기 때문. 검색 먼저 → 한 도구씩 → 빌드 확인.
> **교훈 (Phase 20 조사)**: pipeline.md가 Tailwind v3 방식으로 작성되어 있었으나 실제 v4는 완전히 다른 설정 체계. 명세 작성 시점 ≠ 구현 시점 버전.

## Tailwind CSS v4 가이드 (쇼핑/판매 도메인 예시)

### 설치 (Vite 프로젝트)
```bash
npm install tailwindcss @tailwindcss/vite                    # 코어
npm install @tailwindcss/forms @tailwindcss/typography        # 플러그인
npm install clsx tailwind-merge                               # 유틸리티
```

### 설정 — v3과 완전히 다름
| v3 (pipeline.md 원본) | v4 (실제) |
|------------------------|-----------|
| `tailwind.config.js` | **불필요** — CSS `@theme {}` |
| `postcss.config.js` | **불필요** — `@tailwindcss/vite` |
| `@tailwind base/components/utilities` | `@import "tailwindcss"` |
| `plugins: [require('@tailwindcss/forms')]` | `@plugin "@tailwindcss/forms"` |

### vite.config.ts
```typescript
import tailwindcss from "@tailwindcss/vite"
// plugins 배열에 tailwindcss() 추가
```

### CSS 진입점 (index.css)
```css
@import "tailwindcss";
@plugin "@tailwindcss/forms";
@plugin "@tailwindcss/typography";

@theme {
  --font-sans: "Pretendard Variable", system-ui, sans-serif;
  --color-primary: #2563eb;
  --color-danger: #dc2626;
  --color-success: #16a34a;
  --spacing: 4px;
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
}
```

### cn() 유틸리티 (clsx + tailwind-merge)
```typescript
// src/shared/lib/cn.ts
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

### Gotchas (v4 전용)
- **동적 클래스명 불가**: `bg-${color}-600` → 정적 매핑 객체 사용
- **tailwind-merge v3.x 필요**: v2는 Tailwind v3용, v4에서 작동 안 함
- **`@theme` ↔ TypeScript 자동 동기화 없음**: tokens.ts 수동 유지
- **Radix UI 배경 투명 이슈**: CSS 변수에 `hsl()` 래핑 필요
- **Pretendard**: CDN `pretendardvariable-dynamic-subset.min.css` 사용, 폰트명 `"Pretendard Variable"`

## FE 디자인 세련화 체크리스트 (Design Sophistication)

> Phase 20~23 + 도메인 감사에서 추출한 반복 가능한 의사결정 트리.
> "영어권 개발자 수준의 세련된 UI"를 목표로 할 때 적용.

### IF 디자인 세련화 / 고도화 (Review)
1. **아이콘 감사**: emoji/Unicode → Lucide SVG 아이콘으로 교체
   - UI 아이콘(🔍🛒★☆): 반드시 SVG (Lucide/Heroicons)
   - 마케팅 텍스트(⚡📦): emoji 허용 (배송 안내 등 콘텐츠 내)
2. **색상 감사**: `text-[#xxx]`, `bg-[#xxx]` → 디자인 토큰
   - 범용: `text-danger`, `text-success`, `text-warning`, `text-primary`
   - 도메인 전용: `text-bid-buy`, `bg-bid-sell` (시맨틱 토큰으로 분리)
   - `bg-[#f4f4f4]` 같은 회색 → `bg-gray-100` 시스템 색상
3. **마이크로 인터랙션 추가**:
   - 버튼: `hover:scale-[1.02] active:scale-[0.98] transition-all duration-200`
   - 포커스: `focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary`
   - 그림자: `shadow-sm hover:shadow-md` (primary/danger 버튼)
4. **로딩 상태 세련화**: 텍스트("로딩 중...") → `Loader2` 스피너 (lucide-react)
5. **빈 상태 표준화**: `<p>데이터 없음</p>` → `EmptyState` 컴포넌트 (아이콘+제목+설명+CTA)
6. **평점 표시**: Unicode `★☆` → `Rating` 컴포넌트 (SVG Star, half-star, aria-label)
7. **토스트 알림**: `alert()` → Sonner (`richColors`, `closeButton`, `duration={3000}`)
8. **Skeleton 로딩**: `<Loading />` → 레이아웃 매칭 Skeleton (`animate-pulse`)
9. **Dropdown/Tooltip 애니메이션**: display:none 토글 → opacity/scale 트랜지션

### 디자인 토큰 추가 패턴
도메인별 시맨틱 색상이 필요할 때 (예: 입찰 buy/sell):
```css
@theme {
  /* 기존 danger/success와 의미적으로 구분되는 도메인 전용 색상 */
  --color-bid-buy: #ef6253;
  --color-bid-buy-hover: #d9574a;
  --color-bid-sell: #41b979;
  --color-bid-sell-hover: #389e68;
}
```
- 색상이 기존 토큰(danger/success)과 시각적으로 다른 역할이면 별도 토큰 생성
- 같은 역할이면 기존 토큰 재사용 (중복 방지)

### 공통 UI 컴포넌트 표준 (shadcn/ui 참고)
| 컴포넌트 | 필수 요소 | 패턴 |
|----------|----------|------|
| Button | loading 스피너, disabled, size variants | `Loader2` + `animate-spin` |
| Rating | SVG Star, half-star, aria-label | `Star` (lucide) + `fill-amber-400` |
| EmptyState | 아이콘 + 제목 + 설명 + optional CTA | `PackageOpen` default icon |
| Skeleton | animate-pulse, 레이아웃 매칭 | `rounded-lg bg-gray-200` |
| Loading | 스피너 + 메시지 | `Loader2` center-aligned |

## Gotchas

### 디자인 기본값 함정
Claude는 기본적으로 Inter 폰트, 보라색/파란색 그라디언트, 둥근 카드 UI를 생성하는 경향이 있음. 프로젝트의 실제 디자인 시스템을 먼저 확인하고 따를 것.

### dangerouslySetInnerHTML
React는 기본적으로 XSS를 방지하지만, `dangerouslySetInnerHTML`이나 `innerHTML`을 사용하면 보호가 무력화됨. 사용자 입력은 반드시 DOMPurify 등으로 sanitize.

### useEffect 클린업 누락
async 작업이 있는 useEffect에서 클린업 함수를 빠뜨리면 언마운트 후 setState 호출로 메모리 누수 발생. AbortController 사용할 것.

### 환경변수 접두사
Vite: `VITE_` 접두사 필수. Next.js: `NEXT_PUBLIC_` 접두사 필수. 접두사 없으면 클라이언트에서 undefined.

### 번들에 시크릿 포함
프론트엔드 코드는 모두 공개됨. API 키나 시크릿을 프론트엔드 환경변수에 넣지 말 것. 백엔드 프록시를 통해 호출.

### key prop에 index 사용
리스트 렌더링에서 `index`를 key로 사용하면 항목 추가/삭제/정렬 시 상태가 꼬임. 고유 ID 사용 필수.

### CSS 우선순위 충돌
Tailwind와 컴포넌트 라이브러리(MUI, Chakra 등) 동시 사용 시 스타일 충돌 빈번. `important: true`나 prefix 설정으로 해결하거나 하나만 선택.

### React StrictMode 이중 렌더링
개발 모드에서 StrictMode가 useEffect를 두 번 호출함. API 호출이 두 번 되는 것은 버그가 아니라 정상 동작. 프로덕션에서는 한 번만 실행됨.

## 도구 사용 패턴 (Harness)
- 컴포넌트 찾기: `Glob("src/components/**/*.tsx")`로 패턴 매칭, `Grep`으로 export/import 추적
- 스타일 검색: `Grep`으로 클래스명/tailwind 클래스 검색 (Bash(grep) 대신)
- 빌드 실행: `Bash`로 실행하되, 에러 시 같은 명령 재시도보다 로그 분석 우선
- 번들 분석: `Bash`로 빌드 후 `Read`로 결과 파일 확인

## 에러 복구 패턴 (Harness)
- 빌드 실패 → 에러 메시지를 먼저 읽고 해당 파일/라인을 `Read`로 확인
- 타입 에러 → `Grep`으로 관련 타입 정의 검색 → `Edit`으로 수정
- 모듈 미발견 → `Bash(npm ls)` 또는 node_modules 삭제 후 `Bash(npm ci)` 재설치
- 런타임 에러 → 브라우저 콘솔 로그 확인, 해당 컴포넌트 `Read`로 검토
