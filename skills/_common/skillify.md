---
name: skillify
description: Turn a repeatable workflow from the current session into a reusable harness skill draft with valid frontmatter.
keywords: [skillify, make-skill, extract-skill, codify, repeatable, workflow]
intent: [create-skill, extract, codify, generalize]
phase: plan
min_score: 2
---

# Skillify

Capture a successful multi-step workflow uncovered in this session as a concrete skill draft — instead of rediscovering it later. 하네스 2-Strike 규칙의 직접적 실행 경로.

## 목표

반복 가능한 태스크를 스킬로 승격. 같은 패턴 2회 이상 발견 → 스킬화.

## 워크플로우

1. **반복 가능한 태스크 식별**: 세션에서 성공한 멀티-스텝 작업
2. **추출**:
   - 입력
   - 순서 있는 단계
   - 성공 기준
   - 제약 / 함정
   - 스킬 배치 위치 (스킬 트리 기준)
3. **배치 결정**:
   - 언어 무관 → `~/.claude/skills/_common/<name>.md`
   - 특정 스택 → `~/.claude/skills/<lang>/<framework>/<name>.md`
   - 프로젝트 한정 → `<project>/.claude/skills/<name>.md`
4. **스킬 파일 초안 작성** (YAML frontmatter 필수)

### 최소 Frontmatter

```yaml
---
name: <skill-name>
description: <한줄 설명 — 언제 쓰는지>
keywords: [키워드, 리스트]
intent: [verb, verb]
phase: plan | implement | review | debug | deploy
min_score: 2
---
```

5. 본문: `## 의사결정 트리`, `## 워크플로우`, `## Gotchas`
6. 너무 모호해서 안전하게 인코딩 못하는 부분 명시

## 규칙

- 실제로 반복 가능한 워크플로우만 캡처
- 실용적이고 범위 제한
- 명시적 성공 기준 (모호한 prose 대신)
- 아직 분기 결정이 미해결이면 초안 전에 명시

## 검증

작성 후 `~/.claude/scripts/lib/frontmatter.py`의 `parse_frontmatter`로 파싱 검증. 실패하면 스킬 파일 삭제 후 에러와 함께 중단.

## 출력

- 제안한 스킬 이름
- 타겟 위치
- 초안 워크플로우 구조
- 열린 질문 (있다면)

## Gotchas

- **한 번짜리 태스크를 스킬화**: 실제 반복 가능성 확인. 1회용은 스킬 아님.
- **너무 넓은 범위**: "development-best-practices" 같은 광범위 스킬은 활성도가 낮음. 구체적일수록 좋음.
- **Frontmatter 없이 본문만**: 스킬 매처가 못 찾음. YAML frontmatter 필수.
- **`_common` vs 스택 트리 혼동**: 언어 특화 지시가 있으면 스택 트리. 일반 패턴만 `_common`.
- **기존 스킬과 키워드 충돌**: 매치가 엉뚱한 곳으로 갈 수 있음. `/harness-skill search <keyword>`로 선확인.
