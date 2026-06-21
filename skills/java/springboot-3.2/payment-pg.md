---
keywords: 결제 payment PG pg 토스 toss 토스페이먼츠 tosspayments 카카오페이 kakaopay 네이버페이 naverpay 환불 refund 웹훅 webhook 빌링 billing 정기결제 subscription 결제위젯 paymentwidget
intent: 결제해 연동해 환불해 결제취소해 PG연동해 연동해 결제해 결제연동해 PG해
paths: src/main/java payment/ billing/ webhook/
patterns: tosspayments kakaopay naverpay portone iamport payment billing webhook pg resttemplate webclient
requires: backend security
phase: plan implement
min_score: 4
---

# PG 결제 연동 가이드 (토스페이먼츠 / 카카오페이 / 네이버페이)

## 의사결정 트리

### IF PG 선택 (Plan)
| PG | 장점 | 단점 |
|----|------|------|
| **토스페이먼츠** | 문서 최고, 결제위젯 제공, 테스트 환경 우수 | - |
| **카카오페이** | 사용자 많음, 연동 비교적 간단 | Webhook 미제공 (리다이렉트만) |
| **네이버페이** | 네이버 쇼핑 연동 | 직접 연동 난이도 높음, 검수 15영업일 |
| **PortOne(구 아임포트)** | 여러 PG 통합 인터페이스 | 추상화로 인한 PG 고유 기능 제한 |

### IF 결제 구현 (Implement)
1. 가상 결제 인터페이스(PaymentGateway) 먼저 설계
2. 가상 구현체(MockPaymentGateway)로 개발/테스트
3. 실제 PG 구현체 교체 시 인터페이스만 구현
4. **→ security 스킬: Secret Key 환경변수 관리, HTTPS 필수**

### IF 결제 흐름 설계 (Plan)
```
프론트: 결제 요청 → PG 결제창/위젯 → 인증 완료 → 백엔드에 승인 요청
백엔드: 금액 검증 → PG 승인 API 호출 → 결과 DB 저장 → 응답
```
**핵심**: 프론트에서 받은 금액을 **DB 주문 금액과 반드시 비교** 후 승인 (금액 위변조 방지)

## 인터페이스 설계 (가상 → 실제 전환용)
```java
public interface PaymentGateway {
    PaymentResult approve(String paymentKey, String orderId, Long amount);
    PaymentResult cancel(String paymentKey, String reason, Long cancelAmount);
    PaymentResult query(String paymentKey);
}

// 가상 결제 (개발/테스트용)
@Service
@Profile({"dev", "test"})
public class MockPaymentGateway implements PaymentGateway {
    public PaymentResult approve(String paymentKey, String orderId, Long amount) {
        return PaymentResult.success(paymentKey, orderId, amount);
    }
}

// 토스페이먼츠 (프로덕션용)
@Service
@Profile("prod")
public class TossPaymentGateway implements PaymentGateway { ... }
```

---

## 1. 토스페이먼츠 (Toss Payments)

### 인증
- **Basic Auth**: `Base64(secretKey + ":")`
- Client Key(`test_ck_`) → 프론트엔드, Secret Key(`test_sk_`) → 백엔드
- 같은 세트의 키를 사용해야 함 (혼용 시 `INVALID_API_KEY`)

### 결제 흐름
```
프론트: PaymentWidget SDK 초기화 (Client Key)
  → renderPaymentMethods() 결제 UI 렌더링
  → requestPayment() 결제 요청
  → 인증 성공 → successUrl 리다이렉트 (paymentKey, orderId, amount)
백엔드: POST /v1/payments/confirm (Secret Key)
  → 금액 검증 → 승인 → Payment 객체 반환 (status: "DONE")
```

### 주요 API
| 기능 | Method | Endpoint |
|------|--------|----------|
| 결제 승인 | POST | `/v1/payments/confirm` |
| 결제 조회 (paymentKey) | GET | `/v1/payments/{paymentKey}` |
| 결제 조회 (orderId) | GET | `/v1/payments/orders/{orderId}` |
| 결제 취소 | POST | `/v1/payments/{paymentKey}/cancel` |

Base URL: `https://api.tosspayments.com`

### Spring Boot 구현
```java
@Service
public class TossPaymentGateway implements PaymentGateway {
    private final RestClient restClient;

    public TossPaymentGateway(@Value("${tosspayments.secret-key}") String secretKey) {
        this.restClient = RestClient.builder()
            .baseUrl("https://api.tosspayments.com")
            .defaultHeaders(headers -> {
                headers.setBasicAuth(secretKey, "");
                headers.setContentType(MediaType.APPLICATION_JSON);
            })
            .build();
    }

    public PaymentResult approve(String paymentKey, String orderId, Long amount) {
        Map<String, Object> body = Map.of(
            "paymentKey", paymentKey,
            "orderId", orderId,
            "amount", amount
        );
        return restClient.post().uri("/v1/payments/confirm")
            .body(body)
            .retrieve()
            .body(PaymentResult.class);
    }
}
```

### 결제 상태
`READY` → `IN_PROGRESS` → `DONE` / `CANCELED` / `PARTIAL_CANCELED` / `ABORTED` / `EXPIRED`

### Webhook
- 이벤트: `PAYMENT_STATUS_CHANGED`, `DEPOSIT_CALLBACK` 등
- 10초 내 HTTP 200 응답 필수, 실패 시 최대 7회 재전송
- 개발자센터에서 URL 등록

### 테스트 환경
- `developers.tosspayments.com` 가입만 하면 테스트 키 자동 발급 (사업자등록 불필요)
- `TossPayments-Test-Code` 헤더로 에러 시뮬레이션 가능
- `test_` → `live_` 키 교체로 운영 전환

---

## 2. 카카오페이 (Kakao Pay)

### 인증
```
Authorization: SECRET_KEY {발급받은_시크릿키}
Content-Type: application/json
```
- DEV 키(테스트), LIVE 키(운영) 구분
- 구 방식(`KakaoAK {admin_key}` + form-urlencoded)은 deprecated

### 결제 흐름
```
백엔드: POST /ready (cid, 주문정보, 콜백URL) → tid + redirect_url 수신
프론트: redirect_url로 카카오페이 결제창 → 사용자 인증 → approval_url?pg_token=xxx
백엔드: POST /approve (tid, pg_token) → 결제 완료
```

### 주요 API
| 기능 | Method | Endpoint |
|------|--------|----------|
| 결제 준비 | POST | `/ready` |
| 결제 승인 | POST | `/approve` |
| 결제 취소 | POST | `/cancel` |
| 주문 조회 | POST | `/order` |

Base URL: `https://open-api.kakaopay.com/online/v1/payment`

### Spring Boot 구현
```java
@Service
public class KakaoPayGateway {
    private final RestClient restClient;

    public KakaoPayGateway(@Value("${kakaopay.secret-key}") String secretKey) {
        this.restClient = RestClient.builder()
            .baseUrl("https://open-api.kakaopay.com/online/v1/payment")
            .defaultHeader("Authorization", "SECRET_KEY " + secretKey)
            .defaultHeader("Content-Type", "application/json")
            .build();
    }

    public KakaoReadyResponse ready(String orderId, String userId, String itemName, int amount) {
        Map<String, String> params = Map.of(
            "cid", "TC0ONETIME",
            "partner_order_id", orderId,
            "partner_user_id", userId,
            "item_name", itemName,
            "quantity", "1",
            "total_amount", String.valueOf(amount),
            "tax_free_amount", "0",
            "approval_url", "http://localhost:8080/payment/success",
            "cancel_url", "http://localhost:8080/payment/cancel",
            "fail_url", "http://localhost:8080/payment/fail"
        );
        return restClient.post().uri("/ready")
            .body(params)
            .retrieve()
            .body(KakaoReadyResponse.class);
    }
}
```

### 테스트 환경
- 테스트 CID: `TC0ONETIME` (단건), `TCSUBSCRIP` (정기)
- `developers.kakaopay.com`에서 DEV Secret Key 발급

### 주의사항
- `partner_order_id`, `partner_user_id`는 ready와 approve에서 반드시 동일해야 함
- `tid`를 세션/DB에 저장하여 approve까지 유지
- Webhook 미제공 — 리다이렉트 콜백만 사용
- 멱등성 처리 필요 (approval_url 중복 호출 케이스 있음)

---

## 3. 네이버페이 (Naver Pay)

### 인증
```
X-Naver-Client-Id: {Client_ID}
X-Naver-Client-Secret: {Client_Secret}
Content-Type: application/x-www-form-urlencoded
```

### 결제 흐름 (결제형)
```
프론트: 네이버페이 JS SDK로 결제창 호출 → 사용자 인증 → paymentId 수신
백엔드: POST /apply/payment (paymentId) → 결제 승인
```

### 주요 API
| 기능 | Method | Endpoint |
|------|--------|----------|
| 결제 승인 | POST | `/apply/payment` |
| 결제 취소 | POST | `/cancel/payment` |
| 내역 조회 | GET/POST | `/history` |

Base URL: `https://dev.apis.naver.com/{파트너ID}/naverpay/payments/v2.2`

### 주의사항
- PC는 POPUP, 모바일은 REDIRECTION만 지원
- 최소 결제금액 100원
- 검수 통과 필수 (약 15영업일)
- 직접 연동 난이도 높음 → PortOne 경유 권장

---

## PG 3사 비교

| 항목 | 토스페이먼츠 | 카카오페이 | 네이버페이 |
|------|-------------|-----------|-----------|
| 인증 | Basic Auth | SECRET_KEY 헤더 | Client-Id/Secret 헤더 |
| Content-Type | JSON | JSON | form-urlencoded |
| 결제 단계 | 2단계 (인증→승인) | 3단계 (준비→인증→승인) | 2단계 (인증→승인) |
| Webhook | 있음 (7회 재시도) | 없음 | 제한적 |
| 테스트 진입장벽 | 낮음 (가입만) | 낮음 | 높음 (파트너 등록) |
| 문서 품질 | 최고 | 양호 | 미흡 (PortOne 참고) |

## Gotchas

### 금액 위변조
프론트에서 전달한 amount를 그대로 PG에 보내면 위변조 가능. **DB에 저장된 주문 금액과 반드시 비교** 후 승인.

### Secret Key 노출
Secret Key가 프론트엔드 코드나 Git에 노출되면 즉시 무효화. 환경변수(`application.yml` + `@Value`)로 관리, `.gitignore`에 설정 파일 추가.

### 결제 승인 타임아웃
PG 승인 API가 느릴 수 있음 (네트워크 지연, PG 서버 부하). RestClient 타임아웃 설정 필수 (5~10초).

### 중복 승인 방지
사용자가 결제 완료 후 뒤로가기 → 다시 승인 요청하면 중복 결제. orderId 기반 멱등성 체크 필수.

### 부분 취소 잔액 관리
부분 취소 시 남은 금액 추적 필요. 전체 금액 - 누적 취소 금액 = 취소 가능 금액. DB에서 관리.

### 카카오페이 tid 유실
ready 응답의 tid를 세션이 아닌 DB에 저장 권장. 서버 재시작 시 세션 데이터 유실되면 approve 불가.

## 도구 사용 패턴 (Harness)
- PG 설정: `Read`로 application.yml 확인, `Edit`으로 키/URL 수정
- API 테스트: `Bash(curl)`로 PG API 직접 호출하여 응답 확인
- 에러 디버깅: PG 에러 코드를 `Grep`으로 코드에서 검색, 핸들링 여부 확인

## 에러 복구 패턴 (Harness)
- 승인 실패 → PG 에러 코드 확인 (INVALID_API_KEY → 키 확인, NOT_FOUND_PAYMENT → orderId 확인)
- 타임아웃 → `Bash(curl)`로 PG API 직접 호출하여 PG 서버 상태 확인
- Webhook 미수신 → PG 개발자센터에서 Webhook URL 등록 여부 확인, 서버 방화벽/포트 확인
