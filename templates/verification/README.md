# Verification Template — 자가-감사 3-tier Backbone

> **목적**: 새 프로젝트 시작 시 즉시 도입 가능한 자가-감사 frame. 회귀 0 보장 + 매 sub-task의 변형 선정 + 정량 평가 + 5 Gates audit이 3-tier로 협력 작동.
>
> **검증 출처**: `/home/user/example_project-analysis/.claude/requirements/VERIFICATION.md` (675 LOC, 5 Gates + §1~§12, 15 도메인 × 420 셀, 시스템 평균 4.555). 47-step 동안 living backbone으로 작동 검증.

---

## 자가-감사 3-tier 구조

```
┌──────────────────────────────────────────────────────────┐
│  Tier 1: PATTERNS — abstraction-first.md 스킬             │
│           (16 변형 / 의사결정 트리 / 안티패턴 매트릭스)   │
│           → "어떤 변형으로 만들 것인가" (Designer/E1)     │
└──────────────────────────────────────────────────────────┘
                          ↓ 변형 선정
┌──────────────────────────────────────────────────────────┐
│  Tier 2: SCORING — iso25010-scoring.md 스킬               │
│           (28 sub × 9 카테고리 / 1·3·5 anchor / ±0.5)     │
│           → "얼마나 잘 만들었는가" (Evaluator/E2)          │
└──────────────────────────────────────────────────────────┘
                          ↓ 정량 평가
┌──────────────────────────────────────────────────────────┐
│  Tier 3: VERIFICATION — 본 template                       │
│           (5 Gates + 매트릭스 + audit 결과)               │
│           → "spec과 매핑되는가" (Designer 검증/E1 final)  │
└──────────────────────────────────────────────────────────┘
                          ↓ Gate 결과
                  audit report (audit-matrix.md)
                          ↓ 새 변형 발견 또는 anti-pattern 적용
                          → 본 backbone 자체 갱신 (living)
```

본 3-tier는 CLAUDE.md DGE (Designer-Generator-Evaluator) 원칙의 실행 도구 일습. negative space (repeat-error-tracker.md) 스킬과 cross-reference로 통합.

---

## 디렉토리 구조

```
<프로젝트>/.claude/requirements/
├── VERIFICATION.md          (본 template의 README 채용 + 5 Gates audit 결과)
├── audit-matrix.md          (audit-matrix-template.md 채용 + N 도메인 × 28 sub 점수)
├── SCORING-RUBRIC.md        (`~/.claude/skills/_common/iso25010-scoring.md` 인용 또는 복사 + 운영자 조정)
├── PATTERNS-CATALOG.md      (`~/.claude/skills/_common/abstraction-first.md` 인용 또는 변형 추가 시 분리)
├── changelog.md             (3-tier 갱신 이력)
└── domain/                  (PRD 도메인 파일)
```

본 template (~/.claude/templates/verification/)은 위의 3 파일 (`VERIFICATION.md` / `audit-matrix.md` / 임시 gates 명세)에 대한 빈 frame 제공.

---

## 사용 절차

### Phase 1 — 초기 도입 (새 프로젝트)
1. `cp -r ~/.claude/templates/verification/ <프로젝트>/.claude/requirements/_verification/` (또는 직접 복사)
2. `README.md` → `<프로젝트>/.claude/requirements/VERIFICATION.md`로 rename
3. `gates.md` 읽기 → 5 Gates 사용법 lock
4. `audit-matrix-template.md` → `audit-matrix.md`로 rename + 도메인 N개 행 + 28 sub-attribute 열로 채우기

### Phase 2 — sub-task 별 운용 (매 step)
1. **선정**: abstraction-first.md 의사결정 트리로 V1~V16 변형 매칭 (또는 integration step 승격)
2. **구현**: 신규 모듈/crate 또는 monolith 진입 case별 회귀 감쇄 패턴 (E1)
3. **평가**: iso25010-scoring.md로 단축 평가 (5~6 sub) → 4.5+ 자율 선정
4. **audit**: 본 template의 5 Gates 적용 (gates.md §1~§5)
5. **매트릭스 갱신**: audit-matrix.md의 해당 도메인 row + sub 점수 update

### Phase 3 — 갱신 트리거 (living)
다음 이벤트 시 본 backbone 자체 갱신:

| 트리거 | 갱신 대상 |
|---|---|
| 새 abstraction-first 변형 발견 | PATTERNS-CATALOG에 V17, V18, ... 추가 + audit-matrix 신규 column |
| integration step 첫 발생 | PATTERNS-CATALOG 안티패턴 매트릭스 + repeat-error-tracker E10, E11 추가 |
| 시스템 점수 unlock 변형 (V9 type) | VERIFICATION §시스템 점수 변동 표 + audit-matrix update |
| 도메인 추가 | audit-matrix의 row 추가 + 28 sub 평가 + 일관성 ±0.5 self-check |

---

## 5 Gates 요약 (자세한 명세는 `gates.md`)

| Gate | 항목 | 자동화 |
|---|---|---|
| 1 | 금지어 검사 (적절한 / 충분한 / 빠르게 / 효율적으로 / 처리한다 / 관리한다 / ~할 수 있다 / 등 / 기타) | grep 패턴 명시 |
| 2 | 페르소나 ↔ US `AS` 역할 추적성 | manual + alias 매핑 |
| 3 | SSOT 일관성 (도메인 ↔ architecture/glossary/notification) | manual + cross-reference grep |
| 4 | 에러 AC 쌍 (성공+에러 AC 동시 작성) | spot-check 또는 enumeration |
| 5 | Non-Goals 3종 세트 (제외 / 사유 / 재검토 트리거) | manual + 정량 트리거 검증 |

각 Gate는 PASS / FLAG / FAIL 3 단계.

---

## 짝 스킬 (peer)

본 template는 다음 글로벌 스킬과 작동:

| 스킬 | 역할 |
|---|---|
| `~/.claude/skills/_common/abstraction-first.md` | Tier 1 (PATTERNS 변형 선정) |
| `~/.claude/skills/_common/iso25010-scoring.md` | Tier 2 (SCORING 28-sub 평가) |
| `~/.claude/skills/_common/repeat-error-tracker.md` | negative space (9 entry + anti-pattern matrix) |
| `~/.claude/skills/_common/doc-verify.md` | 본 template의 Gate 1/2/3 자동 검증 |
| `~/.claude/skills/_common/verification-before-completion.md` | sub-task closure 시 5 Gates 강제 |

---

## Self-improvement loop (CLAUDE.md 2원칙)

본 template는 **living backbone**:
1. **신규 Gate 발견** (예: Gate 6 license audit / Gate 7 security CVE) → `gates.md` 확장
2. **신규 sub-attribute 발견** (운영자 특성 차이) → `audit-matrix-template.md` 확장 + iso25010-scoring §5 조정 포인트 갱신
3. **3-tier 협력 흐름 보완** (예: Tier 4 자동 회귀 측정) → 본 README 다이어그램 갱신

---

## Gotchas

### 3-tier 중 한 tier만 운용
PATTERNS만 운용 → 회귀 0 보장 안 됨 (점수 측정 부재). SCORING만 운용 → 변형 선정 약함 (high risk integration step 무방비). 셋 모두 협력해야 backbone.

### audit-matrix를 N×9 카테고리 view만 작성
9 카테고리는 derived. 직접 평가 셀은 N×28 sub. 9 view만 작성하면 일관성 self-check 불가 — 매트릭스는 항상 N×28.

### Living backbone을 frozen reference로 오용
새 변형 / 새 anti-pattern 발견 시 본 backbone 자체를 갱신 안 하면 stale. 매 sub-task 후 변경 후보 확인.

### 본 template와 글로벌 스킬의 evidence 분리
본 template은 evidence 빈 frame. 실제 점수 / commit SHA / 회귀 결과는 `<프로젝트>/.claude/requirements/VERIFICATION.md`에. 본 template는 frame만 lock.

---

## 출처 인용

| 출처 | 위치 |
|---|---|
| 분석 폴더 VERIFICATION | `/home/user/example_project-analysis/.claude/requirements/VERIFICATION.md` (675 LOC, 5 Gates + §1~§12, 15 × 420 cells) |
| SCORING-RUBRIC | `.claude/requirements/SCORING-RUBRIC.md` (28 sub × 1·3·5 anchor) |
| PATTERNS-CATALOG | `.claude/requirements/PATTERNS-CATALOG.md` (16 변형 / 33 applications) |
| 3-tier 검증 commit | `[impl-7]` (SCORING-RUBRIC 신규) + `[impl-31]` (PATTERNS-CATALOG 신규) + `[impl-32]` (VERIFICATION §11 자가-감사 3-tier 완성) |
| AUTOPILOT-PLAN §3 H4 | `synthesis/AUTOPILOT-PLAN.md` (본 template의 의도 lock) |
