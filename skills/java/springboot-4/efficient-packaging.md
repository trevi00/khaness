---
name: efficient-packaging
description: Boot 4 layered images + jarmode=tools extract + dependency/app layer 분리로 컨테이너 rebuild 캐시 효율 극대화
keywords: spring-boot-4 layered-jar layered-image jarmode tools extract dockerfile buildpack container-image cache
intent: layer-image-for-cache extract-jar-tools separate-dependency-and-app-layers reduce-rebuild-time
paths: Dockerfile pom.xml build.gradle build.gradle.kts src/main/resources/application.yml
patterns: spring-boot 4 jarmode=tools layered-jar buildpack paketo dependencies application
requires:
phase: implement review deploy
tech-stack: java
min_score: 2
---

# Efficient Packaging (Boot 4)

> 컨테이너 이미지에서 가장 자주 바뀌는 건 application class. 가장 안 바뀌는 건 dependency jar. 한 layer 에 다 넣으면 코드 한 줄 바꿔도 전체 layer 가 invalidate 된다. Boot 4 의 `jarmode=tools` + layered Dockerfile / buildpack 으로 둘을 분리한다.

## 의사결정 트리

### IF 컨테이너 이미지 빌드 전략 결정 (Plan)
1. **packaging path 선택**: Dockerfile vs Cloud Native Buildpacks (Paketo). 둘 다 Boot 4 reference 가 1급 시민으로 다룸.
   - Dockerfile: 명시적 제어, 조직 표준 base image 강제 가능, layer 정책을 직접 작성.
   - Buildpack: `mvn spring-boot:build-image` / `gradle bootBuildImage`. 합리적 기본값을 자동 적용. 빠르게 시작하고 싶을 때.
2. **layered jar 활성화 확인** — Boot 3 부터 default. `BOOT-INF/layers.idx` 가 jar 안에 생기는지 확인. 안 만들어지면 plugin 설정 점검.
3. **layer 정책**: `dependencies` / `spring-boot-loader` / `snapshot-dependencies` / `application` 4단 분리가 표준. application 만 자주 바뀌도록.

### IF Dockerfile 작성 (Implement)
1. **builder stage 에서 `java -Djarmode=tools -jar app.jar extract --layers --launcher`** — 4.x 의 권장 추출 모드. layer 단위 디렉토리로 풀린다.
2. **각 layer 를 별도 `COPY` 로 따로 이미지에 추가** — dependencies 먼저, application 마지막. Docker 가 자동으로 layer 단위 캐싱.
3. **base image 는 distroless / jre-slim** 같은 가벼운 것. JDK 가 아닌 JRE (Java 17+) 로 충분.
4. **ENTRYPOINT 는 추출된 launcher** — `java -jar my-app/my-app.jar` 또는 `java org.springframework.boot.loader.launch.JarLauncher`.

```dockerfile
# Builder
FROM eclipse-temurin:17-jdk AS builder
WORKDIR /workspace
COPY target/my-app.jar my-app.jar
RUN java -Djarmode=tools -jar my-app.jar extract --layers --launcher

# Runtime
FROM eclipse-temurin:17-jre
WORKDIR /app
COPY --from=builder /workspace/my-app/dependencies/ ./
COPY --from=builder /workspace/my-app/spring-boot-loader/ ./
COPY --from=builder /workspace/my-app/snapshot-dependencies/ ./
COPY --from=builder /workspace/my-app/application/ ./
ENTRYPOINT ["java", "org.springframework.boot.loader.launch.JarLauncher"]
```

### IF Buildpack path 선택 (Implement)
1. `./mvnw spring-boot:build-image` — 별도 Dockerfile 없이 OCI image 생성.
2. builder image 와 결과 image registry / 태깅 정책을 build script 또는 CI 에 명시.
3. application 변경 시 buildpack 이 자동으로 application layer 만 rebuild — Dockerfile 보다 적은 코드로 같은 cache 효과.

### IF 빌드/롤아웃이 느려졌다 (Debug)
1. **이미지가 사실상 한 layer 인지 의심** — `docker history <image>` 로 layer 크기 분포 확인. application class 변경에 dependency layer 까지 invalidate 되면 layering 이 작동 안 한 것.
2. **`jarmode=tools extract` 가 실제로 호출되는지** — Dockerfile 에서 `extract` 단계가 빠지고 uber-jar 전체를 한 번에 `COPY` 한 경우 단일 layer 가 됨.
3. **snapshot dependency 가 매번 바뀌는지** — `snapshot-dependencies` layer 가 자주 바뀌면 그 위 layer 들도 함께 무너짐. SNAPSHOT 의존을 release 로 고정 검토.
4. CI 캐시 키 / Docker BuildKit 캐시가 제대로 잡히는지 — image layering 이 맞아도 CI 단의 cache miss 면 의미 없음.

### IF AOT / native-image 와 함께 쓸 때 (Plan)
1. Boot 4 reference tree 는 AOT / GraalVM native 를 1급으로 다룸. native image 는 jar layer 와 다른 packaging 라이프사이클 — `spring-boot:build-image` (buildpack) 의 native builder, 또는 직접 GraalVM `native-image` 호출.
2. native binary 자체가 큰 단일 산출물 → layer 분리의 이득이 jar 모드보다 작음. cold-start / 메모리 관점에서 native 가 유리한지 / 빌드 시간 trade-off 가 맞는지 별도 결정.
3. native build 는 GraalVM CE 25 + Native Build Tools 0.11.5 baseline 사용.

## 가이드

- 작은 backend service 라도 처음부터 layered packaging 채택 — 나중에 monolithic 에서 layered 로 전환하는 비용보다 처음부터 layered 가 거의 항상 싸다.
- 운영자가 "이 이미지 어떻게 만들어졌나" 를 README 에 1단락으로 — packaging path (Dockerfile/buildpack), layer 정책, base image, java baseline.
- `jarmode=tools` 는 4.x 의 표준 ops 진입점. 옛날 layertools 모드 (`-Djarmode=layertools`) 흔적이 남아 있으면 tools 모드로 정리.

## Gotchas

### 한 layer 에 uber-jar 전체를 `COPY`
- 코드 한 줄 바꿔도 dependency 까지 다시 push. Boot 의 layered jar 를 쓰지 않는 가장 흔한 안티패턴.

### `jarmode=tools extract` 단계 누락
- Dockerfile 에 layered jar 추출 단계 자체가 없으면 layer 분리 효과 0. builder stage 에서 반드시 extract.

### SNAPSHOT 의존이 production image 까지 흘러들어옴
- `snapshot-dependencies` layer 가 빌드마다 바뀌어 그 위 application layer cache 도 매번 무너짐. release 버전으로 고정.

### packaging 정책이 tribal knowledge
- "이 이미지는 어떻게 만들어지나" 가 head 안에만 있으면 운영 사고 시 디버깅이 안 됨. README / Dockerfile 주석에 명시.

### probe 가 main 이미지 port 만 가정
- packaging 효율과 별도로, layered image + management port 분리를 같이 했다면 K8s deploy spec 에서 probe 대상 port 도 같이 바꿔야 함 (`profile-config-topology` 참조).

### buildpack 결과 이미지의 base 가 조직 정책과 안 맞음
- buildpack 은 자체 builder/run image 를 사용. 보안 정책상 특정 base 만 허용된다면 builder image 를 명시적으로 지정하거나 Dockerfile path 로 전환.

## Source

- `frameworks/backend/spring-boot/4.x.x/05_patterns/2026-04-19__spring-docs__configuration-properties-actuator-surface-and-layered-image-patterns__4-x-x.md`
- `frameworks/backend/spring-boot/4.x.x/04_usage/2026-04-19__spring-docs__external-config-actuator-and-container-image-baseline__4-x-x.md`
- `frameworks/backend/spring-boot/4.x.x/09_projects/2026-04-19__spring-docs__small-backend-service-project-baseline__4-x-x.md`
- `frameworks/backend/spring-boot/4.x.x/01_docs/2026-04-19__spring-docs__spring-boot-4-0-official-overview__4-x-x.md`
