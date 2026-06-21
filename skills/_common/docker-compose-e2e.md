---
name: docker-compose-e2e
description: docker-compose 기반 e2e 스택을 CI에서 띄울 때 자주 깨지는 5가지 함정과 healthy 게이트 패턴
keywords: docker-compose healthcheck e2e ci wait actuator
intent: 띄워 실행 시연 테스트 검증
paths: docker-compose.yml .github/workflows
patterns: docker-compose healthcheck depends_on
phase: implement deploy debug
tech-stack: any
min_score: 2
---

# docker-compose e2e healthcheck 패턴

> 핵심 원칙: **healthcheck 명령은 "이 컨테이너 안에 진짜 존재하는 도구"로만 짠다.** image 안의 PATH·실행 가능한 바이너리·shell 형식이 healthcheck 동작을 결정한다. 시작 대기는 application 코드가 아니라 `docker compose --wait`가 책임지게 한다.

## 의사결정 트리

### IF 새 e2e compose 스택을 짤 때 (Design)
1. 의존 순서를 `depends_on.condition: service_healthy`로만 표현. wait 스크립트 자체 작성 X.
2. 각 서비스에 `healthcheck` 명시. `test`는 list 형식만 사용 (`["CMD", ...]` / `["CMD-SHELL", "..."]`). string + folded scalar는 절대 X (인수 분리 함정).
3. `start_period`는 평균 부팅 시간의 **3배** 잡기. JRE 이미지 + JPA + Flyway는 보통 60s ≠ 180s. 너무 짧으면 첫 retry 전에 unhealthy로 떨어짐.
4. healthcheck 명령은 base image에 실제 존재하는 도구만:
   - `eclipse-temurin:21-jre-jammy` → **curl 없음**. `wget --spider` 또는 image에 `apt install curl` 단계 추가.
   - `mysql:8` → `mysqladmin ping -h localhost -u root -p$$MYSQL_ROOT_PASSWORD`
   - `redis:7` → `redis-cli ping`
5. CI workflow에서 startup 대기: `docker compose up -d --wait --wait-timeout 600`. 별도 polling loop 작성 X — compose가 healthcheck 통과까지 block.

### IF e2e workflow가 자주 깨질 때 (Debug)
- 첫 단서: `docker compose logs <svc>` + `docker inspect <container> --format '{{json .State.Health}}'` 로 마지막 5건 healthcheck 결과.
- mysql만 Error state면 init script 인수 분리 함정 의심 → `command:` 필드 다시 보기.
- 컨테이너는 떴는데 host에서 actuator 404면 port mapping이 아니라 `SPRING_PROFILES_ACTIVE` 미적용 의심 (testing 전용 endpoint는 `@Profile=e2e`).
- JWT 빈 생성 실패는 secret base64 형식 의심 — `jjwt`는 hyphen/underscore에 `DecodingException` 던짐 (IllegalArgumentException X).

### IF release 게이트 (Review)
- [ ] 모든 서비스에 healthcheck 명시 + start_period 측정 근거 있음
- [ ] CI 로그에 `Container ... Healthy` 줄이 모든 서비스에 대해 출력됨
- [ ] `docker compose down -v`가 workflow 마지막에 항상 실행 (실패 경로 포함, `if: always()`)
- [ ] artifact upload는 `logs/` + compose `docker compose logs > all.log`까지 (실패 진단용)

## 5축 hotfix 카탈로그

> example_project V-1 phase (run 25831362899) 누적 학습 — 5건 모두 진짜 prod 영향 버그였음

| # | 증상 | 원인 | Fix |
|---|---|---|---|
| 1 | `docker compose up` parallel build로 mysql Error state, 진단 불가 | 같은 step에서 build + up 동시 진행, mysql init fail의 stderr가 다른 컨테이너 출력에 묻힘 | mysql + redis만 먼저 `up -d --wait`로 띄우고, 그 다음 app 컨테이너 build + up. 진단 로그 step 별로 분리. |
| 2 | mysql 부팅 fail: `Too many arguments (first extra is 'NAMES')` | `command: >` folded scalar 안에 `--init-connect=SET NAMES utf8mb4` → SET/NAMES/utf8mb4 3개 인수로 분리 | YAML list 형식: `command: ["--init-connect=SET NAMES utf8mb4", ...]`. folded scalar는 인수 경계가 깨지는 모든 경우에 금지. |
| 3 | app 컨테이너 5분 startup > workflow Wait step 5분 cap | shell 폴링 루프를 직접 짜서 timeout 5분으로 박음 | `docker compose up -d --wait --wait-timeout 600`. compose가 healthcheck 종료까지 block. shell wait 직접 짜기 X. |
| 4 | app unhealthy: `eclipse-temurin:21-jre-jammy`에 curl 미설치 → compose healthcheck `["CMD", "curl"]` 항상 fail | jre 이미지는 SDK 도구 빠져있음 — curl/wget/jstack 다 없음 | curl → wget 으로 healthcheck 변경. **또는** Dockerfile에 `RUN apt-get update && apt-get install -y curl` 단계. start_period 60s→180s, retries 5→10 함께. |
| 5 | JWT 빈 생성 fail: `DecodingException: Illegal base64 character: '-'` | jjwt 0.12.5는 hyphen/underscore에 `IllegalArgumentException`이 아닌 `DecodingException` 던짐. catch IllegalArgumentException만 했으면 잡힘 안 됨. e2e secret 생성 시 hyphen 포함하면 매번 부팅 fail. | `try { Decoders.BASE64.decode(s) } catch (IllegalArgumentException \| DecodingException e)` 양쪽 catch. e2e secret은 영문/숫자만 (`tr -dc A-Za-z0-9` 사용). |

## 다중 profile 함정

```yaml
# .github/workflows/e2e.yml
env:
  SPRING_PROFILES_ACTIVE: prod,e2e   # X "e2e"만 — prod의 datasource/security 누락
```

`@Profile("e2e")` 빈 (test signal controller 등)은 `prod` 또는 다른 profile과 **동시 활성**되어야 함. e2e 단독으로는 prod 빈 (real DB, JWT) 미생성 → 부팅은 되지만 모든 endpoint 500.

## Gotchas

### YAML folded scalar `>` + exec form mix
`command: >` 다음 줄들을 합쳐서 한 줄로 만들면, 그 결과는 **shell이 아니라 컨테이너 entrypoint의 argv**로 전달됨. `--flag=value with spaces` 같은 값은 공백에서 분리됨. list 형식 (`command: [..., "..."]`)이면 인수 경계가 명확.

### healthcheck `test`의 list vs shell 차이
```yaml
test: curl -f http://localhost/health   # X — list로 파싱 안 됨, 동작 부정확
test: ["CMD", "curl", "-f", "http://localhost/health"]   # O exec form
test: ["CMD-SHELL", "curl -f http://localhost/health || exit 1"]   # O shell form (pipe/redirect 필요 시)
```

### depends_on `condition`은 short syntax에 없음
`depends_on: [db]` 형식은 condition 없이 그냥 startup order만 보장. healthy까지 기다리려면 long syntax `depends_on: { db: { condition: service_healthy } }`.

### `docker compose up` 직후 host port가 즉시 available 아님
healthcheck 통과 ≠ host port forward 완료. host에서 `curl localhost:8080` 또는 `actuator/health`로 한 번 더 확인하는 step이 안전 (5축 사용 게이트).

### `docker compose down -v`는 실패 경로에서 빠뜨리기 쉬움
workflow 중간 step에서 fail하면 cleanup 없이 끝남 → 다음 run에서 volume 잔재. `if: always()` 명시 필수.

### Windows host에서 LF/CRLF 끼면 entrypoint script가 깨짐
init script (mysql 등)를 host에서 commit할 때 `* text=auto eol=lf` `.gitattributes` 없으면 CRLF로 들어가서 `\r`이 인수에 붙음. Linux runner에서 부팅 시 cryptic error.
