---
keywords: 디자인 design UI ui UX ux shadcn tailwind 테일윈드 컴포넌트 component 다크모드 dark-mode 테마 theme 애니메이션 animation 모션 motion framer 스켈레톤 skeleton 레이아웃 layout 반응형 responsive 접근성 accessibility a11y 색상 color 타이포 typography
intent: 디자인해 UI만들어 예쁘게해 세련되게해 다크모드해 테마설정해 애니메이션넣어 반응형해
paths: src/shared/ui/ src/app/styles/ components/ui/
patterns: shadcn radix tailwind framer-motion motion animate cn className
requires: frontend fsd
phase: plan implement review
min_score: 3
---

# 모던 UI/UX 디자인 가이드 (shadcn/ui + Tailwind CSS v4)

> 스택: shadcn/ui (Radix 기반) + Tailwind CSS v4 + Motion (Framer Motion) + Lucide Icons
> 원칙: 소유권 모델 (코드 복사, 의존성 없음), 접근성 내장 (Radix), zero-runtime CSS

## 의사결정 트리

### IF 디자인 시스템 초기화 (Plan)
1. `npx shadcn@latest init` (Tailwind v4 + CSS variables)
2. globals.css에 OKLCh 색상 토큰 설정 (light + dark)
3. 쇼핑/판매 도메인 시맨틱 색상 추가 (sale, new, rating, free-shipping)
4. shadcn 필수 컴포넌트 추가 (button, card, dialog, sheet, input, tabs, badge, skeleton, toast)
5. Motion 설치 (`pnpm add motion`)

### IF 새 페이지 레이아웃 (Implement)
1. 반응형 그리드: `grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4`
2. 컨테이너: `mx-auto max-w-7xl px-4 sm:px-6 lg:px-8`
3. 스티키 요소: `sticky top-0 z-50 backdrop-blur`
4. 모바일 퍼스트: 기본값이 모바일, sm/md/lg로 확장

### IF 애니메이션 선택 (Implement)
- 호버/포커스/색상 전환 → **CSS** (transition-*)
- 페이지 전환, 리스트 정렬, 마운트/언마운트 → **Motion** (AnimatePresence)
- 스크롤 트리거, 패럴랙스, 드래그 → **Motion** (useScroll, whileDrag)
- 스켈레톤 로딩 → **CSS** (animate-pulse)

## shadcn/ui 핵심

### 왜 shadcn인가
- **소유권 모델**: 코드가 프로젝트에 복사됨. npm 의존성 lock-in 없음
- **Radix UI**: 접근성(WAI-ARIA, 키보드, 포커스) 자동 처리
- **Tailwind 네이티브**: zero-runtime CSS, SSR 안전, 작은 번들
- **쇼핑/판매 도메인 필수 컴포넌트**: Sheet(카트 드로어), Dialog(퀵뷰), Carousel(상품 이미지)

### 필수 컴포넌트 목록
```bash
npx shadcn@latest add button card dialog dropdown-menu input \
  sheet skeleton tabs avatar badge separator toast carousel \
  command popover select breadcrumb pagination table sidebar
```

## 색상 시스템 (OKLCh)

### Light Mode 핵심
```css
:root {
  --background: oklch(0.995 0.002 250);      /* 따뜻한 오프화이트 */
  --primary: oklch(0.55 0.20 250);            /* 딥 블루 — 신뢰, 안정 */
  --accent: oklch(0.75 0.18 85);              /* 따뜻한 앰버 — Sale, New 뱃지 */
  --destructive: oklch(0.58 0.24 27);         /* 에러, 위험 */
  --radius: 0.625rem;                          /* 10px 기본 */
}
```

### Dark Mode 핵심
```css
.dark {
  --background: oklch(0.13 0.01 250);         /* 딥 네이비 블랙 */
  --primary: oklch(0.70 0.18 250);            /* 밝은 버전 */
  --border: oklch(1 0 0 / 10%);              /* 투명도 기반 */
}
```

### 쇼핑/판매 도메인 시맨틱 색상
```css
--color-sale: oklch(0.58 0.24 27);            /* 할인가 */
--color-new: oklch(0.55 0.20 250);            /* 신상품 뱃지 */
--color-rating: oklch(0.80 0.18 85);          /* 별점 */
--color-free-shipping: oklch(0.65 0.18 145);  /* 무료배송 */
```

## 레이아웃 패턴

### 상품 목록 페이지
```
[필터 사이드바 (lg만)] + [그리드 grid-cols-2/3/4] + [페이지네이션]
```

### 상품 상세 페이지
```
[브레드크럼] → [이미지 갤러리 | 상품 정보(가격+옵션+장바구니)] → [탭(설명/스펙/리뷰)] → [관련 상품 캐러셀]
```

### 카트 드로어 (Sheet)
```
[헤더(수량)] → [아이템 리스트(AnimatePresence)] → [합계 + 결제 버튼]
```

### 체크아웃 (멀티스텝)
```
[스텝 인디케이터] → [AnimatePresence mode="wait" 폼 전환] + [주문 요약(sticky)]
```

### 관리자 대시보드
```
[shadcn Sidebar] + [SidebarInset → header + main]
```

## 애니메이션 레시피

### 상품 그리드 입장
```typescript
const containerVariants = { hidden: {}, visible: { transition: { staggerChildren: 0.06 } } }
const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: { type: "spring", stiffness: 300, damping: 24 } },
}
```

### 카트 뱃지 카운트
```typescript
<motion.span key={count}
  initial={{ scale: 0 }} animate={{ scale: 1 }}
  transition={{ type: "spring", stiffness: 500, damping: 20 }} />
```

### 페이지 전환
```typescript
<AnimatePresence mode="wait">
  <motion.main key={location.pathname}
    initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
    transition={{ type: "tween", ease: [0.2, 0, 0, 1], duration: 0.25 }} />
</AnimatePresence>
```

### 스켈레톤 (CSS — Motion 불필요)
```tsx
<div className="animate-pulse space-y-3">
  <div className="aspect-square rounded-lg bg-muted" />
  <div className="h-4 w-3/4 rounded bg-muted" />
</div>
```

## 반응형 전략

| 브레이크포인트 | 값 | 용도 |
|--------------|-----|------|
| 기본 | 0px | 모바일 (base) |
| sm | 640px | 태블릿 |
| md | 768px | 태블릿 가로 |
| lg | 1024px | 랩탑 |
| xl | 1280px | 데스크탑 |

**모바일 퍼스트**: 기본값이 모바일, sm/md/lg로 확장. 터치 타겟 최소 44x44px.

## 접근성 (Radix 자동 + 수동 보완)

- Radix가 처리: WAI-ARIA, 키보드 내비게이션, 포커스 트랩/복원
- 수동 추가 필요: `aria-label` (아이콘 버튼), `aria-live` (카트 카운트), `sr-only` (스크린 리더용 텍스트)
- 색상 대비: WCAG AA 4.5:1 (일반 텍스트), 3:1 (UI 컴포넌트)
- 다크 모드: 순백(#fff) 금지 → oklch(0.95 0 0), 순흑(#000) 금지

## 다크 모드 구현

```typescript
// ThemeProvider: localStorage + system preference
// class="dark" on <html>
// CSS variables 전환 → 동일 className으로 light/dark 자동 적용
```

## Gotchas

### Glassmorphism 남용
`backdrop-blur`는 플로팅 요소(헤더, 오버레이)에만. 폼/체크아웃 같은 주요 콘텐츠에 사용하면 가독성 저하.

### 순백/순흑 사용 금지
다크 모드에서 #fff 텍스트는 눈부심. oklch(0.95 0 0) 사용. 라이트 모드에서 #000도 마찬가지.

### animate-pulse vs Motion
스켈레톤은 CSS animate-pulse로 충분. Motion은 마운트/언마운트/리스트 정렬 같은 복잡한 케이스에만.

### 컨테이너 쿼리 활용
상품 카드가 그리드/리스트/사이드바 등 다양한 컨텍스트에서 사용되면 `@container`로 카드 자체가 적응하게.

### prefers-reduced-motion 존중
```typescript
const shouldReduceMotion = useReducedMotion()
// true면 애니메이션 duration을 0으로
```

## 도구 사용 패턴 (Harness)
- 컴포넌트 추가: `Bash(npx shadcn@latest add {component})`
- 스타일 확인: `Read(src/app/styles/globals.css)`
- 컴포넌트 수정: `Read` → `Edit` (shadcn 코드는 프로젝트 소유)
- 시각 확인: Playwright MCP `browser_take_screenshot`
