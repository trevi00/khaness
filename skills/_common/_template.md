---
name: skill-name
description: 한 문장 요약 — 이 스킬이 어떤 상황에 호출되는지 (skill matcher가 이 줄을 읽음)
keywords: keyword1 keyword2 키워드3
intent: 만들어 추가해 수정해 삭제해 설치해 설정해
paths: src/api src/routes
patterns: express flask django
requires: security testing
phase: plan implement review
tech-stack: any
min_score: 2
---

# 스킬 제목

## 의사결정 트리

### IF 조건1 (Plan)
1. 첫 번째 단계
2. 두 번째 단계
3. **→ 관련스킬 스킬: 참고할 내용**

### IF 조건2 (Implement)
1. 구현 단계
2. 확인 단계

### IF 조건3 (Review)
- [ ] 검토 항목 1
- [ ] 검토 항목 2

## 가이드

Claude가 이미 아는 일반 지식은 적지 않는다.
이 프로젝트/환경에 특화된 정보만 기술한다.

## Gotchas

### 문제 제목
Claude가 이 작업에서 흔히 저지르는 실수나, 이 환경에서 발생하는 특수한 문제를 기술한다.
실전 경험에서 축적된 것이 가장 가치있다.

---

### 스킬 파일 작성법

**frontmatter 필드 설명** (locked schema, fixplan-meta debate Gen4 W13):
- `name`: 스킬 식별자 (kebab-case). 파일명 stem과 일치 권장. matcher가 fall back할 때 사용.
- `description`: 한 문장 요약. matcher와 사용자가 첫 줄에 읽음 — 무엇을 트리거하면 좋은지 명시.
- `keywords`: 토픽 키워드 (공백 구분). 프롬프트에 포함되면 +1점씩
- `intent`: 의도/동작 키워드 (공백 구분). 프롬프트에 포함되면 +2점씩
- `paths`: 폴더/파일 경로 패턴 (공백 구분). 프롬프트의 경로와 매칭되면 +2점씩
- `patterns`: 코드 패턴 (라이브러리/프레임워크명). 참조된 파일에서 발견되면 +1점씩
- `requires`: 연관 스킬 이름 (공백 구분, .md 없이). 크로스 참조 추천에 사용
- `phase`: 적용 가능한 작업 단계 (plan implement review deploy debug)
- `tech-stack`: 활성화 조건 — `any`(항상) | 단일 스택 (예: `flutter`, `java`) | 콤마 구분 다중 (예: `java,kotlin`). tech-stack.yaml과 매칭.
- `min_score`: 활성화 최소 점수 (기본값: 1)

**핵심 원칙:**
- Claude가 이미 아는 교과서적 내용은 적지 않는다 (Don't State the Obvious)
- Gotchas 섹션이 가장 가치 있다 — 실전에서 Claude가 틀리기 쉬운 것을 기록
- 특정 기술 스택을 강제하지 않는다 (Avoid Railroading)
- 의사결정 트리는 유연하게, 가이드는 프로젝트 특화 정보만

**파일명 규칙:**
- `_`로 시작하는 파일은 무시됨 (템플릿, 메모용)
- `.md` 확장자 필수
