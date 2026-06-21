---
name: release
description: Repo-aware release assistant — analyzes project/CI to derive release rules, caches them, then guides version bump + tag + push.
keywords: [release, version, tag, publish, changelog, bump, semver]
intent: [release, publish, version, tag]
phase: deploy
min_score: 3
---

# Release

프로젝트 + CI를 검사해 release 규칙을 추출하고 `.harness/RELEASE_RULE.md`에 캐시, 이후 그 규칙으로 release 가이드.

## 사용법

```
/release [version]
```

- `version` 선택. 생략하면 물어봄. `patch` | `minor` | `major` | 명시 semver (`2.4.0`) 허용.
- `--refresh`: 캐시된 rule 있어도 재분석 강제.

## 실행 흐름

### Step 0 — Rule 로드 또는 빌드

`<project>/.harness/RELEASE_RULE.md` 존재 확인.

- **없음 또는 `--refresh`**: 전체 repo 분석 + 파일 작성.
- **있음**: 파일 읽음. 빠른 delta 체크 — `.github/workflows/`, `.circleci/`, `.travis.yml`, `Jenkinsfile`, `.gitlab-ci.yml` 중 `last-analyzed` 이후 수정된 파일이 있으면 해당 섹션 재분석 후 업데이트.

### Step 1 — Repo 분석 (첫 실행 / `--refresh`)

#### 1a. Version Sources
- `package.json`, `pyproject.toml`, `Cargo.toml`, `build.gradle`, `VERSION` 파일 등에서 현재 버전 문자열 매칭 위치 파악.
- release 자동화 스크립트 감지 (`scripts/release.*`, `Makefile release`, `bump2version`, `release-it`, `semantic-release`, `changesets`, `goreleaser`).

#### 1b. Registry / 배포
- npm / PyPI / Cargo / Docker / GitHub Packages.
- 태그 푸시 시 자동 publish 하는 CI 스텝 있나? workflow/job 식별.

#### 1c. Release Trigger
- 태그 푸시 (`v*`) / 수동 dispatch / main 병합 / 릴리스 브랜치 병합 / commit 메시지 패턴.

#### 1d. Test Gate
- 테스트 명령 + CI 위치. publish 전 필수? bypass 플래그?

#### 1e. Release Notes / Changelog
- `CHANGELOG.md` 컨벤션: Keep a Changelog / Conventional Commits / GitHub auto / 없음.
- 사전 커밋 release body 파일 (`.github/release-body.md`)?

#### 1f. First-Time 사용자 체크
- `.github/workflows/`에 release workflow 있나? 없으면 scaffold 제안.
- 빌드 아티팩트 `.gitignore` 되어 있나?
- `git tag --list`로 태그 사용 중인가?

### Step 2 — `.harness/RELEASE_RULE.md` 작성

```markdown
# Release Rules
<!-- last-analyzed: YYYY-MM-DDTHH:MM:SSZ -->

## Version Sources
<!-- 파일 + 패턴 리스트 -->

## Release Trigger
<!-- 무엇이 release 시작 -->

## Test Gate
<!-- 명령 + CI job 이름 -->

## Registry / Distribution
<!-- npm / PyPI / Docker 등 + publish하는 CI job -->

## Release Notes Strategy
<!-- 컨벤션 + 파일 -->

## CI Workflow Files
<!-- 관련 workflow 파일 경로 -->

## First-Time Setup Gaps
<!-- 분석 중 발견한 빠진 부분 또는 "none" -->
```

### Step 3 — 버전 결정

인자 있으면 사용. 없으면:
1. 현재 버전 표시 (primary version file에서).
2. `patch` / `minor` / `major` 결과 표시.
3. 사용자 선택.

선택한 버전이 유효 semver인지 검증.

### Step 4 — Pre-Release 체크리스트

- [ ] 이 release의 모든 변경 commit + push 완료
- [ ] target 브랜치 CI green
- [ ] 로컬 테스트 pass (test gate 명령)
- [ ] 모든 version source 파일에 버전 bump 적용
- [ ] Release notes / changelog 준비 (Step 5)

### Step 5 — Release Notes 가이드

감지된 컨벤션 적용. 기본:
- 사용자에게 **바뀐 것** 먼저 (내부 구현 아님).
- 유형별 그룹: `New Features`, `Bug Fixes`, `Breaking Changes`, `Deprecations`, `Internal / Chores`.
- 각 항목: 한 문장 + PR/이슈 링크 + 외부 기여자 크레딧.
- **Breaking changes** 먼저 + 마이그레이션 경로 포함.
- 사용자에게 안 보이는 변경 (refactor, CI, test-only) 생략 (빌드 재현성 영향 제외).

Conventional Commits 프로젝트면:
```bash
git log <prev-tag>..HEAD --no-merges --format="%s"
```
으로 draft changelog 생성, 타입별 그룹화, 사용자 편집 허용.

### Step 6 — Release 실행

1. **Bump version**: 각 version source 파일에 적용.
2. **Run tests**: test gate 명령.
3. **Commit**: `git add <version files> CHANGELOG.md` + `chore(release): bump version to vX.Y.Z`.
4. **Tag**: `git tag -a vX.Y.Z -m "vX.Y.Z"` (annotated).
5. **Push**: `git push origin <branch> && git push origin vX.Y.Z`.
6. **CI가 인수받음**: 태그 푸시 트리거면 CI가 publish 담당. 예상 workflow 표시.
7. **Manual publish**: CI 자동화 없으면 수동 publish 명령 (`npm publish --access public`, `twine upload dist/*`).

### Step 7 — First-Time 설정 제안

Gap 발견 시:
- **Release workflow 없음**: `.github/workflows/release.yml` scaffold 제안.
- **Git tag 없음**: 첫 release 설명 + Step 6에서 생성.
- **빌드 아티팩트 committed**: `.gitignore` 업데이트 제안.

### Step 8 — Verify

- CI 상태: `gh run list --workflow=<release> --limit=3`.
- registry에서 새 버전 확인 (몇 분 후).
- GitHub Release 생성 확인: `gh release view vX.Y.Z`.

## Gotchas

- **Version source 파일 누락**: 같은 버전 문자열이 여러 파일 (README, docker-compose 등)에 있을 수 있음. 모두 업데이트 안 하면 불일치.
- **`--no-verify` 유혹**: pre-commit hook 실패 시 건너뛰지 말고 원인 조사.
- **태그 먼저, push 나중**: 태그만 push하고 commit 안 하면 CI가 존재하지 않는 commit을 봄. 순서: commit → tag → push both.
- **Breaking changes 숨김**: 사용자는 migration 필요. 반드시 first-class notes로.
- **Monorepo 감지**: npm workspaces / pnpm workspaces / Cargo workspace 감지해 서브패키지 버전 분리 처리.

## Related (신규 그래프 cross-ref)

release가 결합되는 신규 노드:
- `infra/spinnaker-pipeline.md` — Spinnaker 2026.x Bake/Deploy/Manual Judgment/Pipeline/Webhook stage 표준 (release 자동화 차세대)
- `_common/api-migration-replay-traffic.md` — 백엔드 swap 시 replay traffic 3-step + sticky canary + 30일 dark mode rollback
- `_common/durable-execution.md` — Temporal로 release rollout step의 exactly-once 보장
- `_common/load-shedding-prioritized.md` — release 시 부하 임계 도달 시 tier 4부터 drop
- `_common/chaos-engineering.md` — release 후 reliability 자동 검증 (AWS FIS / Gremlin)
