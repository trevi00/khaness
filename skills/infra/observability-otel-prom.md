---
name: observability-otel-prom
description: OpenTelemetry SDK + Collector pipeline + Prometheus remote write + tail-sampling 결정. semantic conventions stability 추적
keywords: opentelemetry otel prometheus grafana tracing metrics logs exemplar tail-sampling collector
intent: design-observability tune-collector choose-sampling diagnose-cardinality wire-exemplars
paths:
patterns: opentelemetry tail_sampling prometheusremotewrite exemplar otlp
requires: oncall-and-incident-response monitoring
phase: plan implement review deploy debug
tech-stack: any
min_score: 2
---

# OpenTelemetry + Prometheus + Grafana

> 핵심: OTel SDK는 Java가 모든 signal Stable. Go/Python은 logs 미성숙. **Semantic conventions는 mixed** — duration metric은 stable, body size/connection.duration은 development. 운영 함정 1위는 high-cardinality label 폭증 — Prometheus가 무한 라벨에 폭발.

## 의사결정 트리

### IF 신규 서비스 instrumentation (Implement)
1. SDK 선택:
   - **Java** → traces/metrics/logs 모두 Stable
   - **Go** → traces/metrics Stable, logs Beta
   - **Python** → traces/metrics Stable, logs Development
2. Exporter — OTLP gRPC(`:4317`) 또는 HTTP(`:4318`) → Collector
3. SDK temporality — Prometheus remote write 사용 시 **`temporality_preference=cumulative`** 강제 (delta는 drop됨)
4. semantic conventions stability 확인 — `http.server.request.duration` 같은 Stable 필드만 의존, body-size/active_requests는 향후 변경 가능

### IF Collector pipeline 설계 (Implement)
1. agent (per-host DaemonSet/sidecar) vs gateway (centralized) 결정
2. 표준 pipeline: `receiver(otlp) → processor(batch + tail_sampling) → exporter(prometheusremotewrite + otlp/tempo)`
3. tail-sampling 사용 시 **trace_id 기반 consistent hashing 필수** — "All spans for a given trace MUST be received by the same collector instance"
4. front-tier에 loadbalancing exporter로 trace 단위 routing

### IF 샘플링 전략 (Plan)
| 방식 | 트레이드오프 |
|---|---|
| head-based (probabilistic at trace_id) | low memory, no buffer; post-hoc trace 컨텍스트 사용 불가 |
| **tail-based** (decision_wait ~30s) | error/latency 같은 후행 정책 가능; 메모리 buffer + collocation 필요 |

권장: error 100% + slow (>p99) 100% + baseline 1% probabilistic 조합.

### IF metric ↔ trace 연결 (Implement)
1. Exemplar 활성 — metric event에 `trace_id` + `span_id` 첨부
2. Prometheus는 Exemplar 지원 (text format), Mimir/Cortex/Thanos remote write도 지원
3. Grafana → Prometheus exemplar query → Tempo trace jump 가능

### IF Cardinality 폭발 진단 (Debug)
1. 증상: Prometheus TSDB block 크기 급증, `prometheus_tsdb_symbol_table_size_bytes` 메트릭 증가
2. 원인: user_id, request_id, trace_id가 **label**로 들어감 — 무한 라벨 = 무한 시리즈
3. 조치: 해당 attribute를 metric label에서 제거, exemplar로만 보존

## 가이드

- OTel Collector는 v0.110+ stable 권장. `prometheusremotewriteexporter`는 contrib 모듈 — core 아님.
- queue defaults: `queue_size=10000`, `num_consumers=5`. 백프레셔 시 drop — WAL 활성화로 durability.
- Logs SDK가 Go/Python에서 미성숙 → 운영은 Java instrumentation 우선.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | Stable conventions만 의존 시 수년 호환 보장 |
| 성능 효율성 | tail-sampling으로 storage 비용 ↓ + 의미 있는 trace 보존 |
| 호환성 | OTLP가 vendor neutral — Prometheus/Tempo/Datadog/NewRelic 무관 export |
| 사용성 | Exemplar로 metric → trace 1-click jump |
| 신뢰성 | Collector queue + WAL로 백엔드 outage 흡수 |
| 보안 | redaction processor로 PII attribute 마스킹 |
| 유지보수성 | semantic convention 표준화로 cross-team query 일관 |
| 이식성 | OTel SDK + OTLP wire format이 backend 교체 시 코드 변경 0 |
| 확장성 | Collector pipeline에 receiver/processor/exporter 추가만 |

## Gotchas

### High-cardinality label 폭발
"unbounded labels will blow up Prometheus" (prometheus.io). user_id/request_id/trace_id를 label로 넣지 않는다 — exemplar로 보존. 라벨당 cardinality < 10 권장.

### Tail-sampling routing 누락
"All spans for a given trace MUST be received by the same collector instance." consistent hash 안 하면 trace span이 여러 collector로 흩어져 tail policy silent misfire.

### Delta-temporality drop (silent)
Python/JS SDK default가 delta. prometheusremotewriteexporter는 non-cumulative monotonic/histogram/summary를 **dropping** — SDK에서 `temporality_preference=cumulative` 명시 안 하면 데이터 손실.

### Context propagation 누락 (async)
queue/goroutine으로 작업 넘길 때 명시적 context 전달 안 하면 orphan span. exemplar에 trace_id 없어 metric→trace 점프 깨짐.

### Experimental semantic conventions에 의존
HTTP body size, DB connection.duration 등은 Development. 의존 시 minor release breaking change. Stable 라벨만 사용 권장.

### Exporter backpressure 시 silent drop
queue 가득 차면 default drop. WAL 활성화 또는 queue_size/num_consumers 튜닝, 백엔드 SLO 측정.

## Source

- https://opentelemetry.io/docs/languages/ — Java traces/metrics/logs Stable; Go logs Beta; Python logs Development; "even with stable API/SDK status, if your instrumentation depends on semantic conventions marked as Experimental, your data flow may experience breaking changes", 조회 2026-05-10
- https://opentelemetry.io/docs/specs/semconv/http/http-metrics/ — HTTP metrics Status: Mixed; duration Stable, body size Development, 조회 2026-05-10
- https://opentelemetry.io/docs/specs/otel/metrics/data-model/ — "An exemplar is a recorded value that associates OpenTelemetry context to a metric event"; trace_id/span_id linkage, 조회 2026-05-10
- https://opentelemetry.io/docs/collector/architecture/ — receiver → processor → exporter pipeline 정의, 조회 2026-05-10
- https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/tailsamplingprocessor — "All spans for a given trace MUST be received by the same collector instance", decision_wait 30s, 조회 2026-05-10
- https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/exporter/prometheusremotewriteexporter/README.md — non-cumulative monotonic/histogram/summary metrics dropped, 조회 2026-05-10
- https://prometheus.io/docs/practices/naming/ — "Do not use labels to store dimensions with high cardinality"; "unbounded labels will blow up Prometheus", 조회 2026-05-10
