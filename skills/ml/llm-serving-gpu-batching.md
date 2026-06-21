---
name: llm-serving-gpu-batching
description: vLLM 0.20 / SGLang 0.5 / TensorRT-LLM 1.2 결정 — PagedAttention, RadixAttention, continuous batching, KV cache, FP8/INT4
keywords: vllm sglang tensorrt-llm tgi paged-attention radix-attention continuous-batching kv-cache speculative-decoding fp8
intent: choose-llm-runtime tune-kv-cache enable-speculative-decoding diagnose-throughput-vs-latency plan-quantization
paths:
patterns: vllm sglang tensorrt-llm PagedAttention RadixAttention APC
requires: model-serving-realtime service-resilience-patterns
phase: plan implement review deploy debug
tech-stack: any
min_score: 2
---

# LLM Serving + GPU Batching (vLLM / SGLang / TensorRT-LLM)

> 핵심: 2026-05 기준 vLLM v0.20.2 + SGLang v0.5.11 + TensorRT-LLM v1.2.1이 active. **TGI (HuggingFace)는 maintenance mode** — 신규 채택 금지. release cadence sub-monthly이므로 분기별 재검증 필수. PagedAttention(vLLM)과 RadixAttention(SGLang)은 KV cache 관리 패러다임 차이.

## 의사결정 트리

### IF LLM 런타임 선택 (Plan)
| 신호 | 권장 |
|---|---|
| 일반 high-throughput serving | **vLLM v0.20+** (continuous batching, prefix caching, speculative decoding) |
| 복잡한 prompt 트리 + structured output | **SGLang v0.5+** (RadixAttention prefix tree + xgrammar) |
| NVIDIA H100/B200 + FP8 극한 최적화 | **TensorRT-LLM v1.2+** (in-flight batching + FP8 native) |
| 신규 채택 | **TGI 금지** — maintenance mode |

### IF KV cache OOM 진단 (Debug)
1. PagedAttention은 fragmentation 줄이지만 **capacity 안 늘림** — `gpu_memory_utilization`(default 0.9)와 `max_model_len` 결합으로 block 예산 결정
2. APC(Automatic Prefix Caching)는 LRU eviction — block hash = `hash((parent_hash, block_tokens))`. cache hit 안 잡히면 prefix 결정성 확인
3. tensor parallel(TP) 늘리면 per-GPU memory↓, 단 all-reduce 통신 overhead↑

### IF throughput vs latency 트레이드오프 (Plan)
1. **continuous batching** — throughput 최대화 (default ON). prefill+decode 같은 batch에서 처리
2. **disaggregated prefill** (vLLM) — TTFT vs ITL 독립 튜닝. **단 throughput 향상 아님** (docs 명시) — tail ITL 통제용
3. speculative decoding — n-gram / EAGLE / DFlash. 짧은 prompt + 긴 generation에서 latency 단축

### IF quantization 결정 (Plan)
| 옵션 | 정확도 영향 | 메모리/속도 |
|---|---|---|
| FP16/BF16 | baseline | baseline |
| FP8 (H100+) | NVIDIA 명시 "minimal impact" | ~2x throughput, ~50% memory |
| INT8 | task별 -1~3% | ~2-3x speedup |
| INT4 GPTQ/AWQ | task별 변동 (docs 보장 없음) | ~4x memory savings |

### IF SGLang RadixAttention 활용 (Implement)
1. 공유 prefix가 많은 워크로드(few-shot, system prompt)에서 효과 큼
2. radix tree에 LRU leaf eviction — 짧은 query는 evict 빠름. session 기반이면 explicit cache key로 보존
3. structured output — xgrammar + compressed FSM. JSON schema 강제

## 가이드

- 모든 3 active 런타임이 2026-05에 CUDA 13 + Torch 2.11 정렬.
- 분기별 재검증 — 버전 cadence sub-monthly. frontmatter `Re-verify quarterly` 헤더 권장.
- multi-GPU에서 TP > 4 가면 NVLink/NVSwitch 토폴로지 검증 필수.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | PagedAttention/RadixAttention KV cache가 정확성 100% 유지 |
| 성능 효율성 | FP8(H100+)에서 ~2x throughput, continuous batching 표준 |
| 호환성 | OpenAI-compatible API로 client 코드 무변경 |
| 사용성 | vLLM `LLM(model=...)` 1줄 또는 OpenAI server 1 docker run |
| 신뢰성 | speculative decoding은 정확도 보존 (verification step) |
| 보안 | API key + rate limit + prompt logging 정책 분리 |
| 유지보수성 | OpenAI API 표준화로 런타임 교체 시 client 변경 0 |
| 이식성 | ONNX/HF safetensors weight 표준 — 런타임 무관 |
| 확장성 | TP/PP/EP/DP/CP 병렬화 5종 (vLLM v0.20) |

## Gotchas

### TGI 신규 채택
HuggingFace TGI는 docs에서 "maintenance mode" 명시 — minor bug fix만. vLLM/SGLang으로 마이그레이션. 면접에서도 TGI 채택 시 즉시 감점.

### Disaggregated prefill을 throughput 솔루션으로 오해
vLLM docs verbatim: "Disaggregated prefill DOES NOT improve throughput". TTFT/ITL 독립 튜닝용. throughput 늘리려면 continuous batching + larger batch size.

### KV cache OOM을 model size 문제로 오해
PagedAttention은 fragmentation만 해결, total capacity는 그대로. `gpu_memory_utilization` + `max_model_len` 결합 계산 필요.

### INT4 quantization 정확도 보장 가정
docs에 정확도 보장 명시 없음. task별 평가 필수. FP8(H100+)이 정확도/속도 트레이드오프 가장 안정.

### TP 크기를 무한 증가
all-reduce 통신 비용은 TP 크기에 비례. 8 GPU 단일 노드까지는 NVLink 효율, 노드 간으로 가면 InfiniBand 토폴로지 의존.

## Source

- https://docs.vllm.ai/en/stable/ — "Continuous batching of incoming requests, chunked prefill, prefix caching"; "Speculative decoding including n-gram, suffix, EAGLE, DFlash"; quantization "FP8, MXFP8/MXFP4, NVFP4, INT8, INT4, GPTQ/AWQ, GGUF", 조회 2026-05-10
- https://docs.vllm.ai/en/latest/features/disagg_prefill.html — "Disaggregated prefill DOES NOT improve throughput", 조회 2026-05-10
- https://arxiv.org/abs/2309.06180 — Kwon et al. SOSP 2023, PagedAttention 원논문, 조회 2026-05-10
- https://lmsys.org/blog/2024-01-17-sglang/ — RadixAttention "automatic prefix matching, reuse, and caching"; "LRU eviction policy that recursively evicts leaf nodes", 조회 2026-05-10
- https://nvidia.github.io/TensorRT-LLM/overview.html — in-flight batching; FP8 "can double performance and halve memory consumption"; 조회 2026-05-10
- https://huggingface.co/docs/text-generation-inference/index — "text-generation-inference is now in maintenance mode", 조회 2026-05-10
- https://github.com/sgl-project/sglang/releases — SGLang v0.5.11 (2026-05-05), 조회 2026-05-10
