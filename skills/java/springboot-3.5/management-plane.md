---
name: management-plane
description: Actuator endpoint exposure + health/readiness/liveness + management port — 운영 surface을 의도적으로 분리
keywords: actuator management-port health readiness liveness probes endpoint-exposure
intent: expose-endpoints separate-management-port wire-probes secure-diagnostics
paths: application.yml application.properties src/main/**/*Health*.java
patterns: spring-boot-3.5 spring-boot-starter-actuator management.endpoints management.endpoint.health.probes
requires: configuration-properties observability
phase: implement review deploy
tech-stack: java
min_score: 2
---

# Management Plane (Actuator)

> Actuator는 enable과 expose를 모두 만족해야 보인다. 진단 endpoint(`env`/`configprops`)와 platform probe(`health/*`)는 다른 노출 정책이 필요하다.

## 의사결정 트리

### IF Actuator 신규 도입 (Plan|Implement)
1. `spring-boot-starter-actuator` 추가
2. HTTP exposure 최소화 — `management.endpoints.web.exposure.include`에 필요한 것만 (보통 `health,info,metrics,prometheus`)
3. management port 분리 — `management.server.port=...`로 main server와 별도 채널. 인증/네트워크 정책을 분리해서 적용
4. health groups로 `readiness`/`liveness` 정의 — 플랫폼(K8s)이 의도하는 의미와 맞춘다

### IF "Actuator endpoint가 안 보인다" (Debug)
1. enabled + exposed 두 조건 모두 충족했는지 — endpoint 존재 ≠ HTTP 노출
2. management port가 분리되어 있다면 호출 host:port가 맞는지
3. security 설정이 actuator 경로를 차단하고 있는지

### IF K8s probe 실패 (Debug|Deploy)
1. management port 분리 시 K8s probe가 main server port로 가는 경우 → `management.endpoint.health.probes.add-additional-paths=true`로 main port에 추가 경로 노출
2. readiness/liveness 의미를 health group으로 명확히 — DB 연결 실패 시 readiness만 빠지고 liveness는 유지하는 식의 설계
3. probe path가 의도된 그룹을 평가하는지 `/actuator/health/readiness` 직접 확인

### IF `env`/`configprops` 노출 정책 (Review)
1. 운영자 진단용 — public 트래픽에 노출 금지
2. management port + 내부망 + 인증 3중 보호. monitoring agent에게만 허용

## 가이드

- 부팅 실패는 `FailureAnalyzer` 출력 먼저 읽는다 — Boot의 진단 레이어가 root cause를 직접 알려주는 경우가 많다.
- info contributor로 git commit/build time을 노출하면 incident 시 버전 식별이 빠르다.

## Gotchas

### 모든 endpoint를 `*`로 expose
- `env`, `configprops`, `beans`, `heapdump`는 정보 누출/공격 표면. 명시적 include 목록 사용.

### main server port와 management port 혼용
- 외부 LB가 main port만 노출하면 actuator도 같이 노출됨. 분리 + 네트워크 정책으로 격리.

### probe path 누락
- management port를 분리한 뒤 K8s deploy spec의 probe path를 안 바꿔서 항상 실패 — `add-additional-paths=true`로 main port에 추가 노출 필요.

## Source

- `frameworks/backend/spring-boot/3.5.x/04_usage/2026-04-19__spring-docs__service-connections-config-order-and-actuator-baseline__3-5-x.md`
- `frameworks/backend/spring-boot/3.5.x/07_troubleshooting/2026-04-19__spring-docs__property-source-service-connection-and-probe-troubleshooting__3-5-x.md`
- `frameworks/backend/spring-boot/3.5.x/06_templates/2026-04-19__spring-docs__backend-service-config-and-actuator-template__3-5-x.md`
- `frameworks/backend/spring-boot/3.5.x/08_know-how/2026-04-26__local-spring__version-aware-config-surface-service-connections-and-actuator-review-habits__3-5-x.md`
