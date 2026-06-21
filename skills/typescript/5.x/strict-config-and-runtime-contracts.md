---
keywords: typescript tsconfig strict moduleResolution node20 zod runtime schema branded type contract import boundary 타입 스키마 런타임 검증 모듈
intent: tsconfig 설정해 strict 켜 런타임 검증해 import 경로 정리해 zod 스키마 만들어 모듈 boundary 잡아
paths: tsconfig.json src/ packages/*/tsconfig.json
patterns: strict noUncheckedIndexedAccess exactOptionalPropertyTypes moduleResolution z.object satisfies branded
requires: typescript
phase: design implement review
tech-stack: typescript
min_score: 3
---

# TypeScript 5.x Strict Config + Runtime Contracts

> 핵심 원칙: **tsconfig, runtime schema, import boundary는 한 묶음의 계약**이다. strict가 초록불이어도 런타임 입력이 검증되지 않으면 위험은 그대로다.

## 의사결정 트리

### IF 새 TS 프로젝트 시작 (Design)
1. `tsc --init`으로 시작 → 5.9 prescriptive defaults 그대로 채택
2. `strict: true` + 다음 옵션 같이 켤지 결정:
   - `noUncheckedIndexedAccess` (배열/객체 인덱싱 안전)
   - `exactOptionalPropertyTypes` (optional vs undefined 구분)
   - `noImplicitOverride`, `noFallthroughCasesInSwitch`
3. Node 20 타겟이면 `module: "node20"` (TS 5.9 stable) — `nodenext`보다 명시적
4. monorepo면 `extends`로 base tsconfig 공유 + `references` 사용

### IF 외부 입력이 있는 모듈 (Implement)
1. **runtime schema 먼저** (zod / valibot / arktype) — 타입 정의 직접 하지 말 것
2. `type Foo = z.infer<typeof fooSchema>` — 검증과 타입 동시 생성
3. boundary (HTTP/storage/IPC/parse)에서 `schema.parse(input)` 강제
4. 내부 함수 시그니처는 검증된 타입만 받음 — `unknown` → `Foo` 변환은 boundary에서만

### IF import 경로가 불규칙해짐 (Review)
1. `paths` alias는 boundary 결정 — 편의 토글 아님
2. `~/features/*` vs `~/shared/*` 처럼 의존 방향이 코드화되도록 설계
3. ESLint `import/no-restricted-paths`로 단방향 의존 강제

## tsconfig 베이스라인

```jsonc
// tsconfig.base.json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "node20",            // TS 5.9 stable, Node 20 정렬
    "moduleResolution": "node20",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "noImplicitOverride": true,
    "noFallthroughCasesInSwitch": true,
    "isolatedModules": true,
    "verbatimModuleSyntax": true,  // import type 강제 → 번들러 친화
    "skipLibCheck": true,
    "esModuleInterop": true,
    "forceConsistentCasingInFileNames": true,
    "resolveJsonModule": true,
    "paths": {
      "~/*": ["./src/*"]
    }
  }
}
```

```jsonc
// 패키지별 tsconfig.json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src"
  },
  "include": ["src/**/*"],
  "references": [
    { "path": "../shared" }
  ]
}
```

## Runtime schema 패턴

### 단일 진실 소스 (Zod)
```typescript
// schemas/user.ts
import { z } from "zod";

export const userSchema = z.object({
  id: z.string().uuid(),
  email: z.string().email(),
  role: z.enum(["admin", "member"]),
  createdAt: z.coerce.date(),  // 문자열 → Date 자동 변환
});

export type User = z.infer<typeof userSchema>;
```

### Boundary parse (HTTP 응답)
```typescript
async function fetchUser(id: string): Promise<User> {
  const res = await fetch(`/api/users/${id}`);
  const json: unknown = await res.json();
  return userSchema.parse(json);  // 실패 시 ZodError throw
}
```

### Branded type (ID 혼용 방지)
```typescript
type UserId = string & { readonly __brand: "UserId" };
type OrderId = string & { readonly __brand: "OrderId" };

const UserId = (s: string): UserId => userSchema.shape.id.parse(s) as UserId;

function getUser(id: UserId) { /* ... */ }
// getUser(orderId)  // ❌ 컴파일 에러 — primitive string 혼용 차단
```

### `satisfies`로 좁히기
```typescript
// 타입 보존 + 리터럴 체크
const routes = {
  home: "/",
  product: "/products/:id",
} satisfies Record<string, `/${string}`>;

type RouteKey = keyof typeof routes;  // "home" | "product"
```

## Import boundary 정책

### 단방향 의존 (FSD 풍)
```
shared → entities → features → widgets → pages → app
```
- `shared`는 위 레이어를 import 금지
- `features`는 같은 레벨 features끼리 직접 import 금지 (composition은 widgets/pages에서)

### ESLint 강제
```json
{
  "rules": {
    "import/no-restricted-paths": ["error", {
      "zones": [
        { "target": "./src/shared", "from": "./src/features" },
        { "target": "./src/entities", "from": "./src/features" }
      ]
    }]
  }
}
```

## 5축 품질 체크

| 축 | 체크 |
|---|---|
| 정확성 | `strict` 외에 `noUncheckedIndexedAccess`도 켰나 |
| 안전성 | boundary에서 schema.parse 호출했나 (`unknown` → 도메인 타입) |
| 성능 | `skipLibCheck: true`로 빌드 시간 절감했나 |
| 가독성 | `paths` alias + `verbatimModuleSyntax`로 import 의도 명확한가 |
| 검증성 | 스키마 변경 시 컴파일 에러로 호출처 강제로 따라오는가 |

## Gotchas

### `as` 단언으로 우회하면 strict가 무력화
`as Foo`는 컴파일러 검사를 끈다. boundary에서만 (그것도 schema.parse 후에만) 허용. 내부 코드는 narrowing/제네릭 제약으로 해결.

### `any`가 한 줄 들어오면 전염
함수 반환에 `any`가 있으면 호출처 전체가 `any`로 오염. ESLint `no-explicit-any` + `no-unsafe-*` 규칙 필수.

### moduleResolution mismatch가 가장 흔한 빌드 실패
`module: "esnext"` + `moduleResolution: "node"`처럼 짝이 안 맞으면 import 경로가 런타임에서 깨진다. Node 20 타겟이면 `node20`/`node20`로 통일.

### tsconfig 분기가 늘면 monorepo가 부서짐
패키지마다 옵션을 따로 추가하지 말 것. base에 모으고, 패키지는 `extends`만 + `outDir`/`rootDir`/`references`만 다르게.

### Zod 스키마와 TS 타입 이중 정의 금지
`interface User { ... }`를 따로 정의하면 검증 통과한 데이터와 타입이 어긋난다. 항상 `z.infer`로 추출.

### `exactOptionalPropertyTypes` 켰을 때 함정
`{ name?: string }`에 `{ name: undefined }`를 못 넘김. spread/머지 코드가 깨질 수 있어 점진적 적용 권장.

## 도구 사용 패턴 (Harness)
- 스키마 위치 확인: `Grep("z\\.object\\(", glob="**/*.ts")`
- 위험한 단언 탐지: `Grep("as any|as unknown as", glob="src/**/*.ts")`
- tsconfig 검증: `Read tsconfig.json` → strict/noUncheckedIndexedAccess 확인
- 단방향 의존 검증: `Grep("from ['\"]\\.\\./features", path="src/shared")`
