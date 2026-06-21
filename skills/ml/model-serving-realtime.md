---
name: model-serving-realtime
description: Triton 2.68 / KServe (CNCF) / Seldon v2 결정 — dynamic batching, ensemble, canary, GPU 메모리 누수
keywords: triton kserve seldon onnx tensorrt model-serving dynamic-batching ensemble canary inference
intent: choose-serving-stack tune-batching design-canary diagnose-gpu-leak handle-cold-start
paths:
patterns: triton-inference-server config.pbtxt platform=ensemble canaryTrafficPercent
requires: oncall-and-incident-response service-resilience-patterns
phase: plan implement review deploy debug
tech-stack: any
min_score: 2
---

# Real-time Model Serving (Triton / KServe / Seldon v2)

> 핵심: p99 SLO에 따라 동적 batching tuning이 결정. p99<100ms는 batch 1-4 + low queue delay, p99<1s는 batch 16-32 + ensemble 허용. KServe는 2025-11 CNCF incubation 진입 — multi-model fleet의 default. Seldon v2는 Kafka 데이터 흐름이 이미 있을 때만.

## 의사결정 트리

### IF 서빙 스택 선택 (Plan)
| 신호 | 권장 |
|---|---|
| GPU 단일 모델 high-throughput | **Triton + TensorRT EP** |
| K8s multi-model fleet + GitOps | **KServe** (CNCF incubating) |
| Kafka 이벤트 기반 inference graph | **Seldon Core v2** |
| 단순 REST API + 컨테이너 1개 | FastAPI + ONNX Runtime |

### IF Triton dynamic batching 튜닝 (Implement)
`config.pbtxt` 결정:
1. p99 < 100ms → `preferred_batch_size: [1,2,4]`, `max_queue_delay_microseconds: 2000` 이하
2. p99 < 1s → `preferred_batch_size: [16,32]`, `max_queue_delay_microseconds: 50000` 허용
3. ensemble → `platform: "ensemble"` + `input_map`/`output_map`. `max_inflight_requests`로 step별 backpressure 제한
4. multi-instance → `instance_group [{count: 2, kind: KIND_GPU}]`. GPU saturation 70%↑면 MIG 검토

### IF KServe 배포 (Implement)
1. canary — `predictor.canaryTrafficPercent: 10` (serverless mode 한정 — raw deployment는 silent ignore)
2. promote — field 제거. rollback — 0으로 설정
3. shadow traffic — KServe first-class 아님. Istio `VirtualService.mirror`로 별도 구성

### IF GPU 메모리 누수 / cold start (Debug)
1. **TF backend**: 모델 swap 시 GPU memory 해제 안 함 — pod restart 필요
2. **TorchScript**: load/unload ~50회 후 ~1GB 누수 (Triton issue #5841) — ONNX 변환 권장
3. **PyTorch/ONNX**: peak에서 ceiling, 무한 누수는 아님. pod sizing은 peak에 맞춤
4. **Cold start**: 첫 inference에 GPU memory 부풀림 — `model_warmup` block in `config.pbtxt`

### IF TensorRT engine cache 무효화 (Debug)
driver/GPU/TRT 버전 변경 시 cache 무효 — 노드 업그레이드 후 rebuild 강제. CI에 cache key로 버전 hash 포함.

## 가이드

- ONNX Runtime + TensorRT EP는 "Up to 2X improved performance" — graph partitioning이 supported subgraph만 TRT로 보냄. FP16/INT8 모드 전환 가능.
- Triton 26.04 (v2.68.0)는 quarterly cadence — 버전 pin 권장.
- Seldon v2의 Kafka 통합은 강력하나 운영 부담 ↑ — 단순 inference에는 KServe가 가벼움.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | dynamic batching이 tail latency SLO에 직접 연결 |
| 성능 효율성 | TensorRT EP로 ~2X throughput, multi-instance + MIG로 GPU 활용 |
| 호환성 | ONNX 표준으로 PyTorch/TF/JAX 무관 export → Triton load |
| 사용성 | KServe `canaryTrafficPercent` 1줄로 점진 배포 |
| 신뢰성 | model_warmup으로 cold start tail latency 제거 |
| 보안 | mTLS + RBAC (KServe Istio 통합) |
| 유지보수성 | config.pbtxt 표준화로 모델별 결정 공유 |
| 이식성 | ONNX wire format이 backend 교체 0 코드 변경 |
| 확장성 | ensemble로 pre/post processing pipeline 무한 chaining |

## Gotchas

### `max_queue_delay_microseconds` 너무 높음
저 QPS 환경에서 tail latency 위반. p99 SLO보다 작아야. 너무 낮으면 throughput 붕괴.

### TF backend GPU memory 해제 안 됨
모델 swap 시 누적. PyTorch/ONNX 변환 또는 pod restart 정책 필수.

### KServe `canaryTrafficPercent` raw deployment에서 silent ignore
serverless mode 한정. raw mode 사용 시 canary 동작 안 함 — 명시 확인.

### TensorRT engine cache 노드 업그레이드 후 stale
driver/GPU/TRT 버전 변경 시 cache 무효. CI에 버전 hash key 포함.

### Ensemble `max_inflight_requests` 미설정
step간 backpressure cascade — 1 step OOM이 전체 pipeline timeout. 모든 step에 명시.

## Source

- https://docs.nvidia.com/deeplearning/triton-inference-server/release-notes/index.html — "version 2.68.0 and corresponds to the 26.04 container release", 조회 2026-05-10
- https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/user_guide/batcher.html — dynamic batching `preferred_batch_size`, `max_queue_delay_microseconds`, 조회 2026-05-10
- https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/user_guide/ensemble_models.html — ensemble `platform`, `input_map`/`output_map`, `max_inflight_requests`, 조회 2026-05-10
- https://kserve.github.io/website/docs/model-serving/predictive-inference/rollout-strategies/canary-example — `canaryTrafficPercent: 10`, serverless mode 한정, 조회 2026-05-10
- https://srekubecraft.io/posts/kserve/ — KServe "joined the CNCF as an incubating project" (2025-11), 조회 2026-05-10
- https://onnxruntime.ai/docs/execution-providers/TensorRT-ExecutionProvider.html — "Up to 2X improved performance", FP16/INT8, engine caching, 조회 2026-05-10
- https://github.com/triton-inference-server/server/issues/5841 — TF backend GPU memory leak, TorchScript ~1GB/50 cycles, 조회 2026-05-10
