---
keywords: vue 3 composition api script setup ref reactive computed watch watchEffect onWatcherCleanup onScopeDispose effectScope abortcontroller composable component contract props emits slots teleport pinia
intent: composable설계 reactivity contract watch cleanup async abort props emits 정의 component test boundary
paths: src/composables/ src/components/ src/stores/
patterns: defineProps defineEmits defineSlots <script setup> ref computed watch watchEffect onScopeDispose useTemplateRef
requires: vue
phase: design implement review
tech-stack: typescript
min_score: 3
---

# Vue 3.x Composables + Reactivity Contracts + Watch Cleanup

> 핵심 원칙: **reactivity는 ambient magic이 아니라 reviewed contract**다. composable은 small state machine, watcher는 cleanup이 의무, 컴포넌트는 props/emits/slots를 명시적으로 선언한다.

## 의사결정 트리

### IF 새 composable 작성 (Design)
1. **단일 책임**: 하나의 composable = 하나의 작은 도메인 상태 또는 한 가지 effect orchestration
2. **inputs 명시**: 인자는 모두 `MaybeRefOrGetter<T>` (ref/getter/plain 모두 받음) → `toValue()`로 풀기
3. **반환값 명시**: ref/computed로 반환 (외부에서 reactive 트래킹 가능). 내부 mutation은 함수로 노출
4. **cleanup 보장**: watcher/timer/socket이 있으면 `onScopeDispose`로 해제 (또는 `onWatcherCleanup` Vue 3.5+)
5. **async에 abort**: fetch가 있으면 `AbortController` + 컴포넌트 unmount 시 abort

### IF watcher 추가 (Implement)
```
값 1개 → watch(source, cb)
여러 ref 의존하는 effect → watchEffect(fn)
부수효과 (구독/타이머) → onWatcherCleanup으로 해제 콜백 등록
async + 취소 가능 → AbortController + onWatcherCleanup
```

### IF 컴포넌트 contract 정의 (Implement)
- `defineProps<{...}>()` + 타입으로 명시 (런타임 default는 `withDefaults`)
- `defineEmits<{...}>()` 타입 시그니처로 명시 → 미선언 emit 차단
- 슬롯은 `defineSlots<{...}>()` (Vue 3.3+)
- `useTemplateRef('elName')` (Vue 3.5+)로 DOM 참조 — `ref`보다 명확

### IF teleport 사용 (Review)
- target은 stable selector (id 우선) — 클래스 selector는 테스트에서 유실되기 쉬움
- 테스트 시 jsdom + `attachTo: document.body` 필요
- Modal/Toast 등 root 외부 portal에만 사용. 일반 레이아웃에는 과잉

## 핵심 패턴

### 단일 책임 composable
```ts
// composables/useCounter.ts
import { ref, computed, type MaybeRefOrGetter, toValue } from 'vue';

export function useCounter(initial: MaybeRefOrGetter<number> = 0) {
  const count = ref(toValue(initial));
  const isZero = computed(() => count.value === 0);

  const inc = () => { count.value++; };
  const dec = () => { count.value--; };
  const reset = () => { count.value = toValue(initial); };

  return { count, isZero, inc, dec, reset };
}
```

### Async + abort + cleanup
```ts
// composables/useUser.ts
import { ref, watch, onWatcherCleanup, type MaybeRefOrGetter, toValue } from 'vue';

export function useUser(idSource: MaybeRefOrGetter<string>) {
  const user = ref<User | null>(null);
  const error = ref<Error | null>(null);
  const loading = ref(false);

  watch(
    () => toValue(idSource),
    async (id) => {
      if (!id) return;
      const ctrl = new AbortController();
      onWatcherCleanup(() => ctrl.abort());  // unmount/재실행 시 자동 abort

      loading.value = true;
      error.value = null;
      try {
        const res = await fetch(`/api/users/${id}`, { signal: ctrl.signal });
        user.value = await res.json();
      } catch (e) {
        if ((e as Error).name !== 'AbortError') error.value = e as Error;
      } finally {
        loading.value = false;
      }
    },
    { immediate: true }
  );

  return { user, error, loading };
}
```

### Cleanup이 필요한 외부 자원
```ts
// composables/useEventListener.ts
import { onScopeDispose, watchEffect, toValue, type MaybeRefOrGetter } from 'vue';

export function useEventListener<K extends keyof WindowEventMap>(
  type: K,
  handler: (e: WindowEventMap[K]) => void,
  target: MaybeRefOrGetter<EventTarget | null> = () => window
) {
  watchEffect((onCleanup) => {
    const t = toValue(target);
    if (!t) return;
    t.addEventListener(type, handler as EventListener);
    onCleanup(() => t.removeEventListener(type, handler as EventListener));
  });

  // effectScope 외부에서도 안전하게 정리
  onScopeDispose(() => { /* fallback cleanup */ });
}
```

### 컴포넌트 contract
```vue
<!-- components/UserCard.vue -->
<script setup lang="ts">
import { computed } from 'vue';

interface Props {
  user: { id: string; name: string; email: string };
  variant?: 'compact' | 'detailed';
}
const props = withDefaults(defineProps<Props>(), {
  variant: 'detailed',
});

const emit = defineEmits<{
  edit: [userId: string];
  delete: [userId: string];
}>();

defineSlots<{
  default(): void;
  actions(props: { userId: string }): void;
}>();

const displayName = computed(() => props.user.name || props.user.email);
</script>

<template>
  <article :data-variant="variant">
    <h3>{{ displayName }}</h3>
    <slot />
    <slot name="actions" :user-id="user.id" />
    <button @click="emit('edit', user.id)">편집</button>
  </article>
</template>
```

### Pure computed + 명령 분리
```ts
// ❌ computed 안에서 mutation
const total = computed(() => {
  state.lastViewed = Date.now();  // side effect
  return items.value.reduce(...);
});

// ✅ computed는 pure, mutation은 별도 action
const total = computed(() => items.value.reduce((s, i) => s + i.price, 0));
function markViewed() { state.lastViewed = Date.now(); }
```

## 5축 품질 체크

| 축 | 체크 |
|---|---|
| 정확성 | composable 입력이 `MaybeRefOrGetter`로 받아 ref/getter/plain 모두 동작하는가 |
| 안전성 | watcher에 `onWatcherCleanup` / `onScopeDispose`로 해제 보장되는가 |
| 성능 | `watch`의 `deep: true` 남발 안 했는가 (큰 객체 deep watch는 비싸다) |
| 가독성 | props/emits/slots가 타입으로 명시되어 contract 검토 가능한가 |
| 검증성 | 컴포넌트 테스트가 implicit emit/teleport target 가정 없이 통과하는가 |

## Gotchas

### Watcher가 자기가 보는 상태를 쓰면 무한 루프
```ts
watch(() => state.x, (v) => { state.x = v + 1; });  // ❌ 무한 루프
```
값 정규화는 setter 또는 별도 action에서. watcher는 외부 effect만.

### `deep: true` 남발로 성능 저하
큰 nested 객체에 deep watch는 모든 property 접근을 트래킹. 진짜 필요한 path만 watch하거나 selector로 좁히기.

### Async watcher가 unmount 후 setState
abort 없이 fetch 진행 중 컴포넌트 사라지면 "set on unmounted" 경고. 항상 `AbortController` + cleanup.

### 미선언 emit이 동작
`defineEmits` 안 쓰면 어떤 이벤트든 `$emit` 가능 → contract 부재. 항상 명시.

### teleport target이 mount 시 없음
`teleport` target이 DOM에 아직 없으면 무시. 테스트 시 `attachTo` 필수, 런타임도 mount 순서 주의.

### `ref` vs `reactive` 혼용
`reactive` 객체를 destructure하면 reactivity 깨짐. `toRefs(reactive(...))`로 풀거나 그냥 `ref`로 통일 권장.

### `useTemplateRef` (Vue 3.5+) 미사용
`ref` 변수 + `:ref="..."`보다 `useTemplateRef('name')`이 명확하고 타입 안전.

## 도구 사용 패턴 (Harness)
- watcher 미정리 탐지: `Grep("watch\\(|watchEffect\\(", glob="src/composables/**/*.ts")` → cleanup 호출 확인
- emit 미선언 탐지: `Grep("\\$emit\\(", glob="src/**/*.vue")` 후 같은 파일에 `defineEmits` 있는지 확인
- deep watch: `Grep("deep: true", glob="src/**/*.{ts,vue}")` 검토
- abort 누락: `Grep("await fetch\\(", glob="src/composables/**/*.ts")` → AbortController 동반 확인
