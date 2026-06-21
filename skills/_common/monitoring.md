---
keywords: 모니터링 monitoring 로그 log 로깅 logging 메트릭 metric 알림 alert 알람 alarm 대시보드 dashboard 추적 tracing 관측 observability APM 성능 performance 에러추적 sentry 그라파나 grafana 프로메테우스 prometheus 헬스체크 healthcheck health 상태점검 /health /metrics 엔드포인트
intent: 모니터링구축해 대시보드만들어 메트릭추가해 알림설정해 로깅해 헬스체크해
paths: monitoring/ grafana/ prometheus/ logging/ alerts/ dashboards/ observability/ shared/monitoring/
patterns: prometheus grafana loki tempo jaeger datadog newrelic sentry winston pino bunyan morgan elk elasticsearch kibana fluentd structlog prometheus-fastapi-instrumentator
requires: devops backend
phase: plan implement deploy
min_score: 3
---

# Monitoring & Observability Guide

## 의사결정 트리

### IF 모니터링 시스템 신규 구축 (Plan)
1. Logs + Metrics + Traces 중 우선순위 결정
2. 스택 선택 (Prometheus+Grafana, Datadog, etc.)
3. 커스텀 비즈니스 메트릭 목록 작성
4. 알림 채널 결정
5. **→ devops 스킬: Docker Compose에 모니터링 프로필 추가**

### IF 메트릭/알림 추가 (Implement)
1. 자동 계측 설정 (HTTP 요청/응답)
2. 커스텀 비즈니스 메트릭 추가 (Counter, Histogram)
3. 알림 룰 설정
4. 대시보드 패널 추가
5. **→ backend 스킬: /metrics 엔드포인트 노출**

### IF 헬스체크 구현 (Implement)
1. 3-State: HEALTHY / DEGRADED / UNHEALTHY
2. 의존 서비스 점검 (DB < 100ms, Redis < 50ms 등 임계값)
3. /api/health 엔드포인트 등록
4. 응답에 version, environment, timestamp 포함

### IF 장애 대응 (Debug)
1. 4대 골든 시그널 점검: Latency(p95>2s), Traffic, Errors(>1%), Saturation(>80%)
2. 구조화된 로그에서 request_id 추적
3. 런북(대응 절차서) 참조

### IF 배포 후 확인 (Deploy)
1. 헬스체크 응답 확인
2. 에러율 5분간 관찰
3. 지연시간 p95 확인
4. 알림 룰 작동 확인

## 알림 룰 예시
```yaml
groups:
  - name: app-alerts
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.01
        for: 5m
        labels: { severity: critical }
      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 2
        for: 5m
        labels: { severity: warning }
      - alert: ServiceDown
        expr: up == 0
        for: 1m
        labels: { severity: critical }
```

## Gotchas

### 메트릭 카디널리티 폭발
label에 user_id, request_id 같은 고유값을 넣으면 시계열이 폭발적으로 증가하여 Prometheus OOM 발생. label은 유한한 enum 값만 사용 (status, method, endpoint 등).

### 로그에 시크릿 노출
구조화된 로깅을 사용하더라도 request body 전체를 로깅하면 비밀번호, 토큰이 포함됨. 민감 필드 마스킹하거나 허용 필드만 선택적으로 기록할 것.

### 알림 피로 (Alert Fatigue)
임계값이 너무 낮거나 `for` 기간이 너무 짧으면 잦은 알림으로 무시하게 됨. critical/warning 분리하고 actionable한 알림만 알림 채널로 전송.

### Liveness vs Readiness 혼동
- **Liveness**: 프로세스가 살아있는가 → 실패 시 재시작
- **Readiness**: 트래픽을 받을 준비가 됐는가 → 실패 시 트래픽 차단
DB 연결 실패를 liveness에 넣으면 DB 장애 시 모든 Pod 재시작 → cascading failure.

### UTC vs 로컬 타임존
로그/메트릭 타임스탬프는 반드시 UTC로 기록. KST로 기록하면 Grafana 대시보드에서 시간대 혼란 발생. 표시만 로컬 타임으로.

### /health 엔드포인트 인증
헬스체크 엔드포인트에 인증을 걸면 로드밸런서/쿠버네티스가 상태를 확인할 수 없음. /health는 인증 없이 접근 가능하되, 상세 정보는 인증 후에만 반환.

## 도구 사용 패턴 (Harness)
- 로그 분석: `Bash`로 최근 로그 확인, 긴 로그는 `Bash(tail -100)` + `Grep`으로 필터링
- 설정 파일 수정: prometheus.yml, alertmanager.yml은 `Read` → `Edit` (YAML 구조 보존)
- 메트릭 확인: `Bash(curl localhost:9090/api/v1/query)`로 쿼리
- 대시보드 JSON: `Read`로 확인, `Edit`으로 패널 추가 (전체 Write 금지 — 대시보드 깨짐)

## 에러 복구 패턴 (Harness)
- 알림 미발생 → `Read`로 알림 룰 YAML 확인, PromQL 문법 점검
- 문법 정상 → `Bash(curl)`로 타겟 상태 확인 (up 메트릭, scrape 에러)
- 타겟 정상 → 네트워크/방화벽 확인 (alertmanager ↔ notification 채널)
- 전부 정상 → Prometheus/Alertmanager 재시작 후 룰 리로드 확인

## Related (신규 그래프 cross-ref)

monitoring이 보강되는 신규 노드:
- `infra/observability-otel-prom.md` — OTel SDK + Collector pipeline + tail-sampling collocation + Prometheus high-cardinality 차단
- `_common/oncall-and-incident-response.md` — Google SRE multi-window multi-burn-rate alerts (1h+5m / 6h+30m / 3d+6h)
- `_common/chaos-engineering.md` — KPI 기반 steady-state hypothesis (monitoring metric을 chaos signal로 사용)
- `_common/load-shedding-prioritized.md` — concurrent count + p99 latency가 shedding decision signal
- `_common/durable-execution.md` — Temporal worker metric (`temporal_sticky_cache_size`)도 monitoring 대상
