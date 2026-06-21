---
name: responsibility-recovery-protocol
description: Stop hook 책임 회피 경고 발화 시 5-step 회복 protocol — 원인 정찰 / 카테고리 분류 / 본 작업 인과 분석 / scope 분리 정당화 / 별도 cycle 후보 lock
keywords: stop hook 책임 회피 회수 pre-existing failure cycle scope
intent: 회수해 회복해 책임져 분류해 정찰해
paths: HANDOFF.md
patterns:
requires: handoff-clear-trigger repeat-error-tracker abstraction-first
phase: review debug
tech-stack: any
min_score: 1
---

# Stop hook 책임 회수 5-step protocol

> 원칙: **"pre-existing"으로 분류하는 순간 책임 회피로 해석된다** — Stop hook (또는 사용자)이 "원인을 조사하고 수정하세요. 기존 문제라 해도 범위 내라면 해결해야 합니다" 경고를 발하면, 단순 분류 회피가 아니라 **5-step 회복 protocol**로 답해야 한다.
>
> Evidence: `example_project-analysis` v14.9 → v14.10 cycle (impl-137 → impl-139). impl-137 verification 중 발견된 tools crate 11 failing tests를 단순 "pre-existing"으로 분류 → Stop hook 책임 회피 경고 발화 → 5-step 회복 protocol 실집행 → 카테고리 1 (7건) 완전 해소.

## 의사결정 트리

### IF Stop hook "책임 회피" 경고 발화 시 (Debug)

**5-step 회복 protocol** — 단순 사과/재분류 X. 5단계 모두 명시적으로 발화.

1. **원인 정찰 (Investigate)** — failure 1건씩 read + panic line + assertion shape 확인. log file을 Read tool로 정확히 직접 확인 (요약 X).
2. **카테고리 분류 (Categorize)** — failure를 N개 카테고리로 정렬. 같은 원인 cohesion 묶기. 단순 list 아닌 **원인 카테고리 트리**.
3. **본 작업 인과 분석 (Causal Analysis)** — 변경 영역 vs 실패 영역의 콜그래프 cohesion 검증. import / call 관계 0 확인. byte-identical baseline check (변경 도입 전후 failure set 동일성).
4. **scope 분리 정당화 (Scope Justification)** — 같은 commit에 묶지 않는 이유 명시 (V19 anti-pattern (a) "scope 외 변경을 같은 commit에 묶기 → atomic 깨짐, byte-identical 가드 위반" cross-ref). cohesion 분리해서 별도 cycle 권고.
5. **별도 cycle 후보 lock (Future Cycle Lock)** — HANDOFF에 "별도 cycle scope" + "다음 세션 1순위 후보"에 카테고리별 cycle 추가. 책임 회수 path 열어둠.

### IF 책임 회수 cycle 실집행 단계 (Implement)

5-step 후 자율 cycle로 진입 시:

1. 가장 작은 카테고리부터 fix (회귀 risk 최소화 cohesion 단위)
2. test-only fix가 가능하면 production 코드 변경 0 유지 (V19 anti-pattern (a) 준수)
3. fix 후 baseline 검증 set 회귀 0 확인 (cross-crate 영향 0)
4. atomic commit (책임 회수 evidence cross-ref) + HANDOFF marker v14.x → v14.(x+1)

### IF 회수 cycle 종결 후 (Review)

1. 카테고리 N개 중 처리한 카테고리 명시 + 잔여 카테고리 별도 cycle 후보 lock
2. `handoff-clear-trigger` 스킬 트리거 D ("Stop hook 책임 회수 cycle 종결") 충족 → 다음 작업 진입 전 `/clear`
3. 책임 회수 evidence를 `repeat-error-tracker`에 entry 추가 (재발 방지)

## 5-step protocol templates

### 1. 원인 정찰

```
{N}개 failure 각각의 panic line + assertion shape 직접 read.
- failure_1: line {X} — {assertion 본문}
- failure_2: line {Y} — {assertion 본문}
...
요약 X, 실 line 직접 인용.
```

### 2. 카테고리 분류

```markdown
**카테고리 1: {원인} ({N건})** — {failure list}
공통 형태: {pattern}. 원인: {evidence}.

**카테고리 2: {원인} ({M건})** — {failure list}
...

**카테고리 3: ...**
```

### 3. 본 작업 인과 분석

```
변경 영역 (impl-{X}): {파일} {함수/모듈}
실패 영역: {도메인 N개}
콜그래프 cohesion 검증:
  - {변경 영역} → {실패 영역} import: 0 / call: 0
  - byte-identical baseline check: impl-{X} 도입 전 {N passed; M failed} → 도입 후 {N+신규 passed; M failed} 동일성 확인

본 작업 인과 0 확정 — impl-{X}가 failure 야기 0.
```

### 4. scope 분리 정당화

```
V19 anti-pattern (a) cross-ref: "debate/cycle scope 외 변경을 같은 commit에 묶기 → atomic 깨짐, byte-identical 가드 위반".
{도메인 cohesion 분석}으로 별도 cycle scope 분리:
  - 본 cycle: {원래 scope}
  - 별도 cycle 후보: {failure 카테고리별}
```

### 5. 별도 cycle 후보 lock

```markdown
HANDOFF top entry / "다음 세션 1순위 후보"에 추가:
- **{카테고리} fix ({N건})** — {fix 후보 옵션 A/B/C}, {회귀 risk}, {작업량 LOC}
```

## Gotchas

### in-scope pre-existing를 "잔여(residual)"로 카탈로그 = 회피 (2-strike, debate-1780564679)
step 4-5(scope 분리 + 별도 cycle lock)는 변경 영역과 콜그래프 cohesion이 **0인 진짜 무관** 결함에만 적용된다. **편집 중인 파일/모듈 안의** pre-existing 결함은 scope 분리 대상이 아니라 **지금 같은 commit에서 고칠 대상**이다. "pre-existing이라 별도 cycle" 또는 "본 변경 무관"으로 residual list에 적으면 — 5-step을 돌았더라도 — 책임 회피로 재detect된다. **판별 질문**: (a) 내 변경이 그 결함을 newly reachable/relevant하게 만들었는가? (b) 그 파일을 이미 편집 중인가? → 둘 중 하나라도 예면 **in-scope → 같은 commit fix + 회귀 테스트**. Evidence: roadmap #3 E2-enforcement cycle — escalate-misrouting(decide_completion 'escalate'를 'iterate'처럼 advance_iter) + import-unsafe `sys.stdin.reconfigure`를 처음 "pre-existing residual"로 dismiss → **2회 연속** Stop hook 책임 회피 경고 → 둘 다 편집 중이던 `autopilot_continue.py` 내 in-scope로 재판정 → 같은 commit에서 fix(_terminal 라우팅 / callable-guard reconfigure) + 테스트. *내 D2 wiring이 escalate verdict를 그 게이트에 newly reachable하게 만든 것* 이 (a)의 결정적 신호였다.

### "pre-existing" 단순 분류는 즉시 회피 신호
`pre-existing failures이므로 본 작업과 무관`만 적으면 Stop hook 회피 패턴 100% detect. **반드시 5-step 본문**으로 답해야 회수 protocol 발화.

### 카테고리 분류 없이 단일 list
11 failures를 11줄 list로 나열하면 cohesion 분리 안 됨 → 별도 cycle 1개 = 또 atomic 깨짐. **반드시 N개 카테고리로 정렬** (원인별 cohesion).

### 콜그래프 cohesion 검증 누락
"본 작업과 무관"만 prose로 적으면 진짜 무관한지 확인 못함. **import / call grep 명시 + baseline byte-identical 확인** 필수.

### scope 분리를 V19 anti-pattern cross-ref 없이
"별도 cycle로 위임"만 적으면 왜 같은 commit에 안 묶는지 명시 안 됨. **V19 anti-pattern (a) 또는 `abstraction-first` cross-ref**로 정당화.

### 별도 cycle 후보 lock을 prose에만
HANDOFF에 prose로 "별도 cycle로 위임"만 적고 "다음 세션 1순위 후보" 표/list에 추가 안 하면 다음 세션이 절대 회수 안 함. **반드시 HANDOFF top entry "다음 세션 1순위 후보"에 카테고리별 cycle entry 추가**.

### 회수 cycle을 같은 세션에 무리하게 진행
Stop hook 경고 → 5-step protocol → 회수 cycle 1개 처리 정도가 안전선. 카테고리 N개 모두 같은 세션 처리는 안전선 위반 (`handoff-clear-trigger` 트리거 A 또는 E 발화 가능).

### 회수 cycle 후 `/clear` 안 함
회수 cycle은 큰 결정 직후 (트리거 C) + Stop hook 책임 회수 종결 (트리거 D) 동시 충족. **반드시 `/clear`** 권고.

### 책임 회수 evidence를 `repeat-error-tracker`에 안 적음
같은 종류 책임 회피 재발 가능. `repeat-error-tracker.md`에 본 회수 evidence entry 추가 (Hook 노이즈 식별 entry와 짝). 다음 세션이 자동 회피 가능.
