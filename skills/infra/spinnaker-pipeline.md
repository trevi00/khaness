---
name: spinnaker-pipeline
description: Spinnaker 2026.x multi-cloud CD — 마이크로서비스 9종, 배포 전략(Blue/Green/Highlander/Canary), Argo CD 비교
keywords: spinnaker pipeline orca clouddriver kayenta canary blue-green halyard managed-delivery argocd
intent: choose-cd-tool design-pipeline configure-canary plan-spinnaker-vs-argocd diagnose-stage-stall
paths:
patterns: spinnaker.io orca clouddriver kayenta keel halyard
requires: oncall-and-incident-response service-resilience-patterns
phase: plan implement review deploy debug
tech-stack: any
min_score: 2
---

# Spinnaker Pipeline (2026.x)

> 핵심: Spinnaker의 강점은 multi-cloud + Kayenta canary. K8s-only GitOps라면 Argo CD가 더 적합. **Managed Delivery는 EC2/Titus 한정** — K8s 선언적 워크플로우엔 부적합. 2026.0.0부터 image registry GHCR로 이전.

## 의사결정 트리

### IF CD 도구 선택 (Plan)
| 신호 | 권장 |
|---|---|
| multi-cloud (AWS+GCP+K8s) + Kayenta canary | **Spinnaker** |
| K8s-only GitOps (선언적, drift 자동 정정) | **Argo CD** 또는 Flux |
| 단순 K8s rolling deploy | kubectl + Argo CD |
| EC2/Titus + canary 통합 | Spinnaker |

### IF Spinnaker 채택 후 pipeline 설계 (Implement)
표준 stage chain:
1. **Bake (Manifest)** — Helm/Kustomize 템플릿 → manifest 생성
2. **Deploy** — Red/Black, Blue/Green, Highlander, Dark, Recreate, Canary 중 선택
3. **Manual Judgment** — gate stage (timeout 기본 ~3일, 최대 14일 = 1209600000ms)
4. **Pipeline** — sub-pipeline 호출
5. **Webhook** — 외부 시스템 trigger

### IF 배포 전략 결정 (Implement)
| 전략 | 사용처 | 비고 |
|---|---|---|
| **Blue/Green** | 표준 무중단 | UI에서 Red/Black은 deprecated, Blue/Green이 functionally equivalent |
| **Highlander** | 단일 버전만 유지 | rollback hot standby 없음 |
| **Dark** | traffic 미라우팅 배포 | Enable/Disable Manifest stage 결합 |
| **Canary (Kayenta)** | 자동 통계 분석 | judge가 Kayenta timeseries 분석 — baseline 대비 metric 비교 |
| **Recreate** | 다운타임 허용 | K8s native |

### IF stage stall / 운영 문제 (Debug)
1. **Manual Judgment race** — 1.31.0 미만은 동시 stage 갱신 corruption 위험. 업그레이드 또는 distributed locking 활성
2. **Front50 cache pressure** — `synchronizeCacheRefresh`, `optimizeCacheRefreshes`, `front50.useTriggeredByEndpoint=true` 설정으로 Orca scan 부하 감소
3. **Manual Judgment timeout 누적** — 14일 timeout 동안 Orca worker + Redis memory 점유. 명시적 짧은 timeout 권장
4. **Clouddriver cache scaling** — cluster 수에 비례한 cache refresh time. Netflix Spinnaker scaling 시리즈 참조

## 가이드

- **Halyard installer는 deprecated** — 신규 설치는 Operator 또는 Kustomize.
- 9 마이크로서비스 (Deck/Gate/Orca/Clouddriver/Front50/Echo/Igor/Rosco/Fiat) + Kayenta(canary) + Keel(Managed Delivery).
- K8s V2 provider가 권장 — manifest는 Git/GCS에 외부 저장 후 참조.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | Kayenta canary 자동 분석으로 통계적 배포 검증 |
| 성능 효율성 | Front50 cache 플래그로 Orca scan 부하 감소 |
| 호환성 | EC2/Kubernetes/GCE/Azure 등 멀티 cloud provider 동시 지원 |
| 사용성 | Deck UI + 9 마이크로서비스 명확한 책임 분리 |
| 신뢰성 | Manual Judgment locking(1.31+)으로 stage 동시성 보호 |
| 보안 | Fiat 인증/인가 + Vault 통합 |
| 유지보수성 | Halyard deprecated → Operator/Kustomize로 마이그레이션 |
| 이식성 | manifest는 Git 외부 저장 → Spinnaker 의존성 최소화 |
| 확장성 | Webhook stage로 외부 시스템 연계, sub-pipeline으로 재사용 |

## Gotchas

### Managed Delivery로 K8s GitOps 시도
Spinnaker MD는 "limited to EC2 and Titus with limited feature and UI support". K8s-only GitOps는 Argo CD/Flux로. MD는 EC2/Titus 코호트만.

### Halyard로 신규 설치
deprecated. 새 클러스터는 Operator(spinnaker-operator) 또는 Kustomize 사용. Halyard 마이그레이션 가이드 따로 존재.

### Manual Judgment timeout 14일 누적
default ~3일, 최대 14일. 장기 대기 stage가 Orca worker + Redis memory 점유 → cluster 전체 latency 증가. 명시적 짧은 timeout(예: 1일) 권장.

### Front50 in-memory cache 폭증
applications + pipelines 메타데이터 in-memory 보관. 수천 pipeline 시 GC pressure. 1.31+ 의 `useTriggeredByEndpoint`(default false) 활성으로 Orca의 전수 scan 회피.

### Red/Black UI에서 Blue/Green과 혼동
UI에서 Red/Black은 deprecated 표시. 신규 pipeline은 Blue/Green 사용 — functionally equivalent하지만 명확.

## Source

- https://spinnaker.io/docs/releases/versions/ — 2026.1.0 (2026-05-09); 2026.0.0이 GAR 마지막 release, 이후 GHCR로, 조회 2026-05-10
- https://spinnaker.io/docs/reference/architecture/microservices-overview/ — Deck/Gate/Orca/Clouddriver/Front50/Echo/Igor/Rosco/Fiat/Kayenta/Keel verbatim 정의, 조회 2026-05-10
- https://spinnaker.io/docs/reference/pipeline/stages/ — Bake/Deploy/Manual Judgment/Pipeline/Webhook 표준, 조회 2026-05-10
- https://spinnaker.io/docs/guides/user/kubernetes/rollout-strategies/ — "Red/Black rollout strategy is marked as deprecated in the UI, and a Blue/Green rollout strategy has been added that is functionally equivalent", 조회 2026-05-19 (구 kubernetes-v2/ 경로 deprecated, 신 kubernetes/ 경로)
- https://spinnaker.io/docs/guides/user/managed-delivery/ — "Managed Delivery support is limited to EC2 and Titus with limited feature and UI support", 조회 2026-05-10
- https://spinnaker.io/changelogs/1.31.0-changelog/ — Manual Judgment distributed locking, Front50 cache flags, 조회 2026-05-10
- https://blog.spinnaker.io/scaling-spinnaker-at-netflix-part-1-8a5ae51ee6de — Clouddriver cache scaling at Netflix, 조회 2026-05-10
