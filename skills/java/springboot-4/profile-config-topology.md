---
name: profile-config-topology
description: Boot 4 profile active/include/group + spring.config.import + management topology — 환경 활성화/외부 설정/운영 surface을 한 묶음으로 설계
keywords: spring-boot-4 profiles profile-groups spring-config-import include active management-port management-address actuator
intent: bundle-environments import-external-config separate-management-plane prevent-profile-sprawl
paths: src/main/resources/application.yml src/main/resources/application-*.yml src/main/resources/application.properties
patterns: spring-boot 4 spring.profiles.active spring.profiles.include spring.profiles.group spring.config.import management.server.port management.server.address
requires:
phase: plan implement review deploy
tech-stack: java
min_score: 2
---

# Profile / Config Import / Management Topology (Boot 4)

> Boot 4 환경 설계의 세 축은 분리해서 결정하되, 한 문서로 묶어 본다: (1) profile activation 모델, (2) external config import 모델, (3) management plane topology. 셋이 서로의 가정을 침범하면 환경 drift 가 시작된다.

## 의사결정 트리

### IF profile 구조 설계 (Plan)
1. 환경 의도(local/test/staging/prod) 를 logical profile name 으로 정한다 — "환경 모양"이 profile 의 책임이지 비즈니스 토글이 아님.
2. 함께 활성화될 fine-grained profile (`mysql`, `redis-cluster`, `tracing`) 은 `spring.profiles.group.<env>=...` 으로 묶는다 → 활성화는 1개 이름으로.
3. **profile activation property 는 non-profile-specific 문서에만 둔다** — 공식 docs: `spring.profiles.active`, `spring.profiles.default`, `spring.profiles.include`, `spring.profiles.group` 은 profile-specific 문서나 `spring.config.activate.on-profile` 로 활성화된 문서에 들어갈 수 없음. 이걸 어기면 silent 무시.
4. `include` vs `active` 의미 구분 — `include` 는 **additive** (기존 active 위에 더함), `active` 는 normal property-source precedence 를 따름 (highest source wins, 즉 authoritative). 헷갈리면 둘 중 하나만 쓰는 정책을 팀 컨벤션으로.

### IF external config 가 필요한가 (Plan|Implement)
1. `spring.config.import` 사용 — `spring-cloud-bootstrap` 같은 구식 부팅 의존 없이 시크릿/추가 설정 로드.
2. **import 경로는 deployment contract 를 설명해야 한다** — `configtree:/etc/secrets/` 같은 경로는 "이 환경에서 mounted secrets 가 여기 있다" 는 약속을 표현. 임의 경로는 hidden second source of truth 로 변질됨.
3. import 우선순위 / property source order 를 README 또는 ADR 에 명시 — 운영자가 "왜 이 값이 이긴 거지" 를 코드 안 보고 알 수 있어야 함.

### IF management plane 을 분리할지 결정 (Plan|Deploy)
1. **boundary choice 임을 인지** — 운영 트래픽이 main public surface 와 같은 네트워크에 있어도 되는지가 출발점. afterthought 가 아님.
2. shared 그대로 둘 거면 → exposure 를 narrow 하게 (`include: health` 같이 시작 → 필요한 것만 추가).
3. 분리할 거면 → `management.server.port` (옵션 `management.server.address`) 로 별도 surface. 그러면 platform probe 가 어디로 가는지 / operator 가 무엇을 볼 수 있는지 둘 다 문서화.
4. K8s probe 는 main port 와 management port 중 어디를 때리는지 deploy spec 과 actuator 설정을 동시에 본다 — `management.endpoint.health.probes.add-additional-paths=true` 로 main port 에 probe 경로 추가하는 옵션도 검토.

### IF profile-specific 파일이 의도대로 안 먹힘 (Debug)
1. active profile resolution 확인 — env `SPRING_PROFILES_ACTIVE`, JVM `-Dspring.profiles.active`, CLI `--spring.profiles.active` 중 어디서 왔는지. **highest property source wins for `active`**.
2. `include` 가 끼어 있다면 누가 추가했는지 추적 — 의도 없이 자기 활성화되는 profile 의 단골 원인.
3. profile group 이 expand 되는지 `/actuator/env` 의 effective active profiles 에서 확인.
4. profile activation property 를 profile-specific 문서 안에 잘못 둔 경우 — 공식적으로 무효. 옮긴다.

### IF "한 환경에는 값이 있는데 다른 환경엔 없음" (Debug)
1. application code 를 고치기 전에 imported config 경로 + config data order 부터 검토.
2. configtree / 외부 vault 등 import source 가 환경마다 다르게 mount 되어 있을 가능성.

## 가이드

- profile = 환경 모양. feature flag 가 필요하면 `@ConditionalOnProperty` 또는 별도 flag 라이브러리. profile 에 비즈니스 토글을 얹지 않는다.
- profile 수가 많아 외우기 어려우면 group 으로 묶고 활성화 이름을 1개로 — `staging` 한 단어로 `staging-db + staging-mq + staging-tracing` 이 다 켜지는 식.
- README/CONTRIBUTING 에 "이 profile 은 무엇인가" 1-2줄 — 운영팀이 코드 안 봐도 운영 의도를 읽을 수 있어야 함.

## Gotchas

### profile activation property 를 profile-specific 문서에 작성
- `application-prod.yml` 안에 `spring.profiles.active: ...` 는 무효. 공식 docs 가 명시. non-profile-specific 문서로 옮겨야 함.

### `include` 와 `active` 를 같은 의미로 사용
- `include` 는 더하기, `active` 는 highest source wins. 한 팀에서 둘을 섞으면 override 모델이 추적 불가능해진다.

### profile = 비즈니스 feature flag
- 토글 목적이라면 `@ConditionalOnProperty` 또는 feature flag 라이브러리. profile 매트릭스가 폭발해서 wiring 추적이 안 되기 시작.

### `spring.config.import` 경로가 deployment 와 무관
- 임의 경로를 import 해서 "그냥 잘 되네" 라고 두면, 환경마다 무엇이 import 되는지가 hidden 두 번째 설정 시스템이 됨. 경로는 mount 규약과 일치해야 한다.

### management plane 을 afterthought 로 결정
- 처음에는 shared 였다가 나중에 port 분리 → K8s probe / 보안 정책 / 모니터링 agent 모두 따라 움직여야 하는데 일부만 바뀌어 endpoint 가 끊기는 사고 단골.

### K8s probe 가 main port 인데 actuator 는 management port 분리
- probe 가 항상 실패. `add-additional-paths=true` 또는 deploy spec 에서 management port 를 명시해야 함.

## Source

- `frameworks/backend/spring-boot/4.x.x/05_patterns/2026-04-19__spring-docs__profile-groups-config-import-and-management-topology-patterns__4-x-x.md`
- `frameworks/backend/spring-boot/4.x.x/04_usage/2026-04-19__spring-docs__external-config-actuator-and-container-image-baseline__4-x-x.md`
- `frameworks/backend/spring-boot/4.x.x/05_patterns/2026-04-19__spring-docs__configuration-properties-actuator-surface-and-layered-image-patterns__4-x-x.md`
- `frameworks/backend/spring-boot/4.x.x/09_projects/2026-04-19__spring-docs__small-backend-service-project-baseline__4-x-x.md`
- `frameworks/backend/spring-boot/4.x.x/01_docs/2026-04-19__spring-docs__spring-boot-4-0-official-overview__4-x-x.md`
