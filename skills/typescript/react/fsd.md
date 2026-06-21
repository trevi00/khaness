---
keywords: fsd feature-sliced 아키텍처 architecture 폴더구조 folder-structure 레이어 layer 슬라이스 slice 세그먼트 segment 의존성 dependency import 구조 structure
intent: FSD해 구조만들어 폴더정리해 아키텍처설계해 레이어나눠
paths: src/app/ src/pages/ src/widgets/ src/features/ src/entities/ src/shared/
patterns: feature-sliced entities features widgets pages shared
requires: frontend
phase: plan implement review
min_score: 3
---

# Feature-Sliced Design (FSD) 아키텍처 가이드

> 원칙: **레이어 → 슬라이스 → 세그먼트** 3단 계층. 상위→하위 단방향 의존만 허용.
> 참조: https://feature-sliced.design/

## 의사결정 트리

### IF 새 프론트엔드 프로젝트 (Plan)
1. `src/` 아래 6개 레이어 디렉토리 생성 (app/pages/widgets/features/entities/shared)
2. tsconfig paths에 `@app/*`, `@pages/*`, `@widgets/*`, `@features/*`, `@entities/*`, `@shared/*` 등록
3. eslint-plugin-boundaries로 의존성 규칙 강제
4. shared/api, shared/ui, shared/lib, shared/config 세그먼트 구성

### IF 새 도메인 추가 (Implement)
1. `entities/{도메인}/` 생성 (model/types.ts, api/{도메인}Api.ts, ui/{도메인}Card.tsx)
2. `features/{기능}/` 생성 (ui/, model/, api/)
3. 각 슬라이스에 `index.ts` Public API 작성 (명시적 named export만)
4. pages에서 entities + features 조합

### IF "이 코드 어디에 넣지?" (Implement)
- 앱 전역 초기화/프로바이더 → **app**
- URL 매핑 화면 → **pages**
- 여러 페이지에서 재사용하는 복합 UI 블록 → **widgets**
- 사용자 행동/비즈니스 액션 → **features** (AddToCartButton, LoginForm)
- 도메인 데이터 + 표시 컴포넌트 → **entities** (ProductCard, UserAvatar)
- 도메인 무관 유틸/UI → **shared** (Button, formatPrice, apiClient)

### IF 코드 리뷰 (Review)
- [ ] 상위→하위 단방향 import만 사용하는가
- [ ] 같은 레이어 슬라이스 간 직접 import 없는가
- [ ] 모든 외부 접근이 index.ts Public API를 통하는가
- [ ] shared에 비즈니스 로직이 들어가지 않았는가

## 6개 레이어 (위→아래)

| Layer | 슬라이스 여부 | 역할 | 예시 |
|-------|:-----------:|------|------|
| **app** | No | 앱 진입점, 프로바이더, 라우터, 글로벌 스타일 | App.tsx, providers/ |
| **pages** | Yes | URL별 화면. entities+features 조합 | home/, product-detail/, cart/ |
| **widgets** | Yes | 독립적 복합 UI 블록 | header/, footer/, product-grid/ |
| **features** | Yes | 사용자 행동/비즈니스 기능 | add-to-cart/, auth/, search/ |
| **entities** | Yes | 도메인 모델 + 표시 | user/, product/, category/, order/ |
| **shared** | No | 프로젝트 무관 재사용 코드 | api/, ui/, lib/, config/, hooks/ |

## 의존성 규칙

```
app → pages → widgets → features → entities → shared
         (모든 레이어는 shared 사용 가능)
```

**금지 패턴:**
```typescript
// WRONG: 같은 레이어 슬라이스 간 import
// entities/cart/model/store.ts
import { Product } from '@entities/product';  // 금지!

// WRONG: 하위→상위 import
// entities/product/ui/ProductCard.tsx
import { AddToCartButton } from '@features/add-to-cart';  // 금지!
```

## 슬라이스 세그먼트 (5종)

| Segment | 용도 | 내용 |
|---------|------|------|
| **ui/** | 렌더링 | 컴포넌트, 스타일 |
| **model/** | 데이터/로직 | 타입, 스토어, 스키마, 유효성 |
| **api/** | 서버 통신 | API 호출, 쿼리 훅 |
| **lib/** | 내부 유틸 | 헬퍼, 상수 |
| **config/** | 설정 | 피처 플래그, 환경변수 |

## Public API 패턴 (index.ts)

```typescript
// entities/product/index.ts
export { ProductCard } from './ui/ProductCard';
export { ProductPrice } from './ui/ProductPrice';
export { productApi } from './api/productApi';
export { productQueries } from './api/product.queries';
export type { Product, ProductListResponse } from './model/types';

// WRONG: 와일드카드 재내보내기
export * from './model/types';  // 금지! 내부 구조 노출
```

## 크로스-슬라이스 통신 패턴

### 패턴 1: 상위 레이어에서 조합 (권장)
```typescript
// pages/product-detail/ui/ProductDetailPage.tsx
import { ProductCard } from '@entities/product';
import { AddToCartButton } from '@features/add-to-cart';
// pages가 entities + features를 조합
```

### 패턴 2: Slot 패턴 (Props/Children)
```typescript
// entities/product/ui/ProductCard.tsx
interface ProductCardProps {
  product: Product;
  actions?: React.ReactNode;  // 상위 레이어가 주입
}
```

### 패턴 3: @x 크로스-임포트 (entities 간, 최후수단)
```typescript
// entities/cart/@x/product.ts — 명시적 크로스-임포트 파일
export type { CartItemWithProduct } from '../model/types';
```

## 쇼핑 도메인 폴더 구조 (예시)

```
src/
├── app/
│   ├── providers/ (QueryProvider, RouterProvider, ThemeProvider)
│   ├── styles/global.css
│   └── App.tsx
├── pages/
│   ├── home/            (ui/HomePage.tsx, index.ts)
│   ├── catalog/         (ui/CatalogPage.tsx, model/useCatalogFilters.ts)
│   ├── product-detail/  (ui/ProductDetailPage.tsx)
│   ├── cart/            (ui/CartPage.tsx)
│   ├── checkout/        (ui/CheckoutPage.tsx, model/useCheckoutFlow.ts)
│   ├── auth/            (ui/LoginPage.tsx, ui/RegisterPage.tsx)
│   └── admin/           (product-manage/, category-manage/)
├── widgets/
│   ├── header/          (ui/Header.tsx, ui/Navigation.tsx)
│   ├── footer/          (ui/Footer.tsx)
│   └── cart-summary/    (ui/CartSummary.tsx)
├── features/
│   ├── auth/            (ui/LoginForm.tsx, model/useAuth.ts, api/authApi.ts)
│   ├── add-to-cart/     (ui/AddToCartButton.tsx, model/useAddToCart.ts)
│   ├── filter-products/ (ui/ProductFilters.tsx, model/useFilters.ts)
│   ├── search-products/ (ui/SearchBar.tsx, api/searchApi.ts)
│   └── place-order/     (ui/PlaceOrderButton.tsx, api/orderApi.ts)
├── entities/
│   ├── user/            (ui/UserAvatar.tsx, model/types.ts, api/userApi.ts)
│   ├── product/         (ui/ProductCard.tsx, model/types.ts, api/product.queries.ts)
│   ├── category/        (ui/CategoryCard.tsx, model/types.ts, api/category.queries.ts)
│   ├── cart/            (ui/CartItem.tsx, model/cartStore.ts, api/cartApi.ts)
│   └── order/           (ui/OrderCard.tsx, model/types.ts, api/order.queries.ts)
└── shared/
    ├── api/             (apiClient.ts, queryClient.ts, types.ts)
    ├── ui/              (Button.tsx, Card.tsx, Input.tsx, Modal.tsx, Spinner.tsx)
    ├── lib/             (formatPrice.ts, formatDate.ts, cn.ts)
    ├── config/          (env.ts, constants.ts)
    ├── hooks/           (useDebounce.ts, useLocalStorage.ts)
    └── routes/          (paths.ts)
```

## TanStack Query in FSD

- **QueryClient**: `shared/api/queryClient.ts`
- **Query Factory**: `entities/{entity}/api/{entity}.queries.ts` (queryOptions 사용)
- **Mutations**: `features/{feature}/api/` (useMutation + invalidation)

```typescript
// entities/product/api/product.queries.ts
export const productQueries = {
  all: () => ['products'] as const,
  list: (params: ProductListParams) => queryOptions({
    queryKey: [...productQueries.all(), 'list', params],
    queryFn: () => productApi.getAll(params),
  }),
  detail: (id: string) => queryOptions({
    queryKey: [...productQueries.all(), 'detail', id],
    queryFn: () => productApi.getById(id),
  }),
};
```

## Zustand in FSD

- **Entity 스토어**: `entities/{entity}/model/{entity}Store.ts`
- **Feature UI 상태**: `features/{feature}/model/useFilterStore.ts`
- **전역 상태**: `shared/config/` 또는 `app/`

## ESLint Boundaries 설정

```javascript
// eslint.config.js
'boundaries/element-types': [2, {
  default: 'disallow',
  rules: [
    { from: 'app',      allow: ['pages', 'widgets', 'features', 'entities', 'shared'] },
    { from: 'pages',    allow: ['widgets', 'features', 'entities', 'shared'] },
    { from: 'widgets',  allow: ['features', 'entities', 'shared'] },
    { from: 'features', allow: ['entities', 'shared'] },
    { from: 'entities', allow: ['shared'] },
    { from: 'shared',   allow: ['shared'] },
  ],
}],
```

## Gotchas

### Feature vs Entity 혼동
데이터 표시(ProductCard) = Entity. 사용자 액션(AddToCartButton) = Feature. "장바구니에 추가"는 feature, "장바구니 아이템 표시"는 entity.

### shared가 쓰레기통이 됨
`calculateDiscount`, `formatOrderNumber` 같은 비즈니스 로직은 shared가 아니라 entities에 둬야 한다. shared는 도메인 무관 코드만.

### Public API 우회
`@entities/product/ui/ProductCard` 직접 import 금지. 반드시 `@entities/product` (index.ts)를 통해.

### 세그먼트 과잉 분리
파일 1~2개만 들어갈 세그먼트는 만들지 않는다. 작은 feature는 `ui/` + `index.ts`만으로 충분.

### FSD를 쓰면 안 되는 경우
프로토타입, 1~2명 소규모 앱, 버려질 MVP에는 오버엔지니어링. 성장이 예상되는 프로젝트에만 적용.

## 도구 사용 패턴 (Harness)
- 구조 확인: `Glob`으로 `src/entities/*/index.ts` 패턴 검색
- 의존성 위반: `Grep`으로 `from '@features/` 패턴을 entities/ 안에서 검색
- 새 슬라이스: `Bash(mkdir -p)` + `Write`로 index.ts 작성
