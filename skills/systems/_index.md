---
name: systems-low-level-domain
description: Low-level systems 도메인 진입점 — Vulkan graphics, realtime media transport, hardware acceleration
keywords: vulkan graphics media-transport quic webrtc nvenc gpu cloud-gaming low-level
intent: design-low-level-system choose-graphics-api tune-media-transport plan-gpu-pipeline
paths:
patterns: vulkan webrtc quic nvenc h264 av1
requires: transport-reliability monitoring
phase: plan implement review
tech-stack: any
min_score: 1
---

# Systems / Low-Level 도메인 진입점

> Netflix Cloud Games Platform L5 / Open Connect 등 채용 시그널 기반 low-level systems lane.
> Vulkan, 실시간 media transport, hardware acceleration 등 OS/하드웨어 직접 다룸.

## 매칭 룰
- `vulkan|graphics|gpu|cloud-game` → vulkan-graphics-realtime
- `webrtc|quic|nvenc|h264|av1|jitter-buffer` → realtime-media-transport

## 9축 적용 정책
본 트리 산하 모든 스킬은 9게이트 강제 (`scripts/validators/skill_quality_axes.py`).
`MANDATORY_PREFIXES = ("data/", "infra/", "ml/", "systems/")` 화이트리스트.
