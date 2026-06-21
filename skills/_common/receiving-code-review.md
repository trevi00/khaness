---
name: receiving-code-review
description: Technical evaluation of review feedback, not emotional performance. Verify before implementing, ask before assuming, push back when wrong.
keywords: [receive-review, review-response, feedback, 리뷰응답, 피드백, 리뷰받기]
intent: [handle-review, respond-to-feedback]
phase: review
min_score: 2
---

# Receiving Code Review

> 원본: superpowers (MIT, Jesse Vincent) — eval-tuned behavior-shaping content 보존.

**핵심 원칙**: Verify before implementing. Ask before assuming. Technical correctness > social comfort.

## The Response Pattern

```
WHEN receiving code review feedback:

1. READ:      Complete feedback without reacting
2. UNDERSTAND: Restate requirement in own words (or ask)
3. VERIFY:    Check against codebase reality
4. EVALUATE:  Technically sound for THIS codebase?
5. RESPOND:   Technical acknowledgment or reasoned pushback
6. IMPLEMENT: One item at a time, test each
```

## Forbidden Responses

**NEVER**:
- "You're absolutely right!" (explicit CLAUDE.md 위반)
- "Great point!" / "Excellent feedback!" (performative)
- "Let me implement that now" (verification 전)

**INSTEAD**:
- Technical 요구사항 재언급
- 명확화 질문
- 틀리면 technical reasoning으로 push back
- 그냥 작업 시작 (actions > words)

## Handling Unclear Feedback

```
IF 어떤 항목이 unclear:
  STOP — 아무것도 구현 마라
  Unclear 항목에 대해 명확화 요청

WHY: 항목들이 관련되어 있을 수 있음. 부분 이해 = 잘못된 구현.
```

**Example**:
```
사용자: "Fix 1-6"
당신은 1,2,3,6 이해. 4,5 unclear.

❌ WRONG: 1,2,3,6 지금 구현, 4,5는 나중에 질문
✅ RIGHT: "1,2,3,6 이해했습니다. 4와 5는 진행 전 명확화 필요."
```

## Source-Specific Handling

### From 사용자 (trusted)
- 이해 후 구현
- 범위 unclear면 **여전히 질문**
- Performative 동의 없음
- Action으로 점프 또는 technical acknowledgment

### From External Reviewers
```
BEFORE implementing:
  1. Check: 이 codebase에 technically 맞는가?
  2. Check: 기존 기능 깨지나?
  3. Check: 현 구현의 이유가 있나?
  4. Check: 모든 플랫폼/버전에서 동작?
  5. Check: 리뷰어가 전체 맥락을 이해하나?

IF 제안이 잘못 같음:
  Technical reasoning으로 push back

IF 쉽게 검증 불가:
  그렇게 말하기: "[X] 없이 검증 불가. [investigate/ask/proceed] 중 어느 쪽?"

IF 사용자의 prior 결정과 충돌:
  멈추고 사용자와 먼저 논의
```

**사용자 rule**: "External feedback — 회의적이되, 주의 깊게 확인"

## YAGNI Check for "Professional" Features

```
IF 리뷰어가 "implementing properly" 제안:
  Codebase에서 실제 usage grep

  IF unused: "이 endpoint 호출 없음. 제거할까요 (YAGNI)?"
  IF used:   Properly 구현
```

**사용자 rule**: "너와 리뷰어 둘 다 나에게 보고. 필요 없으면 추가하지 마라."

## Implementation Order

```
FOR multi-item feedback:
  1. Unclear 먼저 clarify
  2. 그 다음 이 순서로:
     - Blocking (깨짐, security)
     - Simple fix (typo, import)
     - Complex fix (refactoring, logic)
  3. 각 fix 개별 테스트
  4. 회귀 없음 검증
```

## When To Push Back

Push back **언제**:
- 제안이 기존 기능 깸
- 리뷰어가 전체 맥락 부족
- YAGNI 위반 (unused feature)
- 이 stack에 technically 맞지 않음
- Legacy / 호환성 이유 존재
- 사용자의 아키텍처 결정과 충돌

**Push back 방법**:
- Defensive 아닌 technical reasoning
- 구체적 질문
- 작동하는 test/code 참조
- 아키텍처면 사용자 개입

**편치 않게 push back하는 신호**: "Strange things are afoot at the Circle K"

## Acknowledging Correct Feedback

피드백이 **맞을 때**:
```
✅ "Fixed. [간단히 뭐 바뀜]"
✅ "Good catch — [구체적 이슈]. [location]에서 fix"
✅ [그냥 fix하고 코드로 보여주기]

❌ "You're absolutely right!"
❌ "Great point!"
❌ "Thanks for catching that!"
❌ "Thanks for [아무 것]"
❌ ANY gratitude expression
```

**왜 감사 금지**: Actions speak. 그냥 fix. 코드 자체가 들었다는 증거.

**"Thanks" 쓰려는 순간**: DELETE IT. Fix만 언급.

## Gracefully Correcting Your Pushback

Push back했는데 틀렸을 때:
```
✅ "You were right — [X] 확인했고 [Y]라서 지금 구현"
✅ "검증했고 맞습니다. 처음 이해가 [reason]으로 틀렸음. Fixing."

❌ 긴 사과
❌ Push back 이유 방어
❌ 과설명
```

사실적으로 정정하고 넘어가라.

## Common Mistakes

| Mistake | Fix |
|---|---|
| Performative agreement | 요구사항 언급 또는 그냥 action |
| Blind implementation | 먼저 codebase 검증 |
| Batch without testing | 한 번에 하나, 각각 테스트 |
| 리뷰어 무조건 맞다 가정 | 깨지는지 체크 |
| Push back 회피 | Technical correctness > comfort |
| Partial 구현 | 먼저 모든 항목 clarify |
| 검증 불가인데도 진행 | 한계 언급, 방향 질문 |

## Real Examples

**Performative (Bad)**:
```
리뷰어: "Remove legacy code"
❌ "You're absolutely right! 지금 제거하겠습니다..."
```

**Technical Verification (Good)**:
```
리뷰어: "Remove legacy code"
✅ "확인... build target이 10.15+, 이 API는 13+ 필요. 호환성 때문에 legacy 필요.
   현 구현 bundle ID 잘못됨 — 고치거나 pre-13 지원 드롭할까요?"
```

**YAGNI (Good)**:
```
리뷰어: "Metrics tracking with DB, date filters, CSV export 제대로 구현"
✅ "codebase grep — 이 endpoint 호출 없음. 제거 (YAGNI) 할까요?
   놓친 usage 있나요?"
```

**Unclear Item (Good)**:
```
사용자: "Fix items 1-6"
당신은 1,2,3,6 이해. 4,5 unclear.
✅ "1,2,3,6 이해. 구현 전 4와 5 명확화 필요."
```

## GitHub Thread Replies

GitHub inline review comment에 답변 시 **comment thread에 reply** (`gh api repos/{owner}/{repo}/pulls/{pr}/comments/{id}/replies`), 최상위 PR comment 아님.

## 우리 하네스 통합

- **Memory feedback_harness_compliance.md** — DGE Critic 단계 자가 수용 방지. 이 스킬은 Critic 피드백을 받는 **수신측 규율**.
- **kha-code-reviewer** 출력 수신 시에도 동일 규율 적용 (리뷰어가 subagent든 사람이든).

## Gotchas

- **"Thanks"는 무의식 습관**: 매 응답 시작 전 "감사" 단어가 있는지 체크. 있으면 삭제.
- **"Great point!" 후 무시**: performative 동의 후 실제로 구현 안 하면 최악. 차라리 push back.
- **External reviewer = 무조건 맞다 vs 무조건 틀리다 양극단**: 케이스별 verify. 둘 다 틀림.
- **한 번에 여러 개 구현**: 한 개 잘못되면 어디가 원인인지 모름. 개별 테스트.

## The Bottom Line

**External feedback = 평가할 suggestion, 따를 order 아님.**

Verify. Question. Then implement.

**No performative agreement. Technical rigor always.**
