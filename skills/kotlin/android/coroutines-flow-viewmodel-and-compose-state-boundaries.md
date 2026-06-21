---
name: coroutines-flow-viewmodel-and-compose-state-boundaries
description: Android에서 코루틴 / Flow / ViewModel / Compose state 경계를 라인 코드로 강제하는 베이스라인.
keywords: android kotlin coroutine flow stateflow viewmodel compose state hoisting collectAsStateWithLifecycle repeatOnLifecycle hiltViewModel viewModelScope lifecycleScope LaunchedEffect DisposableEffect rememberUpdatedState saveable savedstatehandle UDF 화면 생명주기
intent: 만들어 추가해 구현해 노출해 구독해 수정해 검증해
paths: app/src/main/kotlin app/src/main/java app/src/main/res
patterns: ViewModel viewModelScope StateFlow MutableStateFlow asStateFlow stateIn SharingStarted.WhileSubscribed SavedStateHandle hiltViewModel collectAsStateWithLifecycle repeatOnLifecycle Lifecycle.State.STARTED LaunchedEffect DisposableEffect rememberUpdatedState rememberSaveable
requires:
phase: plan implement review debug
tech-stack: kotlin
min_score: 2
---

# Android — Coroutines, Flow, ViewModel, Compose State Boundaries

Android에서 코루틴/Flow는 코드만으로 안전하지 않다. **소유 스코프(viewModelScope/lifecycleScope)**, **수집 시점(STARTED 이상)**, **상태 호이스팅 경계(route↔screen↔leaf)** 세 축이 합치돼야 회전·프로세스 사망·메모리 누수에 강하다. 이 스킬은 그 경계를 라인 단위로 강제한다.

## 의사결정 트리

### IF ViewModel에서 비동기 시작 (Plan / Implement)
1. **항상 `viewModelScope.launch { ... }`** — `GlobalScope` 금지, `CoroutineScope(...)` 직접 생성 금지 (소유자 모호).
2. UI 상태는 `private val _state = MutableStateFlow(initial)` + `val state: StateFlow = _state.asStateFlow()`. 외부에 mutable 노출 금지.
3. one-shot 이벤트(Toast/Navigation)는 `Channel<UiEvent>(Channel.BUFFERED)` + `receiveAsFlow()`. **`StateFlow<Event?>` 안티패턴.**
4. cold flow → state 변환은 `stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), initial)` 표준.

### IF UI에서 Flow 수집 (Implement)
1. **Compose**: `val state by viewModel.state.collectAsStateWithLifecycle()`. `collectAsState()`는 STARTED 미보장 — 사용 금지.
2. **View System**: `viewLifecycleOwner.lifecycleScope.launch { repeatOnLifecycle(STARTED) { flow.collect { } } }`.
3. **금지**: `LaunchedEffect(Unit) { flow.collect { } }` — 백그라운드에서도 수집 → 메모리 누수.
4. one-shot 이벤트도 lifecycle-aware: `flowWithLifecycle(STARTED).collect { ... }`.

### IF Compose에서 상태 다루기 (Implement)
1. **상태 보유 위치**:
   - 화면 간 공유 + 회전 생존 + 비즈니스 로직 → `ViewModel`
   - 한 composable subtree 한정 + UI 한정 → `remember { mutableStateOf(...) }` 또는 plain state holder
   - 회전 생존 (간단한 값) → `rememberSaveable { mutableStateOf(...) }`
2. **상태 호이스팅**: state는 위로, callback은 위에서 아래로. leaf composable에 ViewModel/NavController 전달 금지.
3. **Route ↔ Screen 분리**:
   - `XxxRoute`: ViewModel 획득(`hiltViewModel()`), state 수집, callback 가공, navigation 호출
   - `XxxScreen`: 순수 UI (state + lambda 받음, 프레임워크 핸들 없음)

### IF Compose Effect 사용 (Implement)
1. **`LaunchedEffect(key1, key2)`**: key 변경 시 코루틴 재시작. key 신중히.
2. **`DisposableEffect(key)`**: 등록/해제 필요한 리소스. `onDispose { ... }` 필수.
3. **`SideEffect`**: 매 recomposition마다 — Compose 외부와 동기화 (분석 로그 등).
4. **`rememberUpdatedState(value)`**: 장기 effect가 항상 최신 lambda/value 사용. `LaunchedEffect(Unit) { ... value() ... }` 안에 `value`가 stale.
5. **`LaunchedEffect(true)` 또는 `LaunchedEffect(Unit)`**: 컴포저블 진입~이탈 1회. 의도 확실할 때만.

### IF SavedStateHandle / 프로세스 사망 (Implement)
1. ViewModel 생성자에 `SavedStateHandle` 주입 — Hilt가 자동.
2. `savedStateHandle.getStateFlow("key", default)` — process death 후에도 복원되는 StateFlow.
3. 큰 객체/리스트는 SavedStateHandle 부적합 (TransactionTooLargeException). repository / Room으로 영속.
4. Compose state 회전 복원: `rememberSaveable { ... }`. 커스텀 타입은 `Saver` 정의.

### IF Hilt + Compose Navigation (Implement)
1. Route composable에서 `viewModel: XxxViewModel = hiltViewModel()` — graph-scoped.
2. NavController는 route에만 전달, screen에는 callback (`onBack`, `onSelect`)만.
3. nested graph로 ViewModel 공유는 `hiltViewModel(navController.getBackStackEntry("graphRoute"))`.

### IF 코드 리뷰 (Review)
- [ ] ViewModel에서 GlobalScope 또는 임의 CoroutineScope 사용 안 함
- [ ] state는 private MutableStateFlow + 공개 StateFlow
- [ ] one-shot 이벤트는 Channel 또는 SharedFlow(replay=0)
- [ ] Compose 수집은 collectAsStateWithLifecycle
- [ ] View 수집은 repeatOnLifecycle(STARTED)
- [ ] route 컴포저블이 ViewModel 보유, screen 컴포저블은 state+callback만
- [ ] LaunchedEffect의 key 선택이 의도와 일치
- [ ] DisposableEffect의 onDispose가 모든 등록 자원 해제
- [ ] rememberSaveable 사용 시 Saver 명확
- [ ] SavedStateHandle에 큰 객체 안 저장

## 핵심 패턴

### ViewModel + StateFlow + Channel
```kotlin
@HiltViewModel
class CartViewModel @Inject constructor(
    private val repo: CartRepository,
    private val savedStateHandle: SavedStateHandle,
) : ViewModel() {
    private val _state = MutableStateFlow(CartUiState.Loading)
    val state: StateFlow<CartUiState> = _state.asStateFlow()

    private val _events = Channel<CartEvent>(Channel.BUFFERED)
    val events: Flow<CartEvent> = _events.receiveAsFlow()

    init {
        viewModelScope.launch {
            runCatching { repo.observeCart() }
                .onSuccess { it.collect { cart -> _state.value = CartUiState.Ready(cart) } }
                .onFailure { _events.send(CartEvent.ShowError(it.message ?: "")) }
        }
    }

    fun checkout() {
        viewModelScope.launch {
            try {
                repo.checkout()
                _events.send(CartEvent.NavigateToConfirm)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _events.send(CartEvent.ShowError(e.message ?: ""))
            }
        }
    }
}
```

### Route ↔ Screen 분리 (Compose Navigation)
```kotlin
@Composable
fun CartRoute(navController: NavController) {
    val viewModel: CartViewModel = hiltViewModel()
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle

    LaunchedEffect(viewModel.events, lifecycle) {
        viewModel.events.flowWithLifecycle(lifecycle, Lifecycle.State.STARTED).collect { event ->
            when (event) {
                is CartEvent.ShowError -> Toast.makeText(context, event.msg, Toast.LENGTH_SHORT).show()
                CartEvent.NavigateToConfirm -> navController.navigate("confirm")
            }
        }
    }

    CartScreen(
        state = state,
        onCheckout = viewModel::checkout,
        onBack = { navController.popBackStack() },
    )
}

@Composable
fun CartScreen(
    state: CartUiState,
    onCheckout: () -> Unit,
    onBack: () -> Unit,
) {
    // 순수 UI — ViewModel/NavController 없음
}
```

### rememberUpdatedState — stale callback 방지
```kotlin
@Composable
fun TimerEffect(onTick: () -> Unit) {
    val current by rememberUpdatedState(onTick)
    LaunchedEffect(Unit) {
        while (true) {
            delay(1_000)
            current()                  // 항상 최신 onTick 호출
        }
    }
}
```

### DisposableEffect — 리스너 등록/해제
```kotlin
@Composable
fun ConnectivityListener(onChange: (Boolean) -> Unit) {
    val context = LocalContext.current
    DisposableEffect(Unit) {
        val cm = context.getSystemService(ConnectivityManager::class.java)
        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(net: Network) = onChange(true)
            override fun onLost(net: Network) = onChange(false)
        }
        cm.registerDefaultNetworkCallback(cb)
        onDispose { cm.unregisterNetworkCallback(cb) }
    }
}
```

### SavedStateHandle StateFlow
```kotlin
class FilterViewModel(
    savedStateHandle: SavedStateHandle,
) : ViewModel() {
    val query: StateFlow<String> = savedStateHandle.getStateFlow(KEY_QUERY, "")
    fun setQuery(q: String) { savedStateHandle[KEY_QUERY] = q }
    private companion object { const val KEY_QUERY = "query" }
}
```

## Gotchas

### `LaunchedEffect(Unit) { flow.collect { } }`
앱 백그라운드에서도 collect 계속 → 누수 + 화면 안 보일 때 emit 처리. 항상 `collectAsStateWithLifecycle` 또는 `flowWithLifecycle(STARTED)`.

### `collectAsState()` (lifecycle-unaware)
Compose 1.x 기본 — STARTED 보장 안 함. **`collectAsStateWithLifecycle()`** (lifecycle-runtime-compose) 사용.

### state hoisting 위반: leaf에 ViewModel 전달
재사용성 떨어지고 미리보기 작성 어려움. screen은 state+lambda만 받음.

### `LaunchedEffect(viewModel)` (객체 식별자 key)
viewModel 인스턴스가 회전마다 같으면 1번 실행, 다르면 매번 재시작 → 의도 모호. 명시적 key 사용 (`Unit`, `id` 등).

### `rememberSaveable` 없이 회전 시 상태 유실
`remember { mutableStateOf(initial) }`은 회전 시 초기화. 회전 생존 필요 → `rememberSaveable`. 커스텀 타입은 `Saver`.

### SavedStateHandle에 List<Order>같이 큰 객체 저장
TransactionTooLargeException. SavedStateHandle은 적은 키 (선택된 ID, 검색어). 데이터는 repository에서 재로딩.

### `runBlocking`을 ViewModel에서
viewModelScope 있는데 굳이 메인 블로킹 → ANR. 항상 launch + suspend.

### `MutableStateFlow.value =` race
여러 launch에서 동시에 value 갱신 → lost update. `_state.update { it.copy(...) }` 사용.

### Channel 다중 collector → 이벤트 일부만 도착
한 화면이 두 곳에서 events.collect → 이벤트가 한 쪽으로만. Channel은 단일 collector. 다중 필요시 SharedFlow.

### `hiltViewModel()`을 nested composable 안에서 호출
배포 환경에 따라 다른 graph 스코프로 만들어질 수 있음. **route-level에서만 호출.**

### `DisposableEffect`에 onDispose 누락
컴파일 에러는 아니지만 리스너 누수. 항상 onDispose에서 unregister.

### `viewModelScope`에 long-running CPU loop + suspend point 없음
cancel 무시. `ensureActive()` 또는 `yield()` 삽입. (참조: `kotlin/lang/coroutines-cancellation-supervision-and-timeout-contracts`)

## 검증 체크리스트

- ViewModel이 viewModelScope만 사용
- state는 private mutable + public StateFlow
- one-shot 이벤트는 Channel/SharedFlow(replay=0)
- Compose 수집이 collectAsStateWithLifecycle
- View 수집이 repeatOnLifecycle(STARTED)
- route/screen 분리, leaf에 ViewModel/NavController 없음
- LaunchedEffect key가 의도와 일치
- DisposableEffect onDispose가 모든 자원 해제
- rememberSaveable Saver 명시
- SavedStateHandle에 작은 키만

## 5축 자가 평가

- 검색성: android/coroutine/flow/viewmodel/compose state/lifecycle/한·영 + 실제 식별자
- 의사결정 트리(IF/THEN): 7개 IF + 10개 리뷰 체크
- 코드 식별자: ViewModel, viewModelScope, MutableStateFlow, asStateFlow, stateIn, SharingStarted.WhileSubscribed, SavedStateHandle, hiltViewModel, collectAsStateWithLifecycle, repeatOnLifecycle, Lifecycle.State.STARTED, LaunchedEffect, DisposableEffect, rememberUpdatedState, rememberSaveable, Channel, receiveAsFlow, flowWithLifecycle
- Gotcha-driven: 12개 흔한 실수 + 회피
- 검증 가능: 10개 체크리스트

## Related (신규 그래프 cross-ref)

coroutines-flow-viewmodel-compose가 결합되는 신규 노드:
- `kotlin/android/circuit-unidirectional-architecture.md` — Slack Circuit Presenter는 Compose runtime 기반 — `LaunchedEffect` stable key 강제
- `kotlin/android/dagger-hilt-di-architecture.md` — `@HiltViewModel` + `hiltViewModel()` Compose 통합 (1.3.0+ 패키지 분리)
- `kotlin/android/graphql-apollo-android.md` — Apollo `.toFlow()` Subscription을 ViewModel `viewModelScope`로 수집
- `kotlin/android/paparazzi-screenshot-tests.md` — Compose UI를 JVM에서 렌더링하여 회귀 검증 (state ↔ UI 분리 강제)
