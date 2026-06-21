---
keywords: dart 다트 flutter 플러터 riverpod bloc state 상태관리 gorouter navigation 네비게이션 dio freezed retrofit widget stateful stateless consumer architecture 아키텍처 clean feature provider async stream future
intent: 만들어 추가해 구현해 수정해 화면 페이지 라우팅 상태 API호출 모델
paths: lib/ lib/src lib/features lib/pages lib/widgets lib/providers lib/models lib/services lib/core
patterns: ConsumerWidget StatefulWidget StatelessWidget Riverpod Provider GoRouter StatefulShellRoute AsyncValue AsyncNotifier Dio Freezed Retrofit ChangeNotifier BlocBuilder
phase: plan implement review debug
min_score: 3
---

# Flutter + Dart 앱 개발

## 의사결정 트리

### IF 상태관리 선택 (Plan)
| 기준 | Riverpod | Bloc | Provider |
|------|----------|------|----------|
| 공식 추천 | 2026 표준 | 대규모 팀 | 레거시 |
| 러닝커브 | 중간 | 높음 | 낮음 |
| 보일러플레이트 | 코드생성으로 최소 | Event+State 많음 | 적음 |
| 테스트 | ProviderContainer.overrides | bloc_test 선언적 | 어려움 |
| 서버 상태 | AsyncNotifier 내장 | 별도 구현 | 없음 |

**결론**: 신규 프로젝트 → **Riverpod** (코드생성 방식). 대규모 팀/엄격한 패턴 → Bloc. GetX → **사용 금지** (전역 싱글톤, 테스트 불가).

### IF Riverpod 프로바이더 타입 선택 (Plan)
```
동기 값 (설정, 계산)     → @riverpod Type func(ref) => value;
비동기 값 (API 1회)      → @riverpod Future<Type> func(ref) async => await api();
스트림 (실시간)           → @riverpod Stream<Type> func(ref) => stream;
상태 + 메서드 (CRUD)     → @riverpod class Name extends _$Name { 
                              Type build() => 초기값;
                              void method() { state = newState; }
                           }
비동기 상태 + 메서드      → @riverpod class Name extends _$Name {
                              Future<Type> build() async => await load();
                              Future<void> add(item) async {
                                state = const AsyncValue.loading();
                                state = await AsyncValue.guard(() => save(item));
                              }
                           }
```

**ref 사용 규칙** ("build=watch, 콜백=read, 사이드이펙트=listen"):
- `ref.watch(provider)` — build 메서드 안에서 (반응형 리빌드)
- `ref.read(provider)` — 이벤트 핸들러/콜백 안에서 (1회 읽기)
- `ref.listen(provider, callback)` — 사이드이펙트 (Toast, Navigation)

### IF go_router 네비게이션 설정 (Implement)
1. 기본 라우팅:
   ```dart
   final router = GoRouter(routes: [
     GoRoute(path: '/', builder: (_, __) => HomeScreen()),
     GoRoute(path: '/product/:id', builder: (_, state) {
       final id = state.pathParameters['id']!;
       return ProductScreen(id: id);
     }),
   ]);
   ```
2. `context.go('/path')` — URL 교체 (뒤로가기 시 이전 URL)
3. `context.push('/path')` — 스택 쌓기 (뒤로가기 시 pop)
4. 탭 네비게이션 — `StatefulShellRoute.indexedStack` (탭별 독립 Navigator 유지)
5. 인증 가드:
   ```dart
   GoRouter(redirect: (context, state) {
     final isLoggedIn = ref.read(authProvider);
     if (!isLoggedIn && state.matchedLocation != '/login') return '/login';
     return null;  // null = 리다이렉트 안 함
   }, refreshListenable: authNotifier);
   ```

### IF HTTP 통신 설계 (Implement)
1. **dio + retrofit + freezed** 조합 (2026 표준):
   ```dart
   // 모델 (freezed)
   @freezed class Product with _$Product {
     factory Product({required int id, required String name, required int price}) = _Product;
     factory Product.fromJson(Map<String, dynamic> json) => _$ProductFromJson(json);
   }
   
   // API 인터페이스 (retrofit)
   @RestApi(baseUrl: 'https://api.example.com')
   abstract class ProductApi {
     factory ProductApi(Dio dio) = _ProductApi;
     @GET('/products') Future<List<Product>> getProducts();
     @GET('/products/{id}') Future<Product> getProduct(@Path() int id);
     @POST('/products') Future<Product> create(@Body() Product product);
   }
   ```
2. **dio 인터셉터 3종**:
   - `LogInterceptor` — kDebugMode에서만
   - 인증 헤더 주입 — `options.headers['Authorization'] = 'Bearer $token'`
   - 토큰 리프레시 — `QueuedInterceptorsWrapper` (동시 401 한번만 refresh)
3. **주의**: 토큰 리프레시 시 **refresh 전용 별도 Dio 인스턴스** 필수 (같은 인스턴스 쓰면 무한루프)

### IF 에러 처리 설계 (Plan)
```dart
// sealed class 에러 유니온
sealed class AppFailure {
  const AppFailure();
}
class NetworkFailure extends AppFailure { final String message; ... }
class ServerFailure extends AppFailure { final int statusCode; final String code; ... }
class AuthFailure extends AppFailure {}  // → 로그인 화면 이동 트리거

// dio 에러 → AppFailure 변환
AppFailure mapDioError(DioException e) => switch (e.type) {
  DioExceptionType.connectionTimeout => NetworkFailure('연결 시간 초과'),
  DioExceptionType.badResponse => ServerFailure(e.response?.statusCode ?? 500, ...),
  _ => NetworkFailure(e.message ?? '알 수 없는 에러'),
};
```

### IF 프로젝트 아키텍처 설계 (Plan)
**feature-first + Clean Architecture** (2026 표준):
```
lib/
├── core/              # 공통 (네트워크, 테마, 상수, 에러)
│   ├── network/       # DioProvider, 인터셉터
│   ├── theme/
│   └── error/         # AppFailure sealed class
├── features/
│   ├── auth/
│   │   ├── data/      # AuthRepository 구현체, DTO
│   │   ├── domain/    # AuthRepository 인터페이스, Entity
│   │   └── presentation/  # LoginScreen, AuthNotifier
│   ├── product/
│   │   ├── data/
│   │   ├── domain/
│   │   └── presentation/
│   └── payment/
├── shared/            # 공유 위젯 (커스텀 버튼, 다이얼로그)
└── main.dart
```

**의존성 방향**: presentation → domain ← data (domain은 아무것도 import 안 함)

**DTO ↔ 도메인 분리**:
```dart
extension ProductDtoMapper on ProductDto {
  Product toDomain() => Product(id: id, name: name, price: price);
}
```

### IF 코드 리뷰 (Review)
- [ ] `const` 위젯 사용했는가 (리빌드 비용 제로)
- [ ] `ListView.builder` 사용했는가 (children: [] 은 수십 개 넘으면 금지)
- [ ] `build()` 안에서 사이드이펙트 없는가 (API 호출, Navigation 금지)
- [ ] async 콜백에서 `mounted` 체크했는가 (BuildContext 수명 문제)
- [ ] `ref.watch`가 build 안에 있는가 (콜백에서 watch → 무한 리빌드)
- [ ] `ref.read`가 콜백/이벤트 핸들러 안에 있는가
- [ ] Image에 `cacheWidth`/`cacheHeight` 지정했는가 (메모리 최적화)
- [ ] `Expanded`/`Flexible`가 Row/Column 직계 자식인가
- [ ] `Column` 안에 `ListView` → unbounded height 에러 대응 (`Expanded`로 감싸기)

## 가이드

### Dart 언어 핵심 (백엔드 개발자용)

**var / final / const / late**:
- `var` = TS `let` (재할당 가능)
- `final` = Kotlin `val` (런타임 상수)
- `const` = 컴파일타임 상수 (**Flutter 성능 직결** — 동일 const는 공유)
- `late` = Kotlin `lateinit` (접근 시 미초기화면 런타임 예외)

**Sound Null Safety**: TS의 `any` 같은 구멍 없음. 런타임에서도 non-nullable에 null 불가.

**Dart 3.x Records + Pattern Matching**:
```dart
// Record (튜플)
(String, int) getNameAge() => ('Alice', 30);
final (name, age) = getNameAge();

// Sealed class + switch (exhaustive)
sealed class Result<T> {}
class Success<T> extends Result<T> { final T data; ... }
class Failure<T> extends Result<T> { final String message; ... }

final widget = switch (result) {
  Success(:final data) => Text('$data'),
  Failure(:final message) => Text('에러: $message'),
};
```

### Widget 라이프사이클
```
StatefulWidget:
  createState() → initState() → didChangeDependencies() → build()
  → [setState → build] (반복)
  → didUpdateWidget() (부모가 새 위젯 전달 시)
  → deactivate() → dispose()
```
- `initState()`: 1회 초기화 (컨트롤러 생성, 리스너 등록)
- `dispose()`: 리소스 해제 (**TextEditingController, AnimationController 반드시 dispose**)
- `didChangeDependencies()`: `InheritedWidget` 변경 시 (Theme, MediaQuery)

### AsyncValue 3상태 UI 패턴 (Riverpod)
```dart
class ProductsScreen extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final products = ref.watch(productsProvider);
    return products.when(
      data: (list) => ListView.builder(
        itemCount: list.length,
        itemBuilder: (_, i) => ProductTile(list[i]),
      ),
      loading: () => const CircularProgressIndicator(),
      error: (e, st) => Text('에러: $e'),
    );
  }
}
```

### 토큰 저장소 패턴
```dart
// flutter_secure_storage (iOS Keychain / Android EncryptedSharedPreferences)
final storage = FlutterSecureStorage(
  aOptions: AndroidOptions(encryptedSharedPreferences: true),
  iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock),
);
await storage.write(key: 'access_token', value: token);
final token = await storage.read(key: 'access_token');
```
- **shared_preferences**: 설정값 전용 (평문 저장, 토큰 금지)
- **flutter_secure_storage**: 토큰/비밀키 전용
- **drift**: 구조화된 데이터 (SQLite ORM, watch()→Stream 실시간 UI)

### 프로젝트 부트스트랩 표준 스택
```yaml
# pubspec.yaml 핵심 의존성
dependencies:
  flutter_riverpod: ^2.x
  riverpod_annotation: ^2.x
  go_router: ^14.x
  dio: ^5.x
  freezed_annotation: ^2.x
  json_annotation: ^4.x
  flutter_secure_storage: ^9.x
  gap: ^3.x               # SizedBox 대체

dev_dependencies:
  riverpod_generator: ^2.x
  build_runner: ^2.x
  freezed: ^2.x
  json_serializable: ^6.x
  retrofit_generator: ^8.x
  mocktail: ^1.x
```

빌드: `dart run build_runner watch -d` (백그라운드 코드생성)

## Gotchas

### const 위젯 안 쓰면 성능 손해
`const Text('Hello')`는 리빌드 비용 제로 (같은 인스턴스 재사용). `prefer_const` 린트 활성화 권장.

### ListView.builder 필수
`ListView(children: [Widget1(), Widget2(), ...])` — 수십 개 넘으면 모든 위젯을 한번에 생성. **`ListView.builder`로 lazy 생성**.

### build() 안에서 사이드이펙트 금지
```dart
// 잘못됨 — build에서 API 호출
Widget build(context) {
  fetchData();  // 매 리빌드마다 API 호출!
  return ...;
}
// 올바름 — initState 또는 LaunchedEffect
```

### async 콜백에서 BuildContext 사용
```dart
onPressed: () async {
  await someApi();
  if (!mounted) return;  // ← 필수 체크
  Navigator.of(context).pop();  // mounted 아니면 crash
}
```

### Column 안에 ListView = unbounded height 에러
```dart
// 잘못됨:
Column(children: [Header(), ListView()])  // RenderBox was not laid out
// 올바름:
Column(children: [Header(), Expanded(child: ListView())])
```

### Expanded/Flexible 위치 오류
`Expanded`는 **Row/Column의 직계 자식**이어야 함. 중간에 Container나 Padding으로 감싸면 에러.

### Hot Reload vs Hot Restart 혼동
- Hot Reload: Dart 코드만 갱신 (State 유지). **static 변수, initState 변경 반영 안 됨**
- Hot Restart: 전체 재시작 (State 초기화)
- MethodChannel 핸들러 변경 → **Hot Restart 필요**

### MediaQuery.sizeOf vs MediaQuery.of
`MediaQuery.of(context).size` → MediaQuery의 **모든** 속성 변경 시 리빌드. `MediaQuery.sizeOf(context)` → size 변경 시만 리빌드. 성능 차이 큼.

### Image.network 미캐시
`Image.network(url)`은 캐시 없음. **`CachedNetworkImage`** 패키지 사용. 대용량 이미지는 `cacheWidth`/`cacheHeight`로 디코딩 해상도 제한.

### Release 빌드 ProGuard/R8 이슈
Debug에서 잘 되던 게 Release에서 크래시 → ProGuard가 Flutter 엔진 클래스를 제거. `proguard-rules.pro`에 keep 규칙 추가 필요.

### dio 토큰 리프레시 무한루프
인증 인터셉터에서 401 → 리프레시 API 호출 → 이 호출도 같은 Dio 인스턴스 → 또 401 인터셉터 → 무한루프. **refresh 전용 별도 Dio 인스턴스** 생성 필수.
