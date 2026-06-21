---
name: testcontainers-junit-integration
description: Testcontainers + JUnit 5 + JaCoCo 통합 — @Container 라이프사이클, Spring @ServiceConnection, DinD sibling, 멀티모듈 coverage 집계
keywords: testcontainers junit5 jacoco container service-connection localstack docker dind sibling coverage-aggregation
intent: setup-testcontainer manage-container-lifecycle integrate-spring-boot configure-jacoco handle-dind-ci
paths: src/test/java
patterns: @Testcontainers @Container GenericContainer ServiceConnection jacocoTestReport
requires: api-contracts service-resilience-patterns
phase: plan implement review debug
tech-stack: java
min_score: 2
quality_axes_enforced: true
---

# Testcontainers + JUnit 5 + JaCoCo

> 핵심: `@Testcontainers` extension은 **순차 실행만 지원** (parallel test 미지원). `@Container static` (shared) vs instance (per-test) 결정이 비용을 좌우. Spring Boot 3.1+ `@ServiceConnection`로 boilerplate 제거. CI는 DinD가 아닌 **sibling pattern** (Docker socket mount).

## 의사결정 트리

### IF 신규 integration test (Implement)
1. JUnit 5 extension — `@Testcontainers` 클래스에 + `@Container` 필드에
2. lifecycle — `static @Container` (클래스당 1회 시작) vs instance (테스트마다 재시작). **shared 우선** — 비용 절감
3. parallel execution — **JUnit Jupiter parallel 미지원**. 시퀀셜로
4. Spring Boot 3.1+ → `@ServiceConnection` 으로 properties auto-binding (PG/MySQL/Mongo/Kafka 등)

### IF 모듈 선택 (Implement)
| 백엔드 | 모듈 |
|---|---|
| PostgreSQL/MySQL/Mongo | 전용 module (`PostgreSQLContainer`, `MySQLContainer`) |
| Kafka | `KafkaContainer` |
| AWS (S3/SQS/etc) | **LocalStack** (`LocalStackContainer`) |
| Elasticsearch | `ElasticsearchContainer` |
| 임의 image | `GenericContainer<>` |

### IF Spring Boot 통합 (Implement)
```java
@SpringBootTest
@Testcontainers
class IntegrationTest {
  @Container @ServiceConnection
  static PostgreSQLContainer<?> pg = new PostgreSQLContainer<>("postgres:16");
}
```
Spring Boot 3.1+에서 `@ServiceConnection`이 `ConnectionDetails` bean 자동 생성 — `application.properties` 수정 불필요.

### IF JaCoCo coverage (Implement)
1. plugin — `plugins { jacoco }` 각 모듈
2. report — `tasks.test { finalizedBy(jacocoTestReport) }`
3. 임계 — `jacocoTestCoverageVerification { violationRules { rule { limit { minimum = "0.7".toBigDecimal() } } } }`
4. 멀티모듈 집계 — **JaCoCo Report Aggregation Plugin** (Gradle 7.4+) — 별도 모듈에서 모든 sub-project coverage 합산

### IF CI에서 Testcontainers (Plan)
1. **sibling pattern** (Docker Wormhole) 권장 — `/var/run/docker.sock` mount + same-path source mount
2. DinD (Docker-in-Docker) — "instrument of last resort" (공식 docs verbatim)
3. Mac/Apple Silicon — Docker Desktop + `TESTCONTAINERS_HOST_OVERRIDE=host.docker.internal`
4. LocalStack — 2026-03-23부터 `LOCALSTACK_AUTH_TOKEN` 환경변수 필수

## 가이드

- Reuse — `.withReuse(true)` + `~/.testcontainers.properties testcontainers.reuse.enable=true` 설정 시 컨테이너 재사용 (개발 속도 ↑)
- Network — 같은 `Network`로 묶으면 컨테이너 간 통신 가능 (`@Container` 필드끼리)
- TestContainers Desktop — 로컬 개발용 Docker Desktop 대체

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | 실제 DB/Kafka/S3 통합 — mock 우회로 인한 silent corruption 차단 |
| 성능 효율성 | shared `@Container static` + reuse로 컨테이너 시작 비용 ↓ |
| 호환성 | JUnit 5 + Spring Boot 3.1+ `@ServiceConnection` 자동 연동 |
| 사용성 | annotation-driven, `application.properties` override 불필요 |
| 신뢰성 | LocalStack으로 AWS 통합 테스트 — 실제 AWS 호출 0 |
| 보안 | 테스트용 임시 credential, `LOCALSTACK_AUTH_TOKEN` 명시 |
| 유지보수성 | JaCoCo Report Aggregation으로 멀티모듈 coverage 1개 리포트 |
| 이식성 | sibling pattern으로 어떤 CI runner든 동작 |
| 확장성 | `GenericContainer<>` 로 임의 Docker image 통합 |

## Gotchas

### Parallel test execution 시도
`@Testcontainers` extension docs verbatim: "tested with sequential test execution. Using it with parallel test execution is unsupported." parallel 활성 시 race + flaky.

### Per-test instance `@Container` 남용
컨테이너 시작/종료 비용 (특히 PG/Kafka) 매우 큼. 의도 없으면 **`static`**으로 클래스당 1회 시작.

### DinD를 default로 채택
공식 docs "instrument of last resort". sibling pattern (Docker socket mount + same path) 우선.

### Mac arm64 호환 미검증 image
일부 image는 amd64만 — Mac M1/M2/M3에서 `--platform linux/amd64` 강제 필요. 또는 multi-arch image 사용.

### LocalStack 2026-03-23 이후 auth token 누락
`LOCALSTACK_AUTH_TOKEN` 미설정 시 일부 service 거부. CI secret에 등록.

### JaCoCo 멀티모듈에서 모듈별 리포트만
각 모듈에 `jacoco` 적용해도 통합 리포트 없음. **JaCoCo Report Aggregation Plugin** 별도 모듈 필요.

### `@Container` 필드 순서 의존
JUnit이 클래스 fields 선언 순서로 시작. dependency 있는 컨테이너 (Kafka가 ZK 필요) — `@DependsOn` 패턴 또는 명시 sequence.

## Source

- https://java.testcontainers.org/ — 공식 docs entry, 조회 2026-05-10
- https://java.testcontainers.org/test_framework_integration/junit_5/ — `@Testcontainers` + `@Container` lifecycle; "tested with sequential test execution. Using it with parallel test execution is unsupported", 조회 2026-05-10
- https://java.testcontainers.org/modules/localstack/ — LocalStack `LOCALSTACK_AUTH_TOKEN` 요구 (2026-03-23+), 조회 2026-05-10
- https://java.testcontainers.org/supported_docker_environment/continuous_integration/dind_patterns/ — sibling pattern 우선, DinD "instrument of last resort", 조회 2026-05-10
- https://docs.spring.io/spring-boot/reference/testing/testcontainers.html — `@ServiceConnection` Spring Boot 3.1+ 통합, 조회 2026-05-10
- https://docs.gradle.org/current/userguide/jacoco_plugin.html — `jacocoTestReport`, coverage threshold, Report Aggregation, 조회 2026-05-10
- https://testcontainers.com/modules/ — 모듈 카탈로그, 조회 2026-05-10
