---
keywords: 계획 설계 맥락 시방서 체크리스트 공정표 진행 상황 현황 정리 문서 기억
intent: 컨텍스트정리해 진행상황파악해 이어서 핸드오프해 정리해 문서정리해 컨텍스트해
paths: .claude/plan.md .claude/checklist.md .claude/context.md
patterns: plan.md checklist.md context.md handoff
requires:
phase: plan review
min_score: 3
---

# 프로젝트 컨텍스트 문서 관리 가이드

## 의사결정 트리

### IF 새 프로젝트/기능 시작 (Plan)
1. `.claude/plan.md` 작성 → 전체 목표, 아키텍처, 기술 스택
2. `.claude/checklist.md` 작성 → 할 일 목록, 우선순위
3. `.claude/context.md` 작성 → 현재 상황, 결정 사항

### IF 작업 이어서 진행 (Implement)
1. `.claude/context.md` 읽기 → 현재 상황 파악
2. `.claude/checklist.md` 읽기 → 다음 할 일 확인
3. 작업 후 두 문서 업데이트

### IF 작업 중단/마무리 (Review)
1. `.claude/context.md` 업데이트 → 마지막 작업, 다음 단계
2. `.claude/checklist.md` 업데이트 → 완료 항목 체크, 새 항목
3. 알려진 이슈/워크어라운드 기록

## 문서 위치와 역할
```
<프로젝트>/.claude/
  plan.md       ← "무엇을 만들 것인가" (목표, 아키텍처, 기술 스택)
  context.md    ← "현재 어디에 있는가" (진행 중인 작업, 결정 사항, 이슈)
  checklist.md  ← "무엇이 남았는가" (할 일 목록, 우선순위, 블로커)
```

## 작성 규칙
1. **간결하게**: 각 문서 200줄 이하
2. **최신 상태**: 완료된 작업 즉시 반영
3. **컨텍스트 독립적**: 대화 기록 없이 이 문서만으로 상황 파악 가능
4. **날짜 표기**: 주요 변경에 YYYY-MM-DD 기록
5. **구체적으로**: "UI 수정" 대신 "로그인 폼 유효성 검사 추가"

## Gotchas

### 문서가 너무 길어짐
컨텍스트 문서가 길어지면 Claude가 핵심을 놓침. 완료된 항목은 주기적으로 정리하고 현재 진행 중인 것만 남길 것.

### 상대 날짜 사용
"어제", "다음 주"는 시간이 지나면 무의미. 항상 절대 날짜(2026-03-18) 사용.

### plan.md 미업데이트
구현 중 계획이 바뀌었는데 plan.md를 안 고치면 다음 세션에서 Claude가 구 계획을 따름. 방향 변경 시 즉시 반영.

### checklist.md 항목 폭주
체크리스트에 세부 작업을 너무 많이 넣으면 관리 불가. 최상위는 10개 이내로 유지하고 세부사항은 하위 항목으로.

## 도구 사용 패턴 (Harness)
- 문서 확인: `Read`로 plan.md, context.md, checklist.md 동시 읽기 (병렬 호출)
- 문서 업데이트: `Edit`으로 변경 부분만 수정 (Write로 전체 덮어쓰기 금지 — 다른 내용 손실 위험)
- 진행 상황 기록: 절대 날짜(YYYY-MM-DD)와 구체적 내용으로

## 에러 복구 패턴 (Harness)
- 문서 충돌 (Edit 실패) → `Read`로 최신 내용 다시 확인
- 내용 불일치 → `Edit`으로 정확한 old_string 기반 병합
- 변경 이력 필요 → `Bash(git diff)`로 최근 변경 확인, 누가 언제 수정했는지 파악
