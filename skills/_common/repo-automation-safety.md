---
name: repo-automation-safety
description: Repo automation as governed delivery — release manifests, CI routing, dry-run gates, side-effect scope, and rollback rehearsal kept reviewable beyond raw scripts.
keywords: repo-automation release-manifest provenance approval ci-trigger path-routing protected-branch dry-run side-effect rollback rehearsal bot script-execution release-notes changelog audit-trail signed-commit branch-protection codeowners
intent: 자동화스크립트만들어 release매니페스트정해 dry-run먼저해 ci라우팅정해 rollback리허설해 봇설정해 protected브랜치설정해 자동화안전성검토해
paths: scripts/ tools/ ci/ .github/ Makefile package.json/scripts release/ automation/ bots/
patterns: release-please goreleaser semantic-release changesets renovate dependabot pre-commit husky lefthook git-hooks branch-protection codeowners signed-commits artifact-provenance slsa
requires: github-actions-governance release infra-change-readiness rollback-readiness
phase: implement deploy review
tech-stack: any
min_score: 2
---

# Repo Automation Safety

자동화는 "스크립트가 잘 돌았다"가 아니라 **delivery state가 reviewable한가**로 평가. 4축: release manifest, CI routing, dry-run, rollback rehearsal.

## 의사결정 트리

### IF 새 자동화 스크립트 / 봇 추가 (Plan)
1. side-effect 범위 — 읽기만? PR 만들기? main에 직접 push? 외부 시스템 호출?
2. 권한 최소화 — repo scope, branch scope, secret scope를 명시
3. dry-run 모드 필수 — 첫 실행은 read-only로 결과 보고
4. fail-safe 동작 — 에러 시 rollback인가 그대로 멈춤인가
5. owner와 alert 채널 — 봇 실패 시 누가 보는가

### IF Release 자동화 도입 (Implement)
1. release manifest — 버전, 변경 commits, artifact, signature, approver를 한 객체로
2. 트리거 — tag push / PR merge / manual dispatch 중 어느 것
3. provenance — SLSA/sigstore로 빌드 출처 증명
4. compatibility 노트 — breaking change 감지 시 강제 manual approve
5. **→ release 스킬: repo별 release rule 캐싱**
6. **→ github-actions-governance 스킬: release gate workflow 패턴**

### IF CI Trigger Routing (Implement)
1. branch protection — protected branch에 직접 push 금지, PR만
2. required status checks — 어느 job 통과가 merge 조건인가
3. CODEOWNERS — 영역별 reviewer 자동 지정
4. path별 routing — `.github/workflows/`만 변경하면 별도 워크플로우 검증
5. fork PR 처리 — secret 노출 차단

### IF 자동화가 main을 직접 변경 (Implement)
1. 가능하면 PR 경유 — bot이 PR 생성 → merge는 사람 또는 별도 게이트
2. signed commit — bot identity 검증
3. dry-run report 먼저 — 무엇이 변경될지 출력 + N분 대기 후 실행
4. blast radius 제한 — 한 번에 N개 파일/N개 repo만 변경
5. rollback path — 이전 SHA로 자동 revert PR

### IF Rollback Rehearsal (Review)
- [ ] 마지막 release 기준으로 rollback 명령이 문서화되어 있는가
- [ ] dry-run rollback이 분기마다 1회 이상 수행되는가
- [ ] rollback artifact가 release retention 기간 내 유지되는가
- [ ] rollback owner가 명시되었는가 (보통 release author)
- [ ] **→ rollback-readiness 스킬: cross-domain rollback 패턴**

## 4축 체크리스트

```
[Release Manifest]
□ 버전 + commits + artifact + signature + approver
□ provenance (SLSA / sigstore)
□ breaking change 감지 시 manual approve
□ retention (artifact / changelog)

[CI Trigger Routing]
□ protected branch 설정
□ required status checks
□ CODEOWNERS 매핑
□ fork PR secret 격리

[Dry-run]
□ 첫 실행 read-only 모드 의무
□ 변경 예정 항목 리포트 + 대기 시간
□ side-effect scope 제한 (per-run cap)

[Rollback]
□ 명령 문서화
□ 분기별 rehearsal
□ artifact retention 충분
□ owner 명시
```

## 가이드

### Release manifest의 최소 필드
- `version`: semver
- `commits`: SHA 리스트 + 메시지
- `artifacts`: name, sha256, size, signature
- `breaking_changes`: 있다면 명시 (없으면 빈 리스트)
- `approver`: 사람 + 시점 (자동 release면 system + 정책 ID)
- `rollback_to`: 이전 release version (rollback 명령에서 사용)

### Dry-run report 형식
"변경 예정 N개: <목록>" + "실행하려면 다음 명령" 형태. 자동 5초 대기 후 실행 같은 패턴은 review 의미 약함 — 사람이 명시 confirm 필요.

### Bot identity와 signed commit
GitHub App(권장) 또는 dedicated machine user. PAT 직접 사용은 만료/유출 위험. signed commit으로 봇 변경과 사람 변경 구분 가능.

### protected branch 우회 함정
admin이 "Allow force pushes" 잠시 켜고 작업 후 다시 끄는 패턴 → 그 시간에 protection 무력. 우회 필요하면 admin 일시 escalation 트레일 남김.

### CODEOWNERS와 review concentration
한 사람을 여러 영역의 owner로 두면 그 사람이 휴가 시 모든 PR 정체. 영역별 backup owner + 자동 secondary review 정책.

## Gotchas

### Bot이 main에 force push
"빠른 fix" 명목으로 bot이 force push 하면 다른 개발자 작업 잃음. force push는 항상 사람 결정, bot은 PR만.

### Dry-run이 실제와 다른 코드 경로
read-only 모드에서 "if dry: return" 패턴으로 분기하면 진짜 실행 경로와 달라서 dry-run 통과해도 진짜 실행에서 실패. 같은 코드 경로 + 마지막 commit 단계만 분기.

### Side-effect cap 없음 — bulk 사고
정규식 잘못 써서 bot이 1만 개 PR을 만드는 사고. per-run cap (예: 50개 PR / 100 파일) + 초과 시 자동 정지 + 사람 승인 필요.

### Release manifest에 signature 누락
artifact는 빌드했지만 sha256/signature가 없으면 supply chain 공격 시 변조 감지 불가. 빌드 직후 sign + manifest에 기록 필수.

### Rollback artifact retention 짧음
artifact 7일 보관인데 incident 2주 후 발견 — rollback 불가. 안정 release는 N개월, LTS는 더 길게.

### Bot이 secret을 log에 출력
디버깅 print에 환경변수 dump하면 GitHub Actions log에 secret 평문 노출. structured logger + secret redaction 필수.

### CODEOWNERS 미설정 — 임의 reviewer
CODEOWNERS 없이 "아무나 review"면 보안/DB 영역 변경이 도메인 모르는 사람에게 가서 통과. 영역별 codeowner 명시.

### Required status checks가 stale
새 워크플로우 추가했는데 protected branch 설정에 등록 안 함 → 그 check가 fail해도 merge 가능. 새 check 추가 시 protection 설정 동시 업데이트 절차.

### Bot 권한이 over-broad
한 bot에게 모든 repo의 admin 권한 주면 그 bot 토큰 유출 시 조직 전체 위험. fine-grained PAT 또는 GitHub App per scope.

### Release 자동화가 main 머지 즉시 실행
PR 머지 → 즉시 release면 마지막 review 기회 없음. main 머지 → staging 배포 → manual dispatch로 release tag 권장. hotfix는 별도 fast lane.

### Rollback 절차가 release author 머릿속에만
release한 사람이 rollback 명령 알지만 문서화 안 됨 → 그 사람 부재 시 incident 시 rollback 못 함. release manifest에 rollback 명령 필드 의무.

## 도구 사용 패턴 (Harness)
- 자동화 권한 검토: `Grep`으로 `permissions:`, `secrets:` 사용 검색
- protected branch 점검: `Bash`로 `gh api repos/<owner>/<repo>/branches/<name>/protection`
- release manifest 검증: 빌드 후 `Bash`로 manifest 필드 존재 확인
- rollback rehearsal: dry-run 모드로 이전 release 명령 시뮬레이션

## 에러 복구 패턴 (Harness)
- bot이 잘못된 PR 다수 생성 → cap 정책 회수, 영향 PR을 batch로 close + revert
- release artifact 누락 → CI artifact retention과 manifest retention 매칭 점검
- rollback 명령 실패 → 이전 SHA의 build artifact 존재 / config compatibility 확인
- protected branch 우회 흔적 → audit log에서 admin 일시 변경 추적

## Related (신규 그래프 cross-ref)

repo-automation-safety가 결합되는 신규 노드:
- `_common/skill-distillation-pipeline.md` — 5단계 추출 절차 + 9게이트 강제 (자동화의 메타 표준)
- `_common/chaos-engineering.md` — bot 자동화의 reliability를 active fault injection으로 검증
- `infra/spinnaker-pipeline.md` — Manual Judgment + distributed locking (1.31+) bot 동시성 차단
- `_common/webhook-delivery-and-signing.md` — bot이 webhook 수신/발신 시 HMAC 검증 표준
- `_common/durable-execution.md` — bot의 long-running task는 Temporal activity로 (heartbeat + retry policy)
