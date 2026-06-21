---
name: flow-stateflow-sharedflow-and-one-shot-event-boundaries
description: Flow / StateFlow / SharedFlow 선택 기준과 일회성 이벤트 경계를 코드 라인으로 강제하는 베이스라인.
keywords: kotlin flow stateflow sharedflow channel one-shot event hot cold sharing stateIn shareIn collectAsStateWithLifecycle replay buffer overflow conflate distinctUntilChanged 일회성 이벤트 핫 콜드 스트림
intent: 만들어 추가해 구현해 수정해 노출해 검증해 리팩터
paths: lib/src/ src/main/kotlin app/src/main/kotlin shared/src/commonMain/kotlin
patterns: Flow StateFlow SharedFlow MutableStateFlow MutableSharedFlow Channel asStateFlow asSharedFlow stateIn shareIn SharingStarted.WhileSubscribed flowOn collectAsStateWithLifecycle BufferOverflow.DROP_OLDEST distinctUntilChanged conflate
requires:
phase: plan implement review debug
tech-stack: kotlin
min_score: 2
---

# Kotlin Flow / StateFlow / SharedFlow & One-Shot Event Boundaries

`Flow` 계열은 cold stream(`Flow`)과 hot stream(`StateFlow`/`SharedFlow`/`Channel`) 두 부류로 나뉜다. 잘못 선택하면 **이벤트 중복 발생**, **상태 유실**, **구독자 0명일 때 누수** 같은 버그가 생긴다. 이 스킬은 stream 종류 선택과 one-shot 이벤트 경계를 코드 라인 수준으로 강제한다.

## 의사결정 트리

### IF 새 Flow 노출 (Plan / Implement)
1. **노출 대상이 "현재 상태"**(UI에 항상 한 값이 있어야 함) → `StateFlow`. 초기값 필수, conflate 동작 (느린 collector는 중간값 skip), distinct (같은 값 중복 emit 안 됨).
2. **노출 대상이 "이벤트 스트림"**(0개 이상의 이벤트, 구독 시작 후만 받기) → `SharedFlow` with `replay = 0`.
3. **노출 대상이 "일회성 이벤트 with 백프레셔 보장"** (하나도 놓치면 안 됨) → `Channel` + `receiveAsFlow()`. 단일 구독자 한정.
4. **노출 대상이 "콜드 데이터 소스"**(요청마다 새로 시작) → `Flow { ... }` 또는 `flow { emit(...) }`. 변환 후 그대로 노출.
5. **외부에 mutable 노출 금지** — `MutableStateFlow`/`MutableSharedFlow`는 항상 `private val _state`, 공개는 `val state: StateFlow = _state.asStateFlow()`.

### IF Cold Flow → Hot 변환 (Implement)
1. ViewModel/Repository에서 cold flow를 UI에 노출하려면 `stateIn` 또는 `shareIn`으로 hot 전환.
2. `SharingStarted` 선택:
   - `WhileSubscribed(5_000)` — 구독자 사라지고 5초 후 cold 소스 정지. UI가 회전 등으로 잠깐 떨어질 때 재구독 비용 절약. **Android UI 기본값**.
   - `Eagerly` — 즉시 시작, 영원히. 백그라운드 polling 등.
   - `Lazily` — 첫 구독자 등장 시 시작, 영원히 유지.
3. `stateIn`은 초기값 필수, `shareIn`은 `replay` 정책 필수.

### IF UI에서 Flow 수집 (Implement, Android)
1. **항상** `collectAsStateWithLifecycle()` (Compose) 또는 `repeatOnLifecycle(STARTED) { flow.collect { } }` (View) 사용.
2. **금지**: `LaunchedEffect(Unit) { flow.collect { } }` — STARTED 상태가 아니어도 collect 계속됨 (백그라운드에서 누수).
3. ViewModel에서는 `viewModelScope`로 stateIn — `WhileSubscribed(5_000)` 권장.

### IF 일회성 이벤트 (one-shot: Toast/Navigation) (Implement)
1. **금지**: `StateFlow<Event?>` + null 리셋 — 회전/재구독 시 이벤트 재발생.
2. **권장 1**: `Channel<Event>(Channel.BUFFERED)` + `receiveAsFlow()`. 단일 collector 가정. 받은 이벤트는 자동 소비.
3. **권장 2**: `MutableSharedFlow(replay = 0, extraBufferCapacity = N, onBufferOverflow = SUSPEND)` — 다중 collector 허용, 구독 시작 후의 emit만 받음.
4. UI는 lifecycle-scoped collect로 받아 처리. 처리 후 별도 "consumed" 플래그 불필요.

### IF Flow operator 체이닝 (Implement)
1. **upstream blocking** → `flowOn(Dispatchers.IO)` 또는 `Default`. downstream(collector)에는 영향 없음.
2. **빠른 producer + 느린 consumer**:
   - 최신값만 → `conflate()` 또는 StateFlow로 변환
   - drop oldest → `buffer(N, BufferOverflow.DROP_OLDEST)`
   - drop latest → `buffer(N, BufferOverflow.DROP_LATEST)`
   - 모두 처리 (suspend producer) → `buffer(N, BufferOverflow.SUSPEND)` (기본)
3. `distinctUntilChanged()`는 StateFlow에 이미 내장. cold flow에서는 명시 호출.

### IF 코드 리뷰 (Review)
- [ ] `Mutable*Flow`가 외부에 노출되지 않는가 (private + asStateFlow/asSharedFlow)
- [ ] one-shot 이벤트가 StateFlow로 표현되지 않았는가 (Channel/SharedFlow 사용)
- [ ] UI collect가 lifecycle-aware (`collectAsStateWithLifecycle` / `repeatOnLifecycle`)인가
- [ ] `stateIn`/`shareIn`의 `SharingStarted` 선택이 명시적인가
- [ ] blocking 호출 위에 `flowOn` 있는가
- [ ] 빠른 producer에 백프레셔 정책(`buffer`/`conflate`)이 명시되었는가
- [ ] `replay` 값이 의도적인가 (이벤트 스트림은 0, 캐시는 1)

## 핵심 패턴

### StateFlow — UI 상태 노출
```kotlin
class CartViewModel(
    private val repo: CartRepository,
) : ViewModel() {
    val state: StateFlow<CartUiState> = repo.observeCart()
        .map { cart -> CartUiState.from(cart) }
        .stateIn(
            scope = viewModelScope,
            started = SharingStarted.WhileSubscribed(5_000),
            initialValue = CartUiState.Loading,
        )
}
```

### SharedFlow — 이벤트 스트림 (다중 구독자)
```kotlin
private val _events = MutableSharedFlow<UiEvent>(
    replay = 0,
    extraBufferCapacity = 8,
    onBufferOverflow = BufferOverflow.SUSPEND,
)
val events: SharedFlow<UiEvent> = _events.asSharedFlow()

fun trigger(event: UiEvent) {
    _events.tryEmit(event)   // 또는 viewModelScope.launch { _events.emit(event) }
}
```

### Channel — 일회성 이벤트 (단일 구독자)
```kotlin
private val _navEvents = Channel<NavEvent>(Channel.BUFFERED)
val navEvents: Flow<NavEvent> = _navEvents.receiveAsFlow()

fun navigateToDetail(id: Long) {
    viewModelScope.launch { _navEvents.send(NavEvent.Detail(id)) }
}
```
Channel은 receiveAsFlow의 단일 collector만 받음. 두 곳에서 collect하면 이벤트가 한 쪽에만 감.

### Compose — lifecycle-aware collect
```kotlin
@Composable
fun CartScreen(viewModel: CartViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current

    LaunchedEffect(Unit) {
        viewModel.events.flowWithLifecycle(lifecycle, Lifecycle.State.STARTED).collect { event ->
            when (event) {
                is UiEvent.Toast -> Toast.makeText(context, event.msg, Toast.LENGTH_SHORT).show()
            }
        }
    }
    CartContent(state)
}
```

### Cold Flow + flowOn 백프레셔
```kotlin
fun observeOrders(): Flow<List<Order>> = flow {
    while (currentCoroutineContext().isActive) {
        emit(api.fetchOrders())   // suspend
        delay(5_000)
    }
}
.flowOn(Dispatchers.IO)
.distinctUntilChanged()
.conflate()                       // collector 느려도 최신값만
```

## Gotchas

### `StateFlow<Event?>` + null reset 으로 일회성 이벤트
회전/재구독 → state가 다시 emit → Toast 두 번. **Channel 또는 SharedFlow(replay=0).**

### `Mutable*Flow`를 public으로
외부에서 emit 가능 → 캡슐화 깨짐. `private val _x` + `val x = _x.asStateFlow()`.

### `LaunchedEffect(Unit) { flow.collect { } }`
앱 백그라운드에서도 collect 계속. `collectAsStateWithLifecycle` 또는 `flowWithLifecycle(STARTED)`.

### `stateIn` 없이 cold flow를 UI에 직접 collect
화면 회전마다 cold 소스 재시작 → 네트워크 호출 N배. ViewModel에서 `stateIn(... WhileSubscribed(5_000) ...)`.

### `SharingStarted.Eagerly` 무지성 사용
구독자 없어도 영원히 도는 타이머 → 메모리/배터리 낭새. UI 데이터는 `WhileSubscribed`.

### Channel 다중 collector
한 Channel을 두 화면에서 collect하면 이벤트가 한 쪽으로만. 다중 구독자 필요하면 SharedFlow.

### `replay = 1` SharedFlow를 이벤트로 사용
새 구독자가 마지막 이벤트 다시 받음 → 회전 후 Toast 재발생. **이벤트는 `replay = 0`**.

### `MutableSharedFlow.tryEmit` 실패 무시
`onBufferOverflow = SUSPEND`(기본)이고 buffer 가득 → tryEmit이 false 반환. 결과 무시하면 이벤트 유실. `emit()` (suspend) 사용 또는 `BufferOverflow.DROP_OLDEST`.

### `flowOn(Dispatchers.Main)`을 IO 작업 위에
upstream에 영향. IO 호출이 Main에서 실행 → ANR. blocking 호출 위에는 IO/Default.

### `distinctUntilChanged` 순수성 위반
emit 객체의 `equals`가 `==`(reference)면 매번 다른 인스턴스로 emit → distinct 무력화. data class 또는 명시적 비교.

### `combine`/`zip` 후 stateIn 안 함
combine 결과를 cold로 두 곳에서 collect → 두 번 실행. 합쳐진 결과를 `stateIn`으로 한 번만 계산.

## 검증 체크리스트

- Mutable*Flow가 private이고 공개는 asStateFlow/asSharedFlow
- 일회성 이벤트가 Channel 또는 SharedFlow(replay=0)로 표현
- UI collect가 lifecycle-aware
- stateIn/shareIn에 명시적 SharingStarted
- 빠른 producer에 buffer/conflate 정책 명시
- blocking 호출 위에 flowOn(IO/Default)
- 객체 emit이 distinct 의미를 만족 (data class)

## 5축 자가 평가

- 검색성: Flow/StateFlow/SharedFlow/Channel + 한·영 키워드 + operator 식별자
- 의사결정 트리(IF/THEN): 6개 IF 분기 + 7개 리뷰 체크리스트
- 코드 식별자: StateFlow, SharedFlow, MutableStateFlow, MutableSharedFlow, Channel, asStateFlow, stateIn, shareIn, SharingStarted.WhileSubscribed, BufferOverflow.DROP_OLDEST, flowOn, collectAsStateWithLifecycle, distinctUntilChanged
- Gotcha-driven: 11개 흔한 실수 + 회피
- 검증 가능: 7개 체크리스트
