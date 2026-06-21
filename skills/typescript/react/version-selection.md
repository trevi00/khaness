---
keywords: react 18 19 version 버전 선택 actions useActionState useOptimistic useFormStatus compiler downgrade compat ref forwardRef hydration
intent: 리액트버전선택해 18쓸지19쓸지결정해 마이그레이션 다운그레이드 호환성검토
paths: package.json src/
patterns: useActionState useOptimistic useFormStatus useTransition forwardRef <form action
requires: react
phase: design implement
tech-stack: typescript
min_score: 3
---

# React 18 vs 19 결정 트리 + Downgrade/Compat

> React 19는 2024-12-05 stable. Compiler도 stable 진입. 그러나 **모든 신규 프로젝트가 19여야 하는 건 아니다** — 라이브러리 호환과 SSR 프레임워크 동기화가 결정 요인.

## 의사결정 트리

### IF 신규 프로젝트 시작 (Design)
```
SSR 프레임워크 사용?
├─ Next.js 15+ → React 19 강제 (이미 19)
├─ Remix/React Router 7 → React 19 권장
└─ Vite + 자체 라우터 → 18이냐 19냐 자유
```

### IF "Form 중심 mutation 흐름이 많은가?"
- 예 → React 19 (`<form action>` + `useActionState` + `useOptimistic`로 보일러플레이트 대량 감소)
- 아니오 (대부분 GET 위주, 클라이언트 단일 페이지) → React 18로도 충분, 무리한 19 채택 말 것

### IF 핵심 의존성이 19 호환되는가?
- MUI/Mantine/Chakra 등 큰 UI 라이브러리는 **19 호환 메이저 확인 필수** (peer dep range)
- 잘못된 버전: `peerDependencies: react@^18.0.0` → 19에서 경고 폭주
- `npm ls react` / `pnpm why react`로 단일 인스턴스 확인 (이중 인스턴스 = hooks 깨짐)

### IF React 19 → 18 다운그레이드 필요 (Migrate)
1. **유발 시그널**: 19에서 라이브러리 ref 호환 깨짐, SSR 프레임워크 미정렬, 대규모 codebase 점진 이행 필요
2. **제거할 19 전용 API**:
   - `useActionState` → `useState` + 수동 pending
   - `useOptimistic` → 수동 optimistic state (이전 패턴 복원)
   - `<form action={fn}>` → onSubmit + preventDefault
   - `<Context value>` → `<Context.Provider value>`
   - `ref` as prop → `forwardRef` 복원
3. types: `@types/react@^18` 정확히 매칭

## 신규 프로젝트 default

| 시나리오 | 추천 |
|---|---|
| Next.js 15 / Remix v3 신규 | **React 19** (프레임워크가 강제) |
| 사내 어드민, Vite + Router, mutation 적음 | **React 18** (보수적) |
| Form 많은 SaaS / 대시보드 신규 | **React 19** (Actions ROI 큼) |
| 라이브러리 (publishing) | **peer 18 + 19 둘 다 지원** (`peerDependencies: ">=18.0.0"`) |
| RN 통합 | RN 버전이 지원하는 React로 (현재 19 미지원 케이스 있음 — 확인 필수) |

## React 19 핵심 변화 요약

### Actions 모델 (가장 큰 차이)
```tsx
// React 19
function Save({ id }: { id: string }) {
  const [state, action, pending] = useActionState(
    async (_prev, formData: FormData) => {
      const result = await api.save(id, formData);
      return result;
    },
    null
  );

  return (
    <form action={action}>
      <input name="title" />
      <button disabled={pending}>저장</button>
      {state?.error && <p>{state.error}</p>}
    </form>
  );
}
```

```tsx
// React 18 동등 코드 — 보일러 늘어남
function Save({ id }: { id: string }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        setPending(true); setError(null);
        try {
          const fd = new FormData(e.currentTarget);
          await api.save(id, fd);
        } catch (err) {
          setError(String(err));
        } finally {
          setPending(false);
        }
      }}
    >
      <input name="title" />
      <button disabled={pending}>저장</button>
      {error && <p>{error}</p>}
    </form>
  );
}
```

### `ref` as prop (forwardRef 불필요)
```tsx
// React 19
function MyInput({ ref, ...props }: { ref?: Ref<HTMLInputElement> } & InputHTMLAttributes<HTMLInputElement>) {
  return <input ref={ref} {...props} />;
}

// React 18 — forwardRef 필요
const MyInput = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  (props, ref) => <input ref={ref} {...props} />
);
```

### Context provider 단축
```tsx
// React 19
<UserContext value={user}>...</UserContext>

// React 18
<UserContext.Provider value={user}>...</UserContext.Provider>
```

### React Compiler (별도 패키지)
- `babel-plugin-react-compiler` stable 진입
- 자동 메모이제이션 → 수동 `useMemo`/`useCallback` 거의 불필요
- 단 측정 후 도입: 빌드 시간/번들 영향 확인. 모든 컴포넌트가 Rules of React 준수해야 안전

## Compat 점검 체크리스트

```bash
# 1. React 단일 인스턴스 확인
npm ls react

# 2. peer 호환 확인 (19 채택 시)
npx are-the-types-wrong  # 패키지의 types 정합성

# 3. 런타임 에러 시그널
# - "Cannot read properties of null (reading 'useState')" → 이중 인스턴스
# - "Hydration failed" → SSR 시 server/client 분기 점검
# - "Each child in a list should have a unique key" → 19에서 더 엄격

# 4. forwardRef 사용처
grep -r "forwardRef" src/  # 19로 갈 때 점진 제거 가능
```

## 5축 품질 체크

| 축 | 체크 |
|---|---|
| 정확성 | 프레임워크가 강제하는 React 버전과 일치하는가 |
| 안전성 | 라이브러리 peer 호환 깨지지 않았는가 (`npm ls react`) |
| 성능 | 19 + Compiler 도입 후 번들/빌드 측정했는가 |
| 가독성 | Form 로직이 Actions로 단순화되었는가 (19 채택 시) |
| 검증성 | hydration mismatch / hooks 에러 없이 SSR 통과하는가 |

## Gotchas

### React 19 채택했는데 라이브러리가 18 peer
콘솔 경고 + 런타임 깨짐 가능. resolution overrides 쓰면 안전성 떨어짐. 라이브러리 메이저 업데이트 또는 fork 검토.

### 19로 갈 때 forwardRef 일괄 제거 위험
점진 제거 OK, 일괄 제거하면 외부 노출 컴포넌트 ref API 깨짐. lint 룰로 신규만 막고 기존은 유지.

### Compiler를 켜고 Rules of React 위반이 있으면 미묘한 버그
`useMemo` 의존성 누락된 컴포넌트는 Compiler가 다르게 메모이제이션해서 동작이 달라짐. 도입 전 ESLint `react-hooks/exhaustive-deps` 통과 강제.

### `useOptimistic`을 canonical state로 쓰면 안 됨
optimistic은 일시 투영. canonical은 `useActionState` 또는 server cache. 두 개 섞이면 동기화 지옥.

### 다운그레이드는 types 정확히 18로
`@types/react@19` + `react@18` 조합은 잘못된 hint를 준다. devDependencies 동시 다운그레이드.

## 도구 사용 패턴 (Harness)
- 단일 인스턴스 검증: `Bash("npm ls react")`
- 19 전용 API 사용처: `Grep("useActionState|useOptimistic|useFormStatus", glob="src/**/*.tsx")`
- forwardRef 잔존: `Grep("forwardRef", glob="src/**/*.tsx")`
- Compiler 도입 전 lint: `react-hooks/exhaustive-deps` 위반 0건 확인
