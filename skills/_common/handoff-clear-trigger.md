---
name: handoff-clear-trigger
description: /clear 의무 트리거 + HANDOFF 절대경로 명시 + 다음 세션 진입 prompt 3-tier 작성 가이드 — 모든 프로젝트 자율 cycle 세션 종결 시 필수 protocol
keywords: handoff clear 세션 핸드오프 진입 prompt 트리거 안전선 cycle
intent: 종결해 마무리해 핸드오프 작성해 진입해 이어서
paths: HANDOFF.md
patterns:
requires: repeat-error-tracker abstraction-first responsibility-recovery-protocol
phase: plan review deploy
tech-stack: any
min_score: 1
---

# HANDOFF /clear 트리거 + 진입 prompt protocol

> 원칙: **자율 cycle은 안전선이 있다** — 무한 누적 시 의사결정 품질이 급격히 하락. /clear 의무 조건을 정형화하고, 다음 세션 자율 진입을 위한 prompt를 HANDOFF.md에 미리 lock해두면 회복 비용 0.
>
> Evidence: 분석 폴더 `example_project-analysis` impl-104 (v13.7) / impl-122 (v13.11) / impl-138 (v14.8) 안전선 초과 cycle 3회 검증 결과 — 한 세션 20-30 iter 임계점에서 컨텍스트 누적이 의사결정 quality에 비선형 영향.

## 의사결정 트리

### IF 자율 cycle 종결 시점 (Review)

cycle 종결 시 아래 5개 트리거 중 **1개 이상 충족하면 `/clear` 의무**. 위반 시 다음 cycle의 의사결정 품질 회귀 위험.

| 트리거 | 조건 | 검출 방법 |
|---|---|---|
| **A. autopilot iter 누적** | 한 세션 atomic commit ≥ 20회 | `git log --oneline --since="<session-start>" | wc -l` |
| **B. 안전선 ~0 명시** | HANDOFF top에 `안전선 ~0` 발화 | HANDOFF 작성 시 자가 판단 |
| **C. 큰 결정 직후** | `/harness-debate` 수렴 / V19 적용 / 패턴 정식 승격 / 5축 axis 완성 같은 inflection point cycle | debate sid 발화 + ontology_snapshot 변경 |
| **D. Stop hook 책임 회수 cycle 종결** | Stop hook 경고 직접 후속한 cycle 완료 | `responsibility-recovery-protocol` 스킬 5-step 종료 |
| **E. 안전선 검증 실패** | 같은 세션 cycle 2개 이상 + cohesion 분리 실패 (atomic 깨짐) | V19 anti-pattern (a) 발화 |

### IF HANDOFF.md 작성 시 (Plan)

1. **절대경로 명시 의무** — 본 HANDOFF의 위치를 절대경로로 첫 callout에 명시. multi-repo 프로젝트의 경우 분석/외부/글로벌 3-way 구분 표 함께 작성.
2. **`/clear` 의무 트리거 표** — 위 5종 표를 HANDOFF top entry 직후에 삽입 (또는 본 스킬 cross-ref).
3. **진입 prompt 3-tier** — 다음 세션 자율 진입을 위한 prompt 3종:
   - **1순위 prompt** (명시적): 가장 가치 있는 다음 step + 사전 정찰 후보 + 적용 조건 + 패턴 가이드
   - **Fallback prompts** (옵션 2~5): 대안 cycle 후보들
   - **트리거 키워드** (최소 입력): 절대경로 1줄로 자율 판단 진입 — 단 명시 prompt 권고
4. **Reference commits 명시** — 직전 cycle의 외부 + 분석 + 글로벌 commit SHA 일습 (자율 진입 시 cross-ref 가능)

### IF 다음 세션 진입 시 (Plan)

1. `/clear` 직후 첫 메시지로 **절대경로 명시된 prompt** 복사 — 상대 경로 또는 path 누락 시 잘못된 HANDOFF read 또는 read fail 위험.
2. HANDOFF top entry 읽고 직전 cycle 결과 흡수 → "다음 세션 1순위 후보" lock된 옵션 중 자율 선택.
3. 1순위 prompt가 명시적이면 그대로 진행. 사용자가 옵션 지정 시 그것을 우선.

## HANDOFF 경로 명시 templates

### multi-repo 프로젝트 (분석 + 외부 + 글로벌 3-way)

```markdown
> 📍 **본 HANDOFF 경로 (단일 source-of-truth)**: `{프로젝트}/HANDOFF.md`
> - **분석 repo** = `{프로젝트}/` (HANDOFF.md + .claude/requirements/ SSOT — 본 파일 owner)
> - **외부 repo** = `{외부 코드 경로}/` (실집행 대상 — HANDOFF 없음, 모든 cross-ref는 분석 HANDOFF가 owns)
> - **글로벌 repo** = `~/.claude/` (글로벌 스킬 SSOT — HANDOFF 없음)
```

### 단일 repo 프로젝트

```markdown
> 📍 **본 HANDOFF 경로**: `{프로젝트}/HANDOFF.md` (절대경로)
> CLAUDE.md "HANDOFF 규칙" §1: HANDOFF.md는 반드시 프로젝트 루트, 전역 `~/`에 만들지 않는다.
```

## 진입 prompt 작성 template

```markdown
## 다음 세션 진입 prompt (복사용, v{VERSION})

> 📍 HANDOFF 경로 (모든 prompt 공통): `{프로젝트}/HANDOFF.md`

### 진입 prompt 1순위 — {핵심 다음 step 한 줄}

`/clear` 직후 아래 prompt를 복사:

\`\`\`
# 자율 진입 — v{VERSION} 종결 결과 흡수 + 자율 다음 step
{프로젝트}/HANDOFF.md 읽고 이어서 진행해줘

# 명시: {1순위 step} — 우선순위 1
{사전 정찰 4-5 후보}
{적용 조건 3-5개}
{re-use 가이드 (byte-equivalent / template / 동형 cycle 참조)}

# Fallback 1: {대안 1}
# Fallback 2: {대안 2}
...

# Reference: external + analysis + global commits ({직전 cycle})
{SHA1} {1줄 설명}
{SHA2} {1줄 설명}
...
\`\`\`

### 진입 prompt 트리거 키워드 (최소 입력)

\`\`\`
{프로젝트}/HANDOFF.md 읽고 이어서 진행해줘
\`\`\`

이 한 줄만으로도 HANDOFF top entry의 "다음 세션 1순위 후보"를 자율 판단하여 진입. 단, **명시 prompt 권고** (의도 정확도 높음).

#### 절대경로 누락 시 위험
`HANDOFF.md 읽고 이어서 진행해줘` (상대 path 또는 path 없음) → 현재 워킹 디렉토리에 HANDOFF.md 있으면 그걸 read (잘못된 HANDOFF), 없으면 read fail.
```

## Gotchas

### `/clear` 트리거 누적 무시
A+C+D 동시 충족인데 한 세션 더 끌면 의사결정 quality 급격히 하락. impl-104 (v13.7) 19 iter / impl-122 (v13.11) 14 iter 두 evidence는 안전선 안에서 자율 종결로 회복 검증. 30 iter 초과는 평균적으로 회복 불능 (cycle 재시작 강제).

### `/clear` 후 첫 prompt에서 절대경로 누락
git bash / PowerShell / cmd / Cursor 각 워킹 디렉토리가 다름. 절대경로 없으면 어떤 HANDOFF를 read할지 불확정. 항상 `{프로젝트}/HANDOFF.md 읽고 이어서 진행해줘` (절대경로).

### HANDOFF 진입 prompt 1순위가 prose만 (사전 정찰 없음)
"다음에 X 진행해줘"만 적으면 다음 세션이 X의 corpus / 적용 조건 / re-use template을 처음부터 정찰 — 비용 큼. 1순위 prompt는 반드시 (a) corpus 후보 (b) 적용 조건 (c) byte-equivalent template 가이드 포함.

### Reference commits 누락
직전 cycle의 외부 + 분석 + 글로벌 commit SHA를 prompt에 안 적으면 다음 세션이 직접 `git log` 정찰 → 컨텍스트 낭비. 1순위 prompt 끝에 commits 일습 명시.

### Fallback prompt 1개만 (체인 끊김)
1순위만 적고 Fallback 0이면 1순위가 BLOCK 발화 시 다음 cycle 막힘. Fallback ≥ 2개 권고.

### 진입 prompt를 매 cycle 새로 작성
template은 본 스킬의 `진입 prompt 작성 template`을 그대로 재사용. 매번 새로 작성하면 누락 항목 발생. version 번호만 +1하고 1순위 / Fallback / Reference만 갱신.

### `/clear` 트리거 표를 HANDOFF에 매번 풀로 복사
본 스킬이 글로벌이므로 HANDOFF에서는 cross-ref만 (`~/.claude/skills/_common/handoff-clear-trigger.md` 참조)하고 본 cycle의 어떤 트리거가 충족됐는지만 명시. 풀 복사는 중복 + 갱신 곤란.

### CLAUDE.md "HANDOFF 규칙"과 본 스킬의 책임 분리
CLAUDE.md §HANDOFF 규칙은 **위치 규칙만** (프로젝트 루트, 전역 ~/에 만들지 않는다, 진입 메시지 형식). 본 스킬은 **자율 cycle 종결 protocol** (트리거 + 진입 prompt + 회귀 방지). 두 곳에 중복 명시 금지 — 본 스킬이 owner, CLAUDE.md는 1줄 cross-ref만.
