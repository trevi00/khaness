---
keywords: log4j2 logging log4jdbc 로깅 로그 logger appender roller async 비동기로그
intent: 설정해 구성해 추가해 수정해 최적화해 마스킹해
paths: src/main/resources/log4j2.xml src/main/resources/log4jdbc.log4j2.properties
patterns: log4j2 log4jdbc spring-boot-starter-log4j2 @Log4j2 disruptor
requires: backend debugging monitoring
phase: plan implement review debug
min_score: 2
---

# Log4j2 로깅 설정 (Spring Boot 3.2.x + log4jdbc)

## 의사결정 트리

### IF log4j2.xml 신규 작성 또는 구조 변경 (Plan/Implement)
1. 회사 스켈레톤 기본 구조를 확인 (아래 "회사 기본 설정" 참조)
2. 환경별 분리 전략 결정 (dev/release)
3. Appender 구성: Console + RollingFile + (필요시) AsyncAppender
4. Logger 구성: Root, springframework, jdbc.*, 프로젝트 패키지
5. **-> 관련 스킬: monitoring (운영 로그 수집과 연계)**

### IF Async Logger 도입 (Implement)
1. `com.lmax:disruptor:4.0.0` 의존성 추가 (Spring Boot 3.x는 4.x 호환)
2. 전역 Async 방식 또는 혼합 방식 중 택 1
   - 전역: `src/main/resources/log4j2.component.properties`에 `log4j2.contextSelector=org.apache.logging.log4j.core.async.AsyncLoggerContextSelector`
   - 혼합: `<AsyncLogger>` 태그로 개별 지정
3. RingBuffer 크기 튜닝: `-Dlog4j2.asyncLoggerRingBufferSize=262144` (기본 256K, 고트래픽 시 증가)
4. 테스트: 부하 테스트 후 로그 유실 여부 확인

### IF SQL 로깅 설정 변경 (Implement)
1. `log4jdbc.log4j2.properties` 확인
2. `log4j2.xml`에서 jdbc.* Logger 레벨 조정
3. dev: `jdbc.sqlonly=DEBUG`, `jdbc.resultsettable=INFO` / release: 모두 `OFF` 또는 `WARN`

### IF 민감 데이터 마스킹 (Implement)
1. PatternLayout에 `%replace` 사용
2. 또는 Custom LogEventPatternConverter 작성 (정규식 기반)
3. 마스킹 대상: 주민번호, 카드번호, 비밀번호, 전화번호, 이메일

### IF 로깅 문제 디버그 (Debug)
1. `<Configuration status="DEBUG">`로 변경하여 Log4j2 내부 로그 확인
2. 의존성 충돌 확인: `./gradlew dependencies | grep log` 에서 logback 잔존 여부
3. additivity 설정 확인 (중복 출력 원인)

### IF 리뷰 (Review)
- [ ] Logback 의존성 완전 제거 확인 (`spring-boot-starter-logging` exclude)
- [ ] release 환경에서 DEBUG/TRACE 레벨 비활성화 확인
- [ ] 민감 데이터 마스킹 적용 확인
- [ ] RollingFile 로테이션 정책 적절성 (용량/보관 기간)
- [ ] Async Logger 사용 시 disruptor 의존성 존재 확인
- [ ] `additivity="false"` 누락으로 인한 중복 로그 없는지 확인

## 가이드

### 회사 기본 설정 (스켈레톤 1.0.2 기준)

**log4j2.xml 구조:**
```xml
<Configuration status="INFO">
  <Properties>
    <Property name="COLOR_PATTERN">[%clr{%d{yyyy-MM-dd HH:mm:ss.SSS}}{faint}] %clr{%5p} %clr{${sys:PID}}{magenta} %clr{-}{faint} %clr{%logger[%method:%line]}{cyan} %clr{:}{faint} %m%n%xwEx</Property>
  </Properties>
  <Appenders>
    <Console name="ConsoleAppender" target="SYSTEM_OUT" follow="true">
      <PatternLayout pattern="${COLOR_PATTERN}"/>
    </Console>
  </Appenders>
  <Loggers>
    <Root level="INFO" additivity="false">
      <AppenderRef ref="ConsoleAppender"/>
    </Root>
    <!-- jdbc loggers: sqlonly=INFO, sqltiming=OFF, resultsettable=INFO, audit=OFF, resultset=OFF, connection=OFF -->
  </Loggers>
</Configuration>
```

**log4jdbc.log4j2.properties:**
```properties
log4jdbc.spylogdelegator.name=net.sf.log4jdbc.log.slf4j.Slf4jSpyLogDelegator
log4jdbc.dump.sql.maxlinelength=0
log4jdbc.drivers=com.mysql.cj.jdbc.Driver
log4jdbc.auto.load.popular.drivers=false
```

**Gradle 의존성 (build.gradle):**
```groovy
configurations {
    all*.exclude module: 'spring-boot-starter-logging'
}
dependencies {
    implementation 'org.springframework.boot:spring-boot-starter-log4j2'
    // Async Logger 사용 시:
    // implementation 'com.lmax:disruptor:4.0.0'
}
```

### 환경별 로깅 전략

| 항목 | dev | release |
|------|-----|---------|
| Root level | DEBUG | INFO 또는 WARN |
| jdbc.sqlonly | DEBUG (쿼리 전문) | OFF |
| jdbc.resultsettable | INFO (결과셋 테이블) | OFF |
| jdbc.sqltiming | DEBUG (쿼리 실행 시간) | WARN (슬로우 쿼리만) |
| 프로젝트 패키지 | DEBUG | INFO |
| Appender | Console only | Console + RollingFile |

Spring Profile 기반 분리: `log4j2-spring.xml`을 사용하면 `<SpringProfile>` 태그로 환경별 분기 가능.

### RollingFile 설정 (release 환경)

```xml
<RollingFile name="FileAppender"
    fileName="logs/app.log"
    filePattern="logs/app-%d{yyyy-MM-dd}-%i.log.gz">
  <PatternLayout pattern="%d{yyyy-MM-dd HH:mm:ss.SSS} [%t] %-5level %logger{36}[%method:%line] - %msg%n"/>
  <Policies>
    <TimeBasedTriggeringPolicy interval="1" modulate="true"/>
    <SizeBasedTriggeringPolicy size="100MB"/>
  </Policies>
  <DefaultRolloverStrategy max="30">
    <Delete basePath="logs" maxDepth="1">
      <IfFileName glob="app-*.log.gz"/>
      <IfLastModified age="30d"/>
    </Delete>
  </DefaultRolloverStrategy>
</RollingFile>
```

### Async Logger 설정

**방법 1: 전역 Async (권장 - 고성능)**
`src/main/resources/log4j2.component.properties`:
```properties
log4j2.contextSelector=org.apache.logging.log4j.core.async.AsyncLoggerContextSelector
```
이 방식은 모든 Logger가 자동으로 Async가 됨. 별도의 XML 변경 불필요.

**방법 2: 혼합 (특정 Logger만 Async)**
```xml
<Loggers>
  <AsyncLogger name="com.mycompany" level="DEBUG" additivity="false">
    <AppenderRef ref="ConsoleAppender"/>
    <AppenderRef ref="FileAppender"/>
  </AsyncLogger>
  <Root level="INFO">
    <AppenderRef ref="ConsoleAppender"/>
  </Root>
</Loggers>
```

**방법 3: AsyncAppender 래퍼 (가장 단순, 성능은 방법1보다 낮음)**
```xml
<Appenders>
  <Console name="Console" .../>
  <Async name="AsyncConsole">
    <AppenderRef ref="Console"/>
  </Async>
</Appenders>
```

### 민감 데이터 마스킹

**PatternLayout %replace 사용:**
```xml
<PatternLayout>
  <Pattern>%d %-5p %c - %replace{%msg}{(\d{6}[-]?\d{7})}{******-*******}%n</Pattern>
</PatternLayout>
```

**다중 패턴 마스킹 (RegexReplacement 체인):**
```xml
<PatternLayout pattern="%d %-5p %c - %msg%n">
  <!-- 카드번호 마스킹 -->
  <Replace regex="(\d{4})[-\s]?(\d{4})[-\s]?(\d{4})[-\s]?(\d{4})" replacement="$1-****-****-$4"/>
  <!-- 비밀번호 필드 마스킹 -->
  <Replace regex="(password|pwd)\s*[:=]\s*\S+" replacement="$1=********"/>
</PatternLayout>
```

### log4jdbc SQL 로깅 Logger 역할 정리

| Logger 이름 | 용도 | 권장 (dev) |
|-------------|------|-----------|
| jdbc.sqlonly | 실행된 SQL (바인드 변수 치환됨) | DEBUG |
| jdbc.sqltiming | SQL + 실행 시간 | DEBUG |
| jdbc.resultsettable | 결과셋을 테이블 형태로 출력 | INFO (소량 데이터만) |
| jdbc.audit | JDBC 호출 전체 (매우 상세) | OFF |
| jdbc.resultset | ResultSet 조작 로그 | OFF |
| jdbc.connection | 커넥션 open/close | OFF (누수 의심 시 DEBUG) |

## Gotchas

### Logback 의존성 충돌 - 가장 흔한 오류
`spring-boot-starter-web`, `spring-boot-starter-data-jpa` 등이 `spring-boot-starter-logging`(Logback)을 전이 의존으로 가져옴. 반드시 전역 exclude 필요:
```groovy
configurations { all*.exclude module: 'spring-boot-starter-logging' }
```
제거 안 하면 `SLF4J: Class path contains multiple SLF4J bindings` 경고 또는 Log4j2 설정이 무시됨.

### @Slf4j vs @Log4j2 혼동
회사 표준은 **@Log4j2 (Lombok)** 사용. `@Slf4j`를 쓰면 SLF4J 파사드를 통해 간접 호출되므로 Log4j2 전용 기능(Marker, FlowTracing 등)을 사용할 수 없음. 기존 코드에 `@Slf4j`가 섞여 있으면 동작은 하지만 일관성을 위해 `@Log4j2`로 통일할 것.

### Async Logger + 위치 정보(Location) 성능 저하
`%method`, `%line`, `%class` 등 위치 정보 패턴은 stacktrace를 생성해야 하므로 Async Logger의 성능 이점을 크게 감소시킴(5~20배 느려질 수 있음). 회사 스켈레톤의 COLOR_PATTERN에 `%method:%line`이 포함되어 있으므로, **Async Logger 도입 시 release 환경에서는 위치 정보를 제거하거나 `includeLocation="false"`를 명시**할 것.

### Async Logger에서 disruptor 누락 시 무음 실패
`disruptor` 의존성 없이 AsyncLoggerContextSelector를 설정하면, Spring Boot가 정상 기동하면서 로그만 출력되지 않거나 동기 모드로 폴백됨. 에러 메시지가 눈에 잘 안 띄므로, `<Configuration status="DEBUG">`로 내부 로그를 확인할 것.

### log4jdbc + HikariCP 드라이버 설정
log4jdbc 사용 시 DataSource 설정에서 드라이버를 `net.sf.log4jdbc.sql.jdbcapi.DriverSpy`로, URL을 `jdbc:log4jdbc:mysql://...`로 변경해야 함. 이를 빠뜨리면 SQL 로깅이 작동하지 않음.

### additivity="false" 누락
회사 스켈레톤은 모든 Logger에 `additivity="false"`를 설정해둠. 새 Logger 추가 시 이를 빼먹으면 Root Logger에도 전파되어 **같은 로그가 2번 출력**됨.

### log4j2-spring.xml vs log4j2.xml
Spring Boot는 `log4j2-spring.xml`을 우선 로딩하며, 이 파일명을 써야 `<SpringProfile>` 태그 사용 가능. 회사 스켈레톤은 `log4j2.xml`을 사용하므로, 프로파일별 분기가 필요하면 파일명을 `log4j2-spring.xml`로 변경하거나 `logging.config` 프로퍼티로 명시적 지정.

### Windows 환경에서 파일 로그 경로
`fileName="logs/app.log"` 같은 상대 경로는 프로젝트 루트 기준. Windows에서 절대 경로 사용 시 `fileName="C:/logs/app.log"` (슬래시 사용 가능) 또는 `fileName="C:\\logs\\app.log"`.

### RollingFile에서 .gz 압축 + Delete 정책 미설정
로테이션만 설정하고 Delete 정책을 안 넣으면 디스크가 가득 참. 반드시 `<DefaultRolloverStrategy>` 내에 `<Delete>` 설정을 추가하여 보관 기간/용량 제한.
