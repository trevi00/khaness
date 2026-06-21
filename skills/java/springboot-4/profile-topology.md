---
name: profile-topology
description: spring.profiles.active/include/group + spring.config.import — profile sprawl을 환경 번들로 정리 (Boot 3.5/4 공통)
keywords: profiles profile-groups spring-config-import active-profiles include environment-bundle spring-boot-3.5 spring-boot-4
intent: bundle-environments simplify-activation prevent-profile-sprawl
paths: application.yml application-*.yml application.properties
patterns: spring-boot-3.5 spring-boot-4 spring.profiles.active spring.profiles.group spring.config.import
requires: configuration-properties
phase: plan implement review
tech-stack: java
min_score: 2
---

# Profile Topology (Boot 3.5/4 공통)

> Profiles는 환경 모양(local/staging/prod)을 표현해야 한다 — 비즈니스 feature flag로 쓰지 않는다.

## 의사결정 트리

### IF profile 구조 설계 (Plan)
1. 환경 의도(local/test/staging/prod)를 logical profile name으로 정한다
2. 함께 활성화될 fine-grained profile들(`mysql`, `redis-cluster`, `tracing`)은 `spring.profiles.group.<name>=...`으로 묶는다
3. 외부 설정 import는 `spring.config.import` 사용 — `spring-cloud-bootstrap` 의존 없이 시크릿/추가 설정 로드

### IF profile 활성화가 복잡해 보임 (Refactor|Review)
1. 같이 다니는 profile들이 매번 수동 활성화되고 있는가? → profile group으로 통합
2. profile 이름이 비즈니스 의도(feature/A/B)를 표현하는가? → 그건 feature flag의 책임. profile에서 분리
3. `staging`이 실제로 무엇인지 README에 1-2줄 — 이름만으로 운영 의도가 안 보이면 sprawl

### IF profile-specific 파일이 안 먹힌다 (Debug)
1. active profile resolution 확인 — env var `SPRING_PROFILES_ACTIVE`, JVM `-Dspring.profiles.active`, CLI `--spring.profiles.active`
2. config file location order 확인 — packaged default vs `application-prod.yaml`의 실제 로드 경로
3. profile group이 의도대로 expand 되는지 — `/actuator/env`로 effective active profiles 확인

## Boot 3.5 → 4 delta

> 2026-05-01 (debate-1777610334) MOVE — 본 파일은 원래 `springboot-3.5/profile-topology.md` 였고 Boot 4로 옮겨오면서 두 버전을 같이 다룬다. 본문 의사결정 트리는 양 버전 공통.

| 축 | Boot 3.5 | Boot 4 |
|---|---|---|
| `spring.profiles.group.<name>=...` | GA | 동일 (no breaking change) |
| `spring.config.import=configtree:` | GA (3.4부터) | 동일 |
| `management.server.port` 분리 | 가능 (수동 강조 약함) | management plane separation 패턴이 명시적 권장 — `springboot-4/profile-config-topology.md` 참조 |
| profile-activation property를 profile-specific 문서에 두기 | silently 무시 | 4부터 명시적 제약 — config 파싱 단계에서 문서화된 에러 메시지 |
| AOT compile + profile resolution | 동작은 동일, 도커 이미지 사이즈 영향 약함 | `efficient-packaging.md` 참조 — CDS/AOT가 profile resolution과 결합 |

Boot 4 specific patterns (management plane separation, K8s probe ports, include-vs-active additive semantics) 은 sibling `profile-config-topology.md` 가 다룸. 본 파일은 두 버전이 공유하는 코어 (active/include/group + config.import) 에 초점.

## 가이드

- profile 수가 많아 외우기 어려우면 group으로 묶는다 — 활성화는 1개 이름으로.
- include vs group: `include`는 추가 활성화, `group`은 활성 시 자동 expand. 환경 번들엔 group이 자연스러움.

## Gotchas

### profile = 비즈니스 feature flag
- 토글 목적이라면 feature flag 라이브러리 또는 `@ConditionalOnProperty`. profile은 환경 모양 전용.

### `@Profile` 남용
- 빈 정의가 profile 매트릭스로 폭발하면 wiring 추적이 어려움. 가능하면 `@ConditionalOnProperty`/`@ConfigurationProperties` 분기.

### staging vs prod의 의도가 코드에서만 보임
- README/CONTRIBUTING에 "이 profile은 무엇인가" 한 줄. 운영팀이 코드 안 봐도 의도가 잡혀야 한다.

## Source

- `frameworks/backend/spring-boot/3.5.x/05_patterns/2026-04-19__spring-docs__configuration-properties-profile-groups-and-observability-patterns__3-5-x.md`
- `frameworks/backend/spring-boot/3.5.x/07_troubleshooting/2026-04-19__spring-docs__property-source-service-connection-and-probe-troubleshooting__3-5-x.md`
- `frameworks/backend/spring-boot/3.5.x/04_usage/2026-04-19__spring-docs__service-connections-config-order-and-actuator-baseline__3-5-x.md`
- `frameworks/backend/spring-boot/3.5.x/01_docs/2026-04-19__spring-docs__spring-boot-3-5-official-overview__3-5-x.md`
