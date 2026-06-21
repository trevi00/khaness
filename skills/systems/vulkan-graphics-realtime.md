---
name: vulkan-graphics-realtime
description: Vulkan 1.4 graphics — Dynamic Rendering, Timeline semaphore, descriptor indexing, VMA. Cloud gaming 실시간 렌더링
keywords: vulkan graphics khronos dynamic-rendering timeline-semaphore descriptor-indexing vma swapchain pipeline-barrier validation-layer
intent: design-vulkan-renderer choose-render-path sync-queue manage-descriptors handle-swapchain-recreation
paths:
patterns: VkInstance VkDevice VkCommandBuffer VkPipelineBarrier VK_KHR_dynamic_rendering VMA
requires: transport-reliability monitoring
phase: plan implement review debug
tech-stack: any
min_score: 2
---

# Vulkan Graphics — Realtime (1.4)

> 핵심: Vulkan 1.4 (2024-12 GA)는 push descriptors + dynamic rendering local reads + scalar block layouts를 mandatory로. 가장 흔한 실수는 **timeline semaphore + WSI 혼용** — `vkAcquireNextImageKHR`/`vkQueuePresentKHR`는 binary semaphore 강제, timeline semaphore와 자동 bridge 안 됨.

## 의사결정 트리

### IF Vulkan 버전 결정 (Plan)
| 환경 | 권장 |
|---|---|
| 2025+ 드라이버 baseline 가능 | **Vulkan 1.4** (push descriptors + dynamic rendering local reads core) |
| 2023-2024 베이스 | **Vulkan 1.3** + 명시적 extension enable |
| 모바일/구 GPU | **Vulkan 1.2** + descriptor indexing extension |

### IF Rendering path 결정 (Implement)
1. desktop / forward+compute → **Dynamic Rendering** (1.3 core, VK_KHR_dynamic_rendering) — VkRenderPass + VkFramebuffer 폐기
2. mobile tile GPU + input attachment chain → legacy RenderPass + subpass (tile memory bandwidth 이득)
3. dynamic rendering 사용 시 `vkCmdBeginRendering` / `vkCmdEndRendering` pair

### IF Synchronization (Implement)
1. **timeline semaphore** — queue-internal + host wait + producer/multi-consumer (1.2 core)
2. **binary semaphore** — `vkAcquireNextImageKHR` / `vkQueuePresentKHR` 필수. timeline과 자동 호환 X
3. submit boundary에서 timeline → binary bridge 명시
4. `synchronization2` 활성 + `VK_LAYER_KHRONOS_validation` sync validation

### IF Descriptor 관리 (Implement)
1. bindless → **descriptor indexing** + `UPDATE_AFTER_BIND_BIT`
2. per-draw 작은 데이터 → **push descriptors** (1.4 mandatory)
3. dynamic indexing은 **dynamically uniform** 강제 — non-uniform이면 GLSL `nonuniformEXT()` 또는 HLSL `NonUniformResourceIndex()` 명시

### IF Memory 관리 (Implement)
1. **VMA (Vulkan Memory Allocator)** 사용 — 직접 vkAllocateMemory 금지
2. `VK_KHR_buffer_device_address` (1.2 core) + `VMA_ALLOCATOR_CREATE_BUFFER_DEVICE_ADDRESS_BIT`로 bindless GPU pointer
3. staging — `VMA_ALLOCATION_CREATE_HOST_ACCESS_SEQUENTIAL_WRITE_BIT | VMA_ALLOCATION_CREATE_MAPPED_BIT`
4. staging copy 후 **buffer memory barrier** 필수 (shader read 전)

### IF Swapchain recreation (Debug)
1. `vkAcquireNextImageKHR` 가 `VK_ERROR_OUT_OF_DATE_KHR` 반환 시 swapchain 재생성
2. **frame fence reset 시점** — acquire 성공 확인 후에만 reset. 너무 일찍 reset 시 다음 프레임 `vkWaitForFences` 영구 hang
3. window resize 핸들링 — `framebufferResized` flag + 다음 프레임에 재생성

## 가이드

- validation layer는 dev 환경 항상 활성 — sync validation은 race condition 직접 검출
- pipeline cache 사용 — pipeline 컴파일 비용 큼, 영구 디스크 캐시
- HLSL → SPIR-V는 DXC 사용 가능 (Vulkan SPV)

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | sync validation으로 race/lifetime 정확성 검증 |
| 성능 효율성 | dynamic rendering으로 RenderPass overhead 제거 |
| 호환성 | Vulkan 1.4는 7개 vendor 드라이버 conformant (2025) |
| 사용성 | VMA로 manual memory management 캡슐화 |
| 신뢰성 | timeline semaphore로 host/queue 단방향 progression |
| 보안 | validation layer가 buffer overflow / OOB access 검출 |
| 유지보수성 | push descriptor + descriptor indexing으로 set 수 ↓ |
| 이식성 | Vulkan은 desktop/mobile/console 동일 API |
| 확장성 | bindless descriptor indexing으로 scene complexity 무관 |

## Gotchas

### Swapchain fence deadlock
`vkAcquireNextImageKHR` 가 `VK_ERROR_OUT_OF_DATE_KHR` 후 frame fence reset 먼저 하면 `vkWaitForFences` 영구 hang. acquire 성공 확인 후 reset.

### Timeline semaphore + WSI mismatch
present/acquire는 binary semaphore 강제 — timeline semaphore와 자동 bridge 안 됨. submit boundary에서 명시적 bridge.

### Descriptor indexing validation 사각지대
draw-time bindless access는 validation layer 검증 못 함. uninitialized/destroyed descriptor 접근 시 silent corruption. 코드 레벨에서 lifetime 강제.

### Update-after-bind frame-in-flight 위반
`UPDATE_AFTER_BIND_BIT` 없이 in-flight command buffer 사용 중 descriptor 갱신 시 UB. flag 명시 또는 frame-in-flight 외에서만 갱신.

### Staging copy 후 barrier 누락
`vkCmdCopyBuffer` → shader read 사이 buffer memory barrier 없으면 stale memory 읽음. VK_PIPELINE_STAGE_TRANSFER_BIT → VK_PIPELINE_STAGE_*_SHADER_BIT.

### Validation layer dev 환경에서 비활성
대부분 sync race + lifetime 버그가 validation 없으면 silent. dev 빌드에서 `VK_LAYER_KHRONOS_validation` + `synchronization2` 강제.

### Non-uniform descriptor indexing에서 nonuniformEXT 누락
GLSL `nonuniformEXT()` / HLSL `NonUniformResourceIndex()` 없이 non-uniform index 시 UB. shader 작성 시 명시.

## Source

- https://www.khronos.org/news/press/khronos-streamlines-development-and-deployment-of-gpu-accelerated-applications-with-vulkan-1.4 — "Vulkan 1.4 ... Previously optional extensions and features critical to emerging high-performance applications are now mandatory ... push descriptors, dynamic rendering local reads, and scalar block layouts", 조회 2026-05-10
- https://www.khronos.org/blog/vulkan-timeline-semaphores — "Vulkan's window system integration APIs do not yet support timeline semaphores, and the wait-before-signal behavior of timeline semaphores is not inherited by binary semaphore objects", 조회 2026-05-10
- https://www.khronos.org/blog/streamlining-render-passes — Dynamic Rendering 1.3 core promotion, 조회 2026-05-10
- https://gpuopen-librariesandsdks.github.io/VulkanMemoryAllocator/html/usage_patterns.html — VMA staging buffer + barrier 패턴, 조회 2026-05-10
- https://gpuopen-librariesandsdks.github.io/VulkanMemoryAllocator/html/enabling_buffer_device_address.html — `VMA_ALLOCATOR_CREATE_BUFFER_DEVICE_ADDRESS_BIT` 활성, 조회 2026-05-10
- https://vulkan-tutorial.com/Drawing_a_triangle/Swap_chain_recreation — fence reset 순서 함정, 조회 2026-05-10
- https://vulkan.lunarg.com/doc/sdk/latest/windows/khronos_validation_layer.html — sync validation enable, 조회 2026-05-10
