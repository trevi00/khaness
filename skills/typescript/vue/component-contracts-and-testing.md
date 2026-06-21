---
keywords: vue 3 props emits slots defineProps defineEmits defineSlots defineModel teleport vitest vue-test-utils contract test 컴포넌트 계약 슬롯 텔레포트 테스트
intent: vue3 props emits slots 계약 명시 teleport 안전화 vue-test-utils 컴포넌트 테스트 기반선
paths: components/ src/components/ tests/components/
patterns: defineProps defineEmits defineSlots defineModel <Teleport> mount stubs find emitted
requires: vue
phase: design implement review
tech-stack: typescript
min_score: 3
---

# Vue 3.x Component Contracts (Props / Emits / Slots / Teleport) + Testing

> 핵심 원칙: **컴포넌트의 외부 계약은 명시되어야 한다.** props/emits/slots를 코멘트나 부족 지식으로 흘려보내면 사용처에서 추측 + 테스트 깨짐. defineProps/defineEmits/defineSlots는 계약을 코드로 만든다.

## 의사결정 트리

### IF 새 컴포넌트 작성 (Design)
1. **외부 계약 4가지 명시**:
   - `defineProps<{}>()` — 입력 데이터 + 타입
   - `defineEmits<{}>()` — 발신 이벤트
   - `defineSlots<{}>()` — 슬롯 + slot prop 타입
   - `defineModel<>()` — v-model 양방향
2. **render outside DOM tree?** → `<Teleport to="...">`로 명시 (모달, 토스트)
3. **테스트 가능성 확보**:
   - DOM selector는 stable (`data-testid` 또는 role)
   - teleport target은 mount 시 jsdom에 prepare
   - 외부 의존성은 props/inject로

### IF 기존 컴포넌트 수정 (Review)
1. props/emits/slots 변경은 **breaking change** — semver 또는 호출처 일괄 수정
2. emit이 사용 중인데 `defineEmits`에 없으면 → 즉시 추가 (TS 타입 + dev warning)
3. slot prop이 컴포넌트 내부 reactive에 의존하면 → slot prop으로 노출 (parent 정의 가능하게)
4. teleport target이 동적이면 → `disabled` 옵션 또는 fallback

### IF 테스트 작성 (Implement)
1. props 입력 → DOM 출력 (renders)
2. user interaction → emit 검증 (`wrapper.emitted('event')`)
3. slot 콘텐츠 mount 검증
4. teleport는 attach 옵션 + body 검색
5. composable mock은 inject 또는 provide로

## 컴포넌트 계약 패턴

### 완전 명시 (script setup + TS)
```vue
<!-- BaseButton.vue -->
<script setup lang="ts">
type Variant = "primary" | "secondary" | "danger";

const props = withDefaults(
  defineProps<{
    label: string;
    variant?: Variant;
    disabled?: boolean;
    loading?: boolean;
  }>(),
  { variant: "primary", disabled: false, loading: false }
);

const emit = defineEmits<{
  click: [event: MouseEvent];
  longpress: [];
}>();

defineSlots<{
  default(props: { variant: Variant }): unknown;
  icon(props: { size: number }): unknown;
}>();

function handleClick(e: MouseEvent) {
  if (props.disabled || props.loading) return;
  emit("click", e);
}
</script>

<template>
  <button
    :class="['btn', `btn--${variant}`]"
    :disabled="disabled || loading"
    @click="handleClick"
    :data-testid="$attrs['data-testid'] ?? 'base-button'"
  >
    <slot name="icon" :size="16" />
    <slot :variant="variant">{{ label }}</slot>
  </button>
</template>
```

### `defineModel` (v-model 단순화)
```vue
<!-- TextInput.vue -->
<script setup lang="ts">
const value = defineModel<string>({ required: true });
const error = defineModel<string | null>("error", { default: null });
</script>

<template>
  <input v-model="value" :aria-invalid="!!error" />
  <span v-if="error" role="alert">{{ error }}</span>
</template>
```

```vue
<!-- 사용처 -->
<TextInput v-model="name" v-model:error="nameError" />
```

### Teleport (모달, 토스트)
```vue
<!-- Modal.vue -->
<script setup lang="ts">
defineProps<{ open: boolean; title: string }>();
const emit = defineEmits<{ close: [] }>();
</script>

<template>
  <Teleport to="#modal-root" :disabled="!open">
    <div v-if="open" class="modal-backdrop" @click="emit('close')">
      <div class="modal" role="dialog" :aria-label="title" @click.stop>
        <h2>{{ title }}</h2>
        <slot />
        <button @click="emit('close')">Close</button>
      </div>
    </div>
  </Teleport>
</template>
```

```html
<!-- index.html -->
<body>
  <div id="app"></div>
  <div id="modal-root"></div>  <!-- teleport target -->
</body>
```

## 테스트 패턴 (Vitest + @vue/test-utils)

### 기본 셋업
```typescript
// vitest.config.ts
import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
  },
});
```

```typescript
// tests/setup.ts — teleport target prepare
beforeEach(() => {
  if (!document.getElementById("modal-root")) {
    const root = document.createElement("div");
    root.id = "modal-root";
    document.body.appendChild(root);
  }
});
afterEach(() => {
  document.getElementById("modal-root")?.remove();
});
```

### Props → DOM
```typescript
import { mount } from "@vue/test-utils";
import BaseButton from "@/components/BaseButton.vue";

describe("BaseButton", () => {
  it("renders label", () => {
    const wrapper = mount(BaseButton, { props: { label: "Save" } });
    expect(wrapper.text()).toContain("Save");
  });

  it("disables when loading", () => {
    const wrapper = mount(BaseButton, { props: { label: "Save", loading: true } });
    expect(wrapper.attributes("disabled")).toBeDefined();
  });
});
```

### Emit 검증
```typescript
it("emits click with event", async () => {
  const wrapper = mount(BaseButton, { props: { label: "Save" } });
  await wrapper.find("[data-testid=base-button]").trigger("click");
  expect(wrapper.emitted("click")).toHaveLength(1);
  expect(wrapper.emitted("click")![0][0]).toBeInstanceOf(MouseEvent);
});

it("does not emit when disabled", async () => {
  const wrapper = mount(BaseButton, { props: { label: "Save", disabled: true } });
  await wrapper.find("button").trigger("click");
  expect(wrapper.emitted("click")).toBeUndefined();
});
```

### Slot 콘텐츠
```typescript
it("renders default slot", () => {
  const wrapper = mount(BaseButton, {
    props: { label: "fallback" },
    slots: { default: "<span class='custom'>Custom</span>" },
  });
  expect(wrapper.find(".custom").exists()).toBe(true);
});

it("passes variant to default slot via slot props", () => {
  const wrapper = mount(BaseButton, {
    props: { label: "x", variant: "danger" },
    slots: {
      default: ({ variant }) => `<span data-variant="${variant}">slotted</span>`,
    },
  });
  expect(wrapper.find("[data-variant=danger]").exists()).toBe(true);
});
```

### Teleport 컴포넌트
```typescript
it("renders modal in #modal-root when open", async () => {
  const wrapper = mount(Modal, {
    props: { open: true, title: "Confirm" },
    attachTo: document.body,  // teleport 동작 위해
  });
  // teleport target에서 검색
  const modal = document.querySelector("#modal-root [role=dialog]");
  expect(modal?.getAttribute("aria-label")).toBe("Confirm");
  wrapper.unmount();  // jsdom 정리
});
```

### v-model 컴포넌트
```typescript
it("supports v-model", async () => {
  const wrapper = mount(TextInput, {
    props: { modelValue: "init", "onUpdate:modelValue": (v) => wrapper.setProps({ modelValue: v }) },
  });
  await wrapper.find("input").setValue("changed");
  expect(wrapper.emitted("update:modelValue")![0]).toEqual(["changed"]);
});
```

### Composable / inject mock
```typescript
it("uses provided service", () => {
  const wrapper = mount(MyComponent, {
    global: {
      provide: { authService: { user: { name: "Test" } } },
    },
  });
  expect(wrapper.text()).toContain("Test");
});
```

## 5축 품질 체크

| 축 | 체크 |
|---|---|
| 정확성 | 사용 중인 모든 emit이 `defineEmits`에 명시되어 있는가 |
| 안전성 | teleport target이 production index.html에 미리 있는가 |
| 성능 | slot prop이 비싼 reactive 거대 객체 안 흘리는가 |
| 가독성 | props/emits/slots/model이 한 script setup 위쪽에 모여 있는가 |
| 검증성 | data-testid/role 기반 selector로 brittle 안 한가 |

## Gotchas

### implicit emit (defineEmits에 없는 이벤트 emit)
런타임에 동작은 하지만 dev warning + 타입 에러. `$emit('foo')`만 쓰고 명시 안 하면 호출처가 이벤트 존재를 모름.

### slot prop 변경이 깨짐을 안 알림
slot은 사용처가 분산 → 자동 컴파일 에러 X. `defineSlots<{}>()`로 contract 박아두면 사용처 hint.

### teleport target이 mount 시점에 없음
jsdom에서 `<Teleport to="#x">`인데 `#x`가 없으면 silent skip. 테스트 setup에서 prepare, production은 index.html에.

### deep watch가 source를 mutate → 무한 루프
```typescript
watch(form, (next) => { form.normalized = next.value.trim(); }, { deep: true });
// 자기 자신을 변경 → 다시 발동
```
**해결**: computed로 derive하거나, watch 안에서 별도 ref만 쓰기.

### async watcher cleanup 누락
```typescript
watch(query, async (q, _, onCleanup) => {
  const ctrl = new AbortController();
  onCleanup(() => ctrl.abort());
  const r = await fetch(`/s?q=${q}`, { signal: ctrl.signal });
  // ...
});
```
cleanup 안 하면 stale response가 newest를 덮음.

### `defineProps`에 default 안 주고 optional 사용
template에서 `props.x.foo` 접근 → undefined 시 에러. `withDefaults`로 기본값.

### v-model 두 개 이상인데 이름 안 줌
`<Comp v-model="a" v-model:b="b" />`처럼 여러 model 쓰면 named model 필요. `defineModel("b")`.

### teleport 'disabled' 토글로 hydration 깨짐
SSR에서 teleport `disabled` 다이나믹하면 hydration mismatch. 초기엔 fixed로, `onMounted` 후 변경.

### test에서 wrapper unmount 누락
teleport / portal 사용 컴포넌트 mount 후 unmount 없으면 다음 테스트에 오염. `afterEach` 정리 또는 wrapper.unmount().

### selector를 `wrapper.find('div > div > span')`처럼 구조 의존
markup 변경에 깨짐. `data-testid`, role, aria-label 사용.

## 도구 사용 패턴 (Harness)
- emit 누락 탐지: `Grep("emit\\(['\"]([a-zA-Z-]+)", glob="**/*.vue")` 후 `defineEmits` 비교
- props default 누락: `Grep("defineProps<", glob="**/*.vue")` + withDefaults 사용 여부
- teleport target audit: `Grep("<Teleport.+to=['\"]([^'\"]+)", glob="**/*.vue")` 후 index.html 존재 확인
- 테스트 selector quality: `Grep("\\.find\\(['\"][^'\"]*['\"]", glob="tests/**/*.ts")` → CSS path 깊이
- slot contract: `Grep("defineSlots<", glob="**/*.vue")` — 명시 비율
