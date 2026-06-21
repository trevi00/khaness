---
name: dagger-hilt-di-architecture
description: Dagger Hilt 2.59 / androidx.hilt 1.3 — component scope 8단, KSP2 마이그레이션, multi-module 배치, hiltViewModel 패키지 분리
keywords: hilt dagger di android-entry-point hilt-android-app hilt-viewmodel install-in singleton-component ksp2 binds provides
intent: design-di-architecture migrate-kapt-to-ksp place-modules-multi-module avoid-scope-leak handle-test-cost
paths: app/src/main/kotlin
patterns: @HiltAndroidApp @AndroidEntryPoint @HiltViewModel @InstallIn @Module @Binds @Provides hiltViewModel
requires: coroutines-flow-viewmodel-and-compose-state-boundaries circuit-unidirectional-architecture
phase: plan implement review debug
tech-stack: kotlin
min_score: 2
quality_axes_enforced: true
---

# Dagger Hilt — DI Architecture (2.59+)

> 핵심: Hilt는 Dagger codegen wrapper로 component scope 8단을 강제. **2.59+ 는 AGP 9 + Gradle 9.1 hard requirement** — 마이그레이션 시 동시 업그레이드. **Kotlin 2.0+ 환경은 kapt → KSP2 전환 mandatory** (1.3.0-alpha01부터 KSP2 target).

## 의사결정 트리

### IF Hilt 채택 결정 (Plan)
1. version pin — Hilt 2.59.2 + androidx.hilt 1.3.0 (2026-05 기준)
2. AGP 8.x 프로젝트 → Hilt 2.58까지만. 2.59 채택 시 AGP 9 + Gradle 9.1 동반 업그레이드
3. Kotlin 2.0+ → kapt 폐기, `ksp(...)` 로 전환. kapt 잔존 시 컴파일러 업그레이드 차단

### IF Component scope 결정 (Implement)
parent → child 순서 (Android Developer docs 표):
| Component | Scope |
|---|---|
| `SingletonComponent` | `@Singleton` (Application lifetime) |
| `ActivityRetainedComponent` | `@ActivityRetainedScoped` (config change 통과) |
| `ViewModelComponent` | `@ViewModelScoped` |
| `ActivityComponent` | `@ActivityScoped` |
| `FragmentComponent` | `@FragmentScoped` |
| `ViewComponent` | `@ViewScoped` |
| `ServiceComponent` | `@ServiceScoped` |

원칙: **Repository는 `@ApplicationContext`만 받음** — `Activity`/`Fragment` 직접 참조 시 Singleton 누수.

### IF Multi-module 배치 (Plan)
```
:data       — @InstallIn(SingletonComponent::class) (Repo, Network, DB)
:domain     — @InstallIn(ViewModelComponent::class) (UseCase)
:feature/*  — Hilt module 없음. 생성자 주입만
:app        — @HiltAndroidApp Application + Hilt config
```

### IF Compose 통합 (Implement)
1. ViewModel — `@HiltViewModel class FooViewModel @Inject constructor(...)`
2. Composable — `@Composable fun Foo(vm: FooViewModel = hiltViewModel())`
3. **artifact 분리 (1.3.0+)** — `androidx.hilt:hilt-lifecycle-viewmodel-compose` (navigation 의존 없음). 구 `androidx.hilt.navigation.compose`는 navigation-compose 함께 쓸 때만
4. nav graph scope — `hiltNavGraphViewModels(R.id.my_graph)`

### IF kapt → KSP 마이그레이션 (Plan)
1. 모든 모듈 `build.gradle.kts`에서 `kapt(...)` → `ksp(...)`
2. `kotlin("kapt")` plugin 제거, `com.google.devtools.ksp` 추가
3. annotation processor argument 마이그레이션 — `kapt { ... }` → `ksp { arg(...) }`
4. CI clean build로 회귀 검증 — KSP는 incremental 처리 다름

## 가이드

- ProGuard/R8 — Hilt 자체 rule은 묶여 있으나 **custom `@EntryPoint` interface는 별도 keep rule** 필요 (`-keep interface ... { *; }`).
- `EntryPointAccessors.fromApplication(...)` — 첫 호출 시 reflection 비용. RecyclerView/Compose recomposition hot path 금지.
- broadcast receiver는 `SingletonComponent` 만 — Activity 단위 scope 불가.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | component scope 8단 hierarchy로 lifetime 명확 |
| 성능 효율성 | KSP2가 kapt 대비 빌드 시간 단축, EntryPointAccessors hot path 회피 |
| 호환성 | Hilt 2.59 ↔ AGP 9 + Gradle 9.1 lockstep |
| 사용성 | `@HiltAndroidApp` 1줄로 부트스트랩 |
| 신뢰성 | `@HiltAndroidTest` + `@UninstallModules` + `@BindValue`로 테스트 격리 |
| 보안 | `@ApplicationContext`만 사용 강제로 Activity ref 누수 차단 |
| 유지보수성 | multi-module 분리로 Hilt config 책임 명확 |
| 이식성 | Compose-only 모듈은 navigation 의존 없이 hiltViewModel 사용 가능 (1.3.0+) |
| 확장성 | qualifier + `@IntoSet`/`@IntoMap` multibinding으로 plugin 패턴 |

## Gotchas

### kapt 잔존으로 Kotlin 2.0+ 차단
Hilt 1.3.0-alpha01부터 KSP2 target. kapt 사용 모듈이 1개라도 있으면 Kotlin 컴파일러 업그레이드 차단. 전체 모듈 `ksp` 전환 필수.

### `@AndroidEntryPoint` transitivity 누락
Fragment에 annotation 있는데 hosting Activity에 없으면 `EntryPointAccessors` 런타임 crash (compile error 아님). 모든 hosting 클래스 annotate.

### Repository에 `Context` 직접 주입
`Context` 직접 받으면 Activity/Fragment Context 주입 가능 — Singleton scope에서 view tree 누수. `@ApplicationContext` 강제.

### `EntryPointAccessors.fromApplication(...)` hot path 호출
첫 호출 reflection 비용. RecyclerView binder, Compose recomposition에서 금지. 외부 inject 경로로 대체.

### `@HiltAndroidTest` 비용 폭증
테스트마다 component 생성 — 500+ 테스트면 CI 시간 2배. `@UninstallModules` + `@BindValue`로 좁은 swap, 통합 테스트는 module 셋 그룹.

### custom `@EntryPoint` interface ProGuard에서 stripped
Hilt-generated 클래스는 keep, custom EntryPoint interface는 별도 keep rule. 누락 시 release build 런타임 fail.

### AGP 9 미충족 상태에서 Hilt 2.59 핀
plugin loading fail. AGP 8.x 유지면 Hilt 2.58 핀, 동반 업그레이드 시 2.59+.

## Source

- https://developer.android.com/training/dependency-injection/hilt-android — `@HiltAndroidApp`, `@AndroidEntryPoint`, `@Module` + `@InstallIn`, `@Binds`, broadcast receiver는 SingletonComponent only, 조회 2026-05-10
- https://developer.android.com/training/dependency-injection/hilt-jetpack — `hiltNavGraphViewModels` semantics, 조회 2026-05-10
- https://developer.android.com/jetpack/androidx/releases/hilt — 1.3.0 (2025-09-10), `hiltViewModel()` "moved to a new artifact (androidx.hilt:hilt-lifecycle-viewmodel-compose)"; "target Kotlin 2.0 to support newer Kotlin toolchain including KSP2", 조회 2026-05-10
- https://dagger.dev/hilt/ — "Hilt provides a standard way to incorporate Dagger dependency injection"; "code generating your Dagger setup code", 조회 2026-05-10
- https://github.com/google/dagger/releases — 2.59 (2025-01-21) "Now requires AGP 9 and Gradle 9.1+", 조회 2026-05-10
- https://dagger.dev/dev-guide/ksp.html — KSP migration 절차, 조회 2026-05-10
