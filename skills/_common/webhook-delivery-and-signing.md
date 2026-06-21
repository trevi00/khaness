---
name: webhook-delivery-and-signing
description: Webhook 산업 표준 — HMAC-SHA256 서명, timestamp tolerance(5분), raw body 검증, retry policy. Stripe/GitHub/Slack 공통 패턴
keywords: webhook hmac sha256 signature timestamp replay-attack signing-secret retry exponential-backoff event-delivery raw-body
intent: design-webhook-delivery sign-payload prevent-replay handle-retry rotate-secret verify-signature
paths: src/webhooks src/handlers
patterns: X-Signature Stripe-Signature X-Hub-Signature-256 X-Slack-Signature timestamp.body
requires: idempotency security
phase: plan implement review debug
tech-stack: any
min_score: 2
quality_axes_enforced: true
---

# Webhook Delivery + Signing

> 핵심: Stripe/GitHub/Slack 모두 **HMAC-SHA256 + timestamp + raw body** 3축으로 수렴. 단일 webhook 표준은 없으나 결정 변수는 동일. 가장 흔한 구현 함정은 **JSON parse 후 stringify해서 sign 검증** — whitespace/key order 변경으로 signature mismatch.

## 의사결정 트리

### IF webhook 발신자 설계 (Plan)
1. payload 직렬화 — JSON 바이트 그대로 sign (UTF-8 byte-stable)
2. 서명 알고리즘 — **HMAC-SHA256** (Stripe/Slack/GitHub 모두 표준)
3. timestamp 포함 — replay 방지. signed_payload = `{timestamp}.{body}` (Stripe/Slack 패턴)
4. signing secret — endpoint 단위 + test/live 분리. 테스트키와 라이브키 혼용 시 전수 검증 실패
5. retry — 4xx (5xx 제외) 재시도 안 함. 5xx + timeout만 exponential backoff (1s, 5s, 30s, 1m, 5m, 30m, 1h)
6. delivery 보장 — at-least-once. consumer는 idempotency 필수 (참조: `idempotency.md`)

### IF webhook 수신자 검증 구현 (Implement)
1. **raw body 보존** — body parse 전 raw bytes 캡처. parse 후 stringify 절대 금지 (whitespace/key order 변경 → signature mismatch)
2. timestamp 추출 + 현재 시간 비교 — tolerance 5분 (Stripe/Slack default). 외부면 reject
3. expected = HMAC-SHA256(secret, `{timestamp}.{rawBody}`)
4. constant-time 비교 — `hmac.compare_digest` (Python), `MessageDigest.isEqual` (Java). `==` 비교 시 timing attack 노출
5. 검증 후에만 처리 — verify 전에 DB write 절대 금지

### IF replay 방지 (Implement)
1. timestamp window (5분) — 가장 단순. 클럭 스큐 시 false reject 위험
2. event_id dedup — Redis 또는 DB unique constraint. window 내에서만 검사 (storage 비용 통제)
3. 둘 다 적용 — defense in depth. timestamp window 만료 후에도 dedup table에 남으면 재시도 안전

### IF secret rotation (Implement)
1. rolling rotation — old + new 두 secret 동시 인정. 발신자 쪽 deploy 후 receiver에서 old 제거
2. grace period — 보통 24-48시간. 모든 in-flight retry가 old secret으로 서명됐을 가능성
3. rotation 빈도 — 보안 사고 시 즉시. 정기는 분기 1회 권장

### IF 발신자 선택 (Plan — 산업 표준 비교)
| Provider | Signature header | 서명 input | tolerance |
|---|---|---|---|
| **Stripe** | `Stripe-Signature: t=...,v1=...` | `t.body` | 5분 |
| **Slack** | `X-Slack-Signature: v0=...` + `X-Slack-Request-Timestamp` | `v0:t:body` | 5분 |
| **GitHub** | `X-Hub-Signature-256: sha256=...` | `body` (no timestamp) | 자체 timestamp 없음 |

GitHub는 timestamp 부재 — replay 방지를 event_id dedup에만 의존.

## 가이드

- raw body 보존을 위해 web framework마다 다른 접근 필요. Express는 `bodyParser.raw()`, Spring은 `@RequestBody byte[]`, FastAPI는 `await request.body()`.
- HMAC 비교는 **반드시 constant-time** — Python `==`, Java `Arrays.equals`는 timing attack 가능.
- production에서 5분 tolerance는 클럭 스큐로 false reject 발생 가능 — NTP 강제 + 모니터링.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | HMAC-SHA256 + timestamp 두 축으로 위변조/replay 동시 차단 |
| 성능 효율성 | constant-time 비교 (timing attack 차단)이 보안과 동등 우선 |
| 호환성 | Stripe/Slack/GitHub 모두 동일 HMAC-SHA256 — 라이브러리 재사용 |
| 사용성 | signing secret rotation grace period로 zero-downtime 교체 |
| 신뢰성 | 5xx + timeout 재시도, 4xx 즉시 fail — retry storm 차단 |
| 보안 | raw body 검증으로 JSON canonicalization 우회 차단 |
| 유지보수성 | endpoint별 secret 분리 + test/live 분리 |
| 이식성 | HMAC-SHA256은 모든 언어 stdlib (Python/Java/Go/Node) |
| 확장성 | event_id dedup + idempotency-key 결합으로 N event/s 흡수 |

## Gotchas

### JSON parse 후 stringify해서 sign 검증
가장 흔한 함정. `JSON.parse(body) → JSON.stringify(...)` 하면 whitespace/key order 변경으로 HMAC 다름. **raw bytes**를 검증 input으로 보존 필수.

### `==` 또는 `String.equals`로 signature 비교
timing attack 노출. constant-time 비교 (`hmac.compare_digest`, `MessageDigest.isEqual`) 강제.

### 5분 tolerance가 클럭 스큐에 false reject
서버 NTP가 안 돌면 정상 webhook 거절. NTP 모니터링 + tolerance 늘리지 않고 클럭 자체 수정.

### Test/live signing secret 혼용
테스트 환경에서 live secret 또는 그 반대로 사용 시 전수 검증 실패. endpoint별 + 환경별 secret 격리.

### 검증 전에 DB write
HMAC 검증 통과 전에 payload를 DB write하면 spoofed 데이터 저장 가능. verify → 처리 → idempotency dedup 순서 엄수.

### `starting_after` / `ending_before` 동시 사용 (cursor pagination)
Stripe docs 명시 "cannot be used simultaneously". 둘 다 보내면 API error. 한 방향씩만.

### 5xx 재시도가 retry storm 야기
exponential backoff + jitter 없이 즉시 재시도하면 발신자가 receiver에 DDoS. 1s/5s/30s/1m/5m/30m/1h 권장 schedule.

## Source

- https://docs.stripe.com/webhooks/signatures — "Stripe generates signatures using a hash-based message authentication code (HMAC) with SHA-256"; "default tolerance of 5 minutes"; "signed_payload string is created by concatenating: The timestamp ... `.` ... actual JSON payload", 조회 2026-05-10
- https://docs.stripe.com/api/idempotent_requests — "remove keys from the system automatically after they're at least 24 hours old"; "suggest using V4 UUIDs"; "saving the resulting status code and body of the first request", 조회 2026-05-10
- https://docs.stripe.com/api/pagination — `starting_after`/`ending_before`/`has_more`, "ranging between 1 and 100"; cannot be used simultaneously, 조회 2026-05-10
- https://docs.stripe.com/api/versioning — "current version is 2026-04-22.dahlia"; "Stripe-Version" header; date-based 월별 backward-compatible release, 조회 2026-05-10
- https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries — `X-Hub-Signature-256: sha256=...`, HMAC-SHA256, raw body, constant-time compare, 조회 2026-05-10
- https://api.slack.com/authentication/verifying-requests-from-slack — `v0:{timestamp}:{body}`, `X-Slack-Signature` `v0=...`, 5분 tolerance, 조회 2026-05-10
- https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-idempotency-key-header-07 — IETF Idempotency-Key 표준 draft v07 (active 2025-10-15, expires 2026-04-18), 조회 2026-05-19
