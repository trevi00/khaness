---
name: self-improve
description: Evolutionary code improvement engine — tournament selection of N parallel experiments per iteration, with benchmark validation and git worktree isolation.
keywords: [self-improve, tournament, evolution, iterate, benchmark, optimize]
intent: [optimize, improve, evolve, benchmark-driven]
phase: implement
min_score: 4
---

# Self-Improve

**Autonomous evolutionary code improvement**. 매 iteration마다 N개 병렬 실험, benchmark로 평가, tournament selection으로 승자 merge, worktree로 격리.

## 자율 실행 정책

**루프 중 사용자에게 묻지 마라**. Gate 통과 후 loop 시작되면 stop condition 도달까지 완전 자율.

- iteration 간/단계 간 확인 요청 금지
- 에이전트 실패 시: 1회 retry, 그래도 실패면 skip + 로그
- 모든 plan 거부 시: 로그, 다음 iteration 자동 진행
- Benchmark 에러: 해당 executor 실패로 마크, 다른 executor 계속
- **Stop condition만 루프 종료**
- **Trust**: 사용자가 setup 시 repo 경로 + benchmark 명령 명시 확인. loop는 패키지 설치나 시스템 설정 수정 안 함.
- **Sealed files**: `validate.sh`가 benchmark 코드 수정 방지 (self-modification 방어).

## State 추적

```
<project>/.harness/self-improve/<topic-slug>/
├── config/                  — 사용자 설정
│   ├── settings.json        — agents, benchmark, thresholds, sealed_files
│   ├── goal.md              — 개선 목표 + 타겟 메트릭
│   ├── harness.md           — 가드레일 규칙 (H001/H002/H003)
│   └── idea.md              — 사용자 실험 아이디어
├── state/                   — 런타임 상태
│   ├── agent-settings.json  — iterations, best_score, status, counters
│   ├── iteration_state.json — iteration 내 진행 (재개성)
│   ├── research_briefs/
│   ├── iteration_history/
│   ├── merge_reports/
│   └── plan_archive/
├── plans/                   — 현재 round 활성 plan
└── tracking/                — 시각화 데이터
    ├── raw_data.json
    ├── baseline.json
    ├── events.json
    └── progress.png
```

## 에이전트 매핑

| Step | 역할 | 에이전트 | 모델 |
|------|------|----------|------|
| Research | 코드베이스 분석 + 가설 생성 | general-purpose | opus |
| Planning | 가설 → 구조화 plan | harness-planner | opus |
| Arch Review | 6-point plan review | harness-architect | opus |
| Critic Review | Harness 규칙 강제 | harness-critic | opus |
| Execution | plan 구현 + benchmark | kha-executor | opus |
| Git Ops | 원자적 merge/tag/PR | harness-git-master | sonnet |

## Setup Phase

1. Target repo 경로 확인.
2. `<root>/` 디렉토리 구조 생성 (`templates/`에서 `config/`로 복사).
3. `settings.json`의 `trust_confirmed` 체크.
4. **Trust 확인** (강제):
   - `"Self-improve will run benchmark commands inside {repo}. Confirm? [yes/no]"`
   - 거부 시 abort. 승인 시 `trust_confirmed: true` 기록.
5. goal 미설정 → Socratic 인터뷰 (Objective, Metric, Target, Scope).
6. benchmark 미설정 → benchmark builder agent가 설문/wrap/validate 3x + baseline.
7. harness 규칙 확인 (H001/H002/H003 기본).
8. **Gate**: goal, benchmark, harness, trust 모두 true.
9. 개선 브랜치 생성: `git checkout -b improve/<goal_slug> <target_branch>`
10. 모드 배타: autopilot/ralph/ultrawork 활성이면 거부.

## 개선 루프

### Step 0 — Stale Worktree Cleanup (매 iteration 필수)

```bash
git -C <repo> worktree list
# 현 iteration 소속 아닌 worktrees/round_* 는 --force remove
git -C <repo> worktree prune
```

### Step 1 — State refresh
### Step 2 — Stop request 체크
### Step 3 — 사용자 idea 체크 (`idea.md`)

### Step 4 — Research
`general-purpose` agent(opus). iteration, repo 경로, goal.md, iteration_history, research_briefs 전달. 출력: JSON brief → `research_briefs/round_{n}.json`.

### Step 5 — Plan (병렬 N개)
`harness-planner`(opus) N개 병렬. 각각 planner identity, research brief, history, harness 규칙, data contract 전달. 출력: `plans/round_{n}/plan_planner_{id}.json`.

### Step 6 — Review (순차)

**6a. Architecture Review**: `harness-architect` + 6-point checklist.
1. Testability — 가설 검증 가능?
2. Novelty — 이전 시도와 다름?
3. Scope — 적절 크기?
4. Target files — 존재하고 sealed 아님?
5. Implementation clarity — executor가 추측 없이 구현 가능?
6. Expected outcome — 증거 기반 현실적?

Architect 판결은 **advisory only**.

**6b. Critic Review**: `harness-critic` + harness 규칙:
- H001: exactly one hypothesis (0/복수 거부)
- H002: approach_family 연속 3회 반복 금지
- H003: round 내 다양성 (같은 family 2개 금지)
- Data contract 스키마 검증
- History awareness 체크

`critic_approved: true/false`. false는 실행 제외.

전체 거부 시 Step 9로.

### Step 7 — Execute (병렬, 승인된 plan별)

**Worktree 생성**:
```
git worktree add worktrees/round_{n}_executor_{id} -b experiment/round_{n}_executor_{id} improve/<goal>
```

`kha-executor`(opus): plan JSON, worktree 경로, benchmark 명령, sealed_files, `validate.sh` 경로, Benchmark Result 스키마. 출력: Benchmark Result JSON.

### Step 8 — Tournament Selection

**Pre-merge safety (mandatory)**:
- `git status --porcelain` empty (clean tree). Non-empty → abort iteration with `aborted_dirty_tree`; never auto-stash.
- Snapshot tag `improve-snapshot-{round_n}` on the current HEAD before any merge (`git tag improve-snapshot-{n}`). Required for non-destructive rollback.

1. 결과 수집
2. `status: "success"` 만 필터링. 0개면 Step 9.
3. `benchmark_score`로 랭크 (`benchmark_direction` 존중)
4. **Ranked-candidate loop** (최상위부터):
   a. No-regression 체크: score가 best를 개선/유지 (방향 존중)
   b. `harness-git-master`로 merge `--no-ff`
   c. Merged 상태에서 re-benchmark
   d. 확인되면 winner 수락, break
   e. 회귀면 `git reset --merge improve-snapshot-{n}` (snapshot tag 기준 비파괴 복구; reflog 살아있음) 후 다음 candidate. `git reset --hard`는 사용 금지.
   f. Merge conflict면 `git merge --abort` 후 다음 candidate
5. Winner publication — **default off**. `auto_push` 기본값 `false`. push는 다음 3 조건 모두 충족 시에만:
   - `auto_push: true` 명시
   - `git status --porcelain` clean
   - `git fetch origin` + `git rev-parse origin/improve/<goal>` 비교 (remote snapshot 일치, force push 회피)
   조건 미충족이면 push 건너뛰고 `winner_unpublished`로 보고; 사용자가 수동 `/kha-submit-pr` 또는 `git push` 결정.
6. Non-winner 브랜치 archive (tag + delete)
7. Merge report JSON → `merge_reports/round_{n}.json`

### Step 9 — Record & Visualize
- iteration history 작성 → `iteration_history/round_{n}.json`
- `agent-settings.json` 업데이트 (iterations, best_score, plateau_count, circuit_breaker_count)
- `tracking/raw_data.json`에 candidate 하나당 entry append
- plot 생성

### Step 10 — Cleanup

```bash
git worktree remove worktrees/round_{n}_executor_{id} --force
git worktree prune
```

### Step 11 — Stop Condition

ANY true면 종료:
| 조건 | 체크 |
|------|------|
| User stop | `status: "user_stopped"` |
| Target reached | `best_score`가 `target_value` 도달 |
| Plateau | `plateau_consecutive_count >= plateau_window` |
| Max iterations | `iterations >= max_iterations` |
| Circuit breaker | `circuit_breaker_count >= circuit_breaker_threshold` |

없으면 Step 1으로.

## Approach Family Taxonomy

모든 plan에 하나 태그:
- `architecture` — 모델/컴포넌트 구조
- `training_config` — optimizer, LR, scheduler, batch
- `data` — 데이터 로딩/증강/전처리
- `infrastructure` — mixed precision, distributed, compiled kernels
- `optimization` — 알고리즘/수치 최적화
- `testing` — 평가 방법론 변경
- `documentation` — 문서만
- `other` — 위에 맞지 않음 (evidence에 설명)

## Gotchas

- **Sealed files 무시**: `validate.sh`가 benchmark 코드 수정 차단. sealed 파일 목록 정확하게.
- **Benchmark reproducibility 부족**: 3x validation + baseline 기록 필수. 단일 측정은 neutral.
- **Worktree 누수**: iteration 중단 시 orphan worktree. Step 0이 매번 정리해야.
- **Merge 후 regression**: re-benchmark로 확인. 모든 후보가 재검증 후 회귀면 스킵 (fake winner 방지).
- **Approach family 고착 (H002)**: 같은 family 3회 연속 금지. 다양성이 진화의 핵심.
- **`--auto-push` on public repo**: 실험 브랜치가 공개 push되면 리뷰 혼란. 사용자 확인 후 on.
