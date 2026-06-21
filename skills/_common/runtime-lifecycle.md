---
name: runtime-lifecycle
description: Server runtime lifecycle as governance — config surface, health/readiness split, graceful shutdown, and background service ownership made explicit beyond framework defaults.
keywords: runtime lifecycle 런타임 server config-surface bind secret env override health readiness liveness startup-probe degraded graceful-shutdown drain in-flight signal sigterm sigint background-service worker queue-consumer scheduler cron drain-deadline force-terminate
intent: 서버구동해 health엔드포인트만들어 readiness분리해 graceful셧다운구현해 백그라운드워커돌려 config로딩해 secret주입해 degraded응답해
paths: src/main src/config server/ app/ cmd/ daemon/ worker/ scheduler/ probes/ healthz readyz health.go health.py
patterns: gracefulShutdown SIGTERM SIGINT context.WithCancel signal.Notify shutdownHook bind-address secret-loader feature-flag readyz livez startup-probe drain-timeout in-flight-counter background-job
requires: monitoring sre-operations infra-change-readiness messaging-governance
phase: implement deploy
tech-stack: any
min_score: 2
---

# Runtime Lifecycle

서버 운영의 가치는 framework API trivia가 아니라 **config 표면, startup 계약, stop 동작**이 명시되었는가. 4축: config surface, health/readiness, graceful shutdown, background lifecycle.

## 의사결정 트리

### IF Runtime Config Surface 정의 (Implement)
1. bind 표면 — 어떤 host:port에 listen, internal/external 구분
2. secret source — env var / vault / file mount / cloud secret manager
3. default posture — 안전한 default(예: bind 127.0.0.1) → 명시적 override로 0.0.0.0
4. override 우선순위 — CLI > env > file > default. 충돌 시 명시 로그
5. fail-fast 검증 — 시작 시 필수 env 누락이면 즉시 fail (silent default 금지)
6. **→ security 스킬: secret 주입 패턴**

### IF Health / Readiness / Liveness 분리 (Implement)
1. **liveness** — "프로세스가 살아 있는가". DB/외부 의존 검사 X. fail이면 재시작.
2. **readiness** — "트래픽 받을 준비 됐는가". 의존 검사 OK. fail이면 트래픽 제외.
3. **startup probe** — 느린 startup(JVM warmup) 동안 liveness 비활성화
4. degraded serving 정책 — readiness fail인데 일부 기능은 가능? 부분 503?
5. probe interval/timeout — 너무 짧으면 false positive, 너무 길면 detection 늦음
6. probe endpoint는 인증 면제하되 외부 노출 차단

### IF Graceful Shutdown (Implement)
1. signal handler — SIGTERM 받으면 readiness fail 먼저 (LB가 트래픽 빼게)
2. drain 시작 — 새 요청 거부, in-flight 요청 완료 대기
3. drain deadline — 보통 30-60초. timeout 시 force terminate
4. background work — queue consumer는 ack 후 멈춤, scheduler는 다음 trigger 차단
5. resource cleanup — DB connection, file handle, in-memory cache flush
6. exit code — 정상 종료 0, drain timeout 1
7. PID 1 (Docker) 함정 — init 없이 PID 1이면 signal forwarding 안 됨, `tini` 등 사용

### IF Background Service / Worker (Implement)
1. lifecycle owner — 어떤 컴포넌트가 start/stop 책임
2. backlog 정책 — queue 가득 시 reject / spill / block 어느 것
3. retry — exponential backoff + jitter + max attempts
4. shutdown 동기화 — 메인 종료 시 worker도 drain 후 종료
5. supervision — worker crash 시 자동 재시작? backoff?
6. **→ messaging-governance 스킬: queue consumer 패턴**

### IF Runtime 회고 (Review)
- [ ] startup time이 SLO 안 (보통 < 1분). 길면 startup probe 조정
- [ ] readiness fail 발생율 — 높으면 의존 또는 probe 임계값 검토
- [ ] graceful shutdown 성공률 — drain timeout 빈도
- [ ] background worker backlog — grow-forever 신호
- [ ] config drift — env별 diff 검토

## 4축 체크리스트

```
[Config Surface]
□ bind / port 명시, default가 안전 (127.0.0.1)
□ secret source 단일 (혼용 시 우선순위 명시)
□ 필수 env 누락 시 fail-fast (silent default 금지)
□ override 우선순위 문서화

[Health / Readiness]
□ liveness vs readiness 분리
□ startup probe로 slow startup 보호
□ degraded serving 정책 명시
□ probe endpoint 인증 면제 + 외부 차단

[Graceful Shutdown]
□ SIGTERM 핸들러 등록
□ readiness fail → drain 순서
□ drain deadline (30-60s)
□ PID 1 신호 전달 (Docker init)

[Background Lifecycle]
□ start/stop owner 명시
□ shutdown 시 worker 동기 drain
□ backlog 정책 (reject/spill/block)
□ supervision (재시작 + backoff)
```

## 가이드

### Liveness vs Readiness 차이가 안 잡힐 때
- "이 프로세스 죽었나?" → liveness
- "이 인스턴스 트래픽 보낼 수 있나?" → readiness
- DB가 잠깐 끊겼다고 liveness fail로 재시작하면 cascading restart. DB는 readiness에만 반영.

### Drain 순서가 중요
1. SIGTERM 수신
2. readiness OFF (LB가 새 트래픽 안 보냄)
3. 잠깐 대기(보통 5-10s) — LB가 routing 갱신할 시간
4. server 새 connection accept 중단
5. in-flight 요청 완료 대기 (deadline 까지)
6. background worker drain
7. resource cleanup
8. exit 0

### Config의 12-factor 원칙
- env var로 주입 (코드 변경 없이 환경 전환)
- code와 config를 분리 (image는 모든 env에서 동일)
- secret과 config를 같은 메커니즘으로 (주입 일관성)
- default는 development 안전, production은 명시 override

### Docker PID 1 zombie 문제
PID 1 프로세스는 zombie 자식 프로세스 reap 책임. JVM/Node 등은 reap 안 함 → zombie 누적. `tini`, `dumb-init`, 또는 docker `--init` 옵션.

### Background worker가 main loop에 묶여 있을 때
HTTP server와 worker가 같은 프로세스면 stop도 같이. 하지만 deploy 시 worker가 진행 중인 작업을 잃을 수 있음. queue ack는 작업 완료 후 + idempotency로 redelivery 안전.

## Gotchas

### Liveness probe가 DB 검사 — cascading restart
DB 일시 장애 시 모든 인스턴스 liveness fail → 재시작 → 더 부하 → DB 더 느림. liveness는 process 자체만, dependency는 readiness.

### SIGTERM 무시 — 강제 종료로 in-flight loss
signal handler 등록 안 하면 default가 즉시 종료. 진행 중인 HTTP 요청, DB 트랜잭션이 중단되어 데이터 inconsistent. signal handler 의무.

### Drain deadline 너무 짧음
deadline 5초면 long-running 요청은 항상 죽음. p99 응답 시간 + margin으로. 보통 30-60s. K8s는 `terminationGracePeriodSeconds`도 같이 늘려야 함.

### Readiness가 영원히 OK
의존성 못 찾아도 readiness OK 응답하면 트래픽 받아서 즉시 5xx. startup 시 의존 검사 통과 후에만 ready.

### Startup probe 없음 — JVM 첫 1분 동안 liveness fail
JVM warmup 60초+ 인데 liveness probe가 30초 timeout이면 시작 직후 재시작 루프. startup probe로 첫 N분 동안 liveness 우회.

### Config가 file path만 받음 — secret rotation 못 함
파일을 한 번 읽고 메모리에 보관하면 secret 변경 시 재시작 필요. SIGHUP에 reload 또는 watch 메커니즘.

### Background worker가 SIGTERM 안 받음
HTTP server에만 signal handler 등록하고 worker thread는 daemon으로 두면 강제 종료 시 메시지 ack 못 함 → redelivery + 중복. worker도 shutdown 신호 받아 drain.

### Override 우선순위 모호
같은 변수가 env, file, CLI에 모두 있으면 어느 게 이기는지 코드 안 보면 모름. 시작 로그에 "X loaded from <source>"로 출력.

### Probe endpoint 인증 강제
internal probe도 JWT 요구하면 LB가 probe 실패 → 트래픽 routing 안 됨. probe path는 인증 우회 + 외부 노출만 차단(internal subnet 또는 별도 admin port).

### Health endpoint가 무거움
DB query, external HTTP 호출하는 health endpoint면 probe마다 비용. light weight (DB는 cached state, external은 readiness만).

### Container 이미지에 health command 없음
Dockerfile `HEALTHCHECK`에 사용할 명령(curl, wget)이 image에 없으면 unhealthy. distroless 이미지면 별도 binary 추가하거나 application-level health.

### Drain 도중 새 요청 받음
shutdown 시작했는데 listener를 안 닫으면 drain 도중 새 요청 들어옴 → 무한 drain. listener.close() → in-flight 완료 → exit.

## 도구 사용 패턴 (Harness)
- 시작 로그 검증: `Bash`로 컨테이너 첫 30s 로그 확인 — config source, bind 주소, dependency check
- probe 직접 호출: `Bash`로 `curl -f http://localhost:<port>/healthz`
- shutdown 시뮬레이션: `Bash`로 컨테이너에 `docker kill -s SIGTERM` 후 drain log 관찰
- background worker backlog: monitoring 메트릭 또는 broker CLI

## 에러 복구 패턴 (Harness)
- "config not loaded" → 시작 로그의 config source 출력 확인, env var spelling
- "shutdown timeout" → drain deadline vs 실제 drain 시간 비교, in-flight counter 메트릭
- liveness restart loop → probe 임계값 + 시작 시간 비교, startup probe 추가 검토
- worker가 메시지 잃음 → shutdown 시 worker drain 호출 여부, ack 시점 재검토
