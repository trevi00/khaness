---
name: ml-platform-domain
description: ML 플랫폼 도메인 진입점 — Metaflow pipeline / Triton-KServe serving / Feast feature store / vLLM-SGLang LLM serving
keywords: ml-platform metaflow triton kserve feast vllm sglang model-serving feature-store llm
intent: design-ml-platform choose-serving-stack plan-feature-store tune-llm-batching
paths:
patterns: metaflow triton kserve feast vllm sglang tensorrt-llm
requires: data-pipeline-governance code-quality
phase: plan implement review
tech-stack: any
min_score: 1
---

# ML Platform 도메인 진입점

> Netflix ML Platform L5 / LLM Compute & Serving Systems / Personalization Data Engineering 등
> 채용 시그널에서 verbatim 등장하는 ML pipeline + serving + feature store + LLM serving lane.

## 매칭 룰
- `metaflow|@step|@batch|@kubernetes` → metaflow-pipeline-shape
- `triton|kserve|seldon|onnx|tensorrt|model-serving` → model-serving-realtime
- `feast|tecton|feature-store|point-in-time` → feature-store-online-offline
- `vllm|sglang|tgi|paged-attention|continuous-batching|llm-serving` → llm-serving-gpu-batching

## 9축 적용 정책
본 트리 산하 모든 스킬은 9게이트 강제 (`scripts/validators/skill_quality_axes.py`).
`MANDATORY_PREFIXES = ("data/", "infra/", "ml/")` 화이트리스트 자동 적용.
