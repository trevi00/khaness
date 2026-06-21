---
keywords: typescript 5.x upgrade migration tsconfig strict module resolution drift node20 5.9 verbatim moduleSyntax tsc init 업그레이드 마이그레이션 설정 드리프트
intent: typescript 버전업 마이그레이션 strict 강화 module resolution 정렬 tsconfig drift 잡기 5.9 baseline 적용
paths: tsconfig.json tsconfig.base.json packages/*/tsconfig.json
patterns: strict noUncheckedIndexedAccess module node20 moduleResolution verbatimModuleSyntax isolatedModules tsc --init
requires: typescript
phase: design review release
tech-stack: typescript
min_score: 3
---

# TypeScript 5.x Config Drift + Upgrade Map

> 핵심 원칙: **TS 업그레이드는 syntax 업그레이드가 아니라 config + ecosystem 업그레이드다.** strict 묶음 변경, module 기본값, decorator 의미, Node 정렬이 같이 흔들린다.

## 의사결정 트리

### IF TS 업그레이드 (5.0 → 5.9 등) (Design)
1. **목표 capability 먼저 정의** — "왜 올리는가?" (예: `--module node20` stable 필요, `decorators` 표준 적용)
2. patch-by-patch 말고 release line 한 번에 점검:
   - 5.0: standard decorators
   - 5.1~5.4: 추론/inference 강화
   - 5.5+: tsconfig 기본값 prescriptive 화
   - 5.9: `tsc --init` 기본값 변경 + `module: node20` stable
3. **upgrade pressure는 정상**: strict 묶음에 추가 검사가 들어올 수 있음 — 컴파일러 배신이 아니라 명시적 정책

### IF 업그레이드 후 알 수 없는 에러 폭발 (Review)
1. **`tsconfig` 먼저 의심**: `module`/`moduleResolution`/`strict` 변화
2. 새 프로젝트 (`tsc --init`)와 기존 repo 비교 — 5.9 이후 baseline이 더 빡빡함
3. inherited config 추적 (`extends` 체인)
4. 마지막에 syntax 의심 — 보통 4번째 후보

### IF 모노레포 config drift (Review)
1. `tsconfig.base.json` 단일화 — 패키지는 `extends`만
2. 패키지 차이는 `outDir`/`rootDir`/`references`만 허용
3. `strict` 같은 정책 옵션을 패키지마다 끄고 켜는 건 drift 시작
4. CI: 모든 tsconfig를 dump해서 base 옵션 일치 검증

## Release line 요약 (5.0 → 5.9)

| 버전 | 핵심 변화 | upgrade 시 봐야 할 것 |
|---|---|---|
| 5.0 | Standard decorators (TC39), `const` type params, `extends` 다중, bundler resolution | decorator 사용처 — legacy → standard 동작 차이 |
| 5.1 | 더 정확한 element 추론 | JSX/literal 추론에 의존하던 hack 깨질 수 있음 |
| 5.2 | `using` (Symbol.dispose), 가변 array spread | resource cleanup 패턴 추가 가능 |
| 5.3 | import attributes, switch type narrowing 개선 | JSON import 문법 정렬 |
| 5.4 | `NoInfer<T>`, preserveSymlinks 개선 | 추론 우회 헬퍼 정리 가능 |
| 5.5 | `Set` methods, control flow narrowing 강화 | 좁아진 narrowing이 가짜 에러 잡아냄 |
| 5.6 | iterator helpers, strict builtin checking 강화 | for-of/iter 코드 점검 |
| 5.7 | path rewriting, throw expression 추론 | 빌드 출력 경로 변경 점검 |
| 5.8 | `--erasableSyntaxOnly`, Node 16 cutoff 정리 | namespace/enum 사용처 |
| 5.9 | `tsc --init` baseline 변경, `--module node20` stable | **새 프로젝트 baseline + Node 20 정렬** |

## tsconfig baseline (5.9 기준)

```jsonc
// tsconfig.base.json — 모노레포 공유
{
  "compilerOptions": {
    /* Type checking */
    "strict": true,
    "noUncheckedIndexedAccess": true,        // arr[i]가 T | undefined
    "exactOptionalPropertyTypes": true,      // ?: T 와 T | undefined 구분
    "noImplicitOverride": true,
    "noFallthroughCasesInSwitch": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,

    /* Modules */
    "module": "node20",                       // 5.9 stable, Node 20 정렬
    "moduleResolution": "node20",
    "esModuleInterop": true,
    "resolveJsonModule": true,
    "isolatedModules": true,                  // bundler/transpiler 친화
    "verbatimModuleSyntax": true,             // import type 강제

    /* Emit */
    "target": "ES2022",
    "lib": ["ES2022"],
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,

    /* Paths */
    "paths": { "~/*": ["./src/*"] }
  }
}
```

```jsonc
// 패키지별 tsconfig.json — extends만
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src"
  },
  "include": ["src/**/*"],
  "references": [{ "path": "../shared" }]
}
```

## strict 묶음 — 무엇이 켜지는가

`strict: true`는 다음을 한꺼번에 켬:
- `noImplicitAny`
- `strictNullChecks`
- `strictFunctionTypes`
- `strictBindCallApply`
- `strictPropertyInitialization`
- `strictBuiltinIteratorReturn` (5.6+)
- `noImplicitThis`
- `useUnknownInCatchVariables`
- `alwaysStrict`

**docs 명시**: 향후 버전에 추가 검사가 묶일 수 있음. 업그레이드 시 strict 항목이 늘어나는 건 정상.

## module / moduleResolution 매트릭스

| 런타임 | 권장 module | moduleResolution |
|---|---|---|
| Node 20+ (5.9+) | `node20` | `node20` |
| Node latest stable | `nodenext` | `nodenext` |
| Bundler (Vite/webpack/esbuild) | `esnext` | `bundler` |
| 라이브러리 publish | `nodenext` (또는 dual) | `nodenext` |
| 브라우저 직접 | `esnext` | `bundler` |

**핵심 규칙**: `module`과 `moduleResolution`은 **같이 바뀌어야** 함. `module: esnext` + `moduleResolution: node`는 type 통과 + 런타임 깨짐의 단골 원인.

## 점진 업그레이드 전략

### 1. baseline 비교
```bash
# 새 5.9 프로젝트 baseline 추출
mkdir _ref && cd _ref && npx -p typescript@5.9 tsc --init
# diff로 우리 tsconfig와 비교
diff tsconfig.json _ref/tsconfig.json
```

### 2. strict 점진 활성화
```jsonc
// 한꺼번에 strict: true 못 키면 단계별
{
  "compilerOptions": {
    "noImplicitAny": true,
    "strictNullChecks": true,
    // 다음: strictFunctionTypes
    // 그 다음: noUncheckedIndexedAccess (별개로)
  }
}
```

### 3. node20 마이그레이션
- 단계 1: `module: nodenext` → 빌드 통과 확인
- 단계 2: `module: node20` → 5.9 stable 명시
- import에 `.js` 확장자 빠진 것 잡기 (`isolatedModules` 켜져 있으면 더 빨리 잡힘)

### 4. verbatimModuleSyntax 켜기
```typescript
// 켜기 전
import { Foo } from "./foo";  // type-only인지 value인지 모호

// 켜기 후 — 명시 필요
import type { Foo } from "./foo";    // type only
import { foo } from "./foo";          // runtime
```

## 5축 품질 체크

| 축 | 체크 |
|---|---|
| 정확성 | `module`/`moduleResolution` 짝이 runtime과 맞는가 |
| 안전성 | strict 묶음 + noUncheckedIndexedAccess 모두 켜져 있는가 |
| 성능 | `skipLibCheck: true` + `isolatedModules`로 빌드 시간 짧은가 |
| 가독성 | tsconfig 분기가 base extends + outDir/rootDir만인가 |
| 검증성 | CI에서 `tsc --noEmit`이 변경마다 돌아가는가 |

## Gotchas

### `module`만 바꾸고 `moduleResolution` 안 바꿈
가장 흔한 빌드 실패 패턴. 둘은 짝이고, 5.9는 docs에서 "module affects moduleResolution and type checking"이라고 명시.

### 업그레이드 후 strict가 더 빡빡 → 컴파일러 배신으로 오해
strict는 묶음이고 향후 추가될 수 있다고 docs에 명시. 새 에러는 코드 문제 가능성이 더 높음. `// @ts-expect-error`로 점진 처리하고 PR로 분리.

### 모노레포 패키지마다 `tsconfig` 다르게 + base 없음
config drift의 기원. 어떤 패키지는 strict, 어떤 건 안 strict면 호출 경계에서 unsafe 흐름. base에 모으고 패키지는 outDir/rootDir/references만.

### `isolatedModules` 끄고 namespace 사용
번들러/transpiler가 namespace 못 다룸. 5.x 코드는 `isolatedModules: true` + ES module 사용. namespace는 .d.ts 외에는 피하기.

### `verbatimModuleSyntax` 켰을 때 type import 누락
runtime에서 `Foo is not defined` 발생. `import type` 누락한 곳을 ESLint `consistent-type-imports`로 자동 수정.

### `noEmit: true` 프로젝트라서 module 설정 안 봐도 된다고 가정
docs는 명시적으로 `module`이 type 체크에도 영향 준다고 함. import 분류 / file classification이 module 설정에 좌우됨.

### `tsc --init` baseline을 옛날 버전 그대로 들고 가기
5.9 prescriptive defaults를 모르고 5.0 시절 옵션 유지하면 신규 안전망 누락. 메이저 업그레이드 시 baseline diff 의식적으로 검토.

### decorator 모드 혼용
5.0 standard decorators ↔ legacy `experimentalDecorators` 혼용 시 동작이 다름. 한 코드베이스에서 하나만.

## 도구 사용 패턴 (Harness)
- baseline diff: `Bash("npx -p typescript@5.9 tsc --init --pretty false")` → 비교
- module 미스매치 탐지: `Grep("\"module\":", glob="**/tsconfig*.json")` + `Grep("\"moduleResolution\":", glob="**/tsconfig*.json")`
- strict 누락: `Grep("\"strict\":\\s*false", glob="**/tsconfig*.json")`
- type import 누락 탐지: `npx eslint --rule '@typescript-eslint/consistent-type-imports: error' src/`
- 효과 측정: `Bash("npx tsc --noEmit --extendedDiagnostics")` → check time / files
