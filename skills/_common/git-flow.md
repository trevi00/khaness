---
name: git-flow
description: Vincent Driessen Git Flow 브랜치 모델 + 회사 오버라이드 — 브랜치 전략, 커밋 메시지 규칙, PR 프로세스. validators/git_flow.py가 lint 강제 + pre_tool/guard.py 가 main 직접 push 차단.
keywords: [git-flow, gitflow, branch, merge, PR, pull-request, hotfix, release, feature, develop, main, 브랜치, 깃플로우, 머지, 풀리퀘, 핫픽스]
intent: [start-feature, finish-feature, hotfix, release, branch-strategy]
phase: implement
min_score: 2
---

# Git Flow

Vincent Driessen 브랜치 모델 + 우리 하네스의 강제 룰.

## 의사결정 트리

### IF 새 기능 작업 시작 (Implement)
1. `git checkout develop && git pull`
2. `git checkout -b feature/<기능명>` (kebab-case 권장, 한국어 가능)
3. 작업 + 커밋 (커밋 메시지는 아래 접두사 룰 준수)
4. 완료 시 `git push -u origin feature/<기능명>`
5. **PR 생성** (feature → develop) — 직접 merge 금지
6. 관리자 리뷰 후 merge → 다른 작업자에게도 develop pull 요청

### IF 긴급 버그 수정 (Hotfix)
1. `git checkout main && git pull`
2. `git checkout -b hotfix-<version>` (회사) 또는 `hotfix/<issue>` (일반)
3. 수정 + 커밋 (`[fix]` 접두사)
4. PR 생성 (hotfix → main) — 관리자 merge
5. **반드시 develop에도 merge** (회귀 방지)

### IF 배포 준비 (Release)
1. `git checkout develop && git pull`
2. `git checkout -b release-<version>`
3. 버그 수정 / 문서 / 버전 bump 만 — **새 기능 추가 금지**
4. PR 생성 (release → main) → tag → develop back-merge

### IF 직접 main/develop push 시도 (Pre-tool guard)
- main/master push: **차단** (`pre_tool/guard.py` DENY)
- develop push: **경고** (PR 권장)
- 우회 정책 위반 → `~/.claude/state/decisions/git-flow-overrides.md` 에 사유 기록 후 manual

### IF 프로젝트별 컨벤션 override 사용
- `<project>/.claude/git-flow-overrides.md` 가 있으면 우선 — 프로젝트별 컨벤션 적용
- 없으면 본 스킬의 일반 git flow + 표준 conventional commits
- 회사/프로젝트 별 구체적 prefix·브랜치 형식은 별도 문서로 분리:
  - 회사 ACME_INTERNAL: `flutter/example_app/git-flow-company.md` (사용자 회사 전용 — 일반 공유 컨텐츠 아님)
  - 본인 프로젝트의 override를 추가하려면 `git-flow-overrides.md` 작성 후 회사별 SKILL.md 별도로 둘 것

## 브랜치 명명 규칙 (일반)

| 브랜치 | 형식 |
|---|---|
| 통합 | `develop` |
| 배포 | `main` 또는 `master` |
| 기능 | `feature/<name>` |
| 배포준비 | `release/<version>` |
| 긴급수정 | `hotfix/<issue>` |

회사/프로젝트별 dash 형식 (`release-<version>`, `hotfix-<version>`)은 override 활성 시 별도 문서 참조 (예: `flutter/example_app/git-flow-company.md`).

## 커밋 메시지 접두사

### 일반 (Conventional Commits)
| 접두사 | 용도 |
|---|---|
| `feat:` | 새 기능 |
| `fix:` | 버그 수정 |
| `refactor:` | 동작 무변경 리팩토링 |
| `docs:` | 문서만 |
| `test:` | 테스트만 |
| `chore:` | 빌드/도구/잡일 |
| `perf:` | 성능 개선 |

### 프로젝트별 override (회사 컨벤션 등)

회사 또는 프로젝트별 prefix 체계가 있다면 본 스킬에 인라인하지 말고 별도 문서로 분리한다:

- 분리 위치: 해당 프로젝트의 stack 서브트리 (예: `flutter/example_app/git-flow-company.md`).
- 활성화: 프로젝트 루트의 `<project>/.claude/git-flow-overrides.md` 에 `override: <company-name>` 명시 + 분리 문서 인용.
- 일반 공유 트리 (`_common`)에는 프로젝트 고유 prefix 표를 두지 않는다 (user-private leak 방지).

## PR 프로세스 (둘 다 공통)

1. **개인 브랜치 작업 완료** → push (직접 merge 금지)
2. **PR 생성** (feature/hotfix/release → 타겟 브랜치)
3. **관리자 리뷰 + merge** (자동 merge 권한 없음)
4. **merge 후 알림** — 다른 작업자에게 pull 요청

## 강제 메커니즘 (3 layers)

| 레이어 | 위치 | 동작 |
|---|---|---|
| **1. 사전 차단** | `pre_tool/guard.py` | `git push origin main/master` DENY, `git push origin develop` WARN, 커밋 메시지에 접두사 없으면 WARN |
| **2. Lint** | `validators/git_flow.py` | 현재 브랜치명 검사 + 최근 10 커밋 메시지 접두사 검사. `/harness-audit` Phase 5에서 실행 |
| **3. 문서** | 본 스킬 | 의사결정 트리 + 명명 룰 + 접두사 카탈로그 |

## 프로젝트 오버라이드

`<project>/.claude/git-flow-overrides.md` 형식 (예시 — 구체 prefix는 회사별 별도 문서):

```markdown
---
override: <override-name>
---
# <override-name> git flow override

## 브랜치 prefix
<프로젝트별 형식>  # 예: dash, slash, 등

## 커밋 prefix
<프로젝트별 prefix list>
```

`validators/git_flow.py` 가 자동 감지 후 검사 룰 전환. 회사별 구체 prefix·브랜치 형식은 user-private 트리(예: `flutter/example_app/git-flow-company.md`)에 분리 보관 — 일반 공유 트리에는 두지 않는다.

## Gotchas

- **`--no-verify` 사용 금지**: pre-commit hook을 우회하면 lint 통과 못한 commit이 들어감. 회사 정책 위반.
- **main에 force push**: `pre_tool/guard.py` DENY 패턴이 이미 차단. 우회하지 마라.
- **release 브랜치에 새 기능**: release는 안정화 단계. 새 기능은 다음 release 또는 feature/.
- **hotfix 후 develop merge 누락**: 가장 흔한 회귀 원인. PR template에 체크리스트 포함 권장.
- **한국어 브랜치명**: `feature/로그인` 가능하지만 일부 CI/툴 지원 부족 — 영문 kebab-case 권장.
- **commit 접두사 대소문자**: `[F/D]` 와 `[f/d]` 는 다른 것으로 처리. 메모리 사양 따라 소문자 통일.

## 관련 자산

- `validators/git_flow.py` — 브랜치/커밋 lint
- `tests/test_git_flow.py` — validator 테스트
- `pre_tool/guard.py` — 라이브 차단/경고
- 회사별 git 컨벤션: 사용자 메모리 (`feedback_git_convention.md` 등)에 출처 기록
- `harness-git-master` 에이전트 — 일반 atomic commit + 스타일 매칭 (회사 prefix 자동 감지)
