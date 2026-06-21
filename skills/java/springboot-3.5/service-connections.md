---
name: service-connections
description: Spring Boot 3.5 @ServiceConnection + Docker Compose service discovery — connection-detail이 raw property를 override하는 우선순위
keywords: service-connection testcontainers docker-compose datasource redis kafka connection-details
intent: wire-local-dependencies override-connection-properties prevent-host-port-drift
paths: src/test/**/*.java compose.yaml docker-compose.yaml
patterns: spring-boot-3.5 @ServiceConnection ConnectionDetails
requires: configuration-properties profile-topology
phase: implement review debug
tech-stack: java
min_score: 2
---

# Service Connections (Boot 3.5)

> Boot 3.5의 `@ServiceConnection`/Docker Compose support는 connection-detail이 raw `spring.datasource.*` 등 property보다 우선한다 — "왜 다른 DB에 연결되지?"의 첫 의심 지점.

## 의사결정 트리

### IF 로컬/통합 테스트 의존성 wiring (Implement)
1. 한 서비스당 한 가지 전략 선택
   - 풀스택 로컬 기동 → Docker Compose support
   - 격리된 통합 테스트 → Testcontainers + `@ServiceConnection`
2. raw `spring.datasource.url` / `spring.data.redis.host`를 같이 채우지 않는다 — 우선순위 충돌의 원인
3. ephemeral 포트는 connection-detail이 자동 wire하도록 둔다 (하드코딩 `localhost:5432` 금지)

### IF "DB/Redis가 예상과 다른 인스턴스에 붙는다" (Debug)
1. Boot가 service connection을 생성했는지 먼저 확인 — Compose support 또는 `@ServiceConnection` 빈 존재
2. 공식 문서가 명시: connection details는 connection-related configuration properties보다 우선
3. property 값을 바꾸기 전에 실제 effective host/port를 `/actuator/configprops` 또는 로그로 확인

### IF 운영 환경에서 service connection 사용 검토 (Review)
1. 운영은 일반적으로 명시적 property/secret 기반이 옳음 — Compose/Testcontainers wiring은 dev/test surface
2. `@ServiceConnection` 빈은 test scope에 한정 — production classpath에 흘리지 않는다

## 가이드

- Compose 파일은 single source — 같은 host/port를 application.yml에 중복하지 않는다.
- `@ServiceConnection`은 Testcontainers 컨테이너 빈에 부착. `@DynamicPropertySource` 수동 wiring보다 선호.

## Gotchas

### "property를 바꿨는데 반영 안 됨"
- service connection이 raw property를 덮어씀. 우선순위 모델을 먼저 점검.

### dev wiring을 production profile에 leak
- profile 분리 없이 `@ServiceConnection` 테스트 빈이 메인 classpath로 들어가면 운영에서 의도치 않은 동작.

### Compose 파일과 application.yml 중복
- 같은 값이 두 곳에 있으면 누가 final인지 매번 의심해야 함. service connection 사용 시 raw 값은 비운다.

## Source

- `frameworks/backend/spring-boot/3.5.x/04_usage/2026-04-19__spring-docs__service-connections-config-order-and-actuator-baseline__3-5-x.md`
- `frameworks/backend/spring-boot/3.5.x/05_patterns/2026-04-19__spring-docs__configuration-properties-profile-groups-and-observability-patterns__3-5-x.md`
- `frameworks/backend/spring-boot/3.5.x/07_troubleshooting/2026-04-19__spring-docs__property-source-service-connection-and-probe-troubleshooting__3-5-x.md`
- `frameworks/backend/spring-boot/3.5.x/08_know-how/2026-04-26__local-spring__version-aware-config-surface-service-connections-and-actuator-review-habits__3-5-x.md`
