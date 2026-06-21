---
keywords: 컴파일 compile 빌드 build 점진적 incremental 개발루프 dev-loop 개발진행 development 구현 implement 단위 unit 모듈 module 오류수정 에러수정 fix 반복 iteration 피드백 feedback 빌드확인 build-check 타입체크 typecheck
intent: 개발진행해 구현시작해 빌드하면서해 컴파일확인해 개발해 빌드해 컴파일해 빌드안돼 빌드에러
paths: src/ backend/ frontend/ build/ dist/
patterns: gradlew gradle npm vite tsc javac bootRun bootJar clean build test
requires: backend frontend testing
phase: implement
min_score: 3
---

# Incremental Build Loop Guide

> 파이프라인: 12단계(개발 진행) — 매 단위 컴파일 + 서버 시작 + curl 테스트
> 검증: B1-B4 이진 체크리스트 (매 단위 반복)

코드를 작성하면서 컴파일/빌드를 반복 확인하여 에러를 조기에 잡는 점진적 개발 루프.

## 의사결정 트리

### IF 백엔드 점진적 개발 (Implement)
아래 **개발 단위**를 하나씩 구현하고, 매 단위마다 컴파일 확인:

```
[개발 단위 순서 — 의존성 기반]
1. global/ (CommonResponse, ErrorCode, BusinessException, Custom Annotation)
   → ./gradlew compileJava

2. domain/{도메인}/ (Entity, Enum, Repository 인터페이스, Exception)
   → ./gradlew compileJava
   도메인 간 의존 없는 것부터 (User → Product → Category → ...)

3. application/{도메인}/ (Service, DTO)
   → ./gradlew compileJava
   Service에서 다른 Service 호출이 있으면 피호출자 먼저

4. infrastructure/ (Config, Kafka, Redis, PaymentGateway)
   → ./gradlew compileJava

5. interfaces/{도메인}/ (Controller, Request/Response DTO)
   → ./gradlew compileJava

6. 전체 빌드 + 서버 시작
   → ./gradlew clean build
   → ./gradlew bootRun (서버 시작 확인)
```

### IF 프론트엔드 점진적 개발 (Implement)
```
[개발 단위 순서 — FSD 의존성 기반]
1. shared/ (api client, types, ui components, lib)
   → npm run build (또는 npx tsc --noEmit)

2. entities/{도메인}/ (api queries, model types, ui components)
   → npm run build
   도메인 간 의존 없으므로 순서 무관

3. features/{기능}/ (api mutations, ui forms)
   → npm run build

4. widgets/ (Header, Footer, Sidebar)
   → npm run build

5. pages/{페이지}/ (페이지 컴포넌트 + 라우팅)
   → npm run build

6. app/ (providers, routes, entry)
   → npm run build (최종)
   → npm run dev (dev 서버 시작 확인)
```

### IF 풀스택 연동 개발 (Implement)
```
1. 백엔드 도메인 1개 완성 (Entity → Service → Controller)
2. 컴파일 + 서버 시작 + curl로 API 테스트
3. 프론트 해당 도메인 연동 (entities/api → features → pages)
4. 빌드 + 브라우저 확인
5. 다음 도메인으로 반복
```

## 개발 단위별 빌드 명령

### 백엔드 (Spring Boot + Gradle)
```bash
# 컴파일만 (빠름, 문법/타입 에러 확인)
cd backend && ./gradlew compileJava

# 전체 빌드 (컴파일 + 리소스 + 패키징)
./gradlew clean build

# 테스트 포함 빌드
./gradlew clean build  # 기본적으로 test 포함

# 테스트 제외 빌드 (빠른 확인용)
./gradlew clean build -x test

# 서버 시작
./gradlew bootRun

# 특정 클래스만 컴파일 확인 (Gradle은 증분 빌드)
./gradlew compileJava  # 변경된 파일만 재컴파일
```

### 프론트엔드 (React + Vite + TypeScript)
```bash
# 타입 체크만 (빠름)
cd frontend && npx tsc --noEmit

# 전체 빌드 (타입 체크 + 번들링)
npm run build

# dev 서버 (HMR, 변경 시 자동 반영)
npm run dev

# 린트
npm run lint
```

## 이진 검증 체크리스트 (B1-B4, 매 단위 반복)

| # | 체크 항목 | PASS 기준 | 측정 방법 |
|---|----------|----------|----------|
| B1 | 컴파일 통과 | `compileJava` / `tsc --noEmit` 성공 | exit code = 0 |
| B2 | 서버 시작 | `bootRun` / `npm run dev` 성공 | 포트 리스닝 확인 |
| B3 | API 응답 | `curl` 200 응답 | HTTP 상태코드 확인 |
| B4 | 타입 안전 | TS strict 에러 0개, Java 경고 0개 | 빌드 출력 분석 |

**12단계**: 도메인 1개 구현 → B1-B3 → 다음 도메인 → B1-B3 → ... → 전체 B1-B4

## 에러 발생 시 대응 흐름

```
컴파일 에러 발생
    │
    ├── 1. 에러 메시지에서 파일명:라인번호 확인
    │
    ├── 2. Read로 해당 파일의 에러 라인 확인
    │
    ├── 3. 에러 유형 판단:
    │     ├── import 불가 → 클래스명/패키지명 오타, 의존성 누락
    │     ├── 타입 불일치 → 메서드 시그니처, 제네릭 파라미터
    │     ├── 미구현 메서드 → 인터페이스 구현 누락
    │     ├── 중복 정의 → 같은 이름 클래스/메서드
    │     └── 어노테이션 에러 → 의존성 누락 (build.gradle)
    │
    ├── 4. Edit로 수정
    │
    └── 5. 다시 컴파일 → 통과할 때까지 반복
```

## 도메인별 개발 순서 결정

### 의존성 그래프 기반 (쇼핑/주문 도메인 예시)
```
[의존성 없음 — 먼저]
User, Category

[User에 의존]
Product (sellerId → User)

[Product에 의존]
Cart, Wishlist, Review

[Product + User에 의존]
Order (buyerId, items → Product)
Coupon (User가 수령)

[Order에 의존]
Payment (orderId → Order)

[Payment에 의존]
Shipping (Order → Payment 후 배송)

[모든 도메인에 의존]
Notification (모든 이벤트 구독)
```

### 권장 구현 순서
```
Phase 1: User + Category (인증/인가 기반)
Phase 2: Product (상품 CRUD + 검색)
Phase 3: Cart + Wishlist (구매 준비)
Phase 4: Order + Coupon (주문 핵심)
Phase 5: Payment (결제 연동)
Phase 6: Shipping (배송 관리)
Phase 7: Review (리뷰/평점)
Phase 8: Notification (알림 통합)
```
각 Phase 완료 후 **컴파일 + 서버 시작 + curl 테스트**로 확인.

### Wave 기반 병렬 실행 (GSD 흡수)

도메인 구현을 Wave로 그룹화하여 의존성 없는 작업을 병렬 처리:

| Wave | 도메인 | 의존성 | 실행 |
|------|--------|--------|------|
| 1 | User, Category | 없음 | **병렬** (Agent 동시 실행) |
| 2 | Product | User | Wave 1 완료 후 |
| 3 | Cart, Wishlist, Coupon | Product, User | **병렬** |
| 4 | Order | Product, User, Coupon | Wave 3 완료 후 |
| 5 | Payment | Order | Wave 4 완료 후 |
| 6 | Shipping | Order, Payment | Wave 5 완료 후 |
| 7 | Review | Order (DELIVERED) | Wave 6 완료 후 |
| 8 | Notification | 모든 도메인 | 최후 |

**Wave 실행 규칙:**
- 같은 Wave 내 도메인은 Agent 병렬 실행
- Wave N+1은 Wave N 완료 후 시작
- 같은 Wave에서 files_modified가 겹치면 순차 강제
- 각 Wave 완료 후 `./gradlew compileJava` 확인

## 빌드 실패 빈출 패턴 (Java/Spring Boot)

| 에러 | 원인 | 해결 |
|------|------|------|
| `cannot find symbol` | 클래스명 오타, import 누락 | import 추가 또는 클래스명 수정 |
| `incompatible types` | 메서드 반환 타입 불일치 | 타입 캐스팅 또는 시그니처 수정 |
| `method does not override` | 인터페이스 메서드 시그니처 불일치 | 파라미터/반환 타입 맞추기 |
| `constructor not found` | record/클래스 생성자 파라미터 불일치 | 필드 순서/타입 확인 |
| `package does not exist` | build.gradle 의존성 누락 | 의존성 추가 후 `./gradlew --refresh-dependencies` |
| `duplicate class` | 같은 클래스명이 다른 패키지에 존재 | 이름 변경 또는 패키지 정리 |
| `bean not found` | @Component/@Service 누락 | 어노테이션 추가 |
| `circular dependency` | 서비스 간 순환 참조 | 인터페이스 분리 또는 이벤트 기반으로 전환 |

## 빌드 실패 빈출 패턴 (React/TypeScript)

| 에러 | 원인 | 해결 |
|------|------|------|
| `Module not found` | import 경로 오타, 파일 미존재 | 경로 확인, @ 별칭 설정 확인 |
| `Type 'X' is not assignable` | 타입 불일치 | 인터페이스 정의 확인 |
| `Property 'X' does not exist` | 객체에 없는 필드 접근 | 타입 정의에 필드 추가 또는 optional chaining |
| `JSX element type does not have` | 컴포넌트 export 누락 | default export 또는 named export 확인 |
| `Cannot find module '@/...'` | tsconfig paths 미설정 | tsconfig.json + vite.config.ts 별칭 설정 |

## Gotchas

### 한 번에 전부 작성 후 빌드
모든 파일을 한 번에 작성하면 에러가 쏟아져서 어디가 문제인지 파악 불가. **반드시 단위별로 컴파일 확인**.

### ./gradlew compileJava vs build
`compileJava`는 소스 코드 컴파일만. `build`는 테스트 + 패키징까지 포함. 빠른 문법 확인은 `compileJava`, 서버 시작 전에는 `build`.

### 증분 빌드 캐시 문제
이전 빌드 캐시 때문에 수정이 반영되지 않을 수 있음. `./gradlew clean compileJava`로 클린 빌드.

### TypeScript strict 모드
`tsconfig.json`에 `"strict": true`이면 implicit any, null 체크 등이 엄격. 초기 뼈대에서 에러가 많이 나면 점진적으로 strict 옵션을 켜는 것도 방법.

### 서버 시작 시 DB 연결 실패
Docker MySQL이 안 떠 있으면 Spring Boot 시작 실패. `docker compose up -d`로 인프라 먼저 실행.

### Windows gradlew 실행
Git Bash에서 `./gradlew`가 안 되면 `./gradlew.bat` 또는 `cmd.exe //c gradlew.bat compileJava` 사용.

## 도구 사용 패턴 (Harness)
- 컴파일 확인: `Bash(./gradlew compileJava)` 또는 `Bash(npx tsc --noEmit)`
- 에러 위치 확인: 에러 메시지에서 파일:라인 추출 → `Read`로 해당 라인 확인
- 수정: `Edit`으로 에러 수정 → 다시 `Bash`로 컴파일
- 서버 시작: `Bash(./gradlew bootRun)` (background로)
- API 테스트: `Bash(curl)`로 엔드포인트 확인

## 에러 복구 패턴 (Harness)
- 컴파일 에러 → 에러 메시지 파싱 → `Read` 해당 파일 → `Edit` 수정 → 재컴파일
- 같은 에러 반복 → `./gradlew clean` 후 재빌드
- 의존성 에러 → `Read` build.gradle 확인 → `Edit`으로 의존성 추가
- 서버 시작 실패 → `Bash(docker ps)`로 인프라 확인 → `Read` application.yml 확인
