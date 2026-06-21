---
name: rollback-readiness
description: Rollback as a cross-domain readiness discipline — repo/release/infra/binary upgrade share checkpoint, rehearsal, and recovery patterns made reviewable before incidents.
keywords: rollback revert recovery checkpoint rehearsal preflight upgrade-rollback canary blue-green dark-launch feature-flag kill-switch release-manifest infra-revert binary-rollback abi-compatibility data-migration-revert state-snapshot dual-write shadow-traffic
intent: rollback계획해 revert해 recovery절차정해 checkpoint잡아 rehearsal해 canary배포해 blue-green설정해 feature-flag로보호해 dual-write설계해
paths: release/ rollback/ recovery/ migrations/ flags/ deploy/ ops/ runbooks/
patterns: feature-flag launchdarkly unleash flagsmith blue-green canary dark-launch shadow-traffic helm-rollback git-revert tf-state-rollback dual-write expand-contract migration-rollback
requires: repo-automation-safety release infra-change-readiness sre-operations
phase: plan deploy review
tech-stack: any
min_score: 2
---

# Rollback Readiness

좋은 rollback은 incident 시 결정하는 것이 아니라 **변경 전 미리 설계·리허설된 상태**. 4도메인 공통 패턴: checkpoint, rehearsal, recovery owner, blast radius.

## 의사결정 트리

### IF Repo / Release Rollback (Plan)
1. release manifest에 `rollback_to: <prev-version>` 명시
2. artifact retention — rollback 가능한 옛 버전 image/binary 유지 기간
3. config compatibility — 옛 버전 코드가 새 config 읽을 수 있는가 (rollback safety)
4. DB migration — forward만 적용했나? rollback migration 또는 expand-contract?
5. rollback 명령 문서화 — release manifest 또는 runbook
6. **→ release 스킬: release rule에 rollback 절차 캐싱**
7. **→ repo-automation-safety 스킬: bot rollback PR 생성**

### IF Infra Rollback (Deploy)
1. Terraform — `terraform apply` 전 state snapshot (S3 versioning 또는 backup)
2. K8s — Helm release history(`helm rollback`) 또는 manifest git revert
3. Docker — image tag 옛 버전 유지 + `kubectl set image`
4. config drift — apply 전후 state diff 보관
5. partial rollback — 일부 리소스만 revert 가능한가
6. **→ infra-change-readiness 스킬: change window에 rollback checkpoint**

### IF Binary / Library Upgrade Rollback (Plan)
1. ABI compatibility — 새 버전이 옛 caller binary 호환?
2. feature gate — 새 기능을 flag로 보호. rollback 시 flag만 끔
3. dual-write 또는 expand-contract — 신구 양쪽 read 가능한 기간
4. monitoring — upgrade 후 N시간 watch window
5. preflight check — 옛 데이터 / 옛 caller가 새 버전과 호환

### IF Database Schema Rollback (Plan)
1. **expand-contract 패턴**:
   - Phase 1: 새 컬럼 추가 (additive)
   - Phase 2: app이 둘 다 write
   - Phase 3: backfill
   - Phase 4: app이 새 컬럼만 read
   - Phase 5: 옛 컬럼 deprecate → drop
2. 각 phase가 독립적으로 rollback 가능
3. 한 deploy에 여러 phase 묶지 말 것 — rollback이 다단계 되면 위험
4. drop은 충분한 dwell 후 별도 release

### IF Rollback Rehearsal (Review)
1. 분기별 1회 — staging에서 N개월 전 release로 rollback drill
2. 명령이 documented 그대로 작동하는가
3. artifact가 retention 안에 있는가
4. config compatibility 검증
5. DB는 dry-run 또는 별도 환경
6. 결과를 runbook에 update

### IF Incident Rollback 결정 (Review)
- [ ] error budget burn rate가 rollback 임계값 초과
- [ ] forward fix가 rollback보다 명백히 빠른가? 아니면 rollback
- [ ] rollback의 영향 범위 알고 있는가 (사용자/기능)
- [ ] DB 변경이 있나? rollback 시 데이터 호환?
- [ ] customer comm 준비 — rollback 자체도 변경

## 4-도메인 공통 체크리스트

```
[Checkpoint]
□ 변경 전 상태 snapshot (state file, image tag, schema 버전)
□ retention이 typical incident 발견 시간보다 김
□ 옛 artifact 빌드 가능 (또는 보관)

[Rehearsal]
□ 분기별 1회 staging drill
□ 명령이 runbook에 그대로 있는가
□ 마지막 rehearsal 일자 기록

[Recovery Owner]
□ release author 또는 명시된 owner
□ 24/7 가용 (on-call 또는 dedicated)
□ rollback 권한 사전 부여

[Blast Radius]
□ 영향 사용자 / 리전 / 기능 명시
□ 부분 rollback 가능 여부
□ data 변경 동반 시 dual-read 보호
```

## 가이드

### Forward fix vs Rollback
- **Rollback**: 변경 전으로 즉시 복귀. 안전하지만 data drift 위험.
- **Forward fix**: 새 fix 배포. data 일관성 유지하지만 시간 걸림.
- 결정 기준: error 영향 > 30%면 즉시 rollback, 5-30%면 forward fix 우선 시도(15분 cap), 5% 미만이면 monitor.

### Feature Flag로 rollback을 deploy 없이
risk 있는 기능을 flag 뒤에 두면 incident 시 flag toggle = instant rollback. flag config는 deploy 사이클과 분리(LaunchDarkly, internal flag service).

### Expand-Contract 데이터 마이그레이션
한 release로 schema breaking change + app code 둘 다 바꾸면 rollback 시 schema와 app 사이 mismatch. expand-contract로 여러 release에 분산:
- expand: 새 컬럼/테이블 추가, app 코드는 양쪽 호환
- contract: 옛 컬럼 사용 중단 후 별도 release에서 drop

### Canary / Blue-Green과 rollback
- **Canary**: 5% → 25% → 100% 점진. 문제 시 0%로 즉시 rollback.
- **Blue-Green**: 두 환경 동시 가동, traffic switch. 옛 환경은 N시간 유지.
- 둘 다 deploy 자체가 atomic이라 rollback도 atomic.

### Customer comm vs internal-only rollback
internal change rollback은 communication 없이 OK. user-visible 기능 rollback은 status page 또는 changelog. 자주 rollback하면 신뢰 저하 — postmortem에서 근본 원인 해결.

## Gotchas

### Rollback artifact가 retention 만료
incident 2주 후 발견 — image registry retention 7일이면 rollback 불가. stable release는 N개월, LTS는 더 길게 유지.

### DB migration이 forward only
column drop이 같은 release에 있으면 rollback 시 옛 코드가 없는 컬럼 read → fail. expand-contract로 drop은 별도 release.

### Helm rollback이 부분만 됨
release만 rollback 되고 외부 의존(CRD, ConfigMap의 외부 변경)은 그대로 → 부분 rollback 상태로 inconsistent. helm hook 또는 수동 절차로 외부 동기화.

### Feature flag rollback의 사용자 고립
flag가 user attribute 기반이면 일부 사용자가 새 기능 본 상태에서 flag 끄면 데이터/state 불일치. flag는 새 기능 launch 후 N주 후 cleanup, 양쪽 호환 코드 유지.

### Rollback 절차가 release author 머릿속에만
release한 사람이 휴가 중 incident → 다른 사람이 rollback 명령 모름. release manifest에 rollback 명령 의무 필드.

### Rehearsal 안 한 rollback
"명령은 있는데 실제론 안 해봤음" — 막상 incident에서 syntax error / artifact 없음 / 권한 부족 발견. 분기별 staging drill 의무.

### Rollback 후 monitoring 없음
"rolled back, 끝" 하면 rollback 자체가 cause한 신규 문제 놓침. rollback 후 N시간 watch window + key metric 비교.

### Forward fix가 비싸도 rollback 안 함
data drift 우려로 rollback 미루다가 incident 길어짐. 작은 data drift는 backfill 가능, 확장된 incident는 사용자 신뢰 잃음. 임계값 명시.

### Canary metric이 충분 traffic 없음
canary 5% traffic이 너무 적어 statistical significance 없음 → 30분 후 100% → 사실 문제였음. critical metric은 충분 sample size까지 dwell.

### Blue-green switch 후 옛 환경 즉시 셧다운
즉시 끄면 incident 발견 시 rollback 못 함. 옛 환경 N시간(보통 24h) 유지 + readonly로 switch 가능.

### Multi-region rollback 순서
한 region rollback → 다른 region 그대로면 user가 region 따라 다른 경험. canary region 먼저 → 모니터 → 다른 region.

### Rollback이 이전 buggy version으로
"이전 release로 돌아가" 했는데 그 release도 다른 bug 있음 → 더 큰 문제. last-known-good marker를 release manifest에 유지.

## 도구 사용 패턴 (Harness)
- release manifest: `Read`로 `rollback_to`, `artifact_retention` 필드 확인
- artifact 존재: `Bash`로 registry / artifact storage list
- DB migration: `Grep`으로 `migrations/` 디렉토리에서 forward/backward 스크립트 확인
- feature flag 상태: flag service API 또는 config file
- rehearsal log: `runbooks/rollback-rehearsal-<date>.md` 형식

## 에러 복구 패턴 (Harness)
- "rollback artifact not found" → registry retention 정책 검사, 옛 빌드 재생성 가능 여부
- helm rollback fail → release history(`helm history`) 확인, stale lock 또는 CRD 외부 변경
- DB rollback 시 data loss 위험 → forward fix 검토, dual-read 코드 임시 주입
- feature flag toggle 후 일부 사용자 깨짐 → flag-aware 코드 양쪽 호환 검증, sticky session 영향 확인
