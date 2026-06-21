---
name: activity-result-and-external-intent-contracts
description: Android Activity Result API + 외부 앱 Intent 계약을 라인 코드로 강제하는 베이스라인.
keywords: android activity result intent registerForActivityResult ActivityResultContract ActivityResultLauncher startActivityForResult onActivityResult ActivityNotFoundException ComponentName setClassName external app permission deeplink 외부앱 인텐트 결과
intent: 만들어 추가해 구현해 호출해 연동해 수정해
paths: app/src/main/kotlin app/src/main/java app/src/main/AndroidManifest.xml
patterns: registerForActivityResult ActivityResultContract ActivityResultContracts.StartActivityForResult ActivityResultLauncher Intent setClassName ComponentName startActivityForResult onActivityResult FlutterActivity ActivityResultListener PendingIntent
requires:
phase: plan implement review debug
tech-stack: kotlin
min_score: 2
---

# Android Activity Result API & External Intent Contracts

외부 앱 호출(결제, 카메라, 파일 선택 등)은 Android에서 가장 깨지기 쉬운 경계 중 하나다. **타이밍(언제 등록)**, **계약(어떤 Contract 사용)**, **누락 처리(앱 미설치/취소/시스템 종료)** 세 축에서 빠지면 화면이 멈추거나 ANR. 이 스킬은 그 셋을 라인 코드로 강제한다.

## 의사결정 트리

### IF Activity Result Launcher 등록 (Plan / Implement)
1. **모든 launcher는 `onCreate()` 또는 그 이전에 등록**. lazy/지연 등록 → `LifecycleOwners must call register before they are STARTED` IllegalStateException.
2. **Activity 프로퍼티 (`val xxx = registerForActivityResult(...)`)** 또는 `onCreate()` 내 등록.
3. Fragment에서는 클래스 프로퍼티로 선언 — `onCreateView` 안 등록 금지.
4. `FlutterActivity`는 `ActivityResultCaller` 구현 안 함 → registerForActivityResult 컴파일 에러. **deprecated `startActivityForResult` + `onActivityResult` 오버라이드** 사용.

### IF 표준 Contract 선택 (Implement)
1. **결과 boolean (Yes/No)** → `RequestPermission`, `TakePicture`(Bitmap 미반환).
2. **Bitmap thumbnail** → `TakePicturePreview`.
3. **임의 Intent + 결과** → `StartActivityForResult` (가장 일반).
4. **여러 권한 한 번에** → `RequestMultiplePermissions`.
5. **갤러리 단일/복수** → `PickVisualMedia` / `PickMultipleVisualMedia` (Photo Picker).
6. **파일 선택** → `OpenDocument` / `CreateDocument` / `OpenDocumentTree` (SAF).
7. **표준 Contract로 안 되는 도메인 특화** → 커스텀 `ActivityResultContract<I, O>` 구현.

### IF 외부 앱 호출 (결제/배달/지도) (Implement)
1. **명시적 Intent 사용** — `Intent().setClassName(packageName, className)` 또는 `setComponent(ComponentName(...))`. 암시적 Intent (action만)는 보안·UX 모두 위험.
2. **앱 설치 확인**:
   ```kotlin
   try {
       startActivityForResult(intent, REQ)
   } catch (e: ActivityNotFoundException) {
       showInstallGuide()
   }
   ```
3. **결과 코드 분기**: `RESULT_OK`(정상), `RESULT_CANCELED`(취소/뒤로가기), 그 외(앱 정의).
4. **PendingResult 누수 방지** (Flutter MethodChannel 결합): 모든 분기에서 result.success/error 호출 후 null 초기화.

### IF 앱 외부 → 앱 진입 (Deep Link / 앱 내부 ↔ 결제 앱) (Implement)
1. AndroidManifest에서 `<intent-filter>` + `android:exported="true"` 명시 (API 31+ 필수).
2. 진입 권한 검증: `intent.getStringExtra(...)`로 받은 데이터를 검증 + auth 게이트 통과.
3. taskAffinity / launchMode 결정 (singleTask, singleTop) — 백스택 정책.
4. 받은 Intent의 모든 extra는 untrusted 입력으로 취급.

### IF FlutterActivity 환경 (Plugin) (Implement)
1. `FlutterPlugin + ActivityAware + ActivityResultListener` 구현.
2. `binding.addActivityResultListener(this)` 등록.
3. `onActivityResult(requestCode, resultCode, data)` Boolean 반환 — 처리한 경우 `true`.
4. `onDetachedFromActivity()` 시 activity null 처리 + pendingResult 해제.

### IF 코드 리뷰 (Review)
- [ ] launcher 등록이 onCreate 또는 그 이전인가
- [ ] FlutterActivity면 deprecated startActivityForResult 사용 + @Suppress("DEPRECATION")
- [ ] ActivityNotFoundException try-catch 있는가
- [ ] 명시적 Intent (setClassName/setComponent) 사용
- [ ] PendingResult 모든 분기에서 cleanup
- [ ] Intent extra가 untrusted로 검증
- [ ] Manifest의 exported, intent-filter, launchMode 명시
- [ ] requestCode가 충돌 없는 상수

## 핵심 패턴

### 표준 Activity Result API
```kotlin
class CheckoutActivity : ComponentActivity() {
    private val payLauncher: ActivityResultLauncher<Intent> = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        when (result.resultCode) {
            RESULT_OK -> handleSuccess(result.data)
            RESULT_CANCELED -> handleCancel()
            else -> handleVendorCode(result.resultCode, result.data)
        }
    }

    fun startPayment(amount: Long) {
        val intent = Intent().apply {
            setClassName("com.example_gateway.app", "com.example_gateway.app.PaymentActivity")
            putExtra("amount", amount)
        }
        try {
            payLauncher.launch(intent)
        } catch (e: ActivityNotFoundException) {
            showInstallGuide("com.example_gateway.app")
        }
    }
}
```

### Permission 요청
```kotlin
private val cameraPerm = registerForActivityResult(
    ActivityResultContracts.RequestPermission()
) { granted ->
    if (granted) openCamera() else showRationale()
}

fun requestCamera() {
    cameraPerm.launch(Manifest.permission.CAMERA)
}
```

### Photo Picker (Android 13+)
```kotlin
private val pickMedia = registerForActivityResult(
    ActivityResultContracts.PickVisualMedia()
) { uri: Uri? ->
    uri?.let { uploadAvatar(it) }
}

fun chooseAvatar() {
    pickMedia.launch(
        PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)
    )
}
```

### FlutterActivity (legacy 경로)
```kotlin
class MainActivity : FlutterActivity() {
    companion object { const val PAYMENT_REQUEST_CODE = 9001 }
    private lateinit var handler: PaymentChannelHandler

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        handler = PaymentChannelHandler(this) { intent ->
            @Suppress("DEPRECATION")
            startActivityForResult(intent, PAYMENT_REQUEST_CODE)
        }
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "app.example_gateway/payment")
            .setMethodCallHandler(handler)
    }

    @Suppress("DEPRECATION")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == PAYMENT_REQUEST_CODE) {
            handler.handleActivityResult(resultCode, data)
        }
    }
}
```

### FlutterPlugin + ActivityResultListener
```kotlin
class PaymentPlugin : FlutterPlugin, MethodCallHandler, ActivityAware, ActivityResultListener {
    private var activity: Activity? = null
    private var pendingResult: MethodChannel.Result? = null

    override fun onAttachedToActivity(binding: ActivityPluginBinding) {
        activity = binding.activity
        binding.addActivityResultListener(this)
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?): Boolean {
        if (requestCode != REQ_PAY) return false
        val result = pendingResult ?: return true
        pendingResult = null
        when (resultCode) {
            Activity.RESULT_OK -> result.success(parseSuccess(data))
            Activity.RESULT_CANCELED -> result.error("CANCELED", "user cancel", null)
            else -> result.error("FAIL", "code=$resultCode", null)
        }
        return true
    }

    override fun onDetachedFromActivity() {
        activity = null
        pendingResult?.error("NO_ACTIVITY", "detached", null)
        pendingResult = null
    }
}
```

### 커스텀 Contract
```kotlin
class CapturePaymentContract : ActivityResultContract<PaymentInput, PaymentOutput?>() {
    override fun createIntent(context: Context, input: PaymentInput): Intent =
        Intent().apply {
            setClassName("com.example_gateway.app", "com.example_gateway.app.PaymentActivity")
            putExtra("amount", input.amount)
        }

    override fun parseResult(resultCode: Int, intent: Intent?): PaymentOutput? =
        if (resultCode == Activity.RESULT_OK && intent != null) {
            PaymentOutput.from(intent)
        } else null
}
```

## Gotchas

### `IllegalStateException: LifecycleOwners must call register before they are STARTED`
launcher를 onResume 등에서 등록 → 라이프사이클 위반. 항상 onCreate 이전 또는 onCreate 안 (Activity 프로퍼티).

### `FlutterActivity` + registerForActivityResult 컴파일 에러
FlutterActivity는 `ActivityResultCaller` 구현 안 함. deprecated startActivityForResult + onActivityResult 오버라이드 + `@Suppress("DEPRECATION")`.

### `ActivityNotFoundException` 미처리 → 앱 크래시
외부 앱 미설치 시 발생. **모든 외부 Intent launch는 try-catch.**

### PendingResult 누수 (Flutter MethodChannel)
RESULT_CANCELED 분기에서 result.error 안 부르면 Future가 영영 미해결 → UI 멈춤. 모든 분기 cleanup + null 초기화.

### 암시적 Intent (Action만 + 패키지 미지정)
"앱 선택" 다이얼로그 노출 + 다른 앱이 가로챌 위험. 결제·민감 거래는 명시적 Intent (`setClassName` / `setComponent`).

### `requestCode` 충돌
여러 launcher가 같은 requestCode → 결과 혼선. 상수로 정의 + 한 곳에서 관리. (ActivityResult API는 내부적으로 자동 할당이라 이슈 적음, deprecated 경로에서만)

### Intent extra를 검증 없이 신뢰
외부 앱 → 우리 앱 진입 시 `intent.getStringExtra("amount")`를 그대로 사용 → 위변조 가능. 서버 검증 또는 서명 검증.

### `android:exported` 누락 (API 31+)
빌드 실패 또는 런타임 보안 경고. intent-filter 있는 모든 컴포넌트에 명시.

### `singleTask` launchMode 잘못 사용
deep link 진입에서 새 task 만들지 않으면 백스택이 꼬임. 진입 화면은 `singleTask` 또는 `singleTop` + `taskAffinity` 정의.

### `result.data` null 처리 누락
`RESULT_OK`라도 data가 null일 수 있음 (외부 앱 버그/프로토콜). null 분기 + 기본값.

### Fragment에서 launcher를 `onCreateView`에 등록
Fragment 재생성 시 IllegalStateException. 클래스 프로퍼티로 선언.

### Compose에서 `rememberLauncherForActivityResult` 시점
`@Composable` 함수 안에서 호출 — recomposition 안전. `LaunchedEffect` 안에서 호출하면 안 됨.

## 검증 체크리스트

- launcher 등록 위치가 onCreate 이전 또는 클래스 프로퍼티
- FlutterActivity 경로면 deprecated 사용 + @Suppress 명시
- ActivityNotFoundException try-catch 모든 외부 Intent에
- 명시적 Intent (setClassName/ComponentName) 사용
- PendingResult 모든 분기 cleanup
- Intent extra 검증 (untrusted 가정)
- Manifest의 exported / intent-filter / launchMode 명시
- requestCode 상수로 통일

## 5축 자가 평가

- 검색성: activity result / intent / external app / launcher / 한·영 키워드 + 코드 식별자
- 의사결정 트리(IF/THEN): 6개 IF 분기 + 8개 리뷰 체크
- 코드 식별자: registerForActivityResult, ActivityResultContracts.StartActivityForResult, RequestPermission, PickVisualMedia, ActivityResultLauncher, ActivityResultContract, ActivityNotFoundException, ComponentName, setClassName, ActivityResultListener, FlutterPlugin
- Gotcha-driven: 12개 흔한 실수 + 회피
- 검증 가능: 8개 체크리스트
