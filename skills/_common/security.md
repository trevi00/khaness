---
name: security
description: Auth, authorization, encryption, secret handling, OWASP/CSRF/CORS guidance — applied during implement/review/deploy phases.
keywords: 보안 security 인증 auth 권한 authorization JWT jwt 암호화 encryption 해싱 hashing 취약점 vulnerability XSS xss SQL injection CSRF csrf CORS cors 샌드박스 sandbox 시크릿 secret OWASP owasp Spring Security Rate Limiting 레이트리밋 PCI 로그인 login brute force credential stuffing MFA TOTP OAuth2 OIDC 비밀번호 password NIST 세션 session 계정잠금 account lockout
intent: 보안강화해 암호화해 인증구현해 취약점스캔해 CORS설정해 JWT적용해 보안해 보안검토해 보안확인해
paths: src/security src/auth shared/security/ middleware/ config/
patterns: bcrypt argon2 jsonwebtoken passport helmet cors csrf bandit trivy snyk owasp SecurityFilterChain Bucket4j LoginAttemptService AuthenticationFailureEvent WebAuthn
requires: [backend, framework]
phase: implement review deploy
min_score: 3
---

# Security Guide

## 의사결정 트리

### IF 인증 시스템 구현 (Implement)
1. JWT 토큰: Access(15-30분) + Refresh(7일) 분리
2. 비밀번호: Argon2id 권장 / bcrypt(strength≥12) (평문/MD5/SHA 절대 금지)
3. NIST SP 800-63B 비밀번호 정책 적용 (아래 심화 참고)
4. Brute Force 방어: LoginAttemptService + Rate Limiting + 계정 잠금
5. Refresh Token Rotation 구현 (탈취 방지)
6. 비밀번호 재설정: 토큰 해싱 저장 + 1회 사용 + 15-60분 만료
7. MFA 지원 고려 (TOTP 또는 WebAuthn)
8. 프로덕션 설정 Fail-Fast 검증 (아래 참고)

### IF Spring Boot 프로젝트 보안 (Implement)
1. SecurityFilterChain 설정 (아래 패턴 참고)
2. CORS 설정 (허용 origin 명시, 와일드카드 금지)
3. CSRF: REST API는 disable (JWT 사용 시), 폼 기반이면 enable
4. Actuator 엔드포인트 보안 (아래 참고)
5. 입력 검증: `@Valid` + Bean Validation
6. Rate Limiting: Bucket4j (아래 참고)

### IF 새 API 엔드포인트 보안 (Implement)
1. 인증 미들웨어 (JWT 검증)
2. 인가 확인 (리소스 소유자 검증 — IDOR 방지)
3. 입력 검증 (@Valid / Pydantic / Joi)
4. Rate Limiting (용도별)
5. ORM 파라미터 바인딩 (SQL Injection 방지)
6. 에러 메시지에 내부 정보 노출 금지

### IF 외부 코드 실행 (Implement)
Docker 샌드박스 필수:
- `--network none` / `--read-only` / `--pids-limit 50`
- `--memory 256m` / `--cpus 0.5` / `--tmpfs /tmp:noexec`

### IF 프론트엔드 보안 (Implement)
1. 토큰 저장: Access→메모리, Refresh→httpOnly 쿠키 (아래 참고)
2. XSS 방어: dangerouslySetInnerHTML 사용 시 DOMPurify 필수
3. CSP 헤더 설정 (script-src, connect-src 등)
4. 소스맵 프로덕션 비활성화
5. 외부 CDN 리소스에 SRI(Subresource Integrity) 적용

### IF DB 보안 설정 (Implement)
1. 애플리케이션 DB 계정: DML만 부여 (DDL 금지)
2. 모든 쿼리 파라미터 바인딩 (문자열 결합 금지)
3. 개인정보 컬럼 암호화 (AES-256-GCM + AttributeConverter)
4. 커넥션 풀 leak detection 활성화
5. 프로덕션 쿼리 로깅 비활성화 (민감 정보 보호)

### IF 보안 검토 (Review)
- [ ] 시크릿 하드코딩 없는지 확인
- [ ] CORS: 프로덕션에서 와일드카드(`*`) 금지
- [ ] .env가 .gitignore에 포함
- [ ] 에러 응답에 스택트레이스 노출 없음
- [ ] 의존성 취약점 스캔 통과
- [ ] Actuator 엔드포인트 잠금 확인
- [ ] 가격/수량 서버사이드 검증 확인 (쇼핑/주문 도메인)
- [ ] Security Headers 설정 확인 (CSP, HSTS, X-Frame-Options)
- [ ] 프론트엔드 소스맵 프로덕션 비활성화
- [ ] DB 계정 최소 권한 확인 (DROP/ALTER 없는지)
- [ ] 파일 업로드 화이트리스트 확인

### IF 배포 전 보안 점검 (Deploy)
1. 프로덕션 설정 검증 통과
2. 시크릿 관리 (환경변수/GitHub Secrets)
3. SSL/TLS 인증서 유효성
4. CORS 프로덕션 설정 확인
5. Actuator /health만 공개, 나머지 잠금

## OWASP Top 10:2025 — Spring Boot 대응

| # | 위협 | Spring Boot 대응 | 체크 |
|---|------|-----------------|------|
| A01 | Broken Access Control | `@PreAuthorize` + 리소스 소유자 검증 + IDOR 방지 (findByIdAndUserId) | |
| A02 | Cryptographic Failures | bcrypt 해싱 + JWT 시크릿 ≥256bit + HTTPS 강제 | |
| A03 | Injection | Spring Data 파라미터 바인딩 (네이티브 쿼리 시 `@Param`) + `@Valid` 입력 검증 | |
| A04 | Insecure Design | 비즈니스 로직 서버사이드 검증 (가격/재고/쿠폰 서버 계산) | |
| A05 | Security Misconfiguration | SecurityFilterChain 명시적 설정 + Actuator 잠금 + 에러 상세 숨김 | |
| A06 | Vulnerable Components | `./gradlew dependencyCheckAnalyze` (OWASP Dependency-Check) + Dependabot | |
| A07 | Auth Failures | Rate Limiting (Bucket4j) + 계정 잠금 + Refresh Token Rotation | |
| A08 | Data Integrity Failures | 서명 검증 (JWT) + 의존성 무결성 (Gradle verification-metadata.xml) | |
| A09 | Logging Failures | SLF4J 구조적 로깅 + 민감 정보 마스킹 + 감사 로그 | |
| A10 | SSRF | URL 화이트리스트 + 내부 IP 차단 (10.x, 172.16.x, 192.168.x) | |

## Spring Security 6.x — SecurityFilterChain 패턴

```java
@Bean
SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
    return http
        .csrf(csrf -> csrf.disable())  // REST API + JWT → CSRF 불필요
        .sessionManagement(sm -> sm.sessionCreationPolicy(STATELESS))
        .authorizeHttpRequests(auth -> auth
            // 공개 API
            .requestMatchers("/api/auth/**", "/api/products/**").permitAll()
            .requestMatchers("/actuator/health").permitAll()
            // 역할별 제한
            .requestMatchers("/api/admin/**").hasRole("ADMIN")
            .requestMatchers("/api/seller/**").hasAnyRole("SELLER", "ADMIN")
            // 나머지는 인증 필수
            .anyRequest().authenticated()
        )
        .addFilterBefore(jwtFilter, UsernamePasswordAuthenticationFilter.class)
        .exceptionHandling(ex -> ex
            .authenticationEntryPoint((req, res, e) ->
                res.sendError(401, "인증이 필요합니다"))
            .accessDeniedHandler((req, res, e) ->
                res.sendError(403, "접근 권한이 없습니다"))
        )
        .build();
}
```

## JWT Access + Refresh Token 패턴

```
[로그인 흐름]
1. POST /api/auth/login { email, password }
2. 서버: Access Token (30분) + Refresh Token (7일) 발급
3. Refresh Token은 DB/Redis에 저장 (사용자별 1개)

[토큰 갱신 — Rotation]
1. POST /api/auth/refresh { refreshToken }
2. 서버: 기존 Refresh Token 무효화 + 새 Access/Refresh Token 쌍 발급
3. 이전 Refresh Token 재사용 시도 → 토큰 탈취 감지 → 해당 사용자 전체 세션 무효화

[로그아웃]
1. POST /api/auth/logout
2. 서버: Refresh Token 삭제 + Access Token 블랙리스트 등록 (남은 TTL만큼)
```

**핵심 보안 규칙**:
- Access Token: 짧은 수명 (15-30분), 블랙리스트 최소화
- Refresh Token: 1회성 사용 (Rotation), DB/Redis 저장
- JWT 시크릿: ≥256bit, 환경변수로 주입 (`${JWT_SECRET}`)
- 토큰 페이로드: userId + role만 포함 (민감 정보 금지)

## 로그인/인증 보안 심화

### NIST SP 800-63B Rev.4 비밀번호 정책

| 항목 | 요구사항 |
|------|---------|
| 최소 길이 | MFA 있음: 8자 / MFA 없음: 15자 |
| 최대 길이 | ≥64자 지원 (절삭 금지) |
| 복잡도 규칙 | **폐지** — 대소문자/특수문자 강제 금지 |
| 유출 DB 검사 | 필수 — HaveIBeenPwned API로 검증 |
| 주기적 변경 | **폐지** — 유출 의심 시에만 변경 요구 |
| 해싱 | Argon2id 권장, bcrypt(strength≥12)/scrypt 허용 |

### Brute Force / Credential Stuffing 방어

```java
// LoginAttemptService — IP + 이메일 이중 추적 (Guava Cache, 24h 만료)
@Service
public class LoginAttemptService {
    private final LoadingCache<String, Integer> attemptsCache =
        CacheBuilder.newBuilder()
            .expireAfterWrite(24, TimeUnit.HOURS)
            .build(CacheLoader.from(() -> 0));
    private static final int MAX_ATTEMPTS = 5;

    public void loginFailed(String key) {
        attemptsCache.put(key, attemptsCache.getUnchecked(key) + 1);
    }
    public void loginSucceeded(String key) { attemptsCache.invalidate(key); }
    public boolean isBlocked(String key) {
        return attemptsCache.getUnchecked(key) >= MAX_ATTEMPTS;
    }
}

// Spring Event Listener — 실패 시 IP+이메일 이중 카운트
@Component
public class AuthFailureListener {
    @EventListener
    public void onFailure(AuthenticationFailureBadCredentialsEvent e) {
        loginAttemptService.loginFailed("ip:" + getClientIP(request));
        loginAttemptService.loginFailed("email:" + e.getAuthentication().getName());
    }
}
```

**방어 계층화** (순서대로 적용):
1. **Rate Limiting** (Bucket4j) — IP당 로그인 5회/분 제한
2. **계정 잠금** — 5회 연속 실패 → 30분 잠금 (+ 관리자 수동 해제)
3. **CAPTCHA** — 3회 실패 후 reCAPTCHA v3 표시
4. **보안 알림** — 비정상 패턴(다수 계정 시도 등) 감지 시 알림

**응답 일관성** (계정 열거 방지):
- 로그인 실패 시 항상 동일 메시지: `"이메일 또는 비밀번호가 올바르지 않습니다"`
- 절대 `"사용자를 찾을 수 없습니다"` / `"비밀번호가 틀립니다"` 구분 금지

### 비밀번호 재설정 보안

```
[안전한 재설정 흐름]
1. POST /api/auth/forgot-password { email }
   → 이메일 존재 여부 무관하게 동일 응답 ("발송 완료") — 열거 공격 방지
2. 서버: UUID 토큰 생성 → SHA-256 해싱 후 DB 저장 (만료: 15-60분)
3. 이메일로 리셋 링크 발송 (HTTPS 필수)
4. POST /api/auth/reset-password { token, newPassword }
   → 토큰 검증 → 1회 사용 후 즉시 삭제
   → 해당 사용자의 모든 Refresh Token + 세션 무효화
```

**핵심 규칙**:
- 토큰: UUID → SHA-256 해싱 저장, 15-60분 만료, 1회 사용
- 재설정 요청도 Rate Limit 적용 (동일 IP 3회/시간)
- 새 비밀번호 설정 후 기존 모든 세션 강제 종료

### MFA (Multi-Factor Authentication)

| 방식 | 보안 수준 | 비고 |
|------|----------|------|
| FIDO2/WebAuthn | ★★★ | 피싱 방지 (도메인 바인딩), 최우선 권장 |
| TOTP (Google Authenticator) | ★★☆ | 30초 OTP, 구현 간단, 대부분 서비스에 적합 |
| SMS OTP | ★☆☆ | SIM swap 취약, 최후 수단으로만 사용 |

**TOTP 구현 시 필수사항**:
- 공유 시크릿: 암호화 후 DB 저장 (평문 저장 금지)
- 복구 코드: 10개 사전 생성, bcrypt 해싱 저장, 1회 사용
- 시간 허용 범위: ±1 윈도우 (30초 드리프트 허용)
- 등록 시 QR코드 + 수동 입력 키 모두 제공

### OAuth2/OIDC 소셜 로그인

```yaml
# application.yml — 소셜 로그인 보안 설정
spring:
  security:
    oauth2:
      client:
        registration:
          google:
            client-id: ${GOOGLE_CLIENT_ID}     # 환경변수 필수
            client-secret: ${GOOGLE_CLIENT_SECRET}
            scope: openid, email, profile
```

**보안 규칙**:
- **PKCE 필수** — Spring Security 7.0에서 기본 활성화
- **client-secret**: 환경변수 / 시크릿 매니저 (하드코딩 절대 금지)
- **state 파라미터**: CSRF 방지 (Spring Security 자동 처리)
- **ID Token**: 서명 검증 자동 처리 (수동 파싱 금지)
- **회원 연동**: 이메일 기반 연동 시 `email_verified=true` 반드시 확인

### 세션 보안 (서버 세션 사용 시)

```java
http.sessionManagement(sm -> sm
    .sessionFixation().migrateSession()  // 인증 후 세션 ID 갱신 (기본값)
    .maximumSessions(1)                  // 동시 로그인 1개 제한
    .maxSessionsPreventsLogin(false)     // 새 로그인이 기존 세션 만료
);
```

- **쿠키 보안**: `httpOnly=true`, `secure=true`, `SameSite=Lax`
- **세션 타임아웃**: 비활동 30분 (`server.servlet.session.timeout=30m`)

## Rate Limiting — Bucket4j (Spring Boot)

```java
// 용도별 Rate Limit 설정
@Bean
public Map<String, Bandwidth> rateLimits() {
    return Map.of(
        "login",    Bandwidth.classic(5, Refill.intervally(5, Duration.ofMinutes(1))),  // 5/분
        "api",      Bandwidth.classic(100, Refill.intervally(100, Duration.ofMinutes(1))), // 100/분
        "payment",  Bandwidth.classic(10, Refill.intervally(10, Duration.ofMinutes(1)))  // 10/분
    );
}
```

**키 전략**: 인증된 사용자 → userId 기반, 미인증 → IP 기반 (X-Forwarded-For 신뢰 범위 제한)

## 쇼핑/주문 도메인 특화 보안

### 가격 조작 방지 (A04 Insecure Design)
```
[금지] 클라이언트가 보낸 가격으로 결제
[필수] 서버에서 상품 가격 재조회 → 주문 금액 서버 계산
  - 주문 생성 시: DB에서 상품 가격 조회 → 서버 합산
  - 쿠폰 적용: 서버에서 할인 계산 (클라이언트 값 무시)
  - 결제 금액: 주문 서비스가 계산한 금액만 사용
```

### IDOR (Insecure Direct Object Reference) 방지
```java
// [금지] 단순 ID 조회 — 타인 리소스 접근 가능
orderRepository.findById(orderId);

// [필수] 소유자 + ID 조회
orderRepository.findByIdAndBuyerId(orderId, currentUserId)
    .orElseThrow(() -> new NotFoundException("주문을 찾을 수 없습니다"));
// 타인 리소스 → 404 (403이 아닌 404로 존재 자체를 숨김)
```

### 재고/쿠폰 동시성 보안
- `SELECT FOR UPDATE`로 비관적 락 (재고 차감, 쿠폰 수령)
- 결제 멱등성: `orderId UNIQUE` 제약 → `DuplicateKeyException` 처리
- 쿠폰 중복 수령: `userId + couponId UNIQUE` 제약

### PCI DSS 4.0 핵심 (결제 처리 도메인)
- 카드 정보 직접 저장 금지 → PG사 토큰화 사용 (MockPaymentGateway)
- 결제 관련 로그에 카드번호/CVV 절대 포함 금지
- 결제 API 접근 로그 별도 보관 (감사 추적)

## Spring Boot Actuator 보안

```yaml
# application.yml — 프로덕션 필수 설정
management:
  endpoints:
    web:
      exposure:
        include: health,info,metrics  # 최소한만 노출
  endpoint:
    health:
      show-details: when-authorized   # 인증된 사용자만 상세
    env:
      enabled: false                  # 환경변수 노출 금지
    beans:
      enabled: false                  # 빈 목록 노출 금지
  server:
    port: 9090                        # 별도 포트 (선택적)
```

**Actuator 보안 함정**:
- `include: "*"` → 모든 엔드포인트 노출 (heapdump, env, configprops 포함)
- `/actuator/env` → 환경변수 노출 (DB 비밀번호, JWT 시크릿 등)
- `/actuator/heapdump` → JVM 메모리 덤프 (시크릿 추출 가능)
- **규칙**: 프로덕션에서 health/info/metrics 외 모두 비활성화

## API 보안 체크리스트

```
[인증/인가]
□ 모든 API에 JWT 검증 필터 적용 (공개 API 제외)
□ 역할별 접근 제어 (@PreAuthorize 또는 SecurityFilterChain)
□ 리소스 소유자 검증 (findByIdAndUserId 패턴)
□ 타인 리소스 접근 시 404 반환 (존재 여부 숨김)

[입력 검증]
□ @Valid + Bean Validation (NotNull, Size, Pattern 등)
□ 경로 변수 타입 검증 (Long id → NumberFormatException 처리)
□ 페이징 파라미터 상한 설정 (size ≤ 100)
□ 정렬 필드 화이트리스트 (임의 필드명 정렬 금지)

[출력 보안]
□ 에러 응답에 스택트레이스 미포함 (spring.mvc.log-resolved-exception=false)
□ 비밀번호/토큰 응답 제외 (@JsonIgnore)
□ 페이지네이션으로 대량 데이터 노출 방지

[전송 보안]
□ HTTPS 강제 (spring.security.require-ssl=true)
□ CORS 허용 origin 명시적 설정
□ Content-Security-Policy 헤더 설정
□ X-Content-Type-Options: nosniff
```

## 백엔드 보안 심화

### Security HTTP Response Headers (Spring Security)

```java
http.headers(headers -> headers
    // Clickjacking 방지
    .frameOptions(frame -> frame.deny())
    // MIME 타입 스니핑 방지
    .contentTypeOptions(Customizer.withDefaults())  // X-Content-Type-Options: nosniff
    // XSS 필터 (레거시 브라우저용)
    .xssProtection(xss -> xss.headerValue(
        XXssProtectionHeaderWriter.HeaderValue.ENABLED_MODE_BLOCK))
    // HSTS — HTTPS 강제 (1년 + 서브도메인 + preload)
    .httpStrictTransportSecurity(hsts -> hsts
        .includeSubDomains(true)
        .preload(true)
        .maxAgeInSeconds(31536000))
    // CSP — 스크립트/리소스 출처 제한
    .contentSecurityPolicy(csp -> csp
        .policyDirectives("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; frame-ancestors 'none'"))
    // Referrer 정보 제한
    .referrerPolicy(ref -> ref.policy(ReferrerPolicyHeaderWriter.ReferrerPolicy.STRICT_ORIGIN_WHEN_CROSS_ORIGIN))
    // Feature Policy / Permissions Policy
    .permissionsPolicy(perm -> perm.policy("camera=(), microphone=(), geolocation=()"))
);
```

### 에러 응답 보안

```java
// GlobalExceptionHandler — 내부 정보 노출 방지
@RestControllerAdvice
public class GlobalExceptionHandler {
    @ExceptionHandler(Exception.class)
    public ResponseEntity<ErrorResponse> handleAll(Exception e) {
        log.error("Unhandled exception", e);  // 로그에만 스택트레이스
        return ResponseEntity.status(500)
            .body(new ErrorResponse("서버 오류가 발생했습니다"));  // 클라이언트엔 일반 메시지
    }
}
```

**규칙**:
- `spring.mvc.log-resolved-exception=false` — 에러 상세 로깅 제한
- `server.error.include-stacktrace=never` — 스택트레이스 응답 포함 금지
- `server.error.include-message=never` — 예외 메시지 응답 포함 금지
- 검증 실패(400): 어떤 필드가 잘못됐는지만 알려줌 (내부 로직 노출 금지)

### 보안 로깅 (감사 추적)

```java
// 민감 정보 마스킹 패턴
@Slf4j
public class SecurityAuditLogger {
    public void logLoginAttempt(String email, boolean success, String ip) {
        log.info("LOGIN {} email={} ip={}",
            success ? "SUCCESS" : "FAILURE",
            maskEmail(email),   // u***@gmail.com
            ip);
    }
    // 절대 로그에 포함 금지: 비밀번호, 토큰, 카드번호, 주민번호
}
```

### 의존성 취약점 관리

```groovy
// build.gradle — OWASP Dependency-Check
plugins { id 'org.owasp.dependencycheck' version '11.x' }
dependencyCheck { failBuildOnCVSS = 7.0 }  // CVSS 7.0 이상이면 빌드 실패
```

- CI 파이프라인에 `./gradlew dependencyCheckAnalyze` 포함
- GitHub Dependabot 활성화 (자동 보안 PR)
- Snyk/Trivy 추가 스캔 권장

### 파일 업로드 보안

- 확장자 화이트리스트 (`.jpg`, `.png`, `.pdf` — 블랙리스트 금지)
- 파일 크기 제한 (`spring.servlet.multipart.max-file-size=5MB`)
- 저장 파일명: UUID 재생성 (원본 파일명 사용 금지 — 경로 탐색 방지)
- 업로드 경로: 웹 루트 외부 (`/var/uploads/`, S3 등)
- Content-Type 실제 검증 (확장자만 믿지 말 것)

## 프론트엔드 보안

### XSS 방어

**React/Next.js 기본 방어**:
- JSX `{}` 내 동적 값은 자동 이스케이프됨 (기본 안전)
- `dangerouslySetInnerHTML` 사용 시 반드시 DOMPurify로 정제

```javascript
// [금지] 사용자 입력을 그대로 삽입
<div dangerouslySetInnerHTML={{ __html: userInput }} />

// [필수] DOMPurify로 정제 후 삽입
import DOMPurify from 'dompurify';
<div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(userInput) }} />
```

**추가 방어**:
- `eval()`, `new Function()`, `innerHTML` 직접 사용 금지
- URL 파라미터를 DOM에 렌더링 시 반드시 이스케이프
- Markdown 렌더러 사용 시 HTML 태그 필터링 확인

### 토큰 저장 전략

| 저장소 | XSS 취약 | CSRF 취약 | 권장 |
|--------|----------|----------|------|
| localStorage | ★★★ 위험 | 안전 | 금지 |
| sessionStorage | ★★☆ 위험 | 안전 | 비권장 |
| 일반 쿠키 | ★★☆ 위험 | ★★★ 위험 | 금지 |
| httpOnly 쿠키 | 안전 | ★★☆ 위험 | **권장** (+ CSRF 토큰) |
| 메모리 (변수/상태) | 안전 | 안전 | **최적** (새로고침 시 소실) |

**권장 하이브리드 패턴**:
- Access Token → 메모리(React state/context)에 보관
- Refresh Token → httpOnly + Secure + SameSite=Strict 쿠키
- 새로고침 시 → `/api/auth/refresh` 자동 호출로 Access Token 재발급

### Content Security Policy (프론트엔드)

```html
<!-- Next.js — next.config.js 또는 middleware.ts -->
Content-Security-Policy:
  default-src 'self';
  script-src 'self' 'nonce-{random}';  <!-- 인라인 스크립트는 nonce 필수 -->
  style-src 'self' 'unsafe-inline';    <!-- CSS-in-JS 사용 시 -->
  img-src 'self' data: https:;
  font-src 'self';
  connect-src 'self' https://api.example.com;  <!-- API 서버 명시 -->
  frame-ancestors 'none';              <!-- Clickjacking 방지 -->
```

### Subresource Integrity (SRI)

```html
<!-- 외부 CDN 스크립트 변조 방지 -->
<script src="https://cdn.example.com/lib.js"
  integrity="sha384-abc123..."
  crossorigin="anonymous"></script>
```

- CDN 장악 시 악성 스크립트 주입 방지
- Next.js: `experimental.sri.algorithm = 'sha384'` 설정

### 프론트엔드 보안 체크리스트

```
[XSS 방어]
□ dangerouslySetInnerHTML 사용 시 DOMPurify 적용
□ URL 파라미터 → DOM 렌더링 시 이스케이프
□ eval(), new Function() 미사용
□ 서드파티 라이브러리 정기 업데이트

[인증/토큰]
□ Access Token은 메모리에만 보관 (localStorage 금지)
□ Refresh Token은 httpOnly 쿠키로 전송
□ 토큰 만료 시 자동 갱신 로직

[통신 보안]
□ HTTPS 전용 (mixed content 금지)
□ API 호출 시 CSRF 토큰 포함 (쿠키 인증 시)
□ CORS 에러 발생 시 브라우저 콘솔 확인

[빌드/배포]
□ 소스맵 프로덕션 비활성화 (코드 노출 방지)
□ CSP 헤더 설정 및 report-uri 모니터링
□ SRI 적용 (외부 CDN 리소스)
```

## 데이터베이스 보안

### SQL Injection 방어 계층

```java
// [1순위] Spring Data Repository — 자동 파라미터 바인딩
List<Product> findByNameContaining(String keyword);

// [2순위] JPQL — 네임드 파라미터
@Query("SELECT p FROM Product p WHERE p.name = :name")
Product findByName(@Param("name") String name);

// [3순위] Native Query — 반드시 @Param 사용
@Query(value = "SELECT * FROM products WHERE category = :cat", nativeQuery = true)
List<Product> findByCategory(@Param("cat") String category);

// [금지] 문자열 결합 쿼리
@Query("SELECT * FROM products WHERE name = '" + name + "'")  // SQL Injection!
```

**JdbcTemplate도 동일 규칙**:
```java
// [안전] 파라미터 바인딩
jdbcTemplate.query("SELECT * FROM users WHERE email = ?", mapper, email);

// [금지] 문자열 결합
jdbcTemplate.query("SELECT * FROM users WHERE email = '" + email + "'", mapper);
```

### 컬럼 레벨 암호화 (JPA AttributeConverter)

```java
// 민감 컬럼(주민번호, 카드번호 등) 자동 암호화/복호화
@Converter
public class AesEncryptConverter implements AttributeConverter<String, String> {
    private static final String ALGO = "AES/GCM/NoPadding";

    @Override
    public String convertToDatabaseColumn(String attribute) {
        // 암호화: AES-256-GCM + 랜덤 IV → Base64
    }

    @Override
    public String convertToEntityAttribute(String dbData) {
        // 복호화: Base64 → IV 분리 → AES-256-GCM 복호화
    }
}

// Entity에서 사용
@Convert(converter = AesEncryptConverter.class)
@Column(name = "resident_number")
private String residentNumber;  // DB에는 암호문 저장
```

**핵심 규칙**:
- 알고리즘: AES-256-GCM (인증된 암호화, IV 재사용 금지)
- 키 관리: 환경변수/Vault (코드/DB에 키 저장 금지)
- 암호화 대상: 주민번호, 카드번호, 전화번호, 주소 등 개인정보

### 최소 권한 원칙

```sql
-- 애플리케이션 전용 DB 계정 — 필요한 권한만 부여
CREATE USER 'app_user'@'%' IDENTIFIED BY '${DB_PASSWORD}';
GRANT SELECT, INSERT, UPDATE, DELETE ON ecommerce.* TO 'app_user'@'%';
-- DROP, ALTER, CREATE, GRANT 권한 절대 부여 금지

-- 마이그레이션 전용 계정 (CI/CD에서만 사용)
CREATE USER 'migration_user'@'%' IDENTIFIED BY '${MIGRATION_PASSWORD}';
GRANT ALL PRIVILEGES ON ecommerce.* TO 'migration_user'@'%';
```

### 커넥션 풀 보안 (HikariCP)

```yaml
spring:
  datasource:
    hikari:
      maximum-pool-size: 20           # 과도한 커넥션 방지
      minimum-idle: 5
      connection-timeout: 30000       # 30초 타임아웃
      idle-timeout: 600000            # 유휴 10분 후 반환
      max-lifetime: 1800000           # 30분마다 커넥션 재생성 (보안)
      leak-detection-threshold: 60000 # 60초 이상 미반환 시 경고 로그
```

### DB 감사 로그

```sql
-- 주요 테이블에 감사 컬럼 추가
ALTER TABLE orders ADD COLUMN created_by BIGINT;
ALTER TABLE orders ADD COLUMN updated_by BIGINT;
ALTER TABLE orders ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE orders ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP;
```

```java
// MyBatis — 수동 감사 (CommonHeaderDTO의 creator/updater 활용)
@Getter @Setter
public class Order {
    private Long createdBy;     // INSERT 시 CommonHeaderDTO.creator에서 주입
    private Long updatedBy;     // UPDATE 시 CommonHeaderDTO.updater에서 주입
    private LocalDateTime createdAt;   // DB DEFAULT CURRENT_TIMESTAMP 또는 Service에서 설정
    private LocalDateTime updatedAt;   // Service에서 LocalDateTime.now() 설정
}
// MyBatis XML: #{createdBy}, #{updatedBy}로 바인딩
```

### DB 보안 체크리스트

```
[접근 제어]
□ 애플리케이션 계정에 최소 권한만 부여 (DROP/ALTER 금지)
□ 마이그레이션 계정 분리 (CI/CD 전용)
□ DB 포트 외부 노출 금지 (VPC 내부만 접근)
□ root/admin 계정 원격 접속 금지

[데이터 보호]
□ 개인정보 컬럼 암호화 (AES-256-GCM)
□ 비밀번호는 해싱만 (암호화 아님 — 복호화 불가해야 함)
□ 백업 데이터 암호화
□ 로그에 쿼리 파라미터 (민감 정보) 미포함

[쿼리 보안]
□ 모든 쿼리 파라미터 바인딩 사용
□ 동적 정렬/필터에 화이트리스트 적용
□ 벌크 조회 시 LIMIT 강제

[모니터링]
□ Slow query 로그 활성화 (3초 이상)
□ 커넥션 풀 leak detection 활성화
□ 실패한 로그인 시도 DB 레벨 로깅
```

## 프로덕션 Fail-Fast 검증 (필수)

```java
@Component
public class SecurityConfigValidator implements ApplicationRunner {
    @Value("${jwt.secret}") private String jwtSecret;
    @Value("${cors.allowed-origins}") private String corsOrigins;

    @Override
    public void run(ApplicationArguments args) {
        if (jwtSecret.length() < 32)
            throw new IllegalStateException("JWT secret must be >= 32 chars");
        if (corsOrigins.contains("*"))
            throw new IllegalStateException("Wildcard CORS forbidden in production");
    }
}
```

## Gotchas

### JWT를 localStorage에 저장
XSS 공격 시 탈취 가능. httpOnly 쿠키가 더 안전하지만 CSRF 방어 필요. 트레이드오프를 이해하고 선택할 것.

### bcrypt 72바이트 제한
bcrypt는 입력을 72바이트에서 자름. 긴 비밀번호 지원이 필요하면 먼저 SHA-256으로 해싱 후 bcrypt 적용 (pre-hashing).

### CORS preflight 캐싱 미설정
`Access-Control-Max-Age` 미설정 시 모든 요청마다 OPTIONS preflight 발생 → 성능 저하. 적절한 캐시 시간 설정.

### Rate Limiting IP 위조
X-Forwarded-For 헤더를 무조건 신뢰하면 공격자가 IP 위조 가능. 리버스 프록시가 설정한 헤더만 신뢰하도록 설정.

### .env.example 동기화 누락
새 환경변수 추가 시 `.env.example` 업데이트를 잊으면 다른 개발자가 앱 시작 실패. CI에서 검증 스크립트 추가 권장.

### 계정 열거 공격 (Account Enumeration)
"User not found" vs "Invalid credentials" — 로그인 실패 시 사용자 존재 여부를 노출하면 계정 열거에 취약. 항상 동일한 에러 메시지 사용.

### Refresh Token Rotation 미구현
Refresh Token 탈취 시 공격자가 무한히 재사용 가능. Refresh Token 사용 시 새 토큰을 발급하고 이전 토큰을 무효화하는 rotation 구현 필요.

### Content-Security-Policy 미설정
CSP 헤더 없이 배포하면 인라인 스크립트, 외부 스크립트 로드가 제한 없이 가능 → XSS 공격 표면 증가.

### Spring Boot Actuator 전체 노출
`management.endpoints.web.exposure.include=*` 설정 시 heapdump, env 등이 공개됨. 프로덕션에서는 health/info/metrics만 노출.

### 가격을 클라이언트에서 전송
주문/결제 시 클라이언트가 보낸 가격을 그대로 사용하면 가격 조작 가능. 반드시 서버에서 DB 조회 후 재계산.

### NIST 정책 미적용 — 복잡도 규칙 강제
"대문자+소문자+숫자+특수문자" 강제는 NIST SP 800-63B Rev.4에서 폐지. 사용자 경험만 악화시키고 보안 효과 미미. 대신 최소 길이 + 유출 DB 검사로 대체.

### 비밀번호 재설정 토큰 평문 저장
재설정 토큰을 DB에 평문 저장하면, DB 탈취 시 모든 사용자 계정 접근 가능. SHA-256 해싱 후 저장 필수.

### OAuth2 이메일 기반 자동 연동
소셜 로그인 시 이메일만으로 기존 계정에 자동 연동하면, 미인증 이메일로 타인 계정 탈취 가능. `email_verified=true` 반드시 확인.

### MFA 복구 코드 미제공
TOTP 등록 후 복구 코드 없이 배포하면, 기기 분실 시 계정 영구 잠금. 등록 시점에 10개 복구 코드 발급 필수.

### 프로덕션에 소스맵 배포
프론트엔드 빌드 시 소스맵을 프로덕션에 배포하면 전체 소스코드가 브라우저 DevTools에 노출됨. `productionSourceMap: false` 설정.

### 파일 업로드 확장자 블랙리스트
`.exe`, `.bat` 차단만으로는 부족 — `.jsp`, `.php`, `.svg`(XSS 가능) 등 우회 가능. 반드시 화이트리스트 방식 사용.

### DB 계정에 DDL 권한 부여
애플리케이션 DB 계정에 DROP/ALTER 권한이 있으면, SQL Injection 시 테이블 삭제 가능. 반드시 DML 권한만 부여.

### AES 암호화 시 IV 재사용
동일 키+동일 IV로 암호화하면 패턴 분석으로 복호화 가능. 매 암호화마다 랜덤 IV 생성 필수 (AES-GCM).

### 쿼리 로그에 민감 정보 포함
`spring.jpa.show-sql=true` + 바인딩 파라미터 로깅 시 비밀번호/개인정보가 로그에 남음. 프로덕션에서 쿼리 로깅 비활성화 또는 마스킹.

## 도구 사용 패턴 (Harness)
- 시크릿 스캔: `Grep`으로 API_KEY, SECRET, PASSWORD 패턴 검색 (Bash(grep) 대신)
- 의존성 취약점: `Bash`로 `./gradlew dependencyCheckAnalyze` / `npm audit` 실행
- 권한 확인: 설정 파일은 `Read`로 확인, 런타임 권한은 `Bash`로 테스트
- .env 파일은 절대 `Write`로 생성하지 말 것 — 시크릿이 커밋될 위험
- Actuator 노출 확인: `Read`로 application.yml의 management 섹션 확인

## 에러 복구 패턴 (Harness)
- 인증 실패(401) → `Grep`으로 토큰 생성/검증 로직 확인, 만료 시간 점검
- 권한 거부(403) → `Read`로 SecurityFilterChain/RBAC 설정 확인, 역할 매핑 점검
- CORS 에러 → `Grep("cors|CORS|allowedOrigins")`로 설정 검색, 허용 origin 목록 확인
- 시크릿 로딩 실패 → `Read`로 application.yml 확인, `Bash(printenv)`로 환경변수 비교
- Rate Limit 오탐 → `Read`로 Bucket4j 설정 확인, 용도별 limit 적정성 점검

## Related (신규 그래프 cross-ref)

security가 보강되는 신규 노드:
- `_common/webhook-delivery-and-signing.md` — HMAC-SHA256 서명 + timestamp tolerance 5분 + raw body 검증 (Stripe/GitHub/Slack 표준)
- `_common/load-shedding-prioritized.md` — 503 + Retry-After (criticality tier별 차등) — DoS 보호의 중간 layer
- `_common/chaos-engineering.md` — security 테스트와 다른 디시플린, 단 chaos 실험 자체는 PII scope 제외 강제
- `_common/edge-gateway-routing.md` — Envoy JWT authn filter + Istio mTLS (Istiod CA 자동 cert rotation)
- `kotlin/android/dagger-hilt-di-architecture.md` — `@ApplicationContext` 강제로 Activity/Fragment ref 누수 차단
- `_common/dlq-reprocessing-wal.md` — DLQ 메시지에 PII 포함 가능 — DLQ access RBAC + 마스킹
