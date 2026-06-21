---
name: coroutines-cancellation-supervision-and-timeout-contracts
description: Kotlin 코루틴의 취소(cancellation)·감독(supervision)·timeout 계약을 라인 코드로 강제하는 베이스라인.
keywords: kotlin coroutine cancellation supervision timeout structured-concurrency CancellationException SupervisorJob withTimeout NonCancellable runInterruptible cooperative ensureActive yield isActive 코루틴 취소 감독 타임아웃 구조적동시성
intent: 만들어 추가해 구현해 수정해 검증해 리팩터 디버그
paths: lib/src/ src/main/kotlin app/src/main/kotlin shared/src/commonMain/kotlin
patterns: CancellationException SupervisorJob supervisorScope coroutineScope withTimeout withTimeoutOrNull NonCancellable runInterruptible ensureActive yield isActive Job.cancel CoroutineExceptionHandler
requires:
phase: plan implement review debug
tech-stack: kotlin
min_score: 2
---

# Kotlin Coroutine Cancellation, Supervision, Timeout Contracts

Kotlin 코루틴은 "취소 가능한 비동기 단위"를 다룬다. 같은 `launch` 코드가 한 곳에서 잘 동작하다가 다른 곳에서 영원히 매달리는 가장 흔한 이유는 **취소·감독·timeout 계약을 라인 단위로 명시하지 않아서**다. 이 스킬은 그 세 계약을 코드 라인 수준에서 강제한다.

## 의사결정 트리

### IF 새 코루틴 시작 (Plan / Implement)
1. **소유 스코프 정의**: `viewModelScope`, `lifecycleScope`, 사용자 정의 `CoroutineScope(SupervisorJob() + Dispatchers.Default)` 중 하나. 소유자 없는 `GlobalScope.launch` 금지.
2. **빌더 선택**: 결과가 필요하면 `async`, 없으면 `launch`. `async`를 "장식"으로 쓰지 않는다.
3. **자식 실패 정책**: 형제까지 같이 죽어야 → `coroutineScope` (Job). 한 형제 실패가 다른 형제에 전파되면 안 됨 → `supervisorScope` (SupervisorJob).
4. **dispatcher 명시**: IO는 `Dispatchers.IO`, CPU는 `Dispatchers.Default`, UI는 `Dispatchers.Main`. 빈 `launch { ... }`는 부모 컨텍스트 상속 — 의도가 맞는지 확인.

### IF 장기 실행 / 루프 / CPU-bound 작업 (Implement)
1. 루프 내 **suspend 호출 없으면** 취소 무시됨. `coroutineContext.ensureActive()`, `yield()`, 또는 `if (!isActive) return` 삽입.
2. 블로킹 JVM 호출 (`Thread.sleep`, `BlockingQueue.take`, JDBC) → `runInterruptible { ... }`로 감싸야 cancel 시 `Thread.interrupt`로 끊김.
3. 루프 종료 시 자원 정리는 `try { ... } finally { ... }` — finally 안에서 suspend가 필요하면 `withContext(NonCancellable) { ... }`로만 좁게 감쌈.

### IF 예외 처리 (Implement)
1. **`CancellationException`은 절대 먹지 않는다**. `catch(e: Exception)`로 잡으면 의도치 않게 흡수됨 — 다음 패턴 강제:
   ```kotlin
   try { ... } catch (e: Exception) {
       if (e is CancellationException) throw e
       handle(e)
   }
   ```
   또는 명시적 `catch(e: CancellationException) { throw e }` 다음에 `catch(e: Exception)`.
2. supervisorScope에서는 자식 실패가 부모로 전파 안 됨 → 자식 launch마다 자체 `try-catch` 필수.
3. 최상위 비동기 작업에는 `CoroutineExceptionHandler`로 uncaught 잡아 로그.

### IF Timeout 적용 (Implement)
1. **실패가 정상 흐름** → `withTimeoutOrNull(2.seconds) { ... }` (null 반환 → fallback).
2. **실패가 에러 흐름** → `withTimeout(2.seconds) { ... }` (`TimeoutCancellationException` 발생 → 호출자에 전파).
3. timeout 단위는 `kotlin.time.Duration` (`5.seconds`, `200.milliseconds`) — `Long` 밀리초 리터럴은 단위 모호.
4. timeout 내부에서 catch all 패턴은 `TimeoutCancellationException` (= `CancellationException` 하위)을 먹을 수 있으니 위 1번 패턴 유지.

### IF 취소 후 정리 (Implement)
1. 정리 코드가 suspend 안 함 → `try-finally`만으로 충분.
2. 정리 코드가 suspend 함 → `withContext(NonCancellable) { cleanup() }`. 이 블록은 짧게.
3. **금지**: `launch(NonCancellable) { ... }` 또는 `async(NonCancellable) { ... }` — 구조적 동시성 깨짐. 공식 문서가 명시적으로 경고.

### IF 코드 리뷰 (Review)
- [ ] 모든 `launch`/`async`에 명시적 스코프가 있는가 (`GlobalScope` 없는가)
- [ ] CPU 루프에 `ensureActive()`/`yield()` 또는 자연스러운 suspend 지점이 있는가
- [ ] `catch(Exception)` 위에 `CancellationException` 재throw 가드가 있는가
- [ ] 블로킹 JVM 호출이 `runInterruptible`로 감싸졌는가
- [ ] `withTimeout` vs `withTimeoutOrNull` 선택이 호출자 계약과 일치하는가
- [ ] `NonCancellable`이 cleanup 외 builder에 쓰이지 않는가
- [ ] `async`인데 `await()` 안 부르는 곳 없는가 (예외 누락 위험)

## 핵심 패턴

### 형제 격리 (supervisorScope)
한 자식 실패가 다른 자식에 영향을 주면 안 될 때 (예: 대시보드의 위젯 N개 병렬 로딩):
```kotlin
suspend fun loadDashboardWidgets(): List<WidgetState> = supervisorScope {
    listOf(
        async { runCatching { widgetA() } },
        async { runCatching { widgetB() } },
        async { runCatching { widgetC() } },
    ).map { it.await().getOrElse { WidgetState.Error(it) } }
}
```
반대로 `coroutineScope`는 한 자식 실패 → 형제·부모 모두 취소. 사용 의도를 명시적으로.

### 협력적 취소 (cooperative cancellation)
```kotlin
suspend fun expensiveSort(data: MutableList<Int>) = withContext(Dispatchers.Default) {
    while (true) {
        coroutineContext.ensureActive()   // 취소 체크 — suspend 함수 아님
        data.sort()
    }
}
```
`isActive` 체크 + 그냥 return 도 가능. 차이: `ensureActive`는 throw, `isActive`는 boolean.

### 블로킹 JVM 호출 인터럽트
```kotlin
suspend fun readJdbc(): Row = runInterruptible(Dispatchers.IO) {
    connection.prepareStatement("SELECT 1").executeQuery()
}
```
`runInterruptible` 없으면 `cancel()` 해도 JDBC 호출이 끝날 때까지 대기.

### Timeout 두 가지 계약
```kotlin
// 정상 흐름: null fallback
val data = withTimeoutOrNull(2.seconds) { fetchSlow() } ?: emptyList()

// 에러 흐름: 호출자로 전파
val data = withTimeout(2.seconds) { fetchSlow() }   // TimeoutCancellationException
```

### NonCancellable 좁게
```kotlin
suspend fun closeStream(stream: Stream) {
    try {
        stream.process()
    } finally {
        withContext(NonCancellable) {
            stream.flushAsync()      // 취소돼도 flush는 끝까지
            stream.closeAsync()
        }
    }
}
```

### CancellationException 재throw 가드
```kotlin
suspend fun withRetry(block: suspend () -> T): T {
    repeat(3) {
        try {
            return block()
        } catch (e: CancellationException) {
            throw e                          // 1번 — 가장 먼저
        } catch (e: Exception) {
            log.warn("retry", e)
        }
    }
    return block()
}
```

## Gotchas

### `catch(e: Exception)`이 `CancellationException`을 흡수
가장 흔한 버그. 코루틴이 취소돼도 catch가 받아 정상 흐름으로 진행 → 외부 스코프는 "끝났겠지" 하는데 자식이 살아있어 ANR / 메모리 누수. **재throw 가드 필수.**

### `launch(NonCancellable)` 또는 `async(NonCancellable)`
공식 문서가 명시적으로 금지하는 패턴. `NonCancellable`은 `withContext`의 cleanup 섹션에서만 쓴다. builder에 쓰면 부모 cancel이 자식에 전파 안 돼 구조적 동시성 파괴.

### `GlobalScope.launch`
부모가 없어 어디서도 cancel 불가. 라이프사이클 무시. 라이브러리 내부 데몬 외에는 전부 안티패턴.

### `runBlocking`을 일반 비즈니스 로직에 사용
스레드 잡고 대기 → 메인/UI 스레드면 ANR. 공식 가이드: `runBlocking`은 "non-suspending API에서 suspending으로 다리 놓는 edge"에서만.

### CPU 루프에 suspend point 없음
취소 신호는 suspend 지점에서만 검사됨. `for (i in 1..1_000_000) { compute(i) }`는 cancel 무시. `ensureActive()` / `yield()` 삽입.

### `async`인데 `await()` 안 함
async가 던진 예외는 await 호출 시점에야 표면화. await 안 부르고 자식이 끝나기를 기다리면 예외가 부모 Job으로만 전파되거나 silently 사라질 수 있음. **결과 안 쓸 거면 `launch`.**

### `JDBC`/`Thread.sleep`/`InputStream.read` 가 cancel 무시
이들은 InterruptedException으로만 끊긴다. `runInterruptible`로 감싸야 코루틴 cancel이 인터럽트로 변환됨.

### `withTimeout(0)` 또는 음수 timeout
즉시 `TimeoutCancellationException` 발생. fallback 없는 호출자에게 의도치 않은 실패. `Duration` 검증 후 호출.

### Dispatcher 미명시 + IO 호출
부모가 `Dispatchers.Main`이면 IO 호출이 메인에서 실행돼 ANR. **IO 작업은 항상 `withContext(Dispatchers.IO) { ... }` 또는 `flowOn(Dispatchers.IO)`.**

### `coroutineScope` vs `supervisorScope` 혼동
"한 자식 실패해도 나머지는 살리고 싶다" → `supervisorScope`. 이걸 `coroutineScope`로 쓰면 첫 실패에서 형제 모두 취소.

## 검증 체크리스트

- 모든 launch/async가 명시적 owner scope를 가진다
- CPU 루프에 suspend point 또는 ensureActive 있다
- catch(Exception) 위에 CancellationException 재throw 가드 있다
- 블로킹 호출이 runInterruptible로 감싸져 있다
- timeout 사용 시 withTimeout vs withTimeoutOrNull 선택이 호출자 계약과 맞다
- NonCancellable이 cleanup 외 builder에 안 쓰인다
- supervisorScope vs coroutineScope 선택이 격리 의도와 맞다

## 5축 자가 평가

- 검색성(keywords/intent/patterns 다층): 코루틴/cancellation/supervision/timeout 한·영 키워드 + 코드 식별자 패턴
- 의사결정 트리(IF/THEN): 6개 IF 분기 + 리뷰 체크리스트
- 코드 식별자(actual class/method names): CancellationException, SupervisorJob, supervisorScope, coroutineScope, withTimeout, withTimeoutOrNull, NonCancellable, runInterruptible, ensureActive, yield, isActive, CoroutineExceptionHandler
- Gotcha-driven: 9개 흔한 실수 + 회피
- 검증 가능: 7개 체크리스트
