---
keywords: 데이터베이스 database DB db 쿼리 query 인덱스 index 테이블 table 스키마 schema MySQL mysql 커넥션풀 connection-pool HikariCP hikari 파티셔닝 partition 마이그레이션 migration 초기화 init 정규화 ERD erd 모델링 modeling slow-query 슬로우쿼리 explain 실행계획 레디스 redis 캐시 cache 캐싱 caching TTL ttl mybatis mapper DAO resultMap typeHandler
intent: DB설계해 모델링해 쿼리최적화해 인덱스추가해 스키마수정해 마이그레이션해 DB만들어 테이블해 DDL해 인덱스해
paths: init/ sql/ migration/ schema/ src/main/resources/schema.sql docker-entrypoint-initdb.d
patterns: mysql postgresql h2 hikari flyway liquibase information_schema spring-data-jdbc docker-compose redis lettuce jedis spring-data-redis
requires: backend
phase: plan implement review debug
min_score: 3
---

# Database Guide (MySQL 중심)

## 의사결정 트리

### IF DB 설계/모델링 (Plan)
1. 도메인 분석 → 엔티티 도출 → ERD 작성
2. 정규화 적용 (3NF까지), 필요시 비정규화 판단
3. PK 전략: auto_increment (BIGINT) 기본
4. 인덱스 전략: 검색 조건에 자주 쓰이는 컬럼 중심
5. 데이터 볼륨 추정 → 파티셔닝 필요 여부 판단
6. init 스크립트 작성 (Docker `docker-entrypoint-initdb.d`)

### IF 쿼리 성능 문제 (Debug)
1. `EXPLAIN` 실행 → type, key, rows, Extra 확인
2. type이 `ALL` → Full Table Scan → 인덱스 추가 필요
3. Extra에 `Using filesort`, `Using temporary` → 쿼리/인덱스 재설계
4. 복합 인덱스: 첫 번째 컬럼이 WHERE에 없으면 인덱스 무효 (leftmost prefix)
5. **→ backend 스킬: Repository 쿼리 수정**

### IF 인덱스 설계 (Implement)
1. WHERE, JOIN, ORDER BY에 자주 쓰이는 컬럼 선별
2. 카디널리티 높은 컬럼 우선 (성별 X, 주문번호 O)
3. 복합 인덱스: 등호(=) 조건 → 범위(BETWEEN, >) 순서
4. 커버링 인덱스 고려 (SELECT 컬럼까지 인덱스에 포함)
5. 과도한 인덱스 경계 (INSERT/UPDATE 성능 저하)

### IF 커넥션 풀 설정 (Implement)
1. HikariCP 기본 설정 확인
2. `maximum-pool-size`: CPU 코어 × 2 + 유효 디스크 수 (일반적으로 10~20)
3. `leak-detection-threshold`: 개발 시 60000ms (1분)
4. **→ monitoring 스킬: Grafana에서 pool 메트릭 확인**

### IF DB 리뷰 (Review)
- [ ] 인덱스가 주요 조회 패턴을 커버하는가
- [ ] N+1 쿼리 없는가 (특히 JPA)
- [ ] 트랜잭션 범위가 적절한가 (너무 넓지 않은가)
- [ ] auto_increment PK 사용 (UUID PK → 인덱스 단편화)
- [ ] 민감 데이터 컬럼 암호화 여부

## EXPLAIN 읽기 가이드
| type | 의미 | 대응 |
|------|------|------|
| const/eq_ref | PK/유니크 키 조회 (최상) | OK |
| ref | 인덱스 조회 | OK |
| range | 인덱스 범위 스캔 | 대체로 OK |
| index | 인덱스 풀 스캔 | 개선 여지 |
| ALL | 테이블 풀 스캔 | **인덱스 추가 필수** |

Extra 주의:
- `Using index` → 커버링 인덱스 (좋음)
- `Using where` → 인덱스로 필터링 후 추가 조건 적용
- `Using filesort` → 정렬에 인덱스 미사용 (개선 필요)
- `Using temporary` → 임시 테이블 사용 (개선 필요)

## Docker MySQL 초기화 패턴
```
project/
├── docker-compose.yml
└── init/
    ├── 01-schema.sql     # CREATE TABLE
    ├── 02-index.sql      # CREATE INDEX
    └── 03-seed.sql       # INSERT 초기 데이터
```
`docker-entrypoint-initdb.d`에 마운트된 .sql 파일은 파일명 순서대로 실행.

## HikariCP 설정 (application.yml)
```yaml
spring:
  datasource:
    hikari:
      maximum-pool-size: 10
      minimum-idle: 5
      connection-timeout: 30000      # 30초
      idle-timeout: 600000           # 10분
      max-lifetime: 1800000          # 30분
      leak-detection-threshold: 60000 # 1분 (개발용)
```

## 데이터 볼륨 추정
```sql
-- 테이블 크기 확인
SELECT table_name,
       ROUND(data_length / 1024 / 1024, 2) AS data_mb,
       ROUND(index_length / 1024 / 1024, 2) AS index_mb,
       table_rows
FROM information_schema.tables
WHERE table_schema = 'appdb';
```
예상 레코드 × 행 크기로 1년치 용량 계산 → 디스크/파티셔닝 계획.

## Redis 캐시 전략 (DB 관점)

### IF 캐시 도입 판단 (Plan)
1. **먼저 쿼리 최적화** 시도 (EXPLAIN → 인덱스 추가)
2. 인덱스 최적화로도 부족하면 Redis 캐시 검토
3. 캐시 대상: 읽기 빈도 높고 변경 빈도 낮은 데이터 (상품 상세, 카테고리)
4. 캐시 부적합: 실시간 정합성 필수 (결제 잔액, 재고 수량)

### 캐시 무효화 전략
| 전략 | 설명 | 적합한 경우 |
|------|------|------------|
| TTL 만료 | 일정 시간 후 자동 삭제 | 약간의 지연 허용 (상품 목록) |
| Write-through | DB 쓰기 시 캐시도 갱신 | 읽기/쓰기 비율 균등 |
| Cache-aside | DB 쓰기 시 캐시만 삭제, 다음 읽기 시 재캐시 | 읽기 >> 쓰기 (일반적) |
| Event-driven | Kafka 등 이벤트로 캐시 갱신 | 마이크로서비스, 분산 시스템 |

### 캐시 키 설계 원칙
- 콜론(`:`)으로 네임스페이스: `product:123`, `category:list`
- 검색 조건 해시: `product:search:hash(keyword+page+sort)`
- 목록 캐시는 첫 N페이지만 (대부분 사용자는 1~3페이지만 조회)

## Gotchas

### 복합 인덱스 순서 실수
`INDEX(status, created_at)`에서 `WHERE created_at > ?`만 쓰면 인덱스 무효. 반드시 첫 번째 컬럼(status)이 WHERE에 포함되어야 함 (leftmost prefix rule). 단, MySQL Optimizer가 상황에 따라 index skip scan을 적용할 수 있음.

### auto_increment 대신 UUID를 PK로
UUID는 128비트 + 랜덤 → B-Tree 인덱스 페이지 분할 빈발 → INSERT 성능 저하. 외부 노출용 ID가 필요하면 별도 컬럼(uuid)을 두고 PK는 auto_increment BIGINT 유지.

### Docker MySQL init 스크립트 재실행 안 됨
`docker-entrypoint-initdb.d`는 **볼륨이 비어있을 때만** 실행. 스키마를 수정했는데 반영이 안 되면 `docker volume rm`으로 볼륨 삭제 후 재생성.

### 트랜잭션 범위가 너무 넓음
주문+결제+재고 전체를 하나의 트랜잭션으로 감싸면 커넥션을 오래 점유 → 풀 고갈. 비즈니스 단위로 트랜잭션을 분리하고 보상 트랜잭션(Saga) 패턴 고려.

### MySQL 예약어 충돌
`order`, `rank`, `groups` 등이 예약어. 테이블/컬럼명에 사용하면 SQL 에러. 백틱(`)으로 감싸거나, `orders`, `user_rank` 등으로 변경.

### MySQL 5.7 제약사항
- **CTE (WITH ... AS) 미지원** — 서브쿼리로 대체
- **Window Function 미지원** — ROW_NUMBER(), RANK() 등 사용 불가. 변수(`@rownum`)나 서브쿼리로 대체
- **CHECK 제약조건 미적용** — 파싱만 되고 실제 검증 안 됨. 애플리케이션 레벨에서 검증 필수
- **JSON_TABLE, JSON_ARRAYAGG 미지원** — 기본 JSON 함수(JSON_EXTRACT, JSON_SET 등)만 사용 가능
- **Invisible/Descending Index 미지원**
- **SKIP LOCKED / NOWAIT 미지원** — 비관적 락 사용 시 SELECT FOR UPDATE만 가능

### Gap Lock으로 인한 데드락
MySQL InnoDB의 Gap Lock은 인덱스 범위에 잠금을 걸어 팬텀 리드를 방지하지만, 동시 INSERT 시 데드락 발생 가능. 복합 PK/인덱스 설계 시 잠금 범위를 인지할 것.

### HikariCP pool 고갈 증상
`Connection is not available, request timed out after 30000ms` — 트랜잭션이 오래 유지되거나, 커넥션을 반환하지 않을 때 발생. `leak-detection-threshold` 설정으로 누수 감지.

### information_schema 조회 성능
`information_schema` 조회는 메타데이터 락을 잡을 수 있음. 프로덕션에서 빈번히 호출하지 말 것. 개발/디버깅 용도로만 사용.

### MyBatis 동적 SQL 빈 문자열 체크 누락
`test="name != null"` 만으로는 빈 문자열("")을 걸러내지 못함. `test="name != null and name != ''"` 패턴 사용. `<where>` 태그를 사용하면 조건이 모두 false일 때 WHERE 자체가 생략됨.

### MyBatis #{} vs ${} 혼동
`${}`는 문자열 치환(SQL Injection 위험), `#{}`는 PreparedStatement 파라미터 바인딩. `<foreach>`의 IN절에서 반드시 `#{}` 사용. `${}`는 테이블명/컬럼명 동적 치환에만 제한적으로 사용.

### MyBatis resultMap에서 <id> 누락
1:N 관계(collection) 매핑 시 `<id>` 요소를 지정하지 않으면 MyBatis가 행 중복을 구분하지 못해 잘못된 결과 생성. 반드시 PK 컬럼에 `<id>` 지정.

### MyBatis N+1 쿼리
Nested Select(`<collection select="...">`)는 각 행마다 별도 쿼리 실행 → N+1 발생. Nested Result(JOIN + resultMap collection)로 단일 쿼리 해결. Nested Result에서는 컬럼 alias 필수 (부모/자식 동일 컬럼명 충돌 방지).

### MyBatis <foreach> 빈 컬렉션
빈 리스트를 `<foreach>`에 전달하면 `IN ()` 구문 오류. Java 단에서 빈 리스트 사전 체크 필요.

### MySQL 5.7 대량 OFFSET 성능
`LIMIT 10 OFFSET 100000`이면 100,010행 스캔 후 100,000행 버림. Deferred Join 패턴(서브쿼리에서 PK만 OFFSET 후 본 테이블 JOIN) 또는 Keyset 페이징 사용.

## 도구 사용 패턴 (Harness)
- 스키마 확인: `Bash(docker exec mysql mysql -e "DESC table_name")`
- EXPLAIN 실행: `Bash(docker exec mysql mysql -e "EXPLAIN SELECT ...")`
- 테이블 크기: `Bash`로 information_schema 조회
- init 스크립트: `Read`로 .sql 파일 확인, `Edit`으로 수정
- application.yml의 HikariCP 설정: `Read` → `Edit`

## 에러 복구 패턴 (Harness)
- 쿼리 느림 → `Bash`로 EXPLAIN 실행 → type=ALL이면 인덱스 추가
- 커넥션 타임아웃 → `Read`로 HikariCP 설정 확인, `Bash(docker ps)`로 MySQL 상태 확인
- init 스크립트 미반영 → `Bash(docker volume ls)` → 볼륨 삭제 후 재생성
- 데드락 → `Bash(docker exec mysql mysql -e "SHOW ENGINE INNODB STATUS")`로 락 확인
