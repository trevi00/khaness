---
keywords: 패턴 pattern 상태관리 state zustand tanstack-query react-query 폼 form react-hook-form zod 라우팅 routing 타입 type 제네릭 generic 에러 error 성능 performance 최적화 optimize 훅 hook useMutation useQuery
intent: 패턴적용해 상태관리해 폼만들어 라우팅해 타입정의해 에러처리해 최적화해
paths: src/entities/ src/features/ src/shared/
patterns: zustand tanstack react-query react-hook-form zod useQuery useMutation useForm zodResolver
requires: frontend fsd
phase: implement review
min_score: 3
---

# 모던 React + TypeScript 패턴 가이드

> 스택: React 18 + Zustand + TanStack Query v5 + React Hook Form + Zod + React Router v7

## 의사결정 트리

### IF 상태 관리 선택 (Plan)
- **서버 상태** (API 데이터) → TanStack Query (캐시, 재검증, 낙관적 업데이트)
- **클라이언트 전역** (인증, 카트) → Zustand (3KB, Provider 불필요, persist)
- **폼 상태** → React Hook Form + Zod (런타임 검증 + 타입 동시 생성)
- **로컬 UI** (모달 열림, 탭 선택) → useState (추가 라이브러리 불필요)

### IF API 호출 추가 (Implement)
1. `entities/{entity}/api/{entity}Api.ts` — Axios 호출 함수
2. `entities/{entity}/api/{entity}.queries.ts` — Query Factory (queryOptions)
3. 조회 → `useQuery(productQueries.list(params))`
4. 변경 → `features/{feature}/`에 `useMutation` + `invalidateQueries`

### IF 폼 추가 (Implement)
1. Zod 스키마 정의 (model/{name}Schema.ts)
2. `useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema) })`
3. 에러 메시지는 스키마에 정의 (한국어 지원)

## TanStack Query v5 패턴

### Query Factory 패턴
```typescript
// entities/product/api/product.queries.ts
import { queryOptions } from '@tanstack/react-query'

export const productQueries = {
  all: () => ['products'] as const,
  lists: () => [...productQueries.all(), 'list'] as const,
  list: (params: ProductListParams) => queryOptions({
    queryKey: [...productQueries.lists(), params],
    queryFn: () => productApi.getAll(params),
    staleTime: 5 * 60 * 1000,
  }),
  detail: (id: string) => queryOptions({
    queryKey: [...productQueries.all(), 'detail', id],
    queryFn: () => productApi.getById(id),
  }),
}
```

### Mutation + 캐시 무효화
```typescript
// features/add-to-cart/model/useAddToCart.ts
export const useAddToCart = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (params: { productId: string; quantity: number }) =>
      cartApi.addItem(params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: cartQueries.all() })
    },
  })
}
```

### 낙관적 업데이트
```typescript
useMutation({
  mutationFn: cartApi.updateQuantity,
  onMutate: async (newData) => {
    await queryClient.cancelQueries({ queryKey: cartQueries.all() })
    const previous = queryClient.getQueryData(cartQueries.all())
    queryClient.setQueryData(cartQueries.all(), (old) => /* 업데이트 */)
    return { previous }
  },
  onError: (_err, _vars, context) => {
    queryClient.setQueryData(cartQueries.all(), context?.previous)  // 롤백
  },
  onSettled: () => {
    queryClient.invalidateQueries({ queryKey: cartQueries.all() })
  },
})
```

### Prefetch (마우스 호버)
```typescript
const prefetchProduct = (id: string) => {
  queryClient.prefetchQuery(productQueries.detail(id))
}
<ProductCard onMouseEnter={() => prefetchProduct(product.id)} />
```

## Zustand 패턴

### Entity Store (persist + devtools)
```typescript
// entities/cart/model/cartStore.ts
import { create } from 'zustand'
import { devtools, persist } from 'zustand/middleware'

interface CartState {
  items: CartItem[]
  addItem: (item: CartItem) => void
  removeItem: (productId: string) => void
  getTotalPrice: () => number
}

export const useCartStore = create<CartState>()(
  devtools(persist((set, get) => ({
    items: [],
    addItem: (item) => set((state) => {
      const existing = state.items.find(i => i.productId === item.productId)
      if (existing) {
        return { items: state.items.map(i =>
          i.productId === item.productId ? { ...i, quantity: i.quantity + item.quantity } : i
        )}
      }
      return { items: [...state.items, item] }
    }),
    removeItem: (productId) => set((s) => ({
      items: s.items.filter(i => i.productId !== productId)
    })),
    getTotalPrice: () => get().items.reduce((sum, i) => sum + i.price * i.quantity, 0),
  }), { name: 'cart-storage' }))
)
```

### 배치 위치 (FSD)
| 스토어 유형 | 위치 |
|------------|------|
| Entity 상태 (cart, user) | `entities/{entity}/model/` |
| Feature UI 상태 (필터) | `features/{feature}/model/` |
| 전역 (테마) | `shared/config/` 또는 `app/` |

## React Hook Form + Zod

### 스키마 정의
```typescript
// features/auth/model/authSchema.ts
import { z } from 'zod'

export const loginSchema = z.object({
  email: z.string().email('유효한 이메일을 입력해주세요'),
  password: z.string().min(8, '비밀번호는 8자 이상이어야 합니다'),
})

export const registerSchema = z.object({
  email: z.string().email('유효한 이메일을 입력해주세요'),
  password: z.string().min(8, '비밀번호는 8자 이상이어야 합니다')
    .regex(/[A-Za-z]/, '영문을 포함해야 합니다')
    .regex(/[0-9]/, '숫자를 포함해야 합니다'),
  name: z.string().min(1, '이름을 입력해주세요').max(50),
  phone: z.string().regex(/^\d{10,11}$/, '전화번호 형식이 올바르지 않습니다'),
})

export type LoginInput = z.infer<typeof loginSchema>
export type RegisterInput = z.infer<typeof registerSchema>
```

### 폼 사용
```typescript
const { register, handleSubmit, formState: { errors } } = useForm<LoginInput>({
  resolver: zodResolver(loginSchema),
})
```

## TypeScript 패턴

### API 응답 Discriminated Union
```typescript
type ApiResult<T> =
  | { success: true; data: T }
  | { success: false; error: ApiError }

interface ApiError {
  status: number
  code: string
  message: string
}
```

### 페이지네이션 제네릭
```typescript
interface PagedResult<T> {
  content: T[]
  totalElements: number
  totalPages: number
  currentPage: number
  size: number
}
```

### 제네릭 리스트 컴포넌트
```typescript
interface ListProps<T> {
  items: T[]
  renderItem: (item: T) => React.ReactNode
  keyExtractor: (item: T) => string
  emptyMessage: string
}
function List<T>({ items, renderItem, keyExtractor, emptyMessage }: ListProps<T>) { ... }
```

## 에러 처리 전략

### Axios 인터셉터
```typescript
// 401 → 토큰 갱신 (apiClient에서 자동 처리)
// 422 → 폼에 위임 (throw해서 React Hook Form이 처리)
// 5xx → 토스트 알림
// 네트워크 에러 → 재시도 버튼
```

### Error Boundary + Suspense
```typescript
<ErrorBoundary fallback={<ErrorPage />}>
  <Suspense fallback={<Skeleton />}>
    <ProductList />
  </Suspense>
</ErrorBoundary>
```

## React Router v7 패턴

### 보호 라우트
```typescript
function RequireAuth({ children }: { children: React.ReactNode }) {
  const user = useUserStore((s) => s.user)
  const location = useLocation()
  if (!user) return <Navigate to="/auth/login" state={{ from: location }} replace />
  return <>{children}</>
}
```

### 라우트 상수
```typescript
// shared/routes/paths.ts
export const ROUTES = {
  HOME: '/',
  CATALOG: '/catalog',
  PRODUCT_DETAIL: '/products/:id',
  CART: '/cart',
  CHECKOUT: '/checkout',
  LOGIN: '/auth/login',
} as const
```

## 성능 최적화

### React Compiler (2025+)
- 95%의 메모이제이션을 자동 처리 → 수동 useMemo/useCallback은 **프로파일링 후에만**

### 코드 스플리팅
```typescript
const ProductDetailPage = lazy(() => import('@pages/product-detail'))
// 라우트 레벨에서만 lazy. 컴포넌트 레벨은 과잉.
```

### 가상화 (큰 리스트)
```typescript
import { useVirtualizer } from '@tanstack/react-virtual'
// 상품 1000개+ 목록에서만. 20~50개는 불필요.
```

## Gotchas

### TanStack Query + Zustand 역할 혼동
서버 데이터(상품 목록, 주문)는 TanStack Query. 클라이언트 상태(카트 아이템, 인증)만 Zustand. 서버 데이터를 Zustand에 복사하면 동기화 지옥.

### Zod 스키마 = 단일 진실 소스
타입을 수동으로 interface/type으로 정의하지 말고, `z.infer<typeof schema>`로 추출. 검증 로직과 타입이 항상 일치.

### useEffect 데이터 fetching 금지
`useEffect` + `fetch`는 레이스 컨디션, 캐시 없음, 로딩 상태 수동 관리. TanStack Query 사용.

### 수동 메모이제이션 자제
React Compiler가 있으면 useMemo/useCallback은 거의 불필요. 성능 문제가 측정된 후에만 추가.

## 도구 사용 패턴 (Harness)
- 쿼리 팩토리 확인: `Grep(queryOptions)` → entities/*/api/ 검색
- 스토어 확인: `Grep(create<)` → entities/*/model/ 검색
- 스키마 확인: `Grep(z.object)` → features/*/model/ 검색

---

## 최신 패턴 (2026-04 갱신)

> 출처: react.dev 공식 docs (2026-04-19) + state classification intake (2026-04-20) + state/effect/key/test boundary (2026-04-26).
> 적용 범위: React 18 + 19 공통 (19 전용 API는 명시 표기). 19 채택 결정은 `version-selection.md` 참조.

### 상태 분류 — 출처가 다르면 도구가 다르다

state는 **소유자(source of truth) + lifetime**으로 분류한다. 한 도구에 모든 상태를 욱여넣지 말 것.

| 분류 | source | 예시 | 추천 도구 |
|---|---|---|---|
| Server state | API/DB | 상품 목록, 주문, 사용자 프로필 | TanStack Query |
| Shared client state | 클라이언트 메모리 (cross-tree) | 카트, 인증 토큰, 테마 | Zustand / Context |
| URL state | 라우터 query/path | 필터, 페이지, 정렬 | route loader / `useSearchParams` |
| Form state | 입력 + 검증 | 로그인, 회원가입 | RHF + Zod |
| Local UI state | 단일 컴포넌트 | 모달 열림, 탭 선택, hover | `useState` |

**boundary가 흐려지는 시그널**:
- API 응답을 Zustand에 복사 → 캐시 동기화 지옥. server state는 TanStack Query에 둠.
- URL state를 Zustand로 → 뒤로가기/공유 깨짐. URL을 source로.
- 폼 진행 상태를 Context에 → 폼 라이브러리가 이미 해결한 일. RHF에 위임.

### Effect 분류 — derived state는 effect가 아니다

```tsx
// ❌ 흔한 안티패턴: effect로 derived state 계산
useEffect(() => {
  setTotal(items.reduce((s, i) => s + i.price, 0));
}, [items]);

// ✅ 렌더 중 직접 계산
const total = items.reduce((s, i) => s + i.price, 0);

// ✅ 비싸면 useMemo (Compiler 없을 때만)
const total = useMemo(() => items.reduce(...), [items]);
```

**stale-closure / unstable-key 버그는 state-classification 버그가 먼저**. effect 의존성 배열에서 시작하지 말고, 그 값이 어디 출처인지 다시 분류.

### Route data boundary — page/route loader 우선

React Router v7 / Next.js / Remix 모두 route loader가 first-class. **fetch는 우선 loader에**. component 안 `useQuery`/`useEffect`는 loader가 못 다루는 것 (실시간/상호작용 후 갱신/사용자 액션 트리거)만.

```tsx
// React Router v7 — route data
export async function loader({ params }: LoaderFunctionArgs) {
  return { product: await fetchProduct(params.id!) };
}

export default function ProductPage() {
  const { product } = useLoaderData<typeof loader>();
  // 추가 personalized 데이터만 useQuery로
  const { data: cart } = useQuery(cartQueries.current());
  return <article>{product.name}</article>;
}
```

이렇게 하면:
- 첫 페인트가 빠름 (loader가 병렬 fetch + waterfall 제거)
- 컴포넌트는 데이터 로딩 ceremony 없이 렌더만
- 에러/로딩 boundary가 라우터 단에서 일관됨

### TanStack Query — server state 패턴 (강화)

**queryOptions로 키/fetcher를 한 곳에**:
```ts
// entities/product/api/product.queries.ts
export const productQueries = {
  all: () => ['products'] as const,
  detail: (id: string) =>
    queryOptions({
      queryKey: [...productQueries.all(), 'detail', id],
      queryFn: () => productApi.getById(id),
      staleTime: 60_000,
    }),
};

// 컴포넌트 / 라우트 loader 양쪽에서 동일 객체 재사용
const { data } = useQuery(productQueries.detail(id));
// loader: queryClient.ensureQueryData(productQueries.detail(id))
```

**mutate + invalidate**:
```ts
const { mutate } = useMutation({
  mutationFn: (input: Input) => api.update(input),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: productQueries.all() });
  },
});
```

**낙관적 업데이트는 일시 투영**: server response가 canonical. optimistic state를 long-lived store로 만들지 말 것 (React 19라면 `useOptimistic`이 이 boundary 강제).

### Zustand — client state 패턴 (강화)

**slice 패턴으로 도메인 분리**:
```ts
// shared/stores/auth.store.ts
type AuthState = {
  token: string | null;
  user: User | null;
  signIn: (token: string, user: User) => void;
  signOut: () => void;
};

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      signIn: (token, user) => set({ token, user }),
      signOut: () => set({ token: null, user: null }),
    }),
    { name: 'auth' }
  )
);
```

**selector로 rerender 좁히기**:
```tsx
// ❌ 전체 store subscribe → user 외 다른 필드 변해도 rerender
const { user } = useAuthStore();

// ✅ user만 선택
const user = useAuthStore((s) => s.user);
```

**server data를 store에 복사 금지**: API 데이터는 TanStack Query 캐시가 source of truth. store는 클라이언트 고유 상태만.

### RHF + Zod — form boundary

```ts
// 스키마가 단일 진실 소스
import { z } from 'zod';
export const loginSchema = z.object({
  email: z.string().email('유효한 이메일'),
  password: z.string().min(8, '8자 이상'),
});
export type LoginInput = z.infer<typeof loginSchema>;

// 폼
const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<LoginInput>({
  resolver: zodResolver(loginSchema),
});

const onSubmit = handleSubmit(async (data) => {
  // data는 검증 통과한 LoginInput 타입
  await api.login(data);
});
```

**boundary**:
- 폼 안에서 422 → `setError('email', { message: '...' })`로 RHF에 위임
- 폼 외부 server error → toast / error boundary
- 검증 로직과 타입을 따로 정의하지 말 것 (`z.infer` 강제)

### Test boundary — implicit env magic 거부

```tsx
// ❌ 컴포넌트 테스트가 실제 fetch / 실제 시간 의존
test('shows order total', async () => {
  render(<OrderSummary />);
  await screen.findByText(/총합/);  // 어디서 데이터가 와?
});

// ✅ 명시적 boundary: MSW로 네트워크 / vi.useFakeTimers로 시간
beforeEach(() => server.use(rest.get('/api/orders', () => ...)));
test('shows order total', async () => {
  render(<OrderSummary />, { wrapper: TestQueryProvider });
  expect(await screen.findByText(/총합 \$30/)).toBeInTheDocument();
});
```

**원칙**: 컴포넌트 테스트는 네트워크/시간/스토리지 의존을 의식적으로 모킹한다. 환경 마법(uncontrolled fetch가 우연히 통과)은 long-term flake.

### Compiler 시대의 메모이제이션 (2026 baseline)

React Compiler가 stable. **수동 `useMemo`/`useCallback`은 측정 후에만**. 다만:
- Compiler 도입 전에는 `react-hooks/exhaustive-deps` 위반 0건 강제
- Rules of React 위반 컴포넌트는 Compiler 적용 시 미묘한 동작 차이 가능
- 가상화 (`@tanstack/react-virtual`), 코드 스플리팅, image policy가 hook 메모보다 큰 효과

### 추가 Gotchas

- **route loader 데이터를 컴포넌트가 다시 fetch**: 이중 호출 + waterfall. loader 결과를 `useLoaderData`로 받고 그 위에 personalized만 추가.
- **`useEffect` + `setState`로 derived 계산**: 렌더 두 번 + stale 가능. 렌더 중 직접 계산 또는 `useMemo`.
- **list에 unstable key (index 또는 매 렌더 생성)**: re-mount + state 손실. stable id 사용.
- **TanStack Query에 client-only 데이터 (카트, 테마)**: invalidation/refetch 모델이 안 맞음. 클라이언트 state는 store/context.
- **Zustand selector 미사용 + `getState()`로 우회**: rerender 트래킹이 깨짐. selector 강제.

### 도구 사용 패턴 (Harness, 추가)
- route loader 사용처: `Grep("export (async )?function loader\\(", glob="src/routes/**/*.tsx")`
- effect로 derived state 의심: `Grep("useEffect\\(.*=>.*setState", glob="src/**/*.tsx")` (수동 점검)
- 미명시 query key: `Grep("useQuery\\(\\{", glob="src/**/*.ts")` → queryOptions factory 적용 검토
- form 검증 위임: `Grep("zodResolver", glob="src/features/**/*.tsx")`
