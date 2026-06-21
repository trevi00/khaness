---
name: migration
description: Spring Boot 3.x → 4.x upgrade 흐름 + release-note sweep + properties-migrator 임시 사용/제거 규율
keywords: spring-boot-4 migration upgrade properties-migrator release-notes feature-release skipped-versions java-17
intent: upgrade-version sweep-release-notes diagnose-property-renames remove-transition-aid
paths: pom.xml build.gradle build.gradle.kts src/main/resources/application.yml src/main/resources/application.properties
patterns: spring-boot 3.x 3.5 4.0 spring-boot-properties-migrator @PropertySource feature-release
requires:
phase: plan implement review deploy
tech-stack: java
min_score: 2
---

# Spring Boot 3.x → 4.x Migration

> Boot 4 마이그레이션은 버전 숫자만 올리는 일이 아니다. release-note sweep + properties-migrator 일시 투입 + 제거가 한 묶음이다. 플랫폼 floor (Java 17, Spring Framework 7, Servlet 6.1, Tomcat 11/Jetty 12) 도 함께 움직였다는 점을 잊지 말자.

## 의사결정 트리

### IF 3.x → 4.x upgrade 시작 (Plan)
1. **현재 line과 target line을 명시 기록** — `3.2.x` / `3.5.x` / `4.0.x` 중 어디서 어디로 가는지 PR description에 한 줄.
2. **건너뛰는 feature release의 release notes를 모두 검토** — Boot 공식 가이드는 "skipped versions" 노트를 빠짐없이 sweep 하라고 명시. 예: `3.2 → 4.0` 점프면 `3.3`, `3.4`, `3.5`, `4.0` 모두 sweep.
3. **플랫폼 floor 변동 점검** — Java 17 minimum, Spring Framework 7.0.6+, Maven 3.6.3+, Gradle 8.14+/9.x, Servlet 6.1, Tomcat 11.0.x, Jetty 12.1.x. CI runner / 도커 base image / IDE JDK 모두 맞춰야 함.
4. **`spring-boot-properties-migrator` 의존성 임시 추가** (runtime scope) — feature-release property rename/removal을 런타임에서 진단.
5. **앱 기동 → `/actuator/env` + 콘솔 로그에서 migrator 경고 수집** → 이름 바뀐 / 제거된 property 모두 수정.
6. **migrator 의존성 제거** + 다시 기동 → 경고 없는지 확인. 절대 production에 남기지 않는다.

### IF 3.2 / 3.5 → 4.x 점프 (Plan|Implement)
1. config surface 사전 청소 — 이미 deprecated 된 property가 carryover 되어 있다면 4.x 진입 전에 정리. "config works locally" 가 아니라 "config surface is clean, version-aware" 를 목표로.
2. actuator 노출/profile group 가정 재검토 — 기본값이 4.x에서도 유효한지 확인 (`health` only by default 는 그대로지만, 노출 include 목록은 release note 검토 필요).
3. layered packaging / 운영 surface 가 명시되어 있는지 — 4.x는 container/AOT/native 가이드를 reference tree 1급 시민으로 끌어올림. 패키징을 implicit 으로 두지 말 것.
4. legacy bootstrap 흔적 제거 — `spring-cloud-starter-bootstrap` 같은 구식 부팅 동작이 hidden migration debt 로 남지 않도록.

### IF 업그레이드 후 runtime 동작이 달라짐 (Debug)
1. **plain 동작 차이는 release notes 부터** — 동작 변경(behavior change) 은 거의 모두 공식 노트에 적혀 있음. 코드부터 고치지 말고 노트 먼저.
2. **property 값이 의도와 다르면** `env` / `configprops` actuator 진단으로 property source 순서 확인. migrator 가 잡지 못한 late-added source (`@PropertySource`, programmatic 추가 등) 를 우선 의심.
3. **embedded servlet 차이** — Tomcat 10 → 11, Jetty 11 → 12 자체 동작 변화도 4.x 업그레이드의 일부. Servlet 6.1 호환성 (Jakarta EE 11) 이 깔린 라이브러리들을 check.
4. **native-image / AOT 산출물** 이 깨졌다면 GraalVM CE 25 + Native Build Tools 0.11.5 baseline 부터 맞췄는지 확인.

### IF 점프 폭이 너무 커서 부담스러움 (Plan)
1. **multi-step upgrade 고려** — `3.2 → 3.5 → 4.0` 처럼 중간 정거장. 각 단계마다 release-notes sweep + migrator 1회. 한 번에 점프하면 진단 노이즈가 섞여 root cause 추적이 어려움.
2. 단계 사이에 CI 그린 + 운영 검증 1주기 정도 두고 다음 단계로.

## 가이드

- migrator 가 보고하는 항목을 "그냥 deprecated 경고" 로 흘려 듣지 말 것 — feature release 에서는 property 가 진짜로 제거(removed) 될 수 있다. 경고 = 다음 minor 에서 깨질 가능성.
- 업그레이드 PR 은 별도 브랜치/PR로 분리. 비즈니스 변경과 섞지 않는다 (`feedback_branch_separation.md` 참조).
- release notes 는 "What's New" + "Upgrade Notes" 두 섹션 모두 본다. dependency upgrade 만 보면 운영 surface 변경을 놓침.

## Gotchas

### 버전 숫자만 올리고 release-notes sweep 생략
- Boot upgrade docs 가 명시적으로 "skipped feature releases 모두 검토" 라고 적어둠. 빠진 release 의 변경을 모르면 운영에서 한참 뒤에 알게 됨.

### properties-migrator 를 production 에 영구 의존성으로 남김
- transition aid 다. 런타임 baggage 가 되고, 마이그레이션 완료 여부 자체가 흐려진다. 업그레이드 PR 이 끝나기 전에 반드시 제거.

### `@PropertySource` / 프로그램적 property source 를 migrator 가 봤다고 가정
- 늦게 환경에 추가된 source 는 migrator 분석 대상이 아닐 수 있음. 그 경로는 별도로 수동 검토.

### Java / Servlet baseline 무시
- Boot 4 는 Java 17 floor + Servlet 6.1. CI runner 가 Java 11 이거나, 라이브러리가 Servlet 5 만 지원하면 묘하게 깨진다. dependency tree 를 먼저 본다.

### 3.2/3.5 시절 deprecated property 가 carryover
- 4.x 에서 제거된 키가 `application.yml` 에 남아 있으면 silent 무시되거나 startup 실패. 업그레이드 전에 한번 grep 으로 청소.

## Source

- `frameworks/backend/spring-boot/4.x.x/10_migrations/2026-04-19__spring-docs__migrating-from-3-x-to-4-x-and-properties-migrator-policy__4-x-x.md`
- `frameworks/backend/spring-boot/4.x.x/10_migrations/2026-04-26__local-spring__migrating-from-3-2-and-3-5-config-surface-review-to-4-x-cleanup-discipline__4-x-x.md`
- `frameworks/backend/spring-boot/4.x.x/01_docs/2026-04-19__spring-docs__spring-boot-4-0-official-overview__4-x-x.md`
- `frameworks/backend/spring-boot/4.x.x/04_usage/2026-04-19__spring-docs__external-config-actuator-and-container-image-baseline__4-x-x.md`
