---
name: finishing-a-development-branch
description: Complete development work by verifying tests, presenting 4 structured options (merge/PR/keep/discard), and handling chosen workflow with worktree cleanup.
keywords: [finish-branch, merge, pull-request, worktree-cleanup, 브랜치마감, 병합, 피알, 작업완료]
intent: [finish, merge, create-pr, discard-branch]
phase: deploy
min_score: 2
---

# Finishing a Development Branch

> 원본: superpowers (MIT, Jesse Vincent). 회사 Git 컨벤션 (memory `feedback_git_convention.md`)과 충돌 시 회사 컨벤션 우선.

**핵심 원칙**: Verify tests → Present options → Execute choice → Clean up.

**시작 시 선언**: "finishing-a-development-branch 스킬로 작업을 마감합니다."

## 의사결정 트리

### IF 구현 완료 + 테스트 통과 후 통합 방법 결정 필요 (Deploy)

```
Step 1: 테스트 검증 (필수)
  ├─ FAIL → 중단, fix 먼저
  └─ PASS → Step 2

Step 2: Base 브랜치 판정
  └─ git merge-base HEAD main / master / develop

Step 3: 4 옵션 제시
  1) Merge locally
  2) Push + PR
  3) Keep as-is
  4) Discard

Step 4: 선택 실행

Step 5: Worktree cleanup (옵션 1, 2, 4에서만)
```

## Step 1: 테스트 검증

**옵션 제시 전에 테스트 통과 확인**:

```bash
# 프로젝트 test suite 실행
npm test / cargo test / pytest / ./gradlew test
```

**테스트 FAIL 시**:
```
테스트 실패 (<N>개). 완료 전 fix 필수:

[실패 표시]

테스트 pass까지 merge/PR 불가.
```

**중단. Step 2 진행 금지.**

**PASS 시**: Step 2로.

## Step 2: Base 브랜치 판정

```bash
git merge-base HEAD main 2>/dev/null \
  || git merge-base HEAD master 2>/dev/null \
  || git merge-base HEAD develop 2>/dev/null
```

또는 직접 질문: "이 브랜치는 `main`에서 분기했습니다 — 맞나요?"

**회사 관례** (memory `feedback_git_convention.md`): develop 기본, `feature/*`, `fix/*` prefix.

## Step 3: 4 옵션 제시

**정확히 이 4개** 제시:

```
구현 완료. 어떻게 진행할까요?

1. <base-branch>로 로컬 merge
2. Push하고 Pull Request 생성
3. 브랜치 유지 (나중에 처리)
4. 작업 폐기

어느 옵션?
```

**설명 추가 금지** — 옵션만 간결하게.

## Step 4: 선택 실행

### Option 1: Merge Locally

```bash
git checkout <base-branch>
git pull
git merge <feature-branch>

# Merge 결과에서 테스트 재실행
<test command>

# 통과 시 feature 브랜치 삭제
git branch -d <feature-branch>
```

→ Step 5 worktree cleanup

### Option 2: Push + PR

```bash
git push -u origin <feature-branch>

gh pr create --title "<title>" --body "$(cat <<'EOF'
## Summary
<2-3 bullets of what changed>

## Test Plan
- [ ] <verification steps>
EOF
)"
```

→ Step 5 worktree cleanup (worktree는 유지, PR open이므로)

**회사 컨벤션**: PR 생성 후 reviewer 지정, 라벨 부착 (memory `feedback_git_convention.md` 참조).

### Option 3: Keep As-Is

Report: "브랜치 <name> 유지. Worktree `<path>`에 보존됨."

**Worktree cleanup 안 함.**

### Option 4: Discard

**먼저 확인**:
```
다음이 영구 삭제됩니다:
- 브랜치 <name>
- 모든 commit: <commit-list>
- Worktree at <path>

확인하려면 'discard' 입력.
```

정확한 확인 대기.

확인되면:
```bash
git checkout <base-branch>
git branch -D <feature-branch>
```

→ Step 5 worktree cleanup

## Step 5: Worktree Cleanup

**Option 1, 2, 4용**:

Worktree 안에 있는지 체크:
```bash
git worktree list | grep $(git branch --show-current)
```

있으면:
```bash
git worktree remove <worktree-path>
```

**Option 3**: worktree 유지.

## Quick Reference

| 옵션 | Merge | Push | Worktree 유지 | 브랜치 삭제 |
|---|:-:|:-:|:-:|:-:|
| 1. Merge locally | ✓ | — | — | ✓ |
| 2. Create PR | — | ✓ | ✓ | — |
| 3. Keep as-is | — | — | ✓ | — |
| 4. Discard | — | — | — | ✓ (force) |

## Common Mistakes

### 테스트 검증 skip
- **문제**: 깨진 코드를 merge, failing PR 생성
- **Fix**: 옵션 제시 전 항상 테스트 검증

### Open-ended 질문
- **문제**: "다음 뭐 할까요?" → 모호
- **Fix**: 정확히 4개 structured 옵션

### 자동 worktree cleanup
- **문제**: 필요할 수 있는 worktree 제거 (Option 2, 3)
- **Fix**: Option 1, 4에서만 cleanup

### Discard 확인 없음
- **문제**: 작업 실수로 삭제
- **Fix**: 'discard' 타이핑 확인 요구

## Red Flags

**절대**:
- 실패 테스트로 진행
- 결과 테스트 검증 없이 merge
- 확인 없이 작업 삭제
- 명시 요청 없이 force-push

**항상**:
- 옵션 제시 전 테스트 검증
- 정확히 4 옵션
- Option 4에 타이핑 확인
- Option 1, 4만 worktree cleanup

## 하네스 통합

- **subagent-driven-development (DGE)** Step 7 — 모든 task 완료 후 호출
- **/harness-autopilot** Phase 5 — 모든 batch 완료 후 호출
- **harness-git-master 에이전트** — commit splitting / style 매칭 담당
- **회사 Git 컨벤션** (memory `feedback_git_convention.md`):
  - 브랜치: develop 기본
  - prefix: `feature/`, `fix/`, `hotfix/`, `refactor/`, `chore/`
  - Commit: `feat:`, `fix:`, `refactor:`, `chore:`, `docs:`, `test:`
  - PR: `main`/`develop` target, reviewer 지정, CI 통과 후 merge

## 프로젝트 확장

프로젝트 고유 마감 체크리스트는 `<project>/.claude/finish-checklist.md`에. 이 스킬 수정 없이 Step 1 이후 자동 실행.

예시:
```markdown
# Finish Checklist

- [ ] CHANGELOG.md 업데이트
- [ ] 문서 예제 검증
- [ ] 스키마 변경 마이그레이션 준비
```

## Gotchas

- **테스트 없는 프로젝트**: "테스트 suite가 없습니다 — skip?" 사용자에게 먼저 물어라. 자동 skip 금지.
- **Merge 후 원격 push 잊음**: Option 1은 로컬 merge. 원격 반영은 별도 `git push`.
- **Feature 브랜치 삭제 후 복구 필요**: `git reflog`로 commit SHA 복구 후 `git branch <name> <sha>`.
- **PR 생성 시 template 무시**: gh pr create가 로컬 `.github/pull_request_template.md` 자동 로드. body 명시 시 template 덮어씀.
- **Worktree path에 공백**: Windows에서 흔함. `git worktree remove "<path>"` 따옴표 필수.

## Pairs With

- **using-git-worktrees** (우리 구현 예정): worktree 생성 → 이 스킬이 cleanup
- **requesting-code-review**: Option 2 선택 시 리뷰어 dispatch
- **verification-before-completion**: Step 1 테스트 검증의 메타 규율
