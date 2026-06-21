---
name: github-actions-governance
description: GitHub Actions as contract + policy surfaces — reusable workflows, path routing, cache, concurrency, and release gates kept reviewable beyond YAML length.
keywords: github-actions gha workflow workflow_call workflow_dispatch reusable-workflow path-filter monorepo matrix concurrency cache artifact oidc permissions environment release-gate runner self-hosted action ci cd composite-action job-summary protected-branch
intent: 워크플로우만들어 actions설정해 ci구축해 reusable워크플로우만들어 path라우팅해 캐시설정해 oidc연결해 release게이트만들어 모노레포ci설정해
paths: .github/workflows/ .github/actions/ .github/CODEOWNERS workflow.yml action.yml composite/
patterns: actions/checkout actions/setup-node actions/setup-java actions/cache actions/upload-artifact aws-actions docker/login-action permissions oidc id-token concurrency matrix workflow_call workflow_dispatch
requires: devops repo-automation-safety release security
phase: implement deploy
tech-stack: any
min_score: 2
---

# GitHub Actions Governance

워크플로우 품질은 YAML 길이가 아니라 **계약과 정책 표면이 명시되었는가**로 결정. 권한, path routing, cache, release gate를 정책으로 다룬다.

## 의사결정 트리

### IF 새 워크플로우 작성 (Implement)
1. 트리거 명시 — `push`, `pull_request`, `workflow_dispatch`, `schedule`, `workflow_call` 중 어느 조합
2. 권한 최소화 — `permissions:` block 명시. 기본 read-all → 필요한 것만 write
3. concurrency group — 같은 PR/branch가 동시 실행되면 `cancel-in-progress` 또는 queue
4. 재사용 검토 — 비슷한 패턴 3+ 곳이면 reusable workflow 또는 composite action
5. **→ devops 스킬: CI/CD 전반 기획**

### IF 모노레포 selective CI (Implement)
1. path filter — `paths:` 또는 `dorny/paths-filter` action으로 변경 영역 감지
2. matrix dynamic — 변경된 모듈만 matrix에 포함 (정적 fan-out 금지)
3. 공통 영역(infra, schemas)은 모든 path에 trigger
4. fork PR과 protected workflow의 권한 차이 인지
5. concurrency를 path-aware하게 — `${{ github.workflow }}-${{ matrix.module }}`

### IF Reusable Workflow 만들 때 (Implement)
1. inputs 명시 — 타입(`string`/`boolean`/`number`), required, default
2. permissions 명시 — caller가 상속 안 됨, callee가 자기 것 선언
3. secrets 명시 — `secrets: inherit` vs explicit list
4. outputs — 다음 job/workflow가 참조할 값
5. semver 또는 SHA pin — `@v1` 보다 `@<sha>` 안전, 자동화는 dependabot

### IF Cache / Artifact 정책 (Implement)
1. cache key — 의존성 lockfile hash가 안전. 잘못된 키면 stale cache로 빌드 깨짐
2. cache size — repo cache는 10GB 한도. 적시 eviction 정책
3. artifact retention — 기본 90일, 큰 artifact는 7-14일로 단축
4. 보안 — fork PR cache는 격리, secret이 cache에 들어가지 않게
5. 다단 빌드면 build-cache job → test-cache job → deploy-cache 분리

### IF Release / Production Deploy Gate (Deploy)
1. environment — `production` 환경 만들고 required reviewer 설정
2. OIDC 연동 — long-lived secret 대신 short-lived token (AWS / GCP / Azure)
3. `if:` 조건 — 특정 branch/tag만, 또는 `workflow_dispatch` 수동
4. release artifact는 `release-please` / `goreleaser` 같은 도구로 자동화
5. **→ release 스킬: release rule 캐싱과 묶음**

### IF CI Failure 분석 (Debug)
- [ ] runner 종류 변경 — ubuntu-latest 버전 업글로 깨짐?
- [ ] action 버전 — `@main` 사용 시 무단 변경 가능
- [ ] cache key collision — 다른 브랜치 cache가 오염?
- [ ] permissions 부족 — 새 step이 권한 추가 요구?
- [ ] **→ dx:gha 스킬: GHA failure 분석 자동화**

## 정책 체크리스트

```
[Permissions]
□ workflow level permissions block 명시
□ default `read-all` → 필요시 `write` 명시
□ id-token: write는 OIDC 쓸 때만

[Path Routing]
□ paths / paths-ignore로 selective trigger
□ 변경 영역에 dynamic matrix
□ shared 영역(infra, schemas)은 항상 trigger

[Cache]
□ cache key가 lockfile hash 기반
□ stale cache 감지 시 즉시 무효화
□ fork PR cache 격리

[Concurrency]
□ concurrency group 명시 (PR/branch 단위)
□ deploy workflow는 cancel-in-progress 금지(서로 race)

[Release Gate]
□ production environment + required reviewer
□ OIDC short-lived token (long-lived secret 금지)
□ branch protection + required status checks
□ tag 또는 manual dispatch 트리거

[Reusable]
□ workflow_call inputs 타입 명시
□ permissions를 callee 자체에서 선언
□ action은 SHA pin (또는 dependabot로 추적)
```

## 가이드

### Permission 기본값 변경
조직/repo settings에서 default workflow permission을 `read` 로 설정하면 명시 안 한 워크플로우도 안전. 그 후 필요한 워크플로우만 `permissions:` 블록으로 write 추가.

### OIDC vs long-lived secret
AWS/GCP/Azure는 모두 OIDC 지원. `id-token: write` 권한 + cloud 측 trust policy 설정 → 토큰을 받아서 짧게 사용. credentials를 GitHub Secret에 저장하는 것보다 훨씬 안전.

### Reusable workflow vs composite action
- **Reusable workflow** (`workflow_call`): 여러 job 포함, secrets/permissions 분리. 큰 단위 재사용.
- **Composite action**: 한 job 안의 step들을 묶음. 가볍고 빠름. 권한/secret 별도 못 가짐.
- 큰 deploy 시퀀스 → reusable workflow. setup 같은 step 묶음 → composite action.

### Self-hosted runner 보안
public repo에 self-hosted runner 붙이지 말 것 — fork PR이 임의 코드 실행 가능. private repo + ephemeral(매 job 새 인스턴스) 또는 GitHub Larger Runners.

### Concurrency cancel-in-progress 함정
PR CI에는 좋음(새 push 시 옛 run 취소). 하지만 deploy workflow에 적용하면 배포 도중 취소 → 중간 상태로 깨짐. deploy는 queue 또는 manual.

## Gotchas

### `permissions:` 미명시 — 기본값 폭넓음
명시 안 하면 repo의 default permission을 따름. 조직 default가 `permissive`면 `contents: write` 등이 무방비. 워크플로우마다 명시.

### `actions/checkout@main` — supply chain 위험
tag/SHA가 아닌 브랜치를 참조하면 action 작자가 main을 변경하면 갑자기 다른 코드 실행. 최소 `@v4` (semver tag), 보안 민감하면 `@<full-sha>` + dependabot 자동 갱신.

### Cache key가 너무 광범위
`cache-key: ${{ runner.os }}-build`만 쓰면 모든 브랜치/PR이 같은 cache 공유 → 한 번 오염되면 다 깨짐. lockfile hash 포함 필수: `${{ runner.os }}-build-${{ hashFiles('**/lockfile') }}`.

### Fork PR에서 secret 노출 시도
`pull_request_target` 트리거는 base branch 권한으로 실행 → fork PR 코드가 secret 접근 가능. 정말 필요한 경우만, 그것도 명시적 review 후.

### Matrix fan-out이 정적 — 모노레포 비용 폭발
모든 모듈을 항상 matrix로 돌리면 PR마다 N개 모듈 × M개 OS = 비용 선형 증가. paths-filter로 변경된 모듈만 dynamic matrix.

### Concurrency 누락 — deploy 중복 실행
2개 PR을 동시에 main에 머지하면 deploy workflow 2개가 동시 실행 → infra race. `concurrency: deploy-prod` 그룹 + queue.

### Reusable workflow의 permissions 상속 가정
caller가 `permissions: write-all`이라도 callee는 명시 안 하면 default. 항상 callee에서 자기 권한 선언.

### `workflow_dispatch` inputs 검증 없음
manual dispatch에서 임의 문자열 받으면 injection 가능. inputs를 dropdown(type: choice)이나 정규식 검증.

### Long timeout — runner cost 폭발
`timeout-minutes` 없으면 default 360분(6시간). 한 job hang되면 6시간 비용. 항상 합리적인 timeout 명시(보통 15-30분).

### Branch protection 우회
`if: github.actor == 'admin'` 같은 우회 로직을 워크플로우에 넣으면 protection 의미 사라짐. branch protection은 GitHub UI 설정으로만, 워크플로우는 그걸 신뢰.

### Release artifact가 build job에서 직접 publish
build와 publish를 같은 job에 두면 build 실패 후 부분 publish 가능. build → artifact → 별도 publish job + environment gate.

## 도구 사용 패턴 (Harness)
- 워크플로우 검증: `Bash`로 `actionlint` 또는 GitHub의 `gh workflow lint`
- 실패 분석: `dx:gha` 스킬로 GHA failure 자동 분석
- 권한 점검: `Grep`으로 `.github/workflows/`에서 `permissions:` 누락 검색
- 액션 SHA pin 점검: `Grep`으로 `uses: .*@(main|master)` 패턴

## 에러 복구 패턴 (Harness)
- workflow가 갑자기 실패 → 최근 action 버전 변경 추적, runner image 업글 노트 확인
- "permission denied" → workflow의 `permissions:` block 검사, OIDC trust policy 확인
- cache miss로 빌드 느림 → cache key 충돌 / lockfile 변경 / 사이즈 한도 초과 점검
- deploy hang → concurrency group 충돌 또는 environment reviewer 미응답 확인
