---
keywords: utf8 utf-8 encoding 인코딩 한글 korean charset characterencoding 깨짐 mojibake ì
intent: 새프로젝트 시작 초기세팅 한글데이터 인코딩설정 DB생성 Docker Compose
paths: application.yml application.properties docker-compose.yml init/*.sql build.gradle
patterns: mysql spring-boot mybatis jackson
requires: db-design devops
phase: plan implement debug
min_score: 1
---

# 한글(UTF-8) 프로젝트 필수 체크리스트

> **모든 한글 데이터를 다루는 프로젝트는 시작 시점에 반드시 이 체크리스트를 적용한다.**
> 누락하면 반드시 중간에 터지고, 중간에 고치면 이미 저장된 깨진 데이터를 수복해야 한다.

## 의사결정 트리

### IF 새 한글 프로젝트 시작 (Plan)
프로젝트 초기 세팅 단계에서 **아래 5개 레이어를 모두** 설정한다. 하나라도 빠지면 필드 단위 인코딩 장애가 발생한다:

1. **DB 서버** — MySQL `character-set-server=utf8mb4`, `collation-server=utf8mb4_unicode_ci`
2. **DB 스키마** — 테이블 `DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`
3. **JDBC URL** — `characterEncoding=UTF-8` (절대 `utf8mb4` 쓰지 않는다, 아래 Gotcha 참조)
4. **Init SQL 실행 환경** — `docker-entrypoint-initdb.d`는 기본 latin1로 실행될 수 있음. init SQL 첫 줄에 `SET NAMES utf8mb4;` 추가
5. **쉘/소스 파일 인코딩** — 편집기는 UTF-8, Windows cmd/PowerShell은 `chcp 65001`

### IF 한글 깨짐 발견 (Debug)
**깨진 모양별 원인 매핑** (외워둘 것):

| 깨진 모양 | 원인 |
|----------|------|
| `ì „ìžê¸°ê¸°` (UTF-8 → Latin1 해석) | DB에는 UTF-8로 저장됐으나 연결이 latin1로 읽음. JDBC URL `characterEncoding` 누락 |
| `????` (물음표) | Connection에서 변환 실패. MySQL 서버 `character-set-server` 미설정 |
| `ì•ˆë…•` | client/connection/results 중 일부만 UTF-8. `SET NAMES utf8mb4` 필요 |
| `\uXXXX` 유니코드 이스케이프 | JSON 직렬화는 문제 없음. 소스 코드 한글이 이스케이프된 것 |
| `Invalid UTF-8 middle byte 0xd7` | 소스 파일은 UTF-8이지만 HTTP 요청 body가 cp949로 인코딩됨 (curl/PowerShell) |

**진단 순서**:
1. `SHOW VARIABLES LIKE 'character_set%';` — 서버 변수 확인 (client, connection, database, results 모두 utf8mb4)
2. `SHOW CREATE TABLE <table>;` — 테이블 charset 확인
3. `SELECT HEX(column_name) FROM table LIMIT 1;` — 실제 저장된 바이트 확인 (UTF-8이면 한글 3바이트)
4. 이미 깨진 데이터는 복구 어려움 — 비파괴 복구 먼저 시도. 볼륨 삭제는 **dev 로컬 + 사용자 명시 확인 후에만** (prod·staging 절대 금지).
   - 비파괴 1순위: `ALTER TABLE ... CONVERT TO CHARACTER SET utf8mb4` 또는 `mysqldump --default-character-set=utf8mb4` 후 `iconv` 보정 → 재import.
   - 비파괴 실패 + dev 로컬일 때만: `docker compose down -v && docker compose up -d` (사용자 확인 필수).

### IF Docker Compose로 DB 기동 (Implement)
`docker-compose.yml`의 MySQL 서비스에 **반드시** 아래 3가지 포함:

```yaml
services:
  mysql:
    image: mysql:5.7  # 또는 8.0
    environment:
      MYSQL_CHARACTER_SET_SERVER: utf8mb4
      MYSQL_COLLATION_SERVER: utf8mb4_unicode_ci
    command: >
      --character-set-server=utf8mb4
      --collation-server=utf8mb4_unicode_ci
      --init-connect='SET NAMES utf8mb4'
    volumes:
      - ./init:/docker-entrypoint-initdb.d
```

**init SQL 첫 줄**:
```sql
SET NAMES utf8mb4;
SET CHARACTER SET utf8mb4;
```
(이거 안 쓰면 docker-entrypoint-initdb.d가 latin1로 실행해서 INSERT된 한글이 깨진 채 저장된다)

### IF Spring Boot 프로젝트 세팅 (Implement)
**application.yml에 강제 체크 항목**:
```yaml
spring:
  datasource:
    # characterEncoding=UTF-8 (절대 utf8mb4 쓰지 않는다)
    url: jdbc:mysql://host:3306/db?useSSL=false&characterEncoding=UTF-8&serverTimezone=Asia/Seoul
  jackson:
    time-zone: Asia/Seoul
    default-property-inclusion: non_null

server:
  servlet:
    encoding:
      charset: UTF-8
      force: true  # 요청/응답 강제 UTF-8
```

### IF 테스트 작성 (Test)
- `application-test.yml`도 동일 `characterEncoding=UTF-8` 설정
- Testcontainers의 `MySQLContainer.getJdbcUrl()`은 기본으로 charset 옵션 없음 → `DynamicPropertySource`에서 URL 뒤에 `?characterEncoding=UTF-8` 추가
- 테스트 데이터는 가능하면 **ASCII로 작성** (한글은 E2E 시나리오에만 최소 사용). 쉘에서 실행되는 curl 테스트는 한글 body 피함

## Gotchas

### JDBC `characterEncoding=utf8mb4`는 오류
MySQL 서버 charset과 JDBC charset은 **다른 개념**이다.
- 서버/DB/테이블: `utf8mb4` (MySQL 이름)
- JDBC 연결 문자열: `UTF-8` (Java 표준 이름)

`characterEncoding=utf8mb4`로 쓰면 `java.io.UnsupportedEncodingException: utf8mb4` 터지며 커넥션 풀 초기화 실패 → API 호출 전부 500. 이건 **과거에 발생했던 실제 사고**이며 필드 5개(application.yml, application-docker.yml, application-test.yml, ci.yml 2곳)에 동시 퍼진다. 프로젝트 시작 시 전수 조사.

### 이미 깨진 데이터는 ALTER로 고쳐지지 않는다
`ALTER TABLE ... CONVERT TO CHARACTER SET utf8mb4`는 **latin1으로 저장된 바이트를 utf8mb4로 재해석할 뿐**, 이미 latin1로 한번 변환되어 저장된 바이트는 부분 복구만 가능. 복구 우선순위:

1. **운영(prod·staging)**: 백업 복구가 유일한 안전 경로. 볼륨 삭제 절대 금지.
2. **dev 로컬, 비파괴 1순위**: `mysqldump --default-character-set=utf8mb4`로 dump → `iconv -f UTF-8 -t UTF-8 -c`로 보정 → 재import.
3. **dev 로컬, 비파괴 실패 + 사용자 명시 확인 후에만**: 볼륨 삭제 + 재삽입.
   ```bash
   # 사용자에게 "이 명령은 모든 DB 데이터를 삭제합니다. 진행?" 확인 받기
   docker compose down -v   # -v 필수, 볼륨 삭제
   docker compose up -d
   ```

### Windows Git Bash의 curl은 한글 body 깨트림
```bash
curl -d '{"name":"홍길동"}'   # 깨짐
```
Git Bash의 기본 인코딩이 cp949라 `홍길동`이 cp949 바이트로 전송됨 → 서버가 UTF-8로 디코딩하면 `Invalid UTF-8 middle byte 0xd7`.
**해결**: 파일로 저장 후 전송
```bash
echo -n '{"name":"홍길동"}' > /tmp/body.json
curl -d @/tmp/body.json
```
또는 테스트에서는 한글 대신 ASCII 값 사용.

### MyBatis `map-underscore-to-camel-case`와 별개
underscore 매핑과 인코딩은 무관. 하지만 둘 다 `mybatis.configuration` 블록에서 설정하므로 헷갈리지 말 것. 둘 다 필요.

### Spring Boot 3.2 기본 HTTP 인코딩
서블릿 레벨에서는 기본 UTF-8이지만 `force: true` 명시 안 하면 일부 컨테이너(Tomcat 내부 에러 페이지)에서 ISO-8859-1로 떨어질 수 있음. `server.servlet.encoding.force=true` 권장.

### Tailwind/React에서는 한글 이슈 거의 없음
프론트엔드 단에서는 `<meta charset="UTF-8">`만 있으면 보통 문제 없음. 한글 깨짐이 나면 **100% 백엔드 응답 단계에서 이미 깨진 것**. 브라우저 DevTools Network 탭에서 Response Headers의 `Content-Type: application/json; charset=UTF-8` 확인.

## 도구 사용 패턴 (Harness)

### 프로젝트 시작 시 체크리스트
- [ ] `grep -r "characterEncoding=utf8mb4" .` — 오류 패턴 검색, 있으면 `UTF-8`로 일괄 변경
- [ ] `grep -r "MYSQL_CHARACTER_SET" docker-compose*.yml` — Docker 설정 누락 확인
- [ ] init SQL 첫 줄 `SET NAMES utf8mb4;` 확인
- [ ] application.yml, application-*.yml, ci.yml의 JDBC URL에 `characterEncoding=UTF-8` 있는지 전수 확인

### 빠른 진단 커맨드
```bash
# 컨테이너 내부 MySQL 변수 확인
docker exec <mysql-container> mysql -u root -p<pw> -e "SHOW VARIABLES LIKE 'character_set%';"

# 실제 저장된 바이트 확인 (한글은 UTF-8이면 3바이트)
docker exec <mysql-container> mysql -u root -p<pw> <db> -e "SELECT HEX(name) FROM <table>;"
```
