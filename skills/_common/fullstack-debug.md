---
keywords: 풀스택 fullstack 전체 흐름 flow 스키마 schema 테이블 table 쿼리 query repository 서비스 service DTO dto JSON json 요청 request 응답 response 프론트 frontend 백엔드 backend API api 일치 mismatch 불일치 연동 integration 자바 java spring springboot 프로세스 process 재시작 restart 종료 kill
intent: 흐름추적해 연동안돼 불일치고쳐 DTO맞춰 프론트백엔드연결해 에러추적해 에러해 연동에러
paths: src/main/java src/main/resources src/api src/pages src/components entity/ repository/ service/ controller/ dto/ mapper/
patterns: spring springboot jpa hibernate mybatis mapper entity repository service controller restcontroller requestmapping getmapping postmapping requestbody responsebody spring-data-jdbc jdbctemplate crudrepository
requires: backend debugging verification database
phase: debug
min_score: 3
---

# Fullstack Debug Runbook

DB → Backend(Repository → Service → DTO → Controller) → Frontend(API 호출 → 화면) 전체 흐름을 코드 레벨에서 추적하여 문제를 찾고 수정하는 런북.

## 의사결정 트리

### IF 프론트-백엔드 연동 문제 (Debug)
아래 **계층별 추적 순서**를 반드시 따를 것:
1. **DB 스키마/테이블** 확인 → 실제 컬럼, 타입, 제약조건
2. **Entity/Model** 확인 → DB 스키마와 매핑 일치 여부
3. **Repository** 확인 → 쿼리가 의도한 데이터를 반환하는지
4. **Service** 확인 → 비즈니스 로직, 트랜잭션, 데이터 변환
5. **DTO** 확인 → 필드명, 타입, JSON 직렬화 형식
6. **Controller** 확인 → URL 매핑, HTTP 메서드, 요청/응답 바인딩
7. **Frontend API 호출** 확인 → URL, 메서드, body, 헤더
8. **Frontend 화면** 확인 → 응답 데이터 사용, 상태 관리
9. 문제 지점 발견 → 수정 → 서버 재시작 → 재검증

### IF 데이터가 안 나옴 (Debug)
1. DB에 데이터가 있는지 직접 쿼리로 확인
2. Repository 쿼리 결과 확인 (조건절, JOIN, WHERE)
3. Service에서 필터링/변환 중 누락되는지 확인
4. DTO 변환 시 필드 매핑 누락 확인
5. Controller 응답 형식 확인
6. Frontend에서 응답 파싱 확인 (필드명 오타, 중첩 구조)

### IF 데이터 형식 불일치 (Debug)
1. Backend DTO의 JSON 직렬화 결과를 확인
   - `@JsonProperty`, `@JsonFormat`, snake_case vs camelCase
2. Frontend에서 기대하는 필드명/타입과 비교
3. 날짜 형식 (ISO 8601 vs timestamp), enum (문자열 vs 숫자) 확인

### IF Java 백엔드 수정 후 반영 (Implement)
1. 코드 수정 완료
2. 기존 Java 프로세스 종료 → **아래 프로세스 관리 참고**
3. 빌드 + 재시작
4. 로그 확인 (시작 완료 메시지, 에러 없는지)
5. API 테스트 (curl 또는 프론트엔드에서 확인)
6. **→ verification 스킬: 브라우저에서 최종 확인**

## 계층별 추적 체크리스트

### 1. DB 스키마
```sql
-- 테이블 구조 확인
DESC table_name;
SHOW CREATE TABLE table_name;

-- 실제 데이터 확인
SELECT * FROM table_name WHERE id = ? LIMIT 10;
```
- [ ] 컬럼명이 Entity와 일치하는가
- [ ] 타입이 일치하는가 (VARCHAR vs TEXT, INT vs BIGINT)
- [ ] NOT NULL 제약조건이 맞는가
- [ ] 외래키 관계가 올바른가

### 2. MyBatis DTO/VO ↔ DB 매핑
```xml
<!-- MyBatis Mapper XML -->
<resultMap id="userResultMap" type="UserDTO">
    <id property="id" column="id"/>
    <result property="userName" column="user_name"/>  <!-- 실제 컬럼명과 일치? -->
</resultMap>
```
```java
@Getter @Setter
public class UserDTO {
    private Long id;
    private String userName;  // resultMap의 property와 일치?
}
```
- [ ] MyBatis resultMap의 `column` 속성이 실제 DB 컬럼명과 일치하는지 확인
- [ ] MyBatis typeHandler 설정 (enum 매핑 등)
- [ ] `@JsonFormat` 날짜 형식
- [ ] `<collection>`, `<association>` 태그로 연관관계 매핑 확인

### 3. Repository 쿼리
- [ ] JPQL/네이티브 쿼리 WHERE 조건 확인
- [ ] JOIN 대상 테이블이 맞는가
- [ ] 파라미터 바인딩이 올바른가
- [ ] Pageable 적용 시 정렬 기준 확인

### 4. Service 비즈니스 로직
- [ ] Repository에서 받은 데이터를 올바르게 변환하는가
- [ ] null 처리 (Optional, orElseThrow)
- [ ] 트랜잭션 경계 (`@Transactional`) 확인
- [ ] 다른 Service 호출 시 순환 참조 없는가

### 5. DTO ↔ JSON 매핑
```java
public class UserResponse {
    private String userName;     // JSON: "userName" (camelCase)
    // Frontend에서 "user_name" (snake_case)으로 기대하면 불일치!

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createdAt;
    // Frontend에서 ISO 8601 기대하면 불일치!
}
```
- [ ] 필드명이 Frontend 기대값과 일치하는가
- [ ] 날짜/시간 직렬화 형식
- [ ] enum 직렬화 (문자열? 숫자?)
- [ ] null 필드 포함 여부 (`@JsonInclude`)

### 6. Controller 매핑
- [ ] URL 경로 (`@RequestMapping`, `@GetMapping`)
- [ ] HTTP 메서드 (GET/POST/PUT/DELETE)
- [ ] `@RequestBody` vs `@RequestParam` vs `@PathVariable`
- [ ] 응답 래퍼 (ResponseEntity, 커스텀 ApiResponse)

### 7. Frontend API 호출
- [ ] URL이 Controller 매핑과 일치하는가 (오타, trailing slash)
- [ ] HTTP 메서드 일치
- [ ] Content-Type 헤더 (`application/json`)
- [ ] 인증 헤더 (Bearer 토큰)
- [ ] 요청 body 필드명이 `@RequestBody` DTO와 일치하는가

## Java 프로세스 관리 (Windows)

### 프로세스 찾기 및 종료
```bash
# Java 프로세스 PID 찾기
netstat -ano | findstr :8080
# 또는
tasklist | findstr java

# 프로세스 종료 (관리자 권한 필요할 수 있음)
taskkill /PID <pid> /F

# 또는 포트 기반으로 한번에
for /f "tokens=5" %a in ('netstat -ano ^| findstr :8080') do taskkill /PID %a /F
```

### 빌드 및 재시작
```bash
# Gradle
./gradlew bootRun
# 또는
./gradlew build && java -jar build/libs/app.jar

# 회사 표준: Gradle 사용 (Maven은 레거시)
# ./mvnw spring-boot:run  # 레거시 프로젝트만
```

### 시작 확인
```bash
# 서버 준비 대기 (최대 60초 — Spring Boot는 시작이 느릴 수 있음)
for i in $(seq 1 60); do
  if curl -s http://localhost:8080/actuator/health > /dev/null 2>&1; then
    echo "Server ready"
    break
  fi
  sleep 1
done
```

## Gotchas

### camelCase vs snake_case 불일치
Spring Boot는 기본 camelCase (`userName`), 프론트엔드가 snake_case (`user_name`)를 기대하면 모든 필드가 undefined. `spring.jackson.property-naming-strategy=SNAKE_CASE` 설정 또는 `@JsonProperty`로 명시.

### @Transactional 누락
Service 메서드에서 여러 DB 작업을 하는데 `@Transactional`이 없으면 중간 실패 시 부분 반영됨. 또한 `@Transactional(readOnly = true)` 누락 시 성능 저하.

### LazyInitializationException — MyBatis에서는 해당 없음
MyBatis는 JPA와 달리 Lazy Loading 프록시를 사용하지 않으므로 LazyInitializationException이 발생하지 않음. 대신 필요한 데이터는 SQL JOIN 또는 별도 쿼리로 명시적으로 조회해야 함.

### MyBatis에서 INSERT 후 생성된 ID 조회
MyBatis에서 `<insert>` 태그 사용 시 `useGeneratedKeys="true"` + `keyProperty="id"`를 설정해야 auto_increment로 생성된 ID가 DTO에 반영됨. 누락 시 insert 후 id가 null로 남아있어 후속 로직에서 NPE 발생.

### MyBatis의 #{} vs ${}
`#{}` 는 PreparedStatement 파라미터 바인딩 (SQL Injection 방지). `${}` 는 문자열 치환 (SQL Injection 위험). ORDER BY 동적 컬럼명 등 불가피한 경우만 `${}` 사용하고, 반드시 화이트리스트 검증 필수.

### Windows taskkill 권한
관리자 권한 없이 다른 사용자의 프로세스를 종료할 수 없음. 관리자 권한 터미널이 필요하면 사용자에게 안내할 것.

### Gradle/Maven 데몬 프로세스
`./gradlew bootRun`으로 실행한 서버를 Ctrl+C로 중단해도 Gradle 데몬이 남아있을 수 있음. `./gradlew --stop`으로 데몬 종료 후 재시작.

### Spring Boot DevTools 자동 재시작
`spring-boot-devtools` 의존성이 있으면 클래스 변경 시 자동 재시작됨. 하지만 application.yml 변경이나 의존성 변경은 수동 재시작 필요.

### 빌드 캐시로 인한 변경 미반영
Gradle/Maven 캐시 때문에 수정이 반영되지 않을 수 있음. `./gradlew clean build` 또는 `./mvnw clean package`로 클린 빌드.

### @RequestBody 빈 객체
POST 요청에서 Content-Type이 `application/json`이 아니면 `@RequestBody`가 빈 객체로 바인딩됨. 프론트엔드의 fetch/axios 설정에서 헤더 확인.

### CORS 에러로 인한 데이터 미수신
브라우저에서 CORS 에러가 발생하면 응답 데이터를 아예 읽을 수 없음. Network 탭에서 응답은 200인데 데이터가 없으면 CORS 확인. `@CrossOrigin` 또는 WebMvcConfigurer로 설정.

### DB 커넥션 풀 고갈
트랜잭션을 닫지 않거나 커넥션을 반환하지 않으면 풀이 고갈되어 모든 요청이 타임아웃. `spring.datasource.hikari.maximum-pool-size`와 `leak-detection-threshold` 설정.
