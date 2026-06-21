---
keywords: flutter 3 mvvm viewmodel repository service provider changenotifier listenable command pattern di state management rebuild const widget riverpod bloc
intent: 앱구조설계 mvvm 분리 viewmodel repository service di provider 상태경계 rebuild 줄이기 const 생성자
paths: lib/src/features/ lib/src/data/ lib/src/app/
patterns: ChangeNotifier notifyListeners ListenableBuilder Provider MultiProvider context.read context.watch const ValueNotifier
requires: flutter
phase: design implement review
tech-stack: flutter
min_score: 3
---

# Flutter 3.x App Architecture + State Boundary + Rebuild Habits

> 핵심 원칙 (공식 docs 기반): **views render, view models decide, repositories own data, services wrap I/O**. 한 view = 한 view model. 위젯이 비즈니스 로직을 가지면 boundary가 잘못된 것.

## 의사결정 트리

### IF 새 feature 추가 (Design)
1. **레이어 결정**:
   - View (Widget) — render + 사용자 이벤트 forward
   - ViewModel (`ChangeNotifier`) — UI state 보관 + transition 명령
   - Repository — 데이터 source of truth (캐시/재시도/변환)
   - Service — 외부 API/플랫폼 어댑터 (얇게 유지)
2. **DI**: `MultiProvider`로 root에서 Repository/Service 제공
3. **state lib 선택**: 팀 표준 따르기 — provider+ChangeNotifier, Riverpod, Bloc 모두 가능. **하나만 일관되게**
4. **optional domain layer**: 다중 repository 조합 / 복잡한 도메인 룰 있을 때만 추가

### IF 비동기 작업 (Implement) — Command 패턴
1. ViewModel에 `submit/load/...` 메서드
2. 진입 시 `loading=true; error=null; notifyListeners()`
3. await 작업 후 결과 반영
4. finally에서 `loading=false; notifyListeners()`
5. Widget은 결과 상태만 읽음 — async 진행 로직을 widget에 안 두기

### IF rebuild이 잦음 (Review)
1. `Selector` 또는 `context.select()`로 의존 좁히기
2. ValueNotifier + `ValueListenableBuilder` — 일부 값만 변할 때
3. `const` 생성자 가능한 곳 전부 `const`
4. helper method 대신 sub-widget으로 분리 → const 적용 + rebuild 격리
5. 큰 list는 `ListView.builder` + virtualization

## 핵심 패턴

### 폴더 구조 (공식 가이드 정렬)
```
lib/
└── src/
    ├── app/
    │   ├── app.dart
    │   ├── routes/
    │   └── di/
    ├── features/
    │   └── auth/
    │       ├── view/         ← Widget (LoginScreen)
    │       ├── view_model/   ← LoginViewModel : ChangeNotifier
    │       └── widgets/      ← feature 내부 위젯
    ├── data/
    │   ├── repositories/     ← AuthRepository (interface + impl)
    │   └── services/         ← ApiClient, SecureStorage
    └── shared/
        ├── models/           ← User, Order (data class)
        └── widgets/          ← 앱 전반 공통 위젯
test/
├── unit/
├── widget/
└── golden/
integration_test/
```

### ViewModel + Command
```dart
// features/auth/view_model/login_view_model.dart
import 'package:flutter/foundation.dart';

class LoginViewModel extends ChangeNotifier {
  LoginViewModel(this._authRepository);

  final AuthRepository _authRepository;

  bool _isSubmitting = false;
  bool get isSubmitting => _isSubmitting;

  String? _errorMessage;
  String? get errorMessage => _errorMessage;

  Future<bool> submit({required String email, required String password}) async {
    _isSubmitting = true;
    _errorMessage = null;
    notifyListeners();

    try {
      await _authRepository.signIn(email: email, password: password);
      return true;
    } on AuthException catch (e) {
      _errorMessage = e.userMessage;
      return false;
    } catch (_) {
      _errorMessage = '알 수 없는 오류가 발생했습니다';
      return false;
    } finally {
      _isSubmitting = false;
      notifyListeners();
    }
  }
}
```

### Repository (interface + impl 분리 → 테스트 용이)
```dart
// data/repositories/auth_repository.dart
abstract interface class AuthRepository {
  Future<void> signIn({required String email, required String password});
  Future<void> signOut();
}

// data/repositories/auth_repository_remote.dart
class AuthRepositoryRemote implements AuthRepository {
  AuthRepositoryRemote(this._api, this._storage);
  final ApiClient _api;
  final SecureStorage _storage;

  @override
  Future<void> signIn({required String email, required String password}) async {
    final res = await _api.post('/auth/login', body: {'email': email, 'password': password});
    await _storage.write('token', res.data['token'] as String);
  }

  @override
  Future<void> signOut() async {
    await _storage.delete('token');
  }
}
```

### DI (Provider, root)
```dart
// app/app.dart
class App extends StatelessWidget {
  const App({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        Provider<ApiClient>(create: (_) => ApiClient.create()),
        Provider<SecureStorage>(create: (_) => SecureStorage()),
        ProxyProvider2<ApiClient, SecureStorage, AuthRepository>(
          update: (_, api, storage, __) => AuthRepositoryRemote(api, storage),
        ),
      ],
      child: const MaterialApp(home: HomeScreen()),
    );
  }
}
```

### View — read viewmodel, no business logic
```dart
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  late final LoginViewModel _vm;

  @override
  void initState() {
    super.initState();
    _vm = LoginViewModel(context.read<AuthRepository>());
  }

  @override
  void dispose() {
    _vm.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider.value(
      value: _vm,
      child: Scaffold(
        body: Consumer<LoginViewModel>(
          builder: (context, vm, _) => Column(
            children: [
              if (vm.errorMessage != null) Text(vm.errorMessage!),
              ElevatedButton(
                onPressed: vm.isSubmitting
                    ? null
                    : () => vm.submit(email: 'a@b.c', password: 'pw'),
                child: vm.isSubmitting
                    ? const CircularProgressIndicator()
                    : const Text('로그인'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
```

### Selector — 좁은 rebuild
```dart
// 전체 vm이 아니라 isSubmitting 만 listen
Selector<LoginViewModel, bool>(
  selector: (_, vm) => vm.isSubmitting,
  builder: (_, isSubmitting, __) => isSubmitting
      ? const CircularProgressIndicator()
      : const Text('대기'),
)
```

## State boundary 매트릭스

| 상태 종류 | 위치 |
|---|---|
| 폼 입력 (email, password) | StatefulWidget의 local state 또는 ViewModel |
| 단일 화면 UI (로딩/에러) | feature ViewModel (`ChangeNotifier`) |
| feature 간 공유 (auth user) | App-scope Provider + ViewModel/Repository |
| 영속 데이터 캐시 | Repository (Hive/Isar/SQLite + 메모리 캐시) |
| 외부 I/O (HTTP/storage) | Service (얇게) |
| 라우팅 상태 | go_router state, ViewModel에 복제 X |

## Rebuild 습관

1. **`const` 강제**: lints에 `prefer_const_constructors` 켜기
2. **helper method보다 sub-widget**: `Widget _buildHeader()` 대신 별도 `class _Header extends StatelessWidget` → `const _Header()` 가능, rebuild 격리
3. **`Consumer`/`Selector` 가장 안쪽으로**: build 트리 위쪽에 두면 자식 전부 rebuild
4. **`ValueListenableBuilder` 활용**: 단일 값 listen일 때 ChangeNotifier보다 가벼움
5. **list는 builder**: `Column(children: [...])` 대신 `ListView.builder`

## 5축 품질 체크

| 축 | 체크 |
|---|---|
| 정확성 | view에서 repository 직접 접근 없는가 (one-view-one-viewmodel) |
| 안전성 | ViewModel `dispose`에서 `super.dispose()` 호출 / async 작업 cancel 고려했는가 |
| 성능 | `const` 적용 + helper method 대신 sub-widget으로 분리됐는가 |
| 가독성 | 폴더 구조가 features/data/shared로 명확히 갈렸는가 |
| 검증성 | ViewModel + Repository에 unit test, View에 widget test가 있는가 |

## Gotchas

### Widget이 직접 Repository 호출
one-view-one-viewmodel 깨짐. async 흐름을 widget setState로 처리하면 retry/cache 로직이 widget 트리에 흩뿌려짐. ViewModel에 모으기.

### `ChangeNotifier`를 mutable bag으로
`vm.user = newUser`처럼 raw setter 노출 → 어디서 변하는지 추적 불가. 의도된 transition 메서드만 노출 (`signIn`, `signOut`, `refresh`).

### `notifyListeners()` 호출 누락
state는 바뀌었는데 UI가 안 변함. async finally에서 항상 호출 보장.

### `dispose()` 누락
ViewModel을 StatefulWidget이 만들면 dispose에서 정리 필수. 안 하면 listener 누수 + setState on disposed.

### Provider 위치를 페이지마다 흩뿌림
Repository/Service는 root MultiProvider, feature ViewModel은 feature route에서 생성. 섞이면 의존 추적 불가.

### helper method가 const 못 됨
`Widget _buildCard()`는 호출될 때마다 새 위젯 생성 → 조부모 rebuild 시 자식 전부 rebuild. sub-widget class로 분리하면 `const` 적용 가능.

### setState 남발로 list 전체 rebuild
list 한 줄 바뀌어도 list 전체 rebuild. ChangeNotifier per item 또는 unique key + `ListView.builder` 패턴.

### 한 패키지에 여러 state 라이브러리 혼용
provider + Riverpod + Bloc 섞이면 mental model 폭발. 팀에서 하나 표준화. mock/test 패턴도 단일화.

## 도구 사용 패턴 (Harness)
- one-view-one-viewmodel 검증: `Grep("context\\.(read|watch)<.*Repository>", path="lib/src/features/.*/view")` → view에서 repository 직접 접근 탐지
- notifyListeners 누락: `Grep("notifyListeners", glob="lib/**/view_model/*.dart")`
- const 미사용 위젯: `flutter analyze` 출력의 `prefer_const_constructors`
- dispose 누락: `Grep("class.*ViewModel.*ChangeNotifier", glob="lib/**/view_model/*.dart")` 후 같은 파일에 `dispose` 메서드 확인

## Related (신규 그래프 cross-ref)

app-architecture-and-state가 결합되는 신규 노드:
- `kotlin/android/circuit-unidirectional-architecture.md` — Slack Circuit Screen/Presenter/Ui 분리 (Flutter feature/data/domain 정신과 동일)
- `kotlin/android/coroutines-flow-viewmodel-and-compose-state-boundaries.md` — Android ViewModel + StateFlow + collectAsStateWithLifecycle (Flutter ViewModel + ChangeNotifier 동등)
- `_common/idempotency.md` — Repository layer의 retry 안전성 (HTTP idempotency-key)
- `_common/api-contracts.md` — Repository → API 계약 (REST vs GraphQL 결정)
- `kotlin/android/graphql-apollo-android.md` — Android GraphQL 클라이언트 (Flutter GraphQL 채택 시 패턴 참조)
