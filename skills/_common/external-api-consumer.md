---
name: external-api-consumer
description: 외부 API 호출자(consumer) 응답 검증 — transport status (HTTP) + envelope status (body) 이중 체크. transport만 보면 proxy/static handler/error envelope이 200으로 가려져 거짓 양성. CI/CD pipeline, mobile client, server-to-server 공통.
keywords: [api-consumer, http-status, response-validation, envelope, status-code, false-positive, restclient, retrofit, dio, jq, curl, gh-actions, http-client, body-status]
intent: [call-external-api, validate-response, check-status, error-handling, ci-cd-api-call]
phase: implement review
min_score: 2
---

# External API Consumer Validation

> **핵심 원칙**: 외부 API 응답 검증은 **transport status(HTTP)** 와 **envelope status(body)** 둘 다 본다. 한 쪽만 보면 거짓 양성.

## 왜 둘 다 봐야 하는가

서버는 응답을 두 층에서 처리한다:

| 층 | 의미 | 예 |
|---|------|------|
| **Transport (HTTP)** | 요청이 라우팅·전달됐는가 | 200 OK, 404 Not Found, 502 Bad Gateway |
| **Envelope (Body)** | 비즈니스 로직이 성공했는가 | `status: "200"`, `status: "8020001"` |

**거짓 양성이 발생하는 케이스**:
- 잘못된 path → Spring static resource handler가 404를 반환했어야 하는데 일부 설정에선 **200 + HTML/text** ("No static resource ...")
- API gateway 또는 proxy가 자체 응답 캐시 → 200이지만 stale
- 일부 백엔드는 비즈니스 에러도 **HTTP 200 + envelope에 error code** (대표: `{"status":"8020001","results":"..."}`)
- CDN edge가 default page 200 반환

→ **HTTP만 체크하면 endpoint typo, schema mismatch, business rejection을 놓친다.**

## 의사결정 트리

### IF 새 API 호출 코드 작성 (Implement)
1. **응답 envelope 형식 확인** — provider 문서에서 success/failure body shape
2. **검증 로직**: HTTP 2xx + envelope status 동시 체크
3. **실패 처리**: 어느 층에서 실패했는지 분리 로깅 (transport vs envelope)
4. **응답 body echo (디버깅 모드)**: 거짓 양성 디버깅 시 즉시 원인 보임

### IF 회사 ACME_INTERNAL-style envelope (`{status, results, error, pageInfo}`)
- HTTP 2xx + `body.status == "200"` 둘 다
- `status: "8020001"` 같은 8자리 코드는 비즈니스 에러 — 절대 success 아님
- `results`가 문자열인지 객체인지 success/error에서 다를 수 있음
- 자세한 회사 패턴은 user-private skill 참조 (회사 컨벤션이 별도면 그쪽에 envelope schema 명시)

### IF Stripe/Github-style envelope (`{error: {code, message}}` on failure, raw object on success)
- HTTP 4xx/5xx면 envelope에 `error` 객체 — code로 분기
- HTTP 2xx면 raw success 객체 — `error` 필드 없음
- 따라서 `if (resp.error) fail()` 으로 envelope check (HTTP만 안 보고)

### IF 응답 형식 모름 (Unknown provider)
1. 한 번 호출 → body 출력 → 형식 파악
2. envelope 패턴 확정 후 검증 로직 구현
3. 절대 HTTP만 보고 success 판정 금지

## 베이스라인 — Surface별

### Bash + curl + jq (CI/CD, GitHub Actions)
```bash
RESPONSE=$(curl -sS -w "\n%{http_code}" -X POST "$URL" -d "$BODY")
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')
API_STATUS=$(echo "$BODY" | jq -r '.status')

if [ "$HTTP_CODE" -ge 200 ] && [ "$HTTP_CODE" -lt 300 ] && [ "$API_STATUS" == "200" ]; then
  echo "✅ Success"
  echo "📋 Response: $BODY"
else
  echo "❌ Failed (HTTP=$HTTP_CODE, API_STATUS=$API_STATUS)"
  echo "Response: $BODY"
  exit 1
fi
```

**핵심**:
- `curl -w "\n%{http_code}"` 로 transport status 분리 캡처
- `jq -r '.status'` 로 envelope status 추출
- 둘 다 통과해야 success
- 실패 시 두 값 + body 모두 출력 (디버깅)

### Kotlin (Retrofit / OkHttp)
```kotlin
data class ApiResponse<T>(
    val status: String,         // envelope status — "200" or "8020001" 등
    val results: T?,
    val error: ErrorInfo?,
)

suspend fun <T> Response<ApiResponse<T>>.unwrap(): T {
    if (!isSuccessful) {                       // transport check
        throw ApiException("HTTP ${code()}: ${errorBody()?.string()}")
    }
    val envelope = body() ?: throw ApiException("Empty body")
    if (envelope.status != "200") {            // envelope check
        throw ApiException("API status=${envelope.status}: ${envelope.error?.message}")
    }
    return envelope.results ?: throw ApiException("Null results on status 200")
}
```

### Dart (dio)
```dart
class ApiException implements Exception {
  final int? httpCode;
  final String? envelopeStatus;
  final String message;
  ApiException({this.httpCode, this.envelopeStatus, required this.message});
}

Future<T> callApi<T>(...) async {
  final resp = await dio.post(...);
  if (resp.statusCode == null || resp.statusCode! < 200 || resp.statusCode! >= 300) {
    throw ApiException(httpCode: resp.statusCode, message: 'Transport failed');
  }
  final body = resp.data as Map<String, dynamic>;
  final status = body['status'] as String?;
  if (status != '200') {
    throw ApiException(
      httpCode: resp.statusCode, envelopeStatus: status,
      message: 'Envelope failed: ${body['results']}',
    );
  }
  return parseResults(body['results']);
}
```

### Java RestClient (Spring)
```java
ApiResponse<T> body = restClient.post().uri(url).body(req)
    .retrieve()
    .onStatus(s -> !s.is2xxSuccessful(), (req2, resp) -> {
        throw new TransportException("HTTP " + resp.getStatusCode());
    })
    .body(new ParameterizedTypeReference<ApiResponse<T>>() {});

if (!"200".equals(body.getStatus())) {
    throw new EnvelopeException(body.getStatus(), body.getError());
}
return body.getResults();
```

## Review 체크리스트

API 호출 코드 PR 리뷰 시:
- [ ] HTTP 2xx 체크 있음
- [ ] envelope status 체크 있음 (둘 다)
- [ ] 실패 시 body 또는 error 객체 로깅 (디버깅용)
- [ ] HTTP는 fail인데 body 파싱 시도하지 않음 (transport 실패면 body는 신뢰 불가)
- [ ] 200 + envelope error 케이스 명확히 처리 (silent ignore 금지)
- [ ] CI/CD 스크립트면 `set -euo pipefail` + `exit 1` on fail

## Gotchas

### DTO→DTO/adapter 변환 시 필드 부분복사 (송신측 F2 — 2-Strike)
송신 payload를 만드는 adapter/builder/`toXxxDTO`는 **필드 전수 복사** — 일부만 복사하면 컴파일·green 통과하며 결함/빈값 payload가 vendor로 송신(`payTypeFlag=03`인데 승인필드 빈 값 / `lat·lon` 항상 null). **변환 도입과 같은 PR**에 ArgumentCaptor(또는 raw ObjectMapper JSON contract test)로 송신 payload를 **필드별 assert**. DTO에 새 필드 선언 시 그 필드를 채우는 adapter 매핑을 같은 PR에서 함께 변경하고 '출처→매핑 ✓' 전수표 첨부. (poslink #36 카드10종 누락 / #51→#53 lat·lon adapter 누락 — 2회, 2-Strike)

### HTTP_CODE만 체크 → 거짓 양성 (대표 incident)
endpoint typo (`/pos/program/example_gateway` vs `/pos/program/apk`) 시 일부 백엔드는 200 + `"No static resource ..."` 응답.
`if [ "$HTTP_CODE" == "200" ]; then echo success` 만 있으면 거짓 success → CI/CD는 통과, 실제 등록 안 됨.
운영 측 "왜 안 보이지" 피드백으로만 발견. **반드시 envelope status 같이 체크.**

### envelope status 타입 혼동 (string vs int)
일부 envelope은 `"status": "200"` (string), 일부는 `"status": 200` (int).
jq에서 `'.status'` 결과를 `==` 비교 시 string로 들어옴 → `"200" == 200` false.
숫자라면 `'.status | tonumber'` 또는 처음부터 string 비교 통일.

### `jq -r '.status'` 가 null/빈 응답에서 `null` 출력
non-JSON 응답(HTML 에러 페이지 등) 또는 빈 body면 `jq`가 `null` 반환.
`[ "$API_STATUS" == "200" ]` 비교에서 `null != "200"` → 정상 fail.
다만 에러 메시지에 `null` 그대로 노출되면 디버깅 어려움 → "envelope parse failed (non-JSON?)" 같은 별도 분기 권장.

### `errorBody()` 이미 소비
Retrofit/OkHttp의 `errorBody()`는 한 번 read하면 두 번째는 빈 결과. 로깅 위해 `string()` 호출 후 같은 변수에 저장해야 함. 모르고 두 번 호출하면 두 번째에서 디버깅 정보 없음.

### envelope status 체크 누락 → silent data corruption
`status: "8020001"` (validation error) 무시하고 `results` 파싱 시도 → results는 에러 메시지 string, 코드는 객체로 캐스팅 → ClassCastException 또는 더 나쁘게 `null`이 데이터로 들어가서 무결성 깨짐.

### 200 응답 body가 HTML (error page)
`content-type: text/html`인데 jq로 파싱하려면 stderr에 에러 + 빈 결과. content-type 같이 체크하거나 jq fail 분기 처리.

### CI/CD 스크립트가 `exit 1` 안 함
검증 실패 메시지 echo만 하고 exit 안 하면 GitHub Actions step이 success로 표시. 반드시 `exit 1`. `set -euo pipefail` 도 함께.

### 응답 body 너무 큰데 항상 echo
디버깅 echo가 success path에도 있으면 큰 body가 매번 로그 폭발. fail path에만 echo, success는 짧은 요약.

### 재시도 로직이 envelope error에도 retry
network error는 retry 가치, envelope error(`8020001`)는 재시도해도 같은 결과. retry 정책에 transport 실패만 포함, envelope error는 fail-fast.

## 도구 사용 패턴 (Harness)

- 거짓 양성 진단: `Bash`로 `gh run view <id> --log` 후 `Grep`으로 `(HTTP Status|API_STATUS|Response:)` 추출
- 누락 검출: `Grep`으로 `curl.*POST` 호출 블록 후 `jq.*status` 또는 envelope check 패턴 부재 검사
- 거짓 success 회피: workflow yaml 변경 시 success 판정 라인에 envelope status 조건 포함 확인
- 회사 envelope schema 변경 시 모든 consumer surface 동시 업데이트 (escape hatch 없음)

## 에러 복구 패턴 (Harness)

- "API 통과한 것 같은데 백엔드 데이터 없음" → HTTP_CODE만 본 거짓 양성 의심. body 출력 추가 후 재현
- "응답 status 200인데 results가 에러 메시지 string" → envelope status 체크 누락. 검증 추가 + 데이터 무결성 영향 범위 분석
- envelope schema 변경 → consumer 측 schema sync (Kotlin data class, Dart class, jq path 모두) + contract test
