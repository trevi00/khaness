---
keywords: typescript advanced type conditional mapped template literal infer satisfies branded opaque utility runtime handoff zod 고급타입 매핑 템플릿
intent: 조건부 매핑 템플릿리터럴 타입 설계 branded opaque infer satisfies 활용 runtime 검증과 연결
paths: src/types/ src/schemas/ packages/*/src/types/
patterns: extends ? : keyof in as infer satisfies template literal branded
requires: typescript
phase: design implement review
tech-stack: typescript
min_score: 3
---

# TypeScript 5.x Advanced Type Patterns + Runtime Handoff

> 핵심 원칙: **고급 타입은 도메인 의도를 강제하기 위해 쓴다 — 리뷰어를 감동시키려고 쓰지 않는다.** 정적 타입은 구조를 모델링하고, runtime schema는 입력을 검증한다. 둘이 끊어지면 둘 다 무용.

## 의사결정 트리

### IF 도메인 규칙을 타입으로 표현하고 싶음 (Design)
1. **단순한 분기**: discriminated union (`{ kind: "a" } | { kind: "b" }`) — conditional 안 써도 됨
2. **타입 의존 변환**: conditional + `infer` (예: API 응답 unwrap, Promise 풀기)
3. **키-값 매핑 변형**: mapped type + `as` (key remap, optional 제거)
4. **문자열 패턴 강제**: template literal type (예: 라우트 경로, 이벤트 이름)
5. **primitive ID 혼용 방지**: branded / opaque type
6. **외부 입력 신뢰도**: 위 어떤 것도 runtime 검증을 대체 못 함 → zod/valibot으로 boundary parse

### IF 타입 곡예가 늘어남 (Review)
1. "이게 컴파일 시간을 얼마나 늘리지?" — 깊은 conditional은 `tsc --extendedDiagnostics`로 측정
2. "런타임에서 이 타입이 검증되나?" — 안 되면 schema로 옮기기
3. "이 타입을 호출처에서 이해할 수 있나?" — `.d.ts` 출력 hover로 확인
4. 답이 "no"면 단순화 — 도메인 모델링 실패의 신호

### IF runtime과 type을 동시에 가져가고 싶음 (Implement)
1. zod 스키마를 단일 진실 소스 → `z.infer<typeof S>`
2. boundary에서 `.parse(unknown)` → 도메인 타입으로 승격
3. 내부 로직은 검증된 타입만 받음 — `unknown`을 흘려보내지 않음

## conditional types — 도메인 분해용

### Promise/Array unwrap
```typescript
type Awaited2<T> = T extends Promise<infer U> ? Awaited2<U> : T;
type ElementOf<T> = T extends readonly (infer E)[] ? E : never;

type X = Awaited2<Promise<Promise<number>>>;  // number
type Y = ElementOf<readonly string[]>;        // string
```

### Distributive 동작 주의
```typescript
// distributive: T가 union이면 각 member에 분배됨
type Box<T> = T extends any ? { value: T } : never;
type B = Box<string | number>;  // { value: string } | { value: number }

// 분배 막고 싶으면 [] 감싸기
type NonDist<T> = [T] extends [any] ? { value: T } : never;
type ND = NonDist<string | number>;  // { value: string | number }
```

### API 응답 → 도메인 타입
```typescript
type ApiResponse<T> =
  | { ok: true; data: T }
  | { ok: false; error: string };

type DataOf<R> = R extends { ok: true; data: infer D } ? D : never;
type UserData = DataOf<ApiResponse<User>>;  // User
```

## mapped types — 키 변환

### key remap (`as`)
```typescript
// User → UserSetters: { setId(v): void; setEmail(v): void }
type Setters<T> = {
  [K in keyof T as `set${Capitalize<string & K>}`]: (v: T[K]) => void;
};
type S = Setters<{ id: string; email: string }>;
// { setId(v: string): void; setEmail(v: string): void }
```

### 깊은 readonly / partial
```typescript
type DeepReadonly<T> = T extends Function | Date
  ? T
  : T extends object
  ? { readonly [K in keyof T]: DeepReadonly<T[K]> }
  : T;
```

### 특정 키만 골라내기 (값 타입 기준)
```typescript
type PickByType<T, V> = {
  [K in keyof T as T[K] extends V ? K : never]: T[K];
};
type StringFields = PickByType<{ id: string; age: number; name: string }, string>;
// { id: string; name: string }
```

## template literal types — 문자열 계약

### 라우트 패턴 강제
```typescript
type Route = `/users/${string}` | `/orders/${string}/items`;
const r1: Route = "/users/42";       // OK
// const r2: Route = "/posts/1";     // 컴파일 에러
```

### 이벤트 이름 자동 생성
```typescript
type Events = "click" | "hover" | "focus";
type EventHandlers = {
  [E in Events as `on${Capitalize<E>}`]: () => void;
};
// { onClick(): void; onHover(): void; onFocus(): void }
```

### URL 파라미터 추출
```typescript
type ExtractParams<P extends string> =
  P extends `${string}:${infer Param}/${infer Rest}`
    ? { [K in Param | keyof ExtractParams<`/${Rest}`>]: string }
    : P extends `${string}:${infer Param}`
    ? { [K in Param]: string }
    : {};

type P = ExtractParams<"/users/:userId/orders/:orderId">;
// { userId: string; orderId: string }
```

## branded / opaque type — primitive 혼용 차단

```typescript
declare const brand: unique symbol;
type Brand<T, B> = T & { readonly [brand]: B };

type UserId = Brand<string, "UserId">;
type OrderId = Brand<string, "OrderId">;

const asUserId = (s: string): UserId => s as UserId;

function getUser(id: UserId) { /* ... */ }
const oid: OrderId = asUserId("x") as unknown as OrderId;
// getUser(oid);  // 컴파일 에러 — 다른 brand
```

**zod와 결합**: branded 생성자에 `schema.parse`를 넣으면 runtime + 타입 둘 다 잡힘.
```typescript
const userIdSchema = z.string().uuid().brand<"UserId">();
type UserId = z.infer<typeof userIdSchema>;  // string & z.BRAND<"UserId">
```

## `satisfies` — 추론 보존 + 제약

```typescript
// 문제: 타입 어노테이션은 리터럴을 잃음
const routes1: Record<string, string> = { home: "/" };
// routes1.home: string (리터럴 "/" 잃음)

// 해결: satisfies는 제약만 검사하고 추론 유지
const routes2 = {
  home: "/",
  user: "/users/:id",
} satisfies Record<string, `/${string}`>;
// routes2.home: "/" (리터럴 보존)
type RouteKey = keyof typeof routes2;  // "home" | "user"
```

## Runtime handoff 패턴

### 단일 진실 소스 (Zod)
```typescript
import { z } from "zod";

export const userSchema = z.object({
  id: z.string().uuid().brand<"UserId">(),
  email: z.string().email(),
  role: z.enum(["admin", "member"]),
});
export type User = z.infer<typeof userSchema>;
export type UserId = User["id"];
```

### Boundary parse
```typescript
async function fetchUser(id: UserId): Promise<User> {
  const res = await fetch(`/api/users/${id}`);
  return userSchema.parse(await res.json());
}
```

### 내부 함수는 검증된 타입만
```typescript
// boundary
function handleRequest(input: unknown): Result {
  const parsed = userSchema.parse(input);
  return doBusinessLogic(parsed);  // User만 받음
}

// 내부
function doBusinessLogic(user: User): Result {
  // unknown 없음, schema 호출 없음
}
```

## 5축 품질 체크

| 축 | 체크 |
|---|---|
| 정확성 | conditional/mapped이 도메인 분기와 1:1 매핑되는가 (장식 X) |
| 안전성 | branded type + boundary parse로 unknown → 도메인 타입 단방향인가 |
| 성능 | 깊은 conditional이 컴파일 시간 측정됐는가 (`--extendedDiagnostics`) |
| 가독성 | 타입 hover로 호출처가 의도를 읽을 수 있는가 |
| 검증성 | runtime input이 항상 schema.parse를 거치는가 |

## Gotchas

### Distributive 동작을 잊고 union 대신 단일 처리 가정
`T extends any ? F<T> : never`는 union일 때 분배됨. 분배 안 원하면 `[T] extends [any]`. union을 통째로 다루려는 의도라면 이게 올바름 — 단지 무의식 패턴이 위험.

### `infer` 위치를 잘못 잡으면 `unknown` 추론
`T extends (...args: infer A) => any`처럼 위치가 정확해야 함. `T extends Function` 같은 약한 제약 + infer는 `unknown[]`만 줌.

### template literal recursion이 instantiation depth 초과
긴 문자열 split 같은 재귀 template literal은 TS 깊이 제한(50)에 부딪힘. 5단계 이내로 제약.

### branded type의 `as` 우회
`value as UserId`는 컴파일 통과. brand 함수 (`asUserId`) 안에서 `schema.parse`로 검증 후 단언하도록 강제. 외부에서 raw `as` 금지 — ESLint `no-restricted-syntax`로 막기.

### `satisfies` vs 타입 어노테이션 혼동
`const x: T = ...`은 좁히기 손실, `const x = ... satisfies T`는 유지. 리터럴 보존이 필요하면 satisfies, API 시그니처면 어노테이션.

### Mapped type에 `Function`이 포함되면 메서드 깨짐
`{ [K in keyof T]: ... }`로 클래스 인스턴스를 매핑하면 method binding이 풀림. `T extends Function ? T : ...` guard 추가.

### Zod schema 변경 시 `z.infer`가 호출처를 못 따라감
runtime 검증은 통과하지만 타입은 stale → 빌드 깨짐 신호로 활용. infer 결과를 어디에 쓰는지 IDE rename으로 한 번에 추적.

### Conditional type의 type narrowing 한계
조건이 복잡해지면 TS가 narrow 못 함 → 함수 안에서 type assertion 강요됨. 그 시점이 "타입을 단순화하라"는 신호.

## 도구 사용 패턴 (Harness)
- 깊은 conditional 탐지: `Grep("extends.*\\?.*:.*extends", glob="src/**/*.ts")` (3단 이상)
- branded 일관성: `Grep("as User(Id|Name|Email)", glob="src/**/*.ts")` — schema.parse 우회 의심
- `infer` 사용처: `Grep("infer ", glob="src/**/*.ts")`
- 컴파일 시간: `Bash("npx tsc --noEmit --extendedDiagnostics")` → "Check time" / "Type instantiations"
- schema-type drift: schema 변경 후 `npx tsc --noEmit`으로 호출처 강제 확인
