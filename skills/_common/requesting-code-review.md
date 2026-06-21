---
name: requesting-code-review
description: Dispatch kha-code-reviewer subagent with precisely crafted context for evaluation. Review after each task to catch issues before they cascade.
keywords: [code-review, request-review, kha-code-reviewer, 코드리뷰, 리뷰요청, 리뷰]
intent: [request-review, dispatch-reviewer]
phase: review
min_score: 2
---

# Requesting Code Review

> 원본: superpowers (MIT, Jesse Vincent). 서브에이전트 참조는 우리 하네스로 재매핑.

**핵심 원칙**: Review early, review often.

리뷰어에게는 **session history가 아닌**, 평가용으로 정교하게 만든 context만 전달. 리뷰어 focus는 **work product**에 유지되고, 본인 context는 다음 작업용으로 보존.

## 의사결정 트리

### IF Task 완료 / Major feature 구현 / Merge 직전 (Review)

#### Mandatory
- subagent-driven-development의 각 task 완료 후
- Major feature 완료 후
- Main 병합 직전

#### Optional but Valuable
- 막혔을 때 (fresh perspective)
- 리팩토링 전 (baseline check)
- 복잡한 bug fix 후

### 실행 단계

**1. Git SHA 확보**:
```bash
BASE_SHA=$(git rev-parse HEAD~1)   # 또는 origin/main
HEAD_SHA=$(git rev-parse HEAD)
```

**2. 서브에이전트 dispatch** — 우리 하네스의 `kha-code-reviewer` 사용 (delegation permission 확인 후):

```
Agent(subagent_type="kha-code-reviewer",
      prompt=<아래 템플릿 + 실제 값 채움>)
```

**Capability fallback**: subagent dispatch 불가 (권한 거부 / agent 미등록 / context cap)면 inline `git diff $BASE_SHA..$HEAD_SHA` 결과를 같은 체크리스트로 직접 평가한다. 출력 형식 (Critical/Important/Minor 분류 + 파일·라인 indication)은 동일하게 유지하여 downstream `kha-remediate-code-review`가 차이를 못 느끼게 한다.

**3. Feedback 처리**:
- Critical → 즉시 수정
- Important → 진행 전 수정
- Minor → 나중으로 메모
- 리뷰어가 틀렸으면 technical reasoning으로 push back

## Reviewer Prompt Template (kha-code-reviewer에 전달)

```
You are reviewing code changes for production readiness.

## What Was Implemented
{DESCRIPTION}

## Requirements/Plan
{PLAN_OR_REQUIREMENTS}

## Git Range
Base: {BASE_SHA}
Head: {HEAD_SHA}

git diff --stat {BASE_SHA}..{HEAD_SHA}
git diff {BASE_SHA}..{HEAD_SHA}

## Review Checklist

**Code Quality**:
- Clean separation of concerns?
- Proper error handling?
- Type safety (if applicable)?
- DRY principle followed?
- Edge cases handled?

**Architecture**:
- Sound design decisions?
- Scalability considerations?
- Performance implications?
- Security concerns?

**Testing**:
- Tests actually test logic (not mocks)?
- Edge cases covered?
- Integration tests where needed?
- All tests passing?

**Requirements**:
- All plan requirements met?
- Implementation matches spec?
- No scope creep?
- Breaking changes documented?

**Production Readiness**:
- Migration strategy (schema changes)?
- Backward compatibility considered?
- Documentation complete?
- No obvious bugs?

## Output Format

### Strengths
[구체적으로]

### Issues

#### Critical (Must Fix)
[Bugs, security, data loss, broken functionality]

#### Important (Should Fix)
[Architecture problems, missing features, poor error handling, test gaps]

#### Minor (Nice to Have)
[Code style, optimization, documentation]

**각 이슈마다**: file:line — 뭐가 잘못됐나 — 왜 중요한가 — 어떻게 fix (자명하지 않으면)

### Recommendations
[Code quality, architecture, process 개선]

### Assessment
**Ready to merge?** [Yes/No/With fixes]
**Reasoning**: [1-2 문장 technical assessment]

## Critical Rules

DO:
- 실제 severity로 categorize (전부 Critical 아님)
- 구체적 (file:line, 모호하지 않게)
- WHY를 설명
- 강점도 인정
- 명확한 verdict

DON'T:
- 체크 없이 "looks good"
- nitpick을 Critical로
- 안 본 코드에 feedback
- 모호 ("improve error handling")
- Verdict 회피
```

## Placeholders

| Placeholder | 내용 |
|---|---|
| `{WHAT_WAS_IMPLEMENTED}` | 방금 빌드한 것 |
| `{PLAN_OR_REQUIREMENTS}` | 해야 할 일 |
| `{BASE_SHA}` | 시작 commit |
| `{HEAD_SHA}` | 끝 commit |
| `{DESCRIPTION}` | 간단 요약 |

## Example

```
[Task 2 완료: Verification 함수 추가]

BASE_SHA=$(git log --oneline | grep "Task 1" | head -1 | awk '{print $1}')
HEAD_SHA=$(git rev-parse HEAD)

Agent(subagent_type="kha-code-reviewer", prompt=...) 호출
  WHAT_WAS_IMPLEMENTED: Verification + repair functions for conversation index
  PLAN_OR_REQUIREMENTS: Task 2 from docs/plans/deployment-plan.md
  BASE_SHA: a7981ec
  HEAD_SHA: 3df7661

[Subagent 반환]:
  Strengths: Clean architecture, real tests
  Issues:
    Important: Missing progress indicators
    Minor: Magic number (100) for reporting interval
  Assessment: Ready to proceed

사용자: [Progress indicator fix]
[Task 3로 진행]
```

## 워크플로우 통합

- **subagent-driven-development**: 각 task마다 리뷰. 문제가 누적되기 전에 포착
- **executing-plans (/harness-autopilot)**: batch 단위 (3 task) 리뷰 → feedback → 다음 batch
- **Ad-Hoc**: merge 직전, 막혔을 때

## 우리 하네스 에이전트 매핑

| superpowers 원본 | 우리 하네스 |
|---|---|
| `superpowers:code-reviewer` | `kha-code-reviewer` (기본 bug-focused) |
| — | `harness-code-simplifier` (리팩토링 리뷰 전용) |
| — | `harness-architect` (아키텍처 깊은 리뷰) |
| — | `kha-security-auditor` (보안 리뷰) |

목적에 맞게 선택. 버그/품질은 kha-code-reviewer, 보안은 kha-security-auditor.

## Red Flags

**Never**:
- "간단하니까" 리뷰 skip
- Critical 이슈 무시
- Important 이슈 안 고치고 진행
- 유효한 technical feedback과 다툼

**리뷰어가 틀렸으면**:
- Technical reasoning으로 push back
- 작동하는 code/test 보여주기
- 명확히 질문

## 프로젝트 확장

프로젝트 고유 리뷰 체크리스트는 `<project>/.claude/code-review-checklist.md`에. 이 스킬을 수정하지 않고 reviewer에게 전달하는 prompt에 추가.

## Gotchas

- **BASE_SHA 잘못 잡기**: merge commit 기준이면 전체 branch가 review 범위로 잡힘. 의도한 구간만.
- **전체 session context 전달**: 리뷰어 토큰 낭비 + focus 흐려짐. **위 템플릿 외 session history 전달 금지**.
- **Feedback 받고 바로 "Thanks"**: `receiving-code-review.md` 참조. Performative 감사 금지, 그냥 fix.
- **리뷰 안 받고 merge**: merge 이후 리뷰는 cost가 훨씬 큼. **Merge 전 리뷰 필수**.
