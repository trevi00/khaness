---
name: infra-change-readiness
description: Live-execution readiness for Docker/k8s/Terraform — host posture, cluster context, state lock, approver, and rollback checkpoints checked before apply.
keywords: infrastructure infra docker kubernetes k8s terraform helm kustomize iac apply readiness host-context daemon kubectl-context namespace state-lock workspace approver change-window blast-radius preflight verification rollback-checkpoint live-apply credential-boundary
intent: docker배포해 쿠버네티스배포해 terraform적용해 인프라변경해 apply전점검해 change-window잡아 rollback계획해 cluster-context설정해 namespace확인해
paths: infra/ terraform/ k8s/ kubernetes/ helm/ kustomize/ docker/ docker-compose.yml Dockerfile *.tf *.tfvars manifests/
patterns: terraform kubectl helm kustomize docker docker-compose k9s flux argocd terragrunt cdk pulumi crossplane buildx
requires: devops repo-automation-safety rollback-readiness sre-operations
phase: deploy review
tech-stack: any
min_score: 2
---

# Infra Change Readiness

렌더링된 manifest는 **모양**을 증명하지만 **실행 안전성**은 다른 문제. live apply 전에 host/context/state/approver를 별개 단계로 점검.

## 의사결정 트리

### IF Docker / Compose 명령 실행 (Deploy)
1. host posture — 어느 호스트에서 도는가, daemon 상태, buildx 가능 여부
2. disk 여유 — image pull 후 남는 용량 (보통 빌드 1회당 N GB)
3. credential boundary — registry login이 어디 호스트에 캐시되는가, 다른 사용자 노출?
4. cleanup 정책 — old image / dangling layer / build cache 회수 주기
5. compose의 외부 의존(DB/Redis) state는 별도 보호

### IF Kubernetes mutation 명령 (Deploy)
1. **context pin 의무** — `kubectl config current-context` 명시 후 명령
2. **namespace pin 의무** — `-n <ns>` 또는 namespace alias로 명시
3. server scope — 어느 cluster의 어느 server에 닿는가 (prod 실수 방지)
4. dry-run first — `--dry-run=server` 또는 `kubectl diff`로 변경 미리 확인
5. secret 경계 — secret을 stdin으로 만든 적 있나(shell history에 노출)?
6. rolling update + readiness probe로 zero-downtime
7. **→ runtime-lifecycle 스킬: readiness/health/shutdown 계약**

### IF Terraform Apply (Deploy)
1. backend lock — state file lock이 걸려 있는가 (다른 사람 apply 중인지)
2. workspace 확인 — `terraform workspace show`로 prod/staging 확실히
3. snapshot — apply 전 state backup
4. `plan` review — 사람이 변경 항목 line-by-line 확인
5. variable set — 어느 환경 변수/tfvars 사용 중
6. approver — destructive change(`destroy` line 포함)는 별도 approver 필요
7. apply 후 `terraform output`으로 결과 검증

### IF Change Window 잡을 때 (Plan)
1. blast radius — 어느 서비스/리전/사용자 영향
2. 시간대 — 트래픽 낮은 시간 + 운영자 가용
3. freeze 겹침 — 회사 freeze 기간(이벤트, 분기말)과 충돌 없는지
4. operator load — 같은 시간 다른 변경 작업 없는지
5. verification 명령 — apply 후 어떤 명령으로 확인
6. rollback checkpoint — 시점별 revertable 상태가 있는가
7. **→ sre-operations 스킬: maintenance window 검토 패턴**

### IF Apply 직후 검증 (Review)
- [ ] verification 명령이 모두 PASS
- [ ] 의도치 않은 변경(예: replicas, ingress)이 plan에 없었나
- [ ] state file이 정상 commit (Terraform), 또는 apply 후 read-back (k8s)
- [ ] error budget이 변동 없거나 회복 중
- [ ] rollback checkpoint가 여전히 유효(이전 SHA/state 접근 가능)

## 4축 체크리스트

```
[Host / Context]
□ Docker: daemon up, disk 여유, credential 격리
□ k8s: context + namespace pin
□ Terraform: backend lock + workspace 확인
□ 도구 버전 일치 (CI와 로컬)

[State / Lock]
□ Terraform state lock + snapshot
□ k8s: 같은 cluster에 동시 변경 없음
□ Compose: external state(volume) 보호

[Approver]
□ destructive change 별도 approver
□ prod context 변경 시 명시 confirm
□ change window calendar 등록

[Rollback Checkpoint]
□ 이전 state/manifest 접근 가능
□ rollback 명령이 release manifest에 있음
□ verification 명령 + 임계값 명시
```

## 가이드

### k8s context 실수 방지 — kubeswitch / kubie / direnv
shell prompt에 현재 context + namespace를 항상 표시. `oh-my-zsh kubectl plugin`, `kube-ps1`, `direnv` 등으로 자동. "지금 prod에 있구나" 인지 후 명령.

### Terraform plan ↔ apply 사이 drift
plan 후 apply 사이 누군가 다른 변경을 하면 apply가 다른 동작. plan output을 file로 저장 → `terraform apply <plan-file>`로 정확히 그 plan만 적용.

### Server-side dry-run
`kubectl apply --dry-run=client`는 client 검증만, `--dry-run=server`는 admission webhook 포함 — 진짜 cluster 정책 통과 여부 확인. server-side 권장.

### Buildx multi-arch와 cache
`docker buildx build --platform linux/amd64,linux/arm64`로 다중 아키 빌드. cache는 registry나 GitHub Actions cache에 저장하면 CI 빌드 시간 대폭 감소.

### Helm release vs raw manifest
Helm은 release history + rollback 명령(`helm rollback`) 제공해 rollback이 쉬움. raw manifest는 직접 git revert + apply 필요. 운영 변경이 많으면 Helm/Kustomize 권장.

## Gotchas

### k8s context wrong — prod 명령을 dev에서 실행 시도, 또는 반대
shell history에서 명령 재실행 시 context가 prod로 바뀐 줄 모르고 실행 → 사고. 모든 mutating 명령 전에 `kubectl config current-context` echo 또는 alias로 명시.

### Terraform state lock 풀리지 않음
누가 apply 도중 ctrl-c 또는 crash → lock이 stale. `terraform force-unlock <lock-id>`는 정말 다른 사람 apply 중이 아닌지 확인 후. 무턱대고 풀면 동시 apply.

### `kubectl delete` without `--namespace` (anti-pattern)
default namespace 또는 현재 context의 default에 적용 → 의도와 다른 리소스 삭제. 항상 `-n <ns>` 명시. 사용자 확인 + dry-run (`kubectl delete --dry-run=client -n <ns>`) 우선.

### Docker image pull 시 disk 가득
빌드 머신 disk가 90%+ 면 pull 도중 fail + 부분 이미지로 다음 명령 깨짐. 빌드 전 `docker system df`로 확인 + 주기적 `docker system prune -af --filter "until=72h"`.

### Terraform apply가 secret을 state에 평문 저장
sensitive 변수도 state에는 평문. state는 encrypted backend(S3 + KMS, Terraform Cloud 등)에 저장. local state file 절대 커밋 금지.

### Helm rollback 후 state divergence
Helm release rollback 했지만 외부 의존(CRD, ConfigMap 외부 변경)은 그대로 → 부분 rollback. helm hook 또는 별도 절차로 외부 의존 동기화.

### Docker buildx without `--push`
빌드만 하고 push 잊으면 다음 단계 deploy가 옛 image. CI에선 build + push를 같은 step에. 또는 build 후 image digest 검증.

### kubectl `apply` vs `replace` vs `patch` 혼용
임의로 `replace`하면 다른 사람이 추가한 annotation 삭제. 일반적으로 `apply` (server-side) 권장. patch는 부분 업데이트.

### 같은 cluster에 운영자 2명이 동시 변경
한 사람은 helm, 한 사람은 kubectl edit → race. change-window calendar + lock 파일(SRE 채널 announce) 같은 운영적 단일 직렬화 필요.

### Terraform module을 fork 후 upstream 갱신 누락
보안 패치된 module을 6개월간 못 받음. dependabot이 terraform module도 추적하도록 설정 또는 분기별 module audit.

### Compose의 named volume 삭제 — 데이터 loss
`docker-compose down -v`는 volume도 삭제 → DB 데이터 영구 삭제. local dev에서는 OK, staging/prod에서는 절대 금지. compose file과 운영 절차 분리.

## 도구 사용 패턴 (Harness)
- context 확인: `Bash`로 `kubectl config current-context && kubectl config view --minify -o jsonpath='{..namespace}'`
- terraform plan: `Bash`로 plan → 출력을 review용 file로 저장 → 사람 confirm 후 apply
- docker host posture: `Bash`로 `docker info | grep -E 'Server Version|Storage Driver|Disk'`
- state snapshot: terraform이면 `terraform state pull > backup-<date>.tfstate`

## 에러 복구 패턴 (Harness)
- "context not found" → kubeconfig 통합 확인, vpn/cloud auth 갱신
- terraform "state lock" → 누가 잡고 있는지 확인 후 동의 받고 force-unlock
- helm release stuck "pending-install" → `helm rollback` 또는 `helm uninstall --keep-history`
- docker pull 인증 실패 → registry login 재실행 또는 OIDC 토큰 갱신
