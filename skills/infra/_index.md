---
name: infra-domain
description: Infra/Platform 도메인 진입점 — K8s/Karpenter, Spinnaker CD, OTel/Prometheus, 네트워크 fundamentals
keywords: infra kubernetes karpenter spinnaker opentelemetry prometheus grafana network titus
intent: design-platform choose-cd-tool wire-observability tune-network
paths:
patterns: kubernetes karpenter spinnaker opentelemetry prometheus
requires: sre-operations monitoring
phase: plan implement review deploy
tech-stack: any
min_score: 1
---

# Infra/Platform 도메인 진입점

> 채용 시그널(SRE Cloud Platform L5, Distributed Systems Managed Compute, Open Connect)에서
> 일관 등장하는 K8s 위 컨테이너 추상화 + multi-cloud CD + 옵저버빌리티 + 네트워크 fundamentals.

## 매칭 룰
- `kubernetes|titus|karpenter|eks|gke|aks` → k8s-runtime-titus-style
- `spinnaker|argocd|flux|cd-pipeline` → spinnaker-pipeline
- `opentelemetry|otel|prometheus|grafana|tracing|metrics` → observability-otel-prom
- `tcp|bgp|dns|tls|cdn|http2|http3` → network-tcp-bgp-dns-tls

## 9축 적용 정책
본 트리 산하 모든 스킬은 9축 게이트 강제 (`scripts/validators/skill_quality_axes.py`).
`MANDATORY_PREFIXES = ("data/", "infra/", "ml/")` 화이트리스트 자동 적용.
