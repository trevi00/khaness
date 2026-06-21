---
keywords: flutter 플러터 dart 다트 widget 위젯 methodchannel platform channel 메소드채널 플랫폼채널 eventchannel pigeon ffi plugin 플러그인 네이티브 연동 isolate
intent: 만들어 추가해 구현해 수정해 연동해 통신해 화면 채널
paths: lib/ lib/src lib/pages lib/widgets lib/services android/app/src/main
patterns: MethodChannel EventChannel FlutterActivity FlutterPlugin PaymentPlugin PaymentService RequestMsg PaymentResponse BasicMessageChannel Pigeon
requires: kotlin-android example_gateway-example_vendor
phase: plan implement review debug
min_score: 3
---

# Flutter + Dart 네이티브 연동

## 의사결정 트리

### IF 플랫폼 채널 방식 선택 (Plan)
| 방식 | 용도 | 타입 안전 | 코드량 |
|------|------|----------|--------|
| **MethodChannel** | 단발 요청/응답 (결제, 설정) | 수동 캐스팅 | 적음 |
| **EventChannel** | 지속 스트림 (센서, BLE, 위치) | 수동 캐스팅 | 중간 |
| **Pigeon** | 복잡한 인터페이스 (필드 10개+) | **자동 코드생성** | IDL 정의만 |
| **FFI** | C 라이브러리 직접 호출 (성능 임계) | C 타입 바인딩 | 많음 |

**백엔드 개발자 비유**:
- MethodChannel = gRPC unary call (수동 직렬화)
- Pigeon = Protobuf codegen (IDL → 자동 생성)
- FFI = JNI
- Isolate = Erlang actor model

### IF MethodChannel 통신 구현 (Implement)
1. 채널 이름: `"app.example_gateway/payment"` (실제 프로젝트 기준)
2. Dart: `MethodChannel(채널명).invokeMethod<Map>(메서드명, {vanCode, requestData})`
3. Kotlin: FlutterPlugin 패턴에서 `onAttachedToEngine()`에서 채널 등록
4. 인자: `Map<String, dynamic>` — vanCode + requestData(Map) 묶어서 전달
5. 응답: `Map<String, Any?>` — 29개 필드 + isSuccess 포함
6. **→ kotlin-android 스킬: FlutterPlugin + ActivityResultListener 패턴**

### IF EventChannel 스트림 구현 (Implement)
1. Dart 측: `EventChannel(채널명).receiveBroadcastStream().listen((data) { })`
2. Kotlin 측: `EventChannel.StreamHandler` 구현
   ```kotlin
   object : EventChannel.StreamHandler {
       override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
           // events?.success(data) — 데이터 전송
           // events?.error(code, msg, details) — 에러
           // events?.endOfStream() — 스트림 종료
       }
       override fun onCancel(arguments: Any?) { /* 구독 해제 */ }
   }
   ```
3. 용도: 센서 데이터, BLE 스캔 결과, 위치 업데이트 등 지속적 데이터

### IF Pigeon 타입안전 채널 (Plan — 필드 10개 이상이면 고려)
1. IDL 정의 (`pigeons/payment.dart`):
   ```dart
   @HostApi()
   abstract class PaymentApi {
     @async
     PaymentResponse processPayment(PaymentRequest request);
   }
   
   class PaymentRequest {
     late String vanCode;
     late String tid;
     late String tranAmt;
   }
   ```
2. 코드 생성: `dart run pigeon --input pigeons/payment.dart`
3. Dart + Kotlin 양쪽에 타입안전 클래스 자동 생성
4. **장점**: Map 캐스팅 에러 원천 차단, 필드 추가 시 컴파일 에러로 감지
5. **실 프로젝트 사례**: MethodChannel 사용 중 + 필드 29개 → Pigeon 전환 검토 가치 있음

### IF 플러그인 패키지 구조 (Plan)
```
실제 프로젝트는 Flutter 플러그인으로 구성:
lib/
├── example_gateway_plugin.dart       # Public API export
└── src/
    ├── payment_service.dart  # MethodChannel 래퍼 (7개 메서드)
    ├── models.dart           # RequestMsg, PaymentResponse, PaymentException
    └── van_providers.dart    # VAN 코드 상수 (13개)
```

플러그인 생성: `flutter create --template=plugin --platforms=android my_plugin`

### IF 코드 리뷰 (Review)
- [ ] MethodChannel 채널명이 `"app.example_gateway/payment"` 인가
- [ ] `invokeMethod` 결과를 `Map<String, dynamic>.from(raw)` 으로 안전 변환하는가
- [ ] `PlatformException` **과** `MissingPluginException` 모두 catch 하는가
- [ ] vanCode와 requestData를 Map으로 묶어서 전달하는가 (별도 파라미터 아님)
- [ ] PaymentResponse.fromMap()에서 모든 29개 필드를 nullable 처리하는가
- [ ] 결제 결과의 isSuccess가 `responseCode == "0000"` 인가
- [ ] EventChannel 사용 시 `onCancel`에서 리소스 해제하는가
- [ ] Isolate.run()으로 무거운 파싱을 UI 스레드에서 분리했는가

## 가이드

### 실제 프로젝트 Dart 코드 패턴 (검증됨)

**PaymentService — 7개 결제 메서드**:
```dart
class PaymentService {
  static const _channel = MethodChannel('app.example_gateway/payment');

  Future<PaymentResponse> creditPaymentApproval(String vanCode, Map<String, String> requestData) =>
      _invokePaymentMethod('creditPaymentApproval', vanCode, requestData);

  Future<PaymentResponse> creditPaymentCancel(String vanCode, Map<String, String> requestData) =>
      _invokePaymentMethod('creditPaymentCancel', vanCode, requestData);

  // cashPaymentApproval, cashPaymentCancel,
  // simplePaymentApproval, simplePaymentCancel,
  // merchantRegistration 도 동일 패턴

  Future<PaymentResponse> _invokePaymentMethod(
    String method, String vanCode, Map<String, String> requestData
  ) async {
    try {
      final result = await _channel.invokeMethod<Map>(method, {
        'vanCode': vanCode,
        'requestData': requestData,
      });
      if (result == null) throw PaymentException('NULL_RESPONSE', '응답 없음');
      return PaymentResponse.fromMap(Map<String, dynamic>.from(result));
    } on PlatformException catch (e) {
      throw PaymentException(e.code, e.message ?? '알 수 없는 에러', e.details);
    }
  }
}
```

**PaymentResponse — 응답 (29개 필드)**:
```dart
class PaymentResponse {
  final String? responseCode;     // "0000" = 성공
  final String? displayMsg;
  final String? authNo, authDate, authTime;
  final String? cardNo, cardNm;
  final String? issuerCode, issuerNm;
  final String? acquirerCode, acquirerNm;
  final String? tranUniqNo, merNo, tid;
  // ... 총 29개
  bool get isSuccess => responseCode == '0000';

  factory PaymentResponse.fromMap(Map<String, dynamic> map) => PaymentResponse(
    responseCode: map['responseCode']?.toString(),
    authNo: map['authNo']?.toString(),
    // ...
  );
}
```

### VAN 코드 상수 (Dart)
```dart
class VanProvider {
  static const String koces = '6070005';
  static const String example_vendor = '6070006';  // 내 담당
  static const String kicc = '6070003';
  // ... 13개
}
```

### 플러그인 사용법 (다른 팀 Flutter 개발자가 사용)
```dart
dependencies:
  example_gateway_plugin:
    git:
      url: https://github.com/your_org/example_app-app-example_gateway.git
      ref: develop

// 사용
import 'package:example_gateway_plugin/example_gateway_plugin.dart';

final service = PaymentService();
final response = await service.creditPaymentApproval(
  VanProvider.example_vendor,
  RequestMsg(tid: 'T001', tranAmt: '10000', taxAmt: '1000').toMap(),
);
if (response.isSuccess) { /* 성공 */ }
```

### MethodChannel 전달 가능 타입
| Dart | Kotlin | 비고 |
|------|--------|------|
| null | null | |
| bool | Boolean | |
| int | Int/Long | 값 크기에 따라 자동 |
| double | Double | |
| String | String | |
| Uint8List | ByteArray | |
| Int32List | IntArray | |
| Float64List | DoubleArray | |
| List | ArrayList | 내부 원소도 이 표의 타입만 |
| Map | HashMap | **중첩 Map도 가능** |

**그 외 타입은 전달 불가** — 커스텀 객체는 Map으로 직렬화 필수.

### Isolate — UI 블록 방지
```dart
// 무거운 JSON 파싱을 별도 Isolate에서
final parsed = await Isolate.run(() {
  return jsonDecode(hugeJsonString) as Map<String, dynamic>;
});
```
- UI 스레드(메인 Isolate)에서 50ms 이상 걸리는 작업 → jank 발생
- `Isolate.run()`은 일회성, `compute()`와 동일
- Isolate 간 데이터는 복사됨 (공유 메모리 아님)

### Android host: FlutterPlugin + ActivityResultListener (Activity 결과 통합)

> 이전엔 `kotlin/android/kotlin-android.md`에 거주했으나 Flutter 결합 패턴이라 이쪽이 canonical. (debate-1777606052 D4 MOVE)

**프로덕션 패턴 — Activity 결과를 받아야 하는 native 통합 (예: 결제, 카메라)**:
```kotlin
class NativeBridgePlugin : FlutterPlugin, MethodCallHandler, ActivityAware, ActivityResultListener {
    private var channel: MethodChannel? = null
    private var activity: Activity? = null
    private var pendingResult: Result? = null

    override fun onAttachedToEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        channel = MethodChannel(binding.binaryMessenger, "app/<channel-name>")
        channel?.setMethodCallHandler(this)
    }
    override fun onAttachedToActivity(binding: ActivityPluginBinding) {
        activity = binding.activity
        binding.addActivityResultListener(this)
    }
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?): Boolean {
        if (requestCode == 1001) { /* 응답 처리 */ return true }
        return false
    }
}
```

> 회사/프로젝트별 구체 plugin (예: PaymentPlugin)은 별도 user-private 트리에 보관 — 예: `flutter/example_app/example_gateway-example_vendor.md`.

## Gotchas

### Map 캐스팅 — 가장 흔한 런타임 에러
`invokeMethod<Map>()` 반환값은 `Map<Object?, Object?>`임. 바로 `as Map<String, dynamic>` 하면 타입 에러. **`Map<String, dynamic>.from(raw)`로 안전 변환** 필수.

### PlatformException vs MissingPluginException
- `PlatformException`: Kotlin 핸들러가 `result.error()` 호출 시 — 정상적 에러 응답
- `MissingPluginException`: 채널명 불일치 또는 핸들러 미등록 — **채널명 오타 확인**
- 웹 환경에서도 `MissingPluginException` 발생 — 폴백 처리 필요

### requestData는 Map<String, String>으로 전달
실제 프로젝트에서 requestData의 모든 값은 **String 타입**. `tranAmt: '10000'` (String). Kotlin 측에서도 `HashMap<String, String>`.

### vanCode와 requestData를 묶어서 전달
```dart
// 올바름:
_channel.invokeMethod(method, {'vanCode': vanCode, 'requestData': requestData});
// 잘못됨:
_channel.invokeMethod(method, requestData);  // vanCode 누락
```

### Hot Reload에서 MethodChannel 재등록 안 됨
Dart 측만 갱신되고 Kotlin 측은 유지. MethodChannel 핸들러 변경 시 **Hot Restart** 필요.

### iOS 대응 불필요 확인
ACME_INTERNAL는 Android 태블릿 전용. `flutter.plugin.platforms`에 android만 등록.

### 플러그인 vs 단일 앱 혼동
실제 프로젝트는 **Flutter 플러그인 패키지**. `pubspec.yaml`에 `flutter.plugin.platforms.android` + `pluginClass: PaymentPlugin`.

### EventChannel onCancel 미구현
`onCancel`에서 센서/BLE 리스너를 해제하지 않으면 메모리 누수 + 배터리 소모. Dart 측 `StreamSubscription.cancel()` 호출 시 `onCancel` 트리거됨.

### Pigeon @async 누락
Pigeon에서 `@async` 어노테이션 없이 정의하면 동기 호출이 됨. Android에서 네트워크/IO 작업은 반드시 `@async` 붙여야 코루틴/콜백으로 처리 가능.
