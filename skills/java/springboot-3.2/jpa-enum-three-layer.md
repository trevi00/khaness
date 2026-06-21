---
name: jpa-enum-three-layer
description: Java enum이 DB(VARCHAR), JPA(@Enumerated), JSON wire 세 계층에서 표기가 다를 때 표준화하는 패턴 — Hibernate 6.2+ MySQL native ENUM 함정 회피 포함
keywords: jpa enum hibernate jdbctypecode jsonproperty mysql ddl validate
intent: 매핑 정렬 변환 설계
paths: src/main/java src/main/resources
patterns: @Enumerated @JdbcTypeCode @JsonProperty @Pattern
phase: design implement debug
tech-stack: java
min_score: 2
---

# JPA enum 3-layer 매핑 패턴

> 핵심 원칙: Java enum 이름은 `UPPER_SNAKE_CASE`. DB 컬럼 값은 그 enum 이름을 **그대로** UPPERCASE로 저장 (Hibernate 기본). JSON wire는 **lowercase / dot.notation** (사용자 친화). 세 계층의 변환은 한 곳에서만 일어나고, 양방향 자동화한다. `ddl-auto: validate`로 항상 DDL ↔ Entity 정렬 검증한다.

## 의사결정 트리

### IF 새 enum 추가 (Design)
1. Java enum 정의:
   ```java
   public enum OrderStatus {
       PENDING, ACCEPTED, PREPARING, READY, COMPLETED, CANCELLED
   }
   ```
2. JPA entity field:
   ```java
   @Enumerated(EnumType.STRING)
   @JdbcTypeCode(SqlTypes.VARCHAR)   // Hibernate 6.2+ MySQL ENUM 자동 매핑 회피 (§Gotchas)
   @Column(nullable = false, length = 16)
   private OrderStatus status;
   ```
3. DDL (MySQL):
   ```sql
   status VARCHAR(16) NOT NULL,   -- ENUM('PENDING', ...) 절대 X
   CHECK (status IN ('PENDING', 'ACCEPTED', 'PREPARING', 'READY', 'COMPLETED', 'CANCELLED'))
   ```
4. JSON wire 표기 (필요 시):
   ```java
   public enum OrderStatus {
       @JsonProperty("pending") PENDING,
       @JsonProperty("accepted") ACCEPTED,
       ...
   }
   ```
   `@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)` global 설정과 별개로 enum value는 `@JsonProperty`로 명시.
5. API 요청 측 `@Pattern` validation: `^(pending|accepted|preparing|ready|completed|cancelled)$` (lowercase).

### IF 기존 enum이 어긋남 (Debug)
1. `ddl-auto: validate`로 부팅 — schema mismatch 즉시 fail:
   ```
   Caused by: org.hibernate.tool.schema.spi.SchemaManagementException:
     Schema-validation: wrong column type encountered in column [status]
     in table [orders]; found [varchar (Types#VARCHAR)], but expecting [enum (Types#OTHER)]
   ```
2. Hibernate 6.2+가 MySQL native ENUM 자동 발견하는 경우 → `@JdbcTypeCode(SqlTypes.VARCHAR)` 추가.
3. JSON 응답이 `OrderStatus.PENDING`처럼 UPPERCASE면 → `@JsonProperty` 누락.
4. API 요청 reject가 `pending`을 거부하면 → `@Pattern` 또는 `@Enumerated` parsing 측 lower-case → upper 변환 누락.

### IF release 게이트 (Review)
- [ ] 모든 enum field에 `@Enumerated(STRING)` + `@JdbcTypeCode(VARCHAR)` 또는 명시적 컬럼 타입
- [ ] DDL 컬럼은 VARCHAR(N) — N은 가장 긴 enum name + 여유
- [ ] `application.yml`의 spring.jpa.hibernate.ddl-auto: validate (테스트/프로덕션 모두)
- [ ] JSON 직렬화/역직렬화 round-trip 테스트 (request → entity → JSON response)

## Hibernate 6.2+ MySQL native ENUM 함정

example_project Stage 18 학습: Hibernate 6.2 MySQLDialect는 enum field를 발견하면 자동으로 **DB native `ENUM(...)`** 컬럼으로 매핑 시도. 이는:

1. DDL을 직접 작성한 경우 (보통 VARCHAR로) → schema validation fail
2. ddl-auto: update / create로 자동 생성하면 DB에 `ENUM('A', 'B', ...)` 컬럼 생성됨 — 나중에 enum value 추가 시 `ALTER TABLE` 필수 (운영 부담)

회피: **모든 enum field에 `@JdbcTypeCode(SqlTypes.VARCHAR)`**:

```java
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

@Enumerated(EnumType.STRING)
@JdbcTypeCode(SqlTypes.VARCHAR)
@Column(nullable = false, length = 16)
private OrderStatus status;
```

example_project에서 양 server 16개 field 일괄 추가 후 `ddl-auto: validate` 활성화 성공.

## DDL ↔ Entity 자동 정렬 게이트

```yaml
# application.yml (prod + test 모두)
spring:
  jpa:
    hibernate:
      ddl-auto: validate   # none / create / update 모두 X
```

`validate`는 부팅 시점에 entity 메타데이터 vs DB schema 정합성 검증. 어긋나면 immediate fail. test phase에서 `ddl-auto: validate` 활성화하면 PR 단계에서 DDL drift를 잡을 수 있음.

## JSON ↔ Java 변환 layer

```java
public enum DeploymentStatus {
    @JsonProperty("pending") PENDING,
    @JsonProperty("applied") APPLIED,
    @JsonProperty("rolled_back") ROLLED_BACK,
    @JsonProperty("failed") FAILED;
}
```

수신 측 controller:
```java
public record DeploymentRequest(
    @NotNull
    @Pattern(regexp = "^(pending|applied|rolled_back|failed)$")
    String status   // JSON에서 lowercase로 들어옴
) {}
```

Service 변환:
```java
DeploymentStatus parsed = DeploymentStatus.valueOf(request.status().toUpperCase());
// 또는 ObjectMapper가 @JsonProperty 보고 직접 변환
```

## Gotchas

### `@Enumerated(EnumType.ORDINAL)`은 절대 X
ordinal은 enum 선언 순서에 의존. 중간에 새 value 끼워 넣으면 기존 DB row 의미가 바뀜 (silent data corruption). 항상 `STRING`.

### enum value 이름 변경 = DB schema breaking change
`OrderStatus.READY` → `READY_FOR_PICKUP` rename은 DB에 `WHERE status = 'READY'`로 박힌 모든 row와 `CHECK` constraint를 동시에 바꿔야 함. enum rename은 migration script 필수, `@JsonProperty` value는 wire 호환 위해 그대로 두는 것이 일반적.

### Flyway/Liquibase 없으면 enum 추가가 silent fail
`CHECK (status IN ('PENDING', ...))` 컬럼에 `NEW_VALUE` 추가하려면 ALTER. ddl-auto: validate면 부팅 시점에 잡힘 (good). update/none이면 INSERT 시점에 SQLException — 운영에서 발견 (bad).

### Lombok `@AllArgsConstructor`가 enum 생성자 노출
public enum 생성자는 외부에서 호출 가능하면 안 됨. enum에 Lombok 어노테이션 붙이지 않기 (또는 `@AllArgsConstructor(access = AccessLevel.PRIVATE)`).

### enum 컬럼 length VARCHAR 너무 짧음
`VARCHAR(8)`로 박았는데 새 value `IN_PROGRESS_LONG` 추가 → 부팅 시 validation OK이지만 INSERT 시점에 truncate fail. 가장 긴 enum name + 50% 여유 권장.

### `@JsonProperty` enum value에 dot 들어가는 경우 (`menu.deployed`) request validation
JSON wire에 `menu.deployed` (dot notation) 쓰는 정책이면 `@Pattern` regex에 `\\.` escape 필수. URL path segment로 그대로 쓰면 안 됨 (path는 slash로 해석).

### enum field가 `@Embedded`/`@AttributeOverride` 안에 있을 때 `@JdbcTypeCode` 누락
embeddable 안의 enum field도 같은 함정 — embeddable 정의부에 `@JdbcTypeCode` 명시. example_project Stage 18에서 16개 field 중 7개가 embeddable 또는 collection 안에 있었음.

### Flutter 측 `enhanced_enum` / Dart 3 sealed class 매핑
Dart enum도 `@JsonValue` (json_annotation) 또는 sealed class로 wire value 매핑. 양쪽 정의를 동기화하지 않으면 `cancelled`만 wire에 보내는데 Dart enum이 `cancelled` 모르고 throw. 단일 정의 소스 (OpenAPI spec) 권장.
