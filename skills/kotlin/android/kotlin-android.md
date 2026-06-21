---
keywords: kotlin 코틀린 android 안드로이드 coroutine 코루틴 flow sealed data intent aidl service broadcast activity viewmodel compose hilt room navigation jetpack 컴포즈 di 의존성주입 테스트 kotest mockk
intent: 만들어 추가해 구현해 수정해 리팩터 테스트해 코틀린해 안드로이드해 액티비티 프래그먼트 코루틴
paths: app/src/main/kotlin app/src/main/java android/ src/main/kotlin
patterns: kotlinx.coroutines registerForActivityResult startActivityForResult ViewModel LiveData StateFlow Composable remember LaunchedEffect MutableStateFlow SharedFlow Channel Hilt Inject Module
requires:
phase: plan implement review debug
min_score: 3
---

# Kotlin + Android 앱 개발

## 의사결정 트리

### IF Android Activity/Fragment 생성 (Implement)
1. Activity: `FlutterActivity` 상속 여부 결정 (Flutter 포함 앱이면 FlutterActivity)
2. Fragment: `Fragment` 상속 + ViewModel 연결
3. 생명주기 콜백 순서: `onCreate` → `onStart` → `onResume` → `onPause` → `onStop` → `onDestroy`
4. `registerForActivityResult()`는 반드시 `onCreate()` 또는 그 이전에 등록 (lazy 불가)

### IF 외부 앱 호출 (결제 앱 등) (Implement)
1. 명시적 Intent: `setClassName(패키지명, 클래스명)` 사용
2. FlutterActivity에서는 `startActivityForResult()` + `onActivityResult()` 사용 (registerForActivityResult 불가)
3. Handler를 함수 타입 `(Intent) -> Unit`으로 추출, MainActivity에서 주입
4. `putExtra()`로 데이터 전달, 결과는 `result.data?.getStringExtra()` 등으로 수신
5. **주의**: 결제 앱이 미설치 시 `ActivityNotFoundException` → try-catch 필수
6. **→ example_gateway-example_vendor 스킬: 결제 앱 Intent 필드 상세**

### IF Coroutine 비동기 처리 (Implement)
1. UI 작업: `Dispatchers.Main` (기본)
2. 네트워크/IO: `withContext(Dispatchers.IO) { ... }`
3. CPU 집약: `withContext(Dispatchers.Default) { ... }`
4. ViewModel 내: `viewModelScope.launch { }` (자동 취소)
5. Activity/Fragment 내: `lifecycleScope.launch { }` (생명주기 연동)
6. **금지**: `runBlocking`은 메인 스레드에서 절대 사용 금지 (ANR 발생)
7. **금지**: `GlobalScope.launch`는 안티패턴 — 구조적 동시성 위반, 생명주기 무시

### IF Flow / StateFlow 사용 (Implement)
1. **StateFlow**: UI 상태 표현 (항상 최신값 보유, `value` 접근 가능)
   ```kotlin
   private val _state = MutableStateFlow<UiState>(UiState.Loading)
   val state: StateFlow<UiState> = _state.asStateFlow()
   ```
2. **SharedFlow**: 이벤트 스트림 (일회성 이벤트, Toast/Navigation)
   ```kotlin
   private val _event = MutableSharedFlow<UiEvent>()
   val event: SharedFlow<UiEvent> = _event.asSharedFlow()
   ```
3. **Flow → StateFlow 변환**: `stateIn(scope, SharingStarted.WhileSubscribed(5000), 초기값)`
4. **Flow → SharedFlow 변환**: `shareIn(scope, SharingStarted.WhileSubscribed(), replay)`
5. UI 수집: `repeatOnLifecycle(Lifecycle.State.STARTED) { flow.collect { } }`

### IF sealed class로 상태 관리 (Plan)
1. `sealed class PaymentState` → `Idle`, `Loading`, `Success(data)`, `Failure(error)`, `Canceled`
2. `when(state)` exhaustive 검사로 모든 케이스 강제 처리
3. ViewModel에서 `StateFlow<PaymentState>`로 노출
4. Kotlin 2.0+에서 `sealed interface` 우선 (다중 상속 허용)
5. **주의**: `sealed class`의 `copy()`는 `init` 검증을 우회할 수 있음 (Kotlin 2.0 이전)

### IF Jetpack Compose UI 구현 (Implement)
1. `@Composable` 함수는 순수하게 유지 — 사이드이펙트는 Effect API 사용
2. 상태: `remember { mutableStateOf(초기값) }` — 리컴포지션 간 값 유지
3. 생명주기 효과:
   - `LaunchedEffect(key)`: key 변경 시 코루틴 실행 (API 호출 등)
   - `DisposableEffect(key)`: 정리 필요한 리소스 (리스너 등록/해제)
   - `SideEffect`: 매 리컴포지션마다 실행 (비Compose 코드 동기화)
4. ViewModel 접근: `val viewModel: MyViewModel = hiltViewModel()`
5. Navigation: `NavHost` + `composable("route") { Screen() }`
6. **주의**: `remember` 없이 `mutableStateOf()` → 매 리컴포지션마다 초기화됨

### IF Hilt DI 설정 (Implement)
1. Application 클래스에 `@HiltAndroidApp`
2. Activity에 `@AndroidEntryPoint`
3. Module 정의:
   ```kotlin
   @Module @InstallIn(SingletonComponent::class)
   object AppModule {
       @Provides @Singleton
       fun provideRetrofit(): Retrofit = Retrofit.Builder().build()
   }
   ```
4. 주입: `@Inject constructor(private val repo: Repository)`
5. ViewModel: `@HiltViewModel class MyVM @Inject constructor(repo: Repo) : ViewModel()`

### IF 코드 리뷰 (Review)
- [ ] `registerForActivityResult()`가 `onCreate()` 이전에 등록되는가
- [ ] 메인 스레드에서 네트워크/IO 호출 없는가 (NetworkOnMainThreadException)
- [ ] `result.success()`/`result.error()` 반드시 호출되는가 (MethodChannel 응답 누락 확인)
- [ ] nullable 처리: `call.argument<String?>("key")`에서 null 대응
- [ ] 외부 앱 미설치 시 ActivityNotFoundException 핸들링
- [ ] coroutine 예외 처리: `try-catch` 또는 `CoroutineExceptionHandler`
- [ ] `catch(e: Exception)`에서 `CancellationException` 재throw 하는가
- [ ] `GlobalScope.launch` 사용하지 않는가
- [ ] `!!` 사용 최소화 — `requireNotNull` 또는 `?:` 대체
- [ ] data class에 비밀번호/토큰 필드 → `toString()` 오버라이드 필수
- [ ] `remember` 빠뜨린 `mutableStateOf()` 없는가 (Compose)

## 가이드

> Flutter↔Android bridge 패턴 (`FlutterPlugin` + `ActivityResultListener` + `ActivityAware`)은 본 스킬이 다루지 않습니다. flutter/3.x/flutter-native.md (Android host 섹션) 또는 flutter/3.x/platform-channels-pigeon-and-plugins.md 를 참조하세요. 이 스킬은 순수 Android (Activity/Fragment/Compose/Coroutine/Hilt) 만 다룹니다.

**실습 패턴 (FlutterActivity + 함수 타입 주입)** — 회사 프로젝트가 FlutterActivity를 상속하는 경우 Android 측 lifecycle ownership을 명시하기 위한 참조 패턴:
```kotlin
class MainActivity : FlutterActivity() {
    companion object { const val PAYMENT_REQUEST_CODE = 9001 }
    private lateinit var channelHandler: PaymentChannelHandler

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        channelHandler = PaymentChannelHandler(this) { intent ->
            @Suppress("DEPRECATION")
            startActivityForResult(intent, PAYMENT_REQUEST_CODE)
        }
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL_NAME)
            .setMethodCallHandler(channelHandler)
    }

    @Suppress("DEPRECATION")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == PAYMENT_REQUEST_CODE) {
            channelHandler.handleActivityResult(resultCode, data)
        }
    }
}
```

### Kotlin 타입 ↔ MethodChannel 타입 매핑
| Kotlin | Dart | 비고 |
|--------|------|------|
| Int | int | 범위 주의 (Kotlin Int = 32bit) |
| Long | int | Dart int는 64bit, Kotlin Long도 64bit |
| String? | String? | nullable 양쪽 동일 |
| HashMap<String, Any?> | Map<String, dynamic> | 가장 안전한 전달 방식 |
| ByteArray | Uint8List | 바이너리 데이터 |

### Coroutine 구조적 동시성 패턴

**병렬 실행 + 결과 합치기**:
```kotlin
suspend fun loadDashboard(): Dashboard = coroutineScope {
    val user = async { userRepo.getUser() }
    val orders = async { orderRepo.getOrders() }
    Dashboard(user.await(), orders.await())  // 하나 실패 → 둘 다 취소
}
```

**예외 처리 — CancellationException 주의**:
```kotlin
viewModelScope.launch {
    try {
        val result = apiCall()
    } catch (e: CancellationException) {
        throw e  // 반드시 재throw! 먹으면 코루틴 취소 불가
    } catch (e: Exception) {
        _state.value = UiState.Error(e.message)
    }
}
```

**타임아웃**:
```kotlin
val result = withTimeoutOrNull(5000L) { slowApiCall() }
    ?: fallbackValue
```

### Kotlin Idioms 치트시트

**스코프 함수 선택**:
| 함수 | receiver | 반환 | 용도 |
|------|----------|------|------|
| `let` | `it` | 람다 결과 | null 체크 `x?.let { }`, 값 변환 |
| `run` | `this` | 람다 결과 | 객체 설정 + 결과 계산 |
| `with` | `this` | 람다 결과 | 기존 객체에 여러 호출 |
| `apply` | `this` | 자기 자신 | 객체 빌더/설정 |
| `also` | `it` | 자기 자신 | 부수 효과 (로그, 체크) |

**lateinit vs nullable vs by lazy**:
| 선택 | 언제 |
|------|------|
| `var x: T` (non-null, 바로 할당) | 가능하면 최선 |
| `lateinit var x: T` | DI 주입, `@BeforeEach` 초기화. 원시 타입 불가 |
| `var x: T? = null` | 정말 "없을 수 있는" 의미 |
| `val x: T by lazy { }` | 최초 접근 시 계산. 스레드 안전(기본) |
| `val x by Delegates.notNull<T>()` | lateinit 안 되는 원시 타입 |

**data class를 JPA 엔티티로 쓰지 말 것**:
- equals/hashCode가 모든 필드 기반 → JPA 프록시 충돌
- `copy()`가 영속성 컨텍스트와 어긋남
- `toString()`이 지연 로딩 접근 → N+1 유발
- **권장**: 일반 class + `kotlin-jpa` + `kotlin-allopen` 플러그인

### 컬렉션 성능

**List vs Sequence**:
- Sequence 이득: 원소 수천+, 연산 3단계+, `take(n)`/`first{}` 조기종료 가능
- List가 나음: 원소 수십~수백, 연산 1~2단계, 결과 여러 번 순회
```kotlin
// 좋음: 조기 종료로 이득
val first = names.asSequence()
    .filter { it.startsWith("A") }
    .map { it.uppercase() }
    .firstOrNull { it.length > 10 }

// 불필요: 단순 파이프라인
val result = list.asSequence().map { it.trim() }.toList()  // ← 오버헤드만
```

### Android 테스트 패턴 (Kotest + MockK)

```kotlin
// MockK 기본
val mockRepo = mockk<PaymentRepository>()
every { mockRepo.getPayment(any()) } returns Payment(id = 1)
coEvery { mockRepo.save(any()) } returns Unit  // suspend 함수는 coEvery

// Kotest + CoroutineTest
class PaymentViewModelTest : FunSpec({
    test("결제 성공 시 Success 상태로 전이") {
        val repo = mockk<PaymentRepository>()
        coEvery { repo.processPayment(any()) } returns PaymentResult.Success
        val vm = PaymentViewModel(repo)
        vm.pay(1000)
        vm.state.value shouldBe PaymentState.Success
    }
})
```

### 보안 패턴

**data class 필드 노출 방지**:
```kotlin
data class UserToken(val userId: Long, val token: String) {
    override fun toString() = "UserToken(userId=$userId, token=***)"  // 로그 노출 방지
}
```

**value class로 타입 안전 ID**:
```kotlin
@JvmInline value class BearerToken(val value: String) {
    init { require(value.isNotBlank()) }
    override fun toString() = "BearerToken(***)"
}
```

**코루틴 SecurityContext 전파**:
코루틴은 스레드 전환 → `ThreadLocal` 기반 `SecurityContextHolder` 유실됨. `ThreadContextElement` 구현 또는 Spring Security 6.x 코루틴 지원 사용.

## Gotchas

### pendingResult 누수 — 가장 흔한 MethodChannel 버그
외부 앱 호출 후 사용자가 뒤로가기로 돌아오면 `onActivityResult`가 `RESULT_CANCELED`로 호출됨. 이때 `pendingResult?.error()`를 호출하지 않으면 Flutter 측 Future가 영원히 resolve되지 않아 UI가 멈춤. **모든 경로에서 반드시 result.success/error 호출 후 null 초기화.**

### FlutterActivity에서 registerForActivityResult 사용 불가
FlutterActivity는 `ActivityResultCaller`를 구현하지 않아 `registerForActivityResult()`가 컴파일 에러. **deprecated `startActivityForResult()` + `onActivityResult()` 오버라이드 방식을 사용.** Handler를 함수 타입 `(Intent) -> Unit`으로 받는 패턴이 안정적.

### registerForActivityResult 타이밍 — Fragment에서 주의
`onCreateView()` 안에서 호출하면 Fragment 재생성 시 `IllegalStateException`. 반드시 클래스 프로퍼티로 선언하거나 `onCreate()` 내에서 등록.

### Kotlin Long vs Java int 매핑 혼동
MethodChannel에서 Dart `int` → Kotlin으로 올 때 값이 작으면 `Int`, 크면 `Long`으로 전달됨. **금액 필드는 `call.argument<Number>("amount")?.toLong()`으로 안전 변환.**

### configureFlutterEngine 미호출
`FlutterActivity` 상속 시 `super.configureFlutterEngine()` 빠뜨리면 검은 화면. override 시 반드시 `super` 호출.

### ANR (Application Not Responding)
MethodChannel 핸들러 내에서 동기적으로 무거운 작업 → 5초 넘으면 ANR. `CoroutineScope(Dispatchers.IO).launch` 사용 후 `withContext(Dispatchers.Main) { result.success(...) }`.

### FlutterPlugin의 onDetachedFromActivity — activity null 방지
`onDetachedFromActivity()` 호출 후 `activity` null. 결제 요청 오면 NO_ACTIVITY 에러 반환 + early return.

### HashMap<String, String>으로 Intent 데이터 전달
실제 VAN 앱: `putExtra("hashMap", HashMap<String, String>)` 통째 전달. `getSerializableExtra("hashMap")` + `@Suppress("UNCHECKED_CAST") as? HashMap<String, String>`.

### catch(e: Exception)에서 CancellationException 먹기
코루틴에서 `catch(e: Exception)`이 `CancellationException`까지 잡아버리면 구조적 동시성 파괴. **반드시 재throw** 하거나 `catch(e: Exception) { if (e is CancellationException) throw e; ... }`.

### `!!` 남발 — Java 자동 변환 후 주의
IDE의 Java→Kotlin 변환 후 `!!`가 많이 생김. `requireNotNull()` (비즈니스적 non-null 보장) 또는 `?:` (기본값) 또는 `?.let {}` (null이면 스킵)으로 대체.

### object 싱글톤에 mutable state
`object`에 `var` → 동시성 지옥. `ConcurrentHashMap`, `AtomicReference`, 또는 Spring Bean으로 관리.
