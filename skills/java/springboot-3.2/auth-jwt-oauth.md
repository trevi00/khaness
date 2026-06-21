---
keywords: 인증 auth JWT jwt 토큰 token 로그인 login OAuth oauth 소셜로그인 social SecurityFilterChain SecurityConfig Spring Security 시큐리티 AccessToken RefreshToken 리프레시 액세스 구글 카카오 네이버 google kakao naver OAuth2 JwtFilter JwtService
intent: 로그인구현해 JWT구현해 인증구현해 OAuth구현해 소셜로그인구현해 시큐리티설정해 토큰발급해 로그인해 로그인만들어 인증해 JWT해
paths: src/auth src/security config/ src/main/java/**/auth src/main/java/**/jwt src/main/java/**/oauth src/main/java/**/login
patterns: SecurityFilterChain JwtFilter JwtService AbstractAuthenticationProcessingFilter OncePerRequestFilter CustomOAuth2UserService OAuth2LoginSuccessHandler UserDetailsService nimbus-jose-jwt
requires: security backend
phase: plan implement review
min_score: 3
---

# Spring Security + JWT + OAuth 2.0 Guide

## 아키텍처 개요

### 필터 체인 순서
```
LogoutFilter → JwtFilter → CustomJsonUsernamePasswordAuthenticationFilter
```
- `JwtFilter`: /login 이외 모든 요청에서 AccessToken/RefreshToken 검증
- `CustomJsonUsernamePasswordAuthenticationFilter`: /login POST 요청만 처리 (JSON 기반)
- OAuth2 로그인은 Spring Security의 `OAuth2LoginAuthenticationFilter`가 별도 처리

### 패키지 구조
```
auth/
├── jwt/
│   ├── filter/JwtFilter.java              # /login 이외 URI 인증 필터
│   ├── service/JwtService.java            # 토큰 생성/검증/추출
│   └── util/PasswordUtil.java             # OAuth 유저 랜덤 비밀번호 생성
├── login/
│   ├── filter/CustomJsonUsernamePasswordAuthenticationFilter.java
│   ├── handler/LoginSuccessHandler.java   # JWT 발급
│   ├── handler/LoginFailureHandler.java   # 에러 응답
│   └── service/LoginService.java          # UserDetailsService 구현체
├── oauth2/
│   ├── CustomOAuth2User.java              # OAuth2User 확장 (email, role 추가)
│   ├── OAuthAttributes.java               # 소셜별 응답 분기 DTO
│   ├── userinfo/
│   │   ├── OAuth2UserInfo.java            # 소셜별 유저 정보 추상 클래스
│   │   ├── GoogleOAuth2UserInfo.java
│   │   └── KakaoOAuth2UserInfo.java
│   ├── service/CustomOAuth2UserService.java  # OAuth 유저 정보 처리
│   └── handler/
│       ├── OAuth2LoginSuccessHandler.java
│       └── OAuth2LoginFailureHandler.java
config/
└── SecurityConfig.java                    # 전체 Security 설정
```

## 의사결정 트리

### IF JWT 인증 시스템 구현 (Implement)
1. application.yml에 JWT 설정 추가
   ```yaml
   jwt:
     secretKey: <최소 256bit 이상의 비밀키>
     access:
       expiration: 3600000       # 1시간
       header: Authorization
     refresh:
       expiration: 1209600000    # 14일
       header: Authorization-refresh
   ```
2. JwtService 구현 — nimbus-jose-jwt 사용 (HS256 + MACSigner/MACVerifier)
   - `createAccessToken(email)`: email 클레임 포함, 만료시간 설정
   - `createRefreshToken()`: 클레임 없이 만료시간만 설정
   - `extractAccessToken(request)`: Authorization 헤더에서 Bearer 제거 후 추출
   - `extractRefreshToken(request)`: Authorization-refresh 헤더에서 추출
   - `extractEmail(accessToken)`: 토큰에서 email 클레임 추출
   - `isTokenValid(token)`: 서명 검증
   - `sendAccessAndRefreshToken(response, accessToken, refreshToken)`: JSON 응답 바디로 전송
3. JwtFilter 구현 (OncePerRequestFilter 상속)
   - `/login` 요청은 통과 (NO_CHECK_URL)
   - RefreshToken 존재 시: DB 비교 → AccessToken + RefreshToken 재발급 (RTR 방식)
   - RefreshToken 없음 + AccessToken 유효: 인증 성공 → SecurityContextHolder 등록
   - RefreshToken 없음 + AccessToken 없음/무효: 인증 실패 → 403
4. **→ security 스킬: 비밀번호 정책, Rate Limiting 참고**

### IF 자체 로그인 (Form Login 커스텀) 구현 (Implement)
1. CustomJsonUsernamePasswordAuthenticationFilter 구현
   - `AbstractAuthenticationProcessingFilter` 상속
   - `/login` POST + `application/json`만 처리
   - request body에서 `email`, `password` 추출
   - `UsernamePasswordAuthenticationToken` 생성 → `AuthenticationManager.authenticate()` 호출
2. LoginService 구현 (UserDetailsService)
   - `loadUserByUsername(email)`: DB에서 유저 조회 → `UserDetails` 반환
   - 조회 실패 시 `UsernameNotFoundException`
3. LoginSuccessHandler 구현
   - AccessToken + RefreshToken 생성
   - 응답 바디에 JSON으로 전송
   - RefreshToken DB 저장 (RTR용)
4. LoginFailureHandler 구현
   - 400 응답 + 에러 메시지
5. AuthenticationManager 빈 등록
   ```java
   @Bean
   public AuthenticationManager authenticationManager() {
       DaoAuthenticationProvider provider = new DaoAuthenticationProvider();
       provider.setUserDetailsService(loginService);
       provider.setPasswordEncoder(passwordEncoder());
       return new ProviderManager(provider);
   }
   ```

### IF OAuth 2.0 소셜 로그인 구현 (Implement)
1. 소셜별 OAuth2UserInfo 구현
   - 추상 클래스: `getId()`, `getNickname()` 정의
   - 구글: `attributes.get("sub")` → ID, `attributes.get("name")` → 닉네임
   - 카카오: `attributes.get("id")` → ID, `kakao_account.profile.nickname` → 닉네임
2. OAuthAttributes 분기 DTO 구현
   - `of(socialType, userNameAttributeName, attributes)`: 소셜별 분기
   - `toUserDto()`: OAuth 정보 → 내 서비스 UserDto 변환
3. CustomOAuth2UserService 구현 (DefaultOAuth2UserService 상속)
   - `loadUser()`: OAuth2User 생성 → DB에 유저 존재 여부 확인 → 없으면 저장
   - CustomOAuth2User 반환 (email + role 추가 필드)
4. OAuth2LoginSuccessHandler: AccessToken + RefreshToken 발급
5. OAuth2LoginFailureHandler: 400 + 에러 메시지
6. Role enum 설계
   - `ROLE_GUEST`: OAuth 최초 가입 (추가 정보 미입력)
   - `ROLE_USER`: 추가 정보 입력 완료 또는 자체 로그인
   - 추가 정보 입력 불필요 시 GUEST/USER 구분 생략 가능

### IF SecurityConfig 설정 (Implement)
```java
http
    .formLogin().disable()
    .httpBasic().disable()
    .csrf().disable()
    .sessionManagement().sessionCreationPolicy(SessionCreationPolicy.STATELESS)
    .and()
    .authorizeRequests()
    .antMatchers("/", "/css/**", "/images/**", "/js/**", "/favicon.ico").permitAll()
    .antMatchers("/sign-up", "/login").permitAll()
    .anyRequest().authenticated()
    .and()
    .oauth2Login()
      .successHandler(oAuth2LoginSuccessHandler)
      .failureHandler(oAuth2LoginFailureHandler)
      .userInfoEndpoint().userService(customOAuth2UserService);

// 필터 순서 설정
http.addFilterAfter(customJsonUsernamePasswordAuthenticationFilter(), LogoutFilter.class);
http.addFilterBefore(jwtAuthenticationProcessingFilter(), CustomJsonUsernamePasswordAuthenticationFilter.class);
```

### IF 인증 코드 리뷰 (Review)
- [ ] secretKey가 yml에 평문으로 있지 않은가 (환경변수 사용)
- [ ] secretKey가 256bit(32바이트) 이상인가 (HS256 최소 요건)
- [ ] AccessToken 만료 시간이 적절한가 (15분~1시간)
- [ ] RefreshToken Rotation(RTR) 구현되어 있는가
- [ ] RefreshToken이 DB에 저장/검증되는가
- [ ] /login 외 모든 URI에 JwtFilter가 적용되는가
- [ ] OAuth 유저의 비밀번호가 null이 아닌 랜덤값으로 설정되는가
- [ ] CSRF가 disable인가 (JWT+Stateless에서는 정상)
- [ ] 세션 정책이 STATELESS인가
- [ ] 인증 실패 시 내부 정보가 노출되지 않는가

## 가이드

### JwtFilter 인증 흐름도
```
요청 → /login인가?
        ├─ YES → 다음 필터로 통과 (로그인 필터가 처리)
        └─ NO → RefreshToken 존재?
                 ├─ YES → DB의 RefreshToken과 비교
                 │         ├─ 일치 → AccessToken + RefreshToken 재발급 (RTR)
                 │         └─ 불일치 → 인증 실패
                 └─ NO → AccessToken 유효?
                          ├─ YES → email 추출 → DB 유저 조회 → SecurityContextHolder 등록 → 인증 성공
                          └─ NO → 인증 객체 없음 → 403
```

### OAuth2 로그인 전체 흐름
```
1. 프론트 → /oauth2/authorization/{social} 요청
2. OAuth2AuthorizationRequestRedirectFilter → 소셜 로그인 페이지로 리다이렉트
3. 사용자 → 소셜에서 동의/로그인
4. 소셜 → 인가코드와 함께 스프링 리다이렉트 URI로 콜백
5. OAuth2LoginAuthenticationFilter → 인가코드 추출
6. OAuth2LoginAuthenticationProvider → 인가코드로 AccessToken 요청 (소셜에)
7. CustomOAuth2UserService.loadUser() → AccessToken으로 유저정보 요청 → CustomOAuth2User 반환
8. SecurityContextHolder에 인증 객체 등록
9. OAuth2LoginSuccessHandler → JWT(AccessToken+RefreshToken) 발급 → 클라이언트 응답
```

### 소셜별 응답 구조 차이
| 소셜 | 식별키(PK) | 닉네임 경로 | nameAttributeKey |
|------|-----------|------------|-----------------|
| Google | `sub` | `name` | `sub` |
| Kakao | `id` | `kakao_account.profile.nickname` | `id` |
| Naver | `response.id` | `response.nickname` | `response` |

### nimbus-jose-jwt 사용 패턴
```java
// 토큰 생성
JWSSigner signer = new MACSigner(secretKey);
JWTClaimsSet claimsSet = new JWTClaimsSet.Builder()
    .subject("AccessToken")
    .expirationTime(new Date(now.getTime() + expiration))
    .claim("email", email)
    .build();
SignedJWT signedJWT = new SignedJWT(new JWSHeader(JWSAlgorithm.HS256), claimsSet);
signedJWT.sign(signer);
return signedJWT.serialize();

// 토큰 검증
SignedJWT signedJWT = SignedJWT.parse(token);
JWSVerifier verifier = new MACVerifier(secretKey);
return signedJWT.verify(verifier);
```

### PasswordUtil — OAuth 유저 비밀번호
OAuth 유저는 비밀번호가 null이지만, Spring Security 인증 과정에서 null 비밀번호는 에러 유발. JwtFilter의 `saveAuthentication()`에서 비밀번호가 null이면 랜덤 비밀번호 생성하여 UserDetails 구성.

## Gotchas

### JWT secretKey 길이 부족
HS256은 최소 256bit(32바이트) secretKey 필요. 짧으면 `WeakKeyException` 발생. yml에 충분히 긴 키 설정.

### RefreshToken DB 저장 누락
RefreshToken을 DB에 저장하지 않으면 RTR(Refresh Token Rotation) 검증 불가. `LoginSuccessHandler`와 `OAuth2LoginSuccessHandler` 모두에서 RefreshToken DB 저장 로직 구현 필수.

### OAuth 유저 비밀번호 null → 인증 실패
`saveAuthentication()`에서 비밀번호 null 체크 없이 UserDetails 빌드하면 에러. 반드시 null 체크 후 `PasswordUtil.generateRandomPassword()` 호출.

### CustomJsonFilter에서 Content-Type 체크 누락
`application/json`이 아닌 요청(form-data 등)도 /login으로 오면 필터에 잡힘. Content-Type 체크 후 `AuthenticationServiceException` 발생시켜야 함.

### 필터 순서 잘못 설정
`addFilterAfter(customFilter, LogoutFilter.class)` + `addFilterBefore(jwtFilter, CustomFilter.class)` 순서가 어긋나면 인증이 아예 동작하지 않음. 반드시 `LogoutFilter → JwtFilter → CustomLoginFilter` 순서 유지.

### OAuth registrationId 분기 누락
새 소셜 타입 추가 시 `getSocialType()`과 `OAuthAttributes.of()`에 분기 추가 필수. 누락 시 기본값(Google)으로 처리되어 잘못된 유저 정보 파싱.

### AccessToken 재발급 시 인증 처리 하지 않음
RefreshToken으로 AccessToken 재발급할 때는 `return`으로 필터 체인을 끊음. 이 요청에서 API 호출 결과를 기대하면 안 됨 — 클라이언트는 재발급받은 토큰으로 다시 요청해야 함.

### javax.servlet vs jakarta.servlet
Spring Boot 2.x는 `javax.servlet`, Spring Boot 3.x는 `jakarta.servlet`. 버전 이동 시 import 전체 변경 필요. 현재 회사 코드는 `javax.servlet` (Spring Boot 2.x 기반).

### sendAccessAndRefreshToken에서 response 이미 커밋됨
Handler에서 `response.getWriter().write()`를 호출하면 response가 커밋됨. 이후 다른 필터나 handler에서 response를 수정하려 하면 `IllegalStateException`. Handler는 응답을 한 번만 쓸 것.
