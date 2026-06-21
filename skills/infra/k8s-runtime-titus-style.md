---
name: k8s-runtime-titus-style
description: K8s 컨테이너 런타임 결정 — Karpenter 노드 프로비저닝, VPC IP 관리, spot 활용. Titus 패턴은 reference로만(공개 레포 archived 2022)
keywords: kubernetes karpenter titus eks vpc spot consolidation prefix-delegation cni
intent: design-runtime tune-karpenter handle-vpc-ip-exhaustion choose-spot-strategy migrate-from-titus
paths:
patterns: karpenter EKS pod-density consolidation NodePool EC2NodeClass
requires: oncall-and-incident-response service-resilience-patterns
phase: plan implement review deploy debug
tech-stack: any
min_score: 2
---

# K8s Runtime (Titus-style) + Karpenter

> 핵심: Netflix Titus는 reference architecture로 가치 있으나 **공개 레포는 2022 archived**. 신규 채택은 vanilla K8s + Karpenter 패턴으로. Job/service 통합 추상화 같은 Titus 발상은 K8s priorityClass + Job/Deployment 분리로 매핑.

## 의사결정 트리

### IF 신규 K8s 런타임 설계 (Plan)
1. node provisioning — **Karpenter v1.x** 채택 (reactive autoscaling). cluster-autoscaler는 legacy
2. workload 통합 — batch + service 같은 클러스터 → priorityClass + ResourceQuota로 격리. Titus처럼 단일 Job primitive 직접 만들지 않는다
3. spot 활용 — 인스턴스 타입 ≥ 15종 다양화 + Price Capacity Optimized + SQS 인터럽션 핸들러 + PodDisruptionBudget
4. GPU — NVIDIA device plugin + node taint + extendedResource

### IF VPC IP 고갈 (Debug)
1. 증상: pod가 `ContainerCreating` 영구 stuck — EC2 노드는 launch 성공했지만 CNI가 IP 못 받음
2. 진단: subnet free IP 메트릭 + `aws ec2 describe-subnets` available IPs
3. 조치 — **ENI prefix delegation** (/28, IP 16개/prefix) 활성, secondary CIDR 추가, Karpenter `subnetSelectorTerms` 다양화
4. CNI custom networking 활성 시 노드 ENI 1개 예약됨 — pod density 계산 시 제외

### IF Karpenter consolidation 튜닝 (Implement)
1. **`requests==limits`** (non-CPU) 강제 — 안 하면 consolidation이 너무 작은 노드 선택 → OOMKill 폭증
2. spot-to-spot consolidation 기본 OFF — 비용 최적화 기대하면 `consolidationPolicy` + feature gate 명시 활성화
3. `disruption.budgets`로 동시 termination 제한 — 갑작스러운 대규모 노드 교체 방지

### IF Titus 코드/패턴 마이그레이션 (Plan)
1. **공개 Titus 레포(`Netflix/titus`, `Netflix/titus-control-plane`) 직접 사용 금지** — 2022 archived, v387(2021-03)이 마지막 release, 보안 패치 부재
2. 패턴 매핑 — Titus Job → K8s Job + Deployment 분리, Titus Master scheduler → vanilla kube-scheduler + Karpenter
3. Virtual Kubelet 기반 Titus↔K8s 어댑터(KubeCon 발표)는 reference; 신규 환경은 vanilla K8s 권장

## 가이드

- Netflix 내부에서 Titus가 여전히 운영 중인지는 1차 출처로 단정 불가 — 2차 보도만 존재. 외부 채택 시에는 reference architecture 용도로만.
- Karpenter API CRD는 `karpenter.sh/v1` (2026 stable). 인용/의존성 명시할 때 버전 명기.
- pod density 한계는 prefix delegation 활성/비활성에 따라 동적 (max-pods).

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | priorityClass + ResourceQuota로 batch/service workload 자원 격리 보장 |
| 성능 효율성 | Karpenter consolidation으로 노드 활용률 ↑, spot 다양화로 비용 ↓ |
| 호환성 | EKS/GKE/AKS 무관 동일 추상화 (Karpenter는 EKS 우선, GKE 대응 진행 중) |
| 사용성 | NodePool YAML로 선언적 정의, CRD로 운영 가시성 |
| 신뢰성 | PodDisruptionBudget + SQS 인터럽션 핸들러로 spot 종료 graceful |
| 보안 | image pull secret 노드 단위 격리, IRSA로 pod 단위 IAM |
| 유지보수성 | archived 레포 채택 차단으로 수정성/지원성 보장 |
| 이식성 | priorityClass/Job/Deployment는 K8s 표준 — provider 무관 |
| 확장성 | Karpenter NodePool 추가만으로 새 인스턴스 family 도입 |

## Gotchas

### archived Titus 레포 직접 채택
Netflix/titus와 Netflix/titus-control-plane 둘 다 2022 archived. 보안 패치 부재. reference architecture로만 읽기 — production 채택은 vanilla K8s.

### VPC IP 고갈로 pod ContainerCreating 영구 stuck
EC2 노드는 launch 성공해도 CNI가 IP 못 받으면 pod 무기한. subnet free IP 메트릭 알람 필수. prefix delegation 또는 secondary CIDR로 해결.

### Karpenter consolidation + memory burst → OOMKill 폭증
`requests==limits`(non-CPU) 설정 안 하면 consolidation이 작은 노드 고름. burst 시 OOMKill. 필수 강제.

### Spot-to-spot consolidation 기본 OFF
비용 최적화 기대했는데 노드 통합 안 됨 → spot 운영 비용이 on-demand보다 비쌀 수 있음. `consolidationPolicy` 명시 활성화.

### livenessProbe 오설정으로 pod 재시작 폭주
image pull 폭주(노드 동시 launch 시 ECR throttle) 와중에 짧은 livenessProbe initialDelay → 죽은 pod 무한 재생산. `startupProbe` 분리 권장.

## Source

- https://netflix.github.io/titus/overview/ — "Titus is a container management platform that provides scalable and reliable container execution"; Titus Master + Agent 구조, 조회 2026-05-10
- https://github.com/Netflix/titus — repo archived 2022-07-27, 조회 2026-05-10
- https://github.com/Netflix/titus-control-plane — archived 2022-05-14, last release v387 (2021-03), 조회 2026-05-10
- https://aws.github.io/aws-eks-best-practices/karpenter/ — "When using Spot, Karpenter uses the Price Capacity Optimized allocation strategy"; "Configure requests=limits for all non-CPU resources when using consolidation", 조회 2026-05-10
- https://aws.github.io/aws-eks-best-practices/networking/index/ — "When a subnet becomes IP address constrained ... pod will stay in a ContainerCreating state", 조회 2026-05-19
- https://queue.acm.org/detail.cfm?id=3158370 — Titus: Introducing Containers to the Netflix Cloud (ACM Queue 2018), 조회 2026-05-10
