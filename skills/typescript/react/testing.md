---
keywords: 테스트 test 테스팅 testing vitest playwright msw mock 모킹 단위 unit 통합 integration e2e 커버리지 coverage 스냅샷 snapshot
intent: 테스트해 테스트작성해 테스팅해 커버리지확인해 E2E해
paths: src/**/*.test.ts src/**/*.test.tsx src/**/*.spec.ts e2e/ src/test/ src/mocks/
patterns: vitest describe it expect render screen userEvent msw http HttpResponse playwright test.extend
requires: frontend fsd
phase: implement review
min_score: 3
---

# 프론트엔드 테스트 가이드 (Vitest + RTL + MSW v2 + Playwright)

> 스택: Vitest 3+ / React Testing Library / MSW v2 / Playwright
> 커버리지 목표: 전체 70%, shared/lib 90%+, entities/model 85%+

## 의사결정 트리

### IF 테스트 환경 셋업 (Plan)
1. `pnpm add -D vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom`
2. `pnpm add -D msw` (API 모킹)
3. `pnpm add -D @playwright/test` (E2E)
4. vitest.config.ts 설정 (jsdom, setup 파일, coverage)
5. `src/test/setup.ts` — jest-dom + MSW 서버 lifecycle
6. `src/test/test-utils.tsx` — Custom render (providers 래핑)
7. `src/mocks/handlers/` — 도메인별 MSW 핸들러

### IF 컴포넌트 테스트 (Implement)
1. `{Component}.test.tsx` 파일 co-located (같은 폴더)
2. Custom render 사용 (QueryClient + Router + Auth + Theme 래핑)
3. `userEvent.setup()` 사용 (fireEvent 대신)
4. 쿼리 우선순위: getByRole > getByLabelText > getByText > getByTestId

### IF API 연동 테스트 (Implement)
1. MSW 핸들러에서 기본 성공 응답 정의
2. 에러 케이스: `server.use(http.get(..., () => HttpResponse.json({...}, { status: 500 })))`
3. 테스트 후 `server.resetHandlers()` (setup.ts에서 자동)

### IF E2E 테스트 (Implement)
1. Page Object Model 패턴 사용
2. Fixture로 POM 주입
3. `storageState`로 인증 상태 재사용
4. `page.route()`로 API 모킹

## Vitest 핵심 설정

```typescript
// vitest.config.ts
export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    coverage: {
      provider: 'v8',
      thresholds: { statements: 70, branches: 65, functions: 70, lines: 70 },
      exclude: ['src/**/*.d.ts', 'src/test/**', 'src/mocks/**', 'src/**/index.ts'],
    },
  },
})
```

### Setup 파일
```typescript
// src/test/setup.ts
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { server } from '@/mocks/server'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => { cleanup(); server.resetHandlers() })
afterAll(() => server.close())
```

### Custom Render
```typescript
// src/test/test-utils.tsx
function AllProviders({ children, initialUser, initialCart }: {...}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider initialUser={initialUser}>
          {children}
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

const customRender = (ui, options?) => render(ui, { wrapper: AllProviders, ...options })
export { customRender as render }
```

## MSW v2 패턴

### 핸들러 구조
```typescript
// src/mocks/handlers/product.ts
import { http, HttpResponse, delay } from 'msw'

export const productHandlers = [
  http.get('*/api/products', async ({ request }) => {
    const url = new URL(request.url)
    const page = Number(url.searchParams.get('page') ?? '0')
    await delay(100)
    return HttpResponse.json({ content: [...], totalElements: 100, totalPages: 5 })
  }),
  http.get('*/api/products/:id', ({ params }) => {
    return HttpResponse.json({ id: Number(params.id), name: '상품', price: 29900 })
  }),
]
```

### 테스트별 오버라이드
```typescript
it('서버 에러 시 에러 메시지 표시', async () => {
  server.use(
    http.get('*/api/products', () => HttpResponse.json({ message: '서버 오류' }, { status: 500 }))
  )
  render(<ProductList />)
  expect(await screen.findByText(/서버 오류/)).toBeInTheDocument()
})
```

### 인증 가드 (Higher-Order Resolver)
```typescript
function withAuth(resolver: HttpResponseResolver): HttpResponseResolver {
  return (input) => {
    if (!input.request.headers.get('Authorization')) {
      return HttpResponse.json({ message: '인증 필요' }, { status: 401 })
    }
    return resolver(input)
  }
}
```

## Playwright E2E 패턴

### Page Object Model
```typescript
// e2e/pages/ProductListPage.ts
export class ProductListPage {
  constructor(private page: Page) {}
  readonly productCards = this.page.getByTestId('product-card')
  readonly searchInput = this.page.getByPlaceholder('상품 검색')

  async goto() { await this.page.goto('/products') }
  async searchProduct(keyword: string) {
    await this.searchInput.fill(keyword)
    await this.searchInput.press('Enter')
  }
}
```

### Fixture
```typescript
export const test = base.extend<{ productListPage: ProductListPage }>({
  productListPage: async ({ page }, use) => { await use(new ProductListPage(page)) },
})
```

### API 모킹 (Playwright)
```typescript
test('API 에러 시 에러 페이지', async ({ page }) => {
  await page.route('**/api/products', (route) =>
    route.fulfill({ status: 500, body: JSON.stringify({ message: 'Error' }) })
  )
  await page.goto('/products')
  await expect(page.getByText(/오류/)).toBeVisible()
})
```

## 테스트 배치 (FSD)

```
src/features/auth/
  ui/LoginForm.tsx
  ui/LoginForm.test.tsx          ← co-located 단위 테스트
  model/useAuth.ts
  model/useAuth.test.ts          ← co-located 훅 테스트
  __tests__/auth-flow.test.tsx   ← feature 통합 테스트
src/shared/lib/
  formatPrice.ts
  formatPrice.test.ts            ← 유틸 단위 테스트
e2e/                              ← Playwright (프로젝트 루트)
  fixtures.ts
  pages/
  *.spec.ts
```

## 커버리지 전략

| 레이어 | 목표 | 이유 |
|--------|------|------|
| shared/lib | 90%+ | 순수 함수, 테스트 쉬움 |
| entities/model | 85%+ | 도메인 규칙, 검증 |
| features/model | 80%+ | 훅, 상태 관리 |
| features/ui | 70%+ | 컴포넌트 렌더링 + 인터랙션 |
| **전체** | **70%** | 프론트엔드 현실적 목표 |

## CI (GitHub Actions)

```yaml
unit-test:
  - pnpm vitest run --coverage
  - actions/upload-artifact (coverage/)

e2e-test:
  needs: unit-test
  - npx playwright install --with-deps chromium
  - npx playwright test
  - actions/upload-artifact (playwright-report/)
```

## Gotchas

### fireEvent vs userEvent
`fireEvent`는 이벤트를 직접 발생. `userEvent`는 실제 사용자 행동을 시뮬레이션 (포커스, 키 입력, 클릭 순서). 항상 `userEvent.setup()` 사용.

### getByRole 우선
`getByTestId`는 최후수단. `getByRole('button', { name: /장바구니/ })`가 접근성도 검증하고 의도도 명확.

### TanStack Query 테스트에서 retry: false
테스트에서 QueryClient의 기본 retry를 끄지 않으면 실패 테스트가 3번 재시도하며 타임아웃. Custom render에서 반드시 `retry: false`.

### MSW onUnhandledRequest: 'error'
핸들러가 없는 API 호출을 에러로 처리. 누락된 핸들러를 빠르게 발견.

### Playwright에서 MSW 대신 page.route
Playwright는 브라우저 컨텍스트에서 실행되므로 Node.js의 `setupServer`를 쓸 수 없음. `page.route()`로 네트워크 가로채기.

### 스냅샷 테스트 제한적 사용
작은 리프 컴포넌트(뱃지, 아이콘)에만. 큰 컴포넌트는 개발자가 맹목적으로 `vitest -u`를 누름. 레이아웃 검증은 Playwright `toHaveScreenshot` 사용.

## 도구 사용 패턴 (Harness)
- 테스트 실행: `Bash(pnpm vitest run)` (watch 아님)
- 커버리지: `Bash(pnpm vitest run --coverage)`
- 특정 파일: `Bash(pnpm vitest run src/features/auth/)`
- E2E: `Bash(npx playwright test --project=chromium)`
- E2E 디버그: `Bash(npx playwright test --debug)`
