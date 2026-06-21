---
name: configuration-properties
description: @ConfigurationProperties로 typed 설정 그룹화 + property-source 우선순위 — @Value 산재 금지
keywords: configuration-properties value externalized-config property-source binding validation
intent: type-config audit-precedence consolidate-value-reads
paths: src/main/**/*.java application.yml application.properties application-*.yml
patterns: spring-boot-3.5 @ConfigurationProperties @Value Environment
requires: profile-topology service-connections
phase: plan implement review
tech-stack: java
min_score: 2
---

# Configuration Properties (Boot 3.5)

> 설정은 `@ConfigurationProperties`로 그룹화한다. 흩어진 `@Value`는 property-source 우선순위 디버깅을 어렵게 만든다.

## 의사결정 트리

### IF 새 설정 그룹 추가 (Plan|Implement)
1. 관련 키들을 한 record/class로 묶고 `@ConfigurationProperties("app.x")` 부착
2. validation 필요하면 `@Validated` + JSR-303 — 부팅 시 binding 단계에서 실패하게
3. `@Value`로 시작하지 않는다 — 흩어지면 발견·검증·drift 통제가 모두 약해짐

### IF "값이 환경마다 다르다, 왜?" (Debug|Review)
1. property-source 순서를 확인: packaged default → config import → profile-specific file → env var → system property → CLI
2. `/actuator/env`, `/actuator/configprops`로 effective source와 bound value를 본다
3. 코드 변경 전에 우선순위 mismatch 가설을 먼저 검증 — Boot 3.5는 parser/binder 버그보다 precedence 문제가 압도적으로 많음

### IF 같은 값이 여러 위치에 있다 (Review)
1. 한 환경당 single source of truth 원칙 — config 파일 OR env var OR Compose label, 의도된 precedence 이유 없으면 중복 제거
2. service connection이 connection-related property를 override 가능 — 그래서 raw `spring.datasource.url`은 비우는 게 안전

## 가이드

- `spring.config.import`로 외부 secret store/Vault 통합 — 코드와 secret 분리.
- 공유 설정은 `@ConfigurationProperties` + `@ConfigurationPropertiesScan`으로 부팅 시 binding 보장.

## Gotchas

### `@Value` 다발
- type 안전성·문서화·기본값 처리 모두 약함. binding 검증도 안 됨.

### `application-prod.yaml`이 무시됨
- profile이 실제로 active인지, 파일 위치가 로드 경로에 있는지 확인. profile-specific file은 profile 활성 + 위치 로드 양쪽 충족 필요.

### `env`/`configprops` 무방비 노출
- 진단 도구이지 public API 아님. 노출 채널과 인증을 명시적으로 분리.

## Source

- `frameworks/backend/spring-boot/3.5.x/05_patterns/2026-04-19__spring-docs__configuration-properties-profile-groups-and-observability-patterns__3-5-x.md`
- `frameworks/backend/spring-boot/3.5.x/07_troubleshooting/2026-04-19__spring-docs__property-source-service-connection-and-probe-troubleshooting__3-5-x.md`
- `frameworks/backend/spring-boot/3.5.x/04_usage/2026-04-19__spring-docs__service-connections-config-order-and-actuator-baseline__3-5-x.md`
- `frameworks/backend/spring-boot/3.5.x/06_templates/2026-04-19__spring-docs__backend-service-config-and-actuator-template__3-5-x.md`
