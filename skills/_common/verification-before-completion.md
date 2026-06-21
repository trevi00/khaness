---
name: verification-before-completion
description: Evidence before claims — run verification command and confirm output before any success claim. No "should pass" / "probably works".
keywords: [verification, verify, evidence, pre-claim, completion-gate, 검증, 완료전, 증거먼저]
intent: [verify, check-before-claim, evidence-gate]
phase: review
min_score: 3
---

# Verification Before Completion

> 원본: superpowers (MIT, Jesse Vincent) — eval-tuned behavior-shaping content 보존.

## 의사결정 트리

### IF 완료/성공/fix 선언 직전 (Review→Deploy)
1. **IDENTIFY**: 이 주장을 증명하는 명령은?
2. **RUN**: FULL 명령 실행 (fresh, complete — 이전 run 재사용 금지)
3. **READs**: 전체 output 읽고 exit code 확인, failure 개수 셈
4. **VERIFY**: output이 주장을 확인하나?
   - NO → 실제 상태를 evidence와 함께 보고
   - YES → 주장 + evidence 함께 언급
5. **ONLY THEN**: 주장

**어떤 단계라도 skip = 거짓말, verification 아님**

### IF "probably" / "should" / "seems to" 쓰려는 순간 → STOP
- 그 단어 자체가 verification 안 한 증거

## The Iron Law

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
```

이 메시지에서 verification 명령을 실행하지 않았으면, **통과 주장 불가**.

## Common Failures

| 주장 | 필요한 증거 | 불충분한 것 |
|---|---|---|
| Tests pass | 테스트 명령 output: 0 failures | 이전 run, "should pass" |
| Linter clean | Linter output: 0 errors | 부분 체크, 추론 |
| Build succeeds | Build 명령: exit 0 | Linter pass, "logs look good" |
| Bug fixed | 원래 증상 테스트: passes | 코드 변경, 고쳤다고 가정 |
| Regression test works | Red-green cycle 검증 완료 | 테스트가 한 번 pass |
| Agent completed | VCS diff로 변경 확인 | Agent가 "success" 보고 |
| Requirements met | Line-by-line 체크리스트 | 테스트 pass |

## Red Flags — STOP

- "should", "probably", "seems to" 사용
- Verification 전 만족 표현 ("Great!", "Perfect!", "Done!")
- Verification 없이 commit/push/PR 직전
- Agent success report 신뢰
- 부분 verification에 의존
- "Just this once" 생각
- 피곤해서 작업 끝내고 싶음
- **Verification 실행 없이 성공 암시하는 모든 표현**

## Rationalization Prevention

| Excuse | Reality |
|---|---|
| "Should work now" | RUN the verification |
| "I'm confident" | Confidence ≠ evidence |
| "Just this once" | No exceptions |
| "Linter passed" | Linter ≠ compiler |
| "Agent said success" | Verify independently |
| "I'm tired" | Exhaustion ≠ excuse |
| "Partial check is enough" | Partial proves nothing |
| "Different words so rule doesn't apply" | Spirit over letter |

## Key Patterns

### Tests
```
✅ [테스트 명령 실행] [See: 34/34 pass] "All tests pass"
❌ "Should pass now" / "Looks correct"
```

### Regression test (TDD Red-Green)
```
✅ Write → Run (pass) → Revert fix → Run (MUST FAIL) → Restore → Run (pass)
❌ "I've written a regression test" (red-green 검증 없이)
```

### Build
```
✅ [Build 실행] [See: exit 0] "Build passes"
❌ "Linter passed" (linter는 compile 체크 안 함)
```

### Requirements
```
✅ 계획 재독 → 체크리스트 작성 → 각각 검증 → 갭/완료 보고
❌ "Tests pass, phase complete"
```

### Agent delegation
```
✅ Agent success 보고 → VCS diff 체크 → 변경 검증 → 실제 상태 보고
❌ Agent report 신뢰
```

## Why This Matters

**Honesty is a core value. If you lie, you'll be replaced.**

- 시간 낭비 → 재작업
- Undefined 함수 shipped → 크래시
- Missing requirements shipped → 불완전 기능
- 사용자 신뢰 상실

## When To Apply

**항상 다음 직전에**:
- 성공/완료 주장의 모든 변형
- 만족 표현
- 작업 상태에 대한 positive statement
- Commit / PR / task 완료
- 다음 task 이동
- Agent 위임

**이 규칙이 적용되는 범위**:
- 정확한 표현
- Paraphrase, 동의어
- 성공 암시
- 완료/정확성 시사하는 모든 커뮤니케이션

## 우리 하네스 통합

- **validators/** (13 verify-*.py) — 기계적 verification 자동화. 이 스킬은 그 위의 "주장 전에 validator 돌렸나?" 메타 체크.
- **/harness-ralph** — validator 실패 시 자동 fix 루프. verify + fix 통합.
- **harness-verifier 같은 에이전트 없음** → kha-verifier (GSD 워크플로우용)로 위임 가능
- **feedback_harness_compliance.md** memory — DGE Critic 단계 건너뛰기 방지. 이 스킬이 Critic의 수동 버전.

## 프로젝트 확장

프로젝트 고유 verification 명령은 `<project>/.claude/verify.yml`에 정의:
```yaml
tests: npm test
build: npm run build
lint: npm run lint
typecheck: npm run typecheck
```
이 스킬을 수정하지 않고 자동 로드.

## Gotchas

- **"Agent가 success 보고했으니 믿자"**: Agent가 거짓 보고 가능. VCS diff + 실제 실행 결과로 독립 검증.
- **"Partial check로 충분"**: Linter pass ≠ build pass ≠ test pass. 각각 별개.
- **"이번만 skip"**: 이 한 번의 예외가 수십 번의 습관이 됨. 예외 없음.
- **Fresh 아님**: 10분 전 run 재사용 금지. 코드 바뀌었을 수 있음.
- **"Looks good" / "should pass"**: 이런 단어 쓰는 순간 verification 안 한 것. 이 단어가 신호.

## The Bottom Line

**No shortcuts for verification.**

Run the command. Read the output. THEN claim the result.

**Non-negotiable.**
