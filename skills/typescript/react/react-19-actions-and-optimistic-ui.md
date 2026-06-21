---
keywords: react 19 action useActionState useFormStatus useOptimistic startTransition form mutation pending optimistic compiler memoization 액션 폼 낙관적 업데이트
intent: react19 폼 액션 mutation 설계 useActionState useFormStatus useOptimistic 분리 startTransition pending optimistic 경계 잡기
paths: src/features/ src/components/ app/
patterns: <form action> useActionState useFormStatus useOptimistic startTransition compiler memo
requires: react
phase: design implement review
tech-stack: typescript
min_score: 3
---

# React 19 Actions, useActionState, useOptimistic + Compiler-era Memoization

> 핵심 원칙: **Action / pending / optimistic은 서로 다른 책임이다.** `useActionState` = canonical state, `useFormStatus` = parent form pending, `useOptimistic` = 임시 projection. 한 hook이 두 역할을 가지면 truth source가 둘이 된다.

## 의사결정 트리

### IF 데이터 변경(mutation) 인터랙션 추가 (Design)
1. **form 형태인가?**
   - YES → `<form action={fn}>` — Action boundary + transition 자동
   - NO → 일반 async + `startTransition` 또는 다른 패턴
2. **결과 state가 필요한가?** (예: 에러 메시지, 마지막 응답)
   - YES → `useActionState((prev, formData) => next, initial)`
   - NO → 그냥 form action prop만
3. **submit 버튼/스피너가 form 안에 있나?**
   - YES → `useFormStatus()` (자식 컴포넌트에서)
   - NO → form 자식으로 분리
4. **즉시 보이는 가짜 상태 필요?** (낙관적 UI)
   - YES → `useOptimistic` — 단, 임시 projection으로만
   - NO → canonical state만 보여줌

### IF UI가 이상하게 동작 (Review)
1. `pending`이 안 변함 → `useFormStatus`가 form 자식인가?
2. FormData가 비어 보임 → reducer 시그니처가 `(prevState, formData)`인가?
3. 후속 클릭이 무시됨 → 이전 Action이 throw했나? → catch + return error state로 변경
4. optimistic UI가 깜빡임 → optimistic을 두 번째 source of truth로 쓰고 있나?

### IF Compiler 시대 메모화 (Review)
1. **React Compiler 켜져 있으면 default memo 적용** — `useMemo`/`useCallback` 수동 추가는 측정 후
2. measurement 먼저: React DevTools Profiler 또는 web-vitals
3. list 크기/번들 형태가 hook 미세조정보다 영향 큼
4. 유의미한 개선이 안 보이면 롤백

## 핵심 패턴

### 1) `<form action>` + `useActionState`
```tsx
"use client";
import { useActionState } from "react";

type State = { ok: boolean; error?: string };

async function login(prev: State, formData: FormData): Promise<State> {
  const email = String(formData.get("email") ?? "");
  const pw = String(formData.get("password") ?? "");
  try {
    await api.login({ email, pw });
    return { ok: true };
  } catch (e) {
    // throw 금지 — 후속 Action 큐가 끊김
    return { ok: false, error: (e as Error).message };
  }
}

export function LoginForm() {
  const [state, formAction, isPending] = useActionState(login, { ok: false });
  return (
    <form action={formAction}>
      <input name="email" type="email" required />
      <input name="password" type="password" required />
      <SubmitButton />
      {state.error && <p role="alert">{state.error}</p>}
    </form>
  );
}
```

### 2) `useFormStatus` — form **자식** 컴포넌트에서만
```tsx
"use client";
import { useFormStatus } from "react-dom";

function SubmitButton() {
  const { pending } = useFormStatus();  // 부모 form의 상태
  return (
    <button type="submit" disabled={pending}>
      {pending ? "Loading..." : "Sign in"}
    </button>
  );
}
```
**잘못된 곳**: `<form>` 자체를 렌더하는 컴포넌트에서 호출 → `pending` 항상 `false`.

### 3) `useOptimistic` — 임시 projection만
```tsx
"use client";
import { useOptimistic, startTransition } from "react";

export function MessageList({ messages }: { messages: Msg[] }) {
  const [optimisticMessages, addOptimistic] = useOptimistic(
    messages,
    (state, newText: string) => [...state, { id: "temp", text: newText, pending: true }]
  );

  async function handleSend(formData: FormData) {
    const text = String(formData.get("text"));
    addOptimistic(text);                  // form action 내부 → 자동으로 transition
    await sendMessage(text);              // canonical state는 server/parent가 갱신
  }

  return (
    <>
      <ul>{optimisticMessages.map(m => <li key={m.id} aria-busy={m.pending}>{m.text}</li>)}</ul>
      <form action={handleSend}><input name="text" /><button>Send</button></form>
    </>
  );
}
```
**규칙**: optimistic setter는 Action 내부 또는 `startTransition` 내부에서만. form action은 자동 transition.

### 4) form 밖에서 optimistic
```tsx
function LikeButton({ liked }: { liked: boolean }) {
  const [optimisticLiked, setOptimistic] = useOptimistic(liked);

  return (
    <button
      onClick={() => {
        startTransition(async () => {
          setOptimistic(!optimisticLiked);
          await toggleLike();
        });
      }}
    >
      {optimisticLiked ? "♥" : "♡"}
    </button>
  );
}
```

## 책임 분리 매트릭스

| 역할 | 도구 | 살아남는 시간 |
|---|---|---|
| 변경 입구 | `<form action={fn}>` 또는 `formAction` prop | submit 1회 |
| canonical state (마지막 결과) | `useActionState` | 컴포넌트 lifecycle |
| pending indicator | `useFormStatus` (form 자식) | submit 동안 |
| 즉시 보이는 임시 UI | `useOptimistic` | Action 진행 중만 — 끝나면 canonical 복귀 |
| form 밖 transition | `startTransition` | 콜백 동안 |

## Compiler-era memoization

### React Compiler가 켜진 경우
- 자동 memo 적용 → `useMemo`/`useCallback` **자동으로 다는 게 default 아님**
- 추가하려면 measurement 근거 필수
- 컴파일러 결과 확인: `react-compiler-runtime` 출력 / DevTools Profiler에서 commit 빈도

### measurement 우선
```tsx
import { Profiler } from "react";

<Profiler id="MessageList" onRender={(id, phase, actualDuration) => {
  if (actualDuration > 16) console.warn(id, phase, actualDuration);
}}>
  <MessageList />
</Profiler>
```

### 진짜 효과 큰 것부터
1. **list virtualization** (react-virtuoso, react-window)
2. **code splitting** (`React.lazy`, route-level)
3. **이미지 전략** (next/image, AVIF/WebP)
4. **bundle analyze** (`source-map-explorer`)
5. 그다음에 hook-level memo

## 5축 품질 체크

| 축 | 체크 |
|---|---|
| 정확성 | useActionState reducer 시그니처가 `(prev, formData)`인가 |
| 안전성 | Action 내부 throw 대신 error state 반환하는가 |
| 성능 | optimistic이 임시 projection으로만 쓰이는가 (두 번째 store X) |
| 가독성 | useFormStatus가 form 자식 컴포넌트에 있는가 |
| 검증성 | Profiler/web-vitals로 측정 후 memo 추가됐는가 |

## Gotchas

### `useActionState` reducer 시그니처 혼동
plain form action: `(formData) => ...`. `useActionState` reducer: `(prevState, formData) => ...`. previousState가 첫 번째. 이걸 놓치면 FormData 누락처럼 보임.

### `useFormStatus`를 form과 같은 컴포넌트에서 호출
`pending`이 항상 `false`. 자식 컴포넌트로 분리해야 함. submit 버튼 / 스피너를 별도 컴포넌트로 빼는 습관.

### Action 안에서 throw → 후속 Action skip
docs 명시: 던지면 큐에 쌓인 Action이 cancel됨. 사용자가 다시 클릭해도 무시되는 것처럼 보임. catch해서 error state 반환.

### `useOptimistic`을 long-lived store처럼 사용
optimistic은 canonical에서 derived → confirmed가 들어오면 자동 복귀. 두 번째 진실 소스로 만들면 깜빡임 + 충돌. 항상 canonical을 입력으로 받음.

### `useOptimistic` setter를 Action/Transition 밖에서 호출
런타임 에러 발생. form action은 자동 transition, 외부에서는 `startTransition(...)`로 감싸기.

### `useActionState`에 reset 기대
docs: built-in reset 없음. reducer로 모델링하거나 부모에서 `key`를 바꿔 remount.

### compiler 있는데 useMemo/useCallback 새로 추가
중복 메모화. compiler가 이미 처리. measurement 없이 추가하면 가독성만 깎이고 성능 이득 없음.

### list 천 개를 그냥 `.map()`
virtualization 없으면 재렌더가 list 전체. memo로 못 막음. react-virtuoso 같은 라이브러리로 구간 렌더.

### form action prop을 onClick으로 대체
button onClick에 mutation 적으면 transition boundary 잃음 + progressive enhancement (JS 없을 때 동작) 깨짐. form-shaped UX면 항상 `<form action>`.

## 도구 사용 패턴 (Harness)
- form 자식 분리 검증: `Grep("useFormStatus", glob="**/*.tsx")` 후 같은 파일에 `<form` 있는지 확인
- throw in action: `Grep("throw .* (in|inside).*action|async function.*Action", glob="**/*.tsx")` 후 try/catch 검토
- optimistic 오용: `Grep("useOptimistic", glob="**/*.tsx")` 후 setter가 transition/action 안에 있는지
- compiler 동작 확인: `Bash("npx react-compiler-healthcheck")` (실험적) 또는 빌드 출력에 `_c` 제거 패턴
- profiler: React DevTools Profiler `commit duration` 16ms 초과 컴포넌트 추적
