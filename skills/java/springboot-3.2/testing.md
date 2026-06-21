---
keywords: 테스트 test 테스팅 testing 유닛 unit 통합 integration E2E e2e 커버리지 coverage 모킹 mock 픽스처 fixture pytest playwright jest vitest 자동화 QA junit mockito testcontainer testcontainers fixture-monkey 단위테스트 통합테스트 jacoco 레디스 redis 카프카 kafka mybatis @MybatisTest mapper DAO
intent: 테스트해 테스트작성해 커버리지올려 단위테스트해 통합테스트해
paths: tests/ test/ __tests__/ e2e/ spec/ src/tests/ backend/tests/ src/test/java
patterns: pytest pytest-asyncio pytest-cov jest vitest playwright cypress mocha chai sinon junit5 junit-jupiter mockito testcontainers fixture-monkey springboottest datajdbctest
requires: database
phase: implement review
min_score: 3
---

# Testing Strategy Guide

> 파이프라인: 15단계(테스트 코드 작성) — 단위/통합 테스트로 소스코드 신뢰성 확보
> 검증: T1-T4 이진 체크리스트 (커버리지 목표 달성)

## 의사결정 트리

### IF 테스트 전략 수립 (Plan)
1. 프레임워크 선택: Java(JUnit5+Mockito) / Python(pytest) / JS(vitest/jest) / E2E(Playwright)
2. 커버리지 목표: 전체 70%, 도메인 90%, API 80%
3. CI 실행: PR(유닛+통합), 주간(E2E)

### IF 새 기능 테스트 작성 — Java/Spring (Implement)
1. **단위 테스트**: Service 로직 → Mockito로 Repository mock
2. **DAO 테스트**: `@MybatisTest` 또는 `@SpringBootTest` + TestContainer (실제 MySQL 5.7)
3. **통합 테스트**: `@SpringBootTest` + TestContainer (전체 컨텍스트)
4. Assertion: `assertNotNull` → `assertEquals` → `assertAll`로 묶기 → `assertThrows`
5. 테스트 데이터: Fixture Monkey로 객체 생성 자동화
6. **→ database 스킬: Repository 쿼리 검증 시 EXPLAIN 확인**

#### 서비스 테스트 누락 방지 체크리스트 (Phase 17 회고 반영)
JaCoCo 100% 달성 시 반복적으로 누락되는 패턴들. 서비스 테스트 작성 전 **선제적으로** 전수 확인:

- [ ] **모든 public 메서드** — `create/update/delete`뿐 아니라 `findBy*/findAll/exists*/count*` read 메서드도 전부
- [ ] **Null branch** — `if (x != null)` 이 있는 필드 업데이트는 **각 필드 null + fullUpdate 최소 2케이스**
- [ ] **Lambda** — `orElseThrow(() -> new X())` 같은 lambda는 예외 케이스 테스트 필수 (METHOD counter에 별도 항목)
- [ ] **Short-circuit** — `a != null && b != null` 은 `a=null` / `b=null` / 둘 다 null / 둘 다 있음 4케이스
- [ ] **Stream 람다** — `filter(x -> x.isHidden())` 같은 필터는 통과/거름 케이스 각각
- [ ] **Record DTO** — Record 인스턴스화 자체도 METHOD 카운터에 잡힘 (record 미사용 시 해당 없음)
- [ ] **Enum switch default** — 명시 안 해도 default 브랜치 발생

- [ ] **Exception 리팩터 연쇄** — `RuntimeException` → 도메인 `BusinessException` 변경 시, 테스트의 `assertThrows(RuntimeException.class, ...)` → `assertThrows(XxxNotFoundException.class, ...)` 동시 수정. mock도 `findById` → `findByIdForUpdate` 전환 시 일괄 변경
- [ ] **Repository 메서드 변경 연쇄** — Service가 호출하는 Repository 메서드가 바뀌면 (`findById` → `findByIdForUpdate`), 해당 Service의 모든 테스트에서 mock `when(repo.findById(...))` → `when(repo.findByIdForUpdate(...))` 수정 필수. 누락 시 mock이 null 반환하여 NPE 발생

**절대 피할 것**: "JaCoCo가 빨간색으로 표시한 것만 쫓아가기" — 반응적 패턴은 회귀 위험.
**원칙**: 서비스 공개 API 목록을 먼저 뽑은 뒤 위 체크리스트 전수 통과시키기.

### IF 새 도메인 확장 시 테스트 일괄 생성 (Implement — Phase 22+ 패턴)

**대규모 도메인 추가 시 JaCoCo 100% 달성을 위한 컴포넌트별 테스트 템플릿.**
새 도메인(예: bidding) 추가 시 아래 6가지 타입을 **모두** 작성해야 100% 달성 가능.

#### 1. Service 테스트 (기존 파일 확장 또는 신규)
```java
@ExtendWith(MockitoExtension.class)
class XxxServiceTest {
    @Mock XxxRepository xxxRepository;
    @Mock EventPublisher eventPublisher;
    @InjectMocks XxxService xxxService;
    // 모든 public 메서드 × (성공 + 실패 + 분기) 케이스
}
```
**필수**: read-only 메서드(`findByUser`, `findAll`, `findById`)도 빠짐없이.

#### 2. Controller 테스트
```java
@WebMvcTest(XxxController.class)
class XxxControllerTest extends ControllerTestSupport {
    @MockBean XxxService xxxService;
    // authenticate(userId, role) → mockMvc.perform() → status().isOk()
}
```
**주의**: CommonHeaderDTO를 상속한 DTO 테스트 시 헤더 필드(userRoleCode, userStoreUnqcd 등)도 세팅 필요. 미설정 시 Service에서 NPE 발생 가능.

#### 3. Kafka Consumer 테스트
```java
@ExtendWith(MockitoExtension.class)
class XxxEventConsumerTest {
    @Mock NotificationService notificationService;
    @Mock ProcessedEventRepository processedEventRepository;
    @Mock DltMessageRepository dltMessageRepository;
    XxxEventConsumer consumer;
    @BeforeEach void setup() {
        consumer = new XxxEventConsumer(notificationService, processedEventRepository,
                dltMessageRepository, new ObjectMapper());
    }
    // 필수 3케이스: 정상 처리, 중복 skip, 파싱 실패→DLT
    // 이벤트 타입별 분기도 각각 테스트
}
```

#### 4. Scheduler 테스트
```java
@ExtendWith(MockitoExtension.class)
class XxxSchedulerTest {
    @Mock XxxRepository xxxRepository;
    @InjectMocks XxxScheduler scheduler;
    // 필수 2케이스: 대상 있음(상태 전환 확인), 대상 없음(save 호출 없음)
}
```

#### 5. 기존 Service에 메서드 추가 시
기존 테스트 파일에 `@Nested` 클래스 추가. 새 파일 만들지 않음.

#### 6. Checkstyle 준수 사항
- **star import 금지** (`import com.xxx.*` → 개별 import으로 나열)
- **미사용 import 금지** (PMD도 잡지만 Checkstyle이 먼저 실패)
- **파라미�� 재할당 금지** (`expiresAt = x` → `LocalDateTime effectiveExpiresAt = ...`)

### IF 새 기능 테스트 작성 — Python/JS (Implement)
1. 유닛 테스트: 도메인 로직 커버
2. 통합 테스트: API 엔드포인트 정상/에러 케이스
3. 엣지 케이스: 빈 값, 최대값, 잘못된 입력

### IF E2E 테스트 작성 (Implement)
1. 핵심 사용자 흐름 식별
2. 인증 상태 fixture 생성
3. 페이지 객체 패턴 적용

### IF 커버리지 검토 (Review)

#### 이진 검증 체크리스트 (T1-T4, 모두 PASS 필수)

| # | 체크 항목 | PASS 기준 | 측정 방법 |
|---|----------|----------|----------|
| T1 | 전체 커버리지 | ≥ 70% | `gradlew jacocoTestReport` |
| T2 | 도메인 커버리지 | ≥ 90% | JaCoCo 도메인 패키지별 리포트 |
| T3 | 테스트 전부 통과 | 실패 0개 | `gradlew test` exit code = 0 |
| T4 | 실제 DB 테스트 | Repository → TestContainer 사용 | mock DB 테스트 = 0 |

#### JaCoCo 갭 리스트업 (반복 작업 제거)
```bash
# 상세 — 미커버 클래스/메서드/브랜치 전체 출력
python ~/.claude/scripts/jacoco-gap.py

# 요약만 (CI용)
python ~/.claude/scripts/jacoco-gap.py --summary-only

# 특정 counter만
python ~/.claude/scripts/jacoco-gap.py --counter BRANCH

# 특정 클래스 제외
python ~/.claude/scripts/jacoco-gap.py --exclude "Dto,Config"
```
Phase 17 회고(2026-04-11): 수동 XML 파싱을 7회 반복 → 영구 도구화.

- [ ] 테스트 독립성 (순서 무관, 단 통합테스트는 `@TestMethodOrder`로 순서 고정 가능)
- [ ] 외부 의존성 mock 여부 (Service: mock, Repository: 실제 DB)
- [ ] 테스트 데이터 격리 (트랜잭션 롤백 또는 `@DirtiesContext`)
- [ ] DTO setter/getter 같은 의미없는 테스트 배제 → 비즈니스 로직 집중

## JUnit 5 + Spring Boot 테스트 가이드

### 테스트 구조
```
src/test/java/com/project/
├── unit/                    # Mockito 기반 Service 테스트
├── integration/             # @SpringBootTest 전체 흐름
├── dao/                     # @MybatisTest DAO/Mapper 테스트
└── support/                 # TestContainer 설정, 공통 fixture
```

### JUnit 5 핵심 패턴
```java
@Nested
@DisplayName("주문 생성")
class CreateOrder {
    @Test
    @DisplayName("정상 주문 - 재고 차감 및 주문 생성")
    void success() {
        // given-when-then
        assertAll(
            () -> assertNotNull(result.getId()),
            () -> assertEquals(OrderStatus.CREATED, result.getStatus()),
            () -> assertTrue(result.getTotalPrice() > 0)
        );
    }

    @Test
    @DisplayName("재고 부족 시 예외")
    void insufficientStock() {
        assertThrows(BusinessException.class, () -> orderService.create(request));
    }
}
```

### TestContainer 설정 (MySQL) — 2-Strike 수정: static 초기화 블록 필수
```java
@MybatisTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
abstract class BaseDAOTest {

    // ⚠️ @Container 어노테이션 사용 금지! @DynamicPropertySource 타이밍 이슈로
    // "Mapped port can only be obtained after the container is started" 에러 발생.
    // 반드시 static 블록에서 수동 start() 할 것.
    static final MySQLContainer<?> mysql;

    static {
        mysql = new MySQLContainer<>("mysql:5.7")
                .withDatabaseName("test")
                .withUsername("root")
                .withPassword("root")
                .withInitScript("schema-test.sql");
        mysql.start();
    }

    @DynamicPropertySource
    static void configureProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", mysql::getJdbcUrl);  // jdbc-url 아닌 url 사용!
        registry.add("spring.datasource.username", mysql::getUsername);
        registry.add("spring.datasource.password", mysql::getPassword);
        registry.add("spring.datasource.driver-class-name", () -> "com.mysql.cj.jdbc.Driver");
    }
}
```

### Fixture Monkey (테스트 객체 자동 생성)
```java
// Lombok @Getter/@Setter DTO → FieldReflectionArbitraryIntrospector 사용 (실 프로젝트 검증)
FixtureMonkey monkey = FixtureMonkey.builder()
    .objectIntrospector(FieldReflectionArbitraryIntrospector.INSTANCE)
    .build();

// DB 제약조건(ENUM, UNIQUE, FK)은 .set()으로 명시
UserDTO user = monkey.giveMeBuilder(UserDTO.class)
    .set("id", null)  // auto-increment
    .set("email", UUID.randomUUID() + "@test.com")  // UNIQUE
    .set("role", "BUYER")  // ENUM
    .set("status", "ACTIVE")  // ENUM
    .sample();
```

### DAO 테스트 작성 프로세스 (2-Strike: 실 프로젝트 회고)
1. **Mapper XML 먼저 읽기** — 실제 SQL이 어떤 컬럼을 사용하는지, `<if test="">` 변수명이 뭔지 확인
2. **DESCRIBE 테이블** — INSERT/UPDATE 대상 테이블의 실제 컬럼 확인
3. **고정값 확인** — INSERT가 특정 필드를 하드코딩하는지 (예: `is_read = 0`)
4. **테스트 assertion은 Mapper 동작 기준** — DTO 입력값이 아닌 SQL이 실제 수행하는 동작 기준

### useGeneratedKeys Mock 패턴 (2-Strike: ProductServiceTest NPE 사건)
```java
// MyBatis useGeneratedKeys=true인 INSERT mock 시 반드시 doAnswer로 ID 주입
// 미주입 시 getId()가 null → Map.of("id", null) → NPE
doAnswer(inv -> {
    OrderDTO o = inv.getArgument(0);
    o.setId(1L);
    return 1;
}).when(orderDAO).insertOrder(any(OrderDTO.class));
```

### Mockito 패턴
```java
// given
when(orderRepository.findById(1L)).thenReturn(Optional.of(order));
// when
OrderResponse result = orderService.findById(1L);
// then
verify(orderRepository, times(1)).findById(1L);  // 호출 검증
verifyNoMoreInteractions(orderRepository);
```

### MyBatis DAO Mock 패턴
```java
// given — MyBatis DAO mock
when(memberDao.selectById(1L)).thenReturn(member);
// when
MemberDto result = memberService.getMember(1L);
// then
verify(memberDao, times(1)).selectById(1L);
```

### Redis TestContainer 설정
```java
@Testcontainers
@SpringBootTest
abstract class RedisTestBase {
    @Container
    static GenericContainer<?> redis = new GenericContainer<>("redis:7-alpine")
        .withExposedPorts(6379);

    @DynamicPropertySource
    static void redisProps(DynamicPropertyRegistry registry) {
        registry.add("spring.data.redis.host", redis::getHost);
        registry.add("spring.data.redis.port", () -> redis.getMappedPort(6379));
    }
}
```

### Kafka TestContainer 설정
```java
@Testcontainers
@SpringBootTest
abstract class KafkaTestBase {
    @Container
    static KafkaContainer kafka = new KafkaContainer(
        DockerImageName.parse("confluentinc/cp-kafka:7.6.0")
    );

    @DynamicPropertySource
    static void kafkaProps(DynamicPropertyRegistry registry) {
        registry.add("spring.kafka.bootstrap-servers", kafka::getBootstrapServers);
    }
}
```
Kafka 컨슈머 테스트 시 `@EmbeddedKafka` 또는 TestContainer 중 선택. TestContainer가 프로덕션에 더 가까운 환경 제공.

## 계약 테스트 (Contract Testing — SDD)

OpenAPI spec이 FE-BE 간 계약. 구현이 계약과 일치하는지 자동 검증.

### BE: springdoc 런타임 spec ↔ 설계 spec 대조
```java
@SpringBootTest(webEnvironment = WebEnvironment.RANDOM_PORT)
class ApiContractTest {
    @LocalServerPort int port;

    @Test
    @DisplayName("런타임 OpenAPI spec이 설계 spec과 일치")
    void apiSpecMatchesDesign() throws Exception {
        // 런타임 spec 가져오기
        String runtimeSpec = RestAssured.get("http://localhost:" + port + "/v3/api-docs").asString();

        // 설계 spec 로드
        String designSpec = Files.readString(Path.of(".claude/design/openapi.yaml"));

        // 경로 수 일치 검증
        // 스키마 필드명 일치 검증
        // 에러 응답 코드 일치 검증
    }
}
```

### FE: 타입 안전 보장
```
OpenAPI spec → openapi-typescript → generated.ts → FE import
→ OpenAPI 변경 시 FE 타입 불일치 = TS 컴파일 에러 (자동 감지)
```

### 검증 기준 추가
| # | 체크 항목 | PASS 기준 |
|---|----------|----------|
| T5 | 계약 테스트 존재 | OpenAPI ↔ Controller 대조 테스트 1개 이상 |

## 회사 JUnit 테스트 패턴

### 기본 테스트 구조 (Controller/Service)
```java
@TestMethodOrder(OrderAnnotation.class)
class MemberControllerTest {
    private MemberController memberController;

    @Mock
    private MemberService memberService;

    @BeforeEach
    public void initTest() throws Exception {
        MockitoAnnotations.openMocks(this);
        memberController = new MemberController(memberService);
    }

    @AfterEach
    public void endTest() throws Exception { }

    @Test
    @Order(1)
    public void shouldReturnMemberJoinSuccess() throws Exception {
        // given — 검증할 메소드의 조건 생성
        Member member = new Member();
        member.setId(1L);
        JSONObject join = new JSONObject();
        given(memberService.memberJoin(member)).willReturn(join);

        // when — 검증할 메소드 실행
        JSONObject successJoin = memberController.memberJoin(member);

        // then — 결과 검증
        assertThat(successJoin, is(join));
    }
}
```
**핵심 패턴:**
- `given(메서드).willReturn(데이터)` — mock 메서드 동작 정의
- `assertThat(검증할데이터, is(결과값))` — 값 비교 검증
- `@Order(N)` — 테스트 실행 순서 (같은 번호면 알파벳/숫자 순)

### Static 메서드 테스트 (MockedStatic)
`@Mock`은 static 메서드를 지원하지 않음. `MockedStatic<?>` 사용 필수:
```java
@TestMethodOrder(OrderAnnotation.class)
class CalculatorControllerTest {
    private CalculatorController calculatorController;

    @Mock
    private CalculatorService calculatorService;

    // static 메서드가 있는 클래스를 MockedStatic으로 선언
    private static MockedStatic<CalculatorCheck> calculatorCheck;

    @BeforeEach
    public void initTest() throws Exception {
        MockitoAnnotations.openMocks(this);
        calculatorCheck = mockStatic(CalculatorCheck.class);  // static mock 초기화
        calculatorController = new CalculatorController(calculatorService);
    }

    @AfterEach
    public void endTest() throws Exception {
        calculatorCheck.close();  // 반드시 close — static은 모든 인스턴스가 공유
    }

    @Test
    @Order(1)
    public void shouldReturnSuccess() throws Exception {
        // given — static 메서드는 클래스명으로 호출
        Calculator calculator = new Calculator();
        given(CalculatorCheck.checkInputZero(calculator)).willReturn(true);
        given(calculatorService.calculatorPlus(calculator)).willReturn(0);

        // when
        String result = calculatorController.calculatorPlus(calculator);

        // then
        assertThat(result, is("0"));
    }
}
```
**주의:** `@AfterEach`에서 `calculatorCheck.close()` 누락 시 다른 테스트에 영향. static 영역은 모든 인스턴스가 공유하므로 반드시 종료 선언.

## Gotchas

### MockedStatic close 누락
`MockedStatic`을 `@AfterEach`에서 `close()` 하지 않으면 다른 테스트 클래스에서 해당 static 메서드가 여전히 mock 상태로 남음. 테스트 격리 실패의 주요 원인.

### TestContainer 여러 개 뜨는 문제
테스트 클래스마다 `@Container`를 선언하면 MySQL 컨테이너가 N개 생성됨. static 싱글턴 패턴 또는 추상 부모 클래스에서 한 번만 선언할 것.

### @MybatisTest와 @SpringBootTest 혼용
`@MybatisTest`는 MyBatis 매퍼만 로드 (Service 빈 미로드), `@SpringBootTest`는 전체 컨텍스트. DAO만 테스트할 때는 `@MybatisTest`가 빠르고 격리됨.

### DB 테스트 격리 실패
각 테스트가 DB 상태를 공유하면 테스트 순서에 따라 결과가 달라짐. `@Transactional` 자동 롤백 또는 테스트마다 데이터 초기화.

### 테스트 순서 의존성
단위 테스트는 순서 독립이 원칙이지만, 통합 테스트에서 순서가 필요하면 `@TestMethodOrder(MethodOrderer.OrderAnnotation.class)` + `@Order(1)` 사용. 가급적 피할 것.

### mock vs 실제 DB
Service는 Mockito로 빠르게, **Repository는 반드시 실제 DB(TestContainer)로 테스트**. Mock만 사용하면 스키마 불일치, 쿼리 오류를 놓침.

### Fixture Monkey IntrospectorSelection
회사 DTO는 Lombok @Getter/@Setter 기반이므로 `BeanArbitraryIntrospector.INSTANCE` 사용. record용 `ConstructorPropertiesArbitraryIntrospector`는 사용하지 않음.

### assertThat만 쓰는 습관
`assertThat`만 사용하면 다양한 검증을 놓침. `assertAll`로 여러 검증 묶기, `assertThrows`로 예외 검증, `assertTrue`/`assertNotNull` 적극 활용.

### Windows에서 TestContainer Docker 연결
Docker Desktop이 실행 중이어야 함. WSL2 백엔드 사용 시 `DOCKER_HOST` 환경변수 설정 불필요 (자동 감지). Docker Desktop이 꺼져있으면 테스트 자체가 실패.

## 도구 사용 패턴 (Harness)
- Java 테스트 실행: `Bash(gradlew test)` → 실패 시 `Read`로 테스트/소스 확인 → `Edit`
- 테스트 파일 찾기: `Glob("src/test/**/*.java")` 또는 `Glob("tests/**/*.py")`
- 커버리지 확인: `Bash(gradlew jacocoTestReport)` → `Read`로 리포트 확인
- 실패한 테스트만 재실행: `Bash(gradlew test --tests "*.OrderServiceTest")`

## 에러 복구 패턴 (Harness)
- 테스트 실패 → 에러 메시지의 assertion/stacktrace를 먼저 읽기
- TestContainer 실패 → `Bash(docker ps)`로 Docker 상태 확인
- 컨텍스트 로딩 실패 → `Read`로 application-test.yml 확인, 빈 의존성 점검
- 특정 테스트만 실패 → `Bash`로 단일 테스트 격리 실행하여 재현 여부 확인

## Related (신규 그래프 cross-ref)

java/springboot-3.2/testing이 결합되는 신규 노드:
- `java/lang/testcontainers-junit-integration.md` — `@Testcontainers` parallel 미지원, `@Container static` lifecycle, `@ServiceConnection` (Spring 3.1+), DinD sibling pattern
- `_common/test-driven-development.md` — TDD red-green-refactor 원칙 (사후 테스트 anti-pattern)
- `_common/dlq-reprocessing-wal.md` — Kafka consumer DLQ 통합 테스트 시 KafkaContainer 활용
- `_common/durable-execution.md` — Temporal activity test (deterministic replay 검증)
