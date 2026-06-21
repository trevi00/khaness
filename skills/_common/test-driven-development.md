---
name: test-driven-development
description: Write the test first, watch it fail, write minimal code to pass. The Iron Law — no production code without a failing test.
keywords: [tdd, test-first, red-green-refactor, 테스트주도, 테스트먼저, 실패먼저]
intent: [test, tdd, implement-with-test]
phase: implement
min_score: 3
---

# Test-Driven Development

> 원본: superpowers (MIT, Jesse Vincent) — eval-tuned behavior-shaping content 보존.

## 의사결정 트리

### IF 새 기능 / 버그픽스 / 리팩토링 / 동작 변경 (Implement)
1. **RED**: 실패하는 테스트 1개 작성 (한 동작, 명확한 이름, 실제 코드 — mock은 불가피할 때만)
2. **Verify RED**: 테스트 실행 → 실패 확인 (에러 아닌 fail, 예상된 이유로)
3. **GREEN**: 통과할 최소 코드만 작성 (과엔지니어링 금지)
4. **Verify GREEN**: 테스트 통과 + 기존 테스트도 green + output 청결
5. **REFACTOR**: green 유지하면서 중복 제거 / 이름 개선 / 헬퍼 추출
6. 다음 RED로 반복

### IF 버그 발견 (Debug→Implement)
- 먼저 버그 재현하는 failing test → TDD cycle → 테스트가 fix 증명 + 회귀 방지
- **테스트 없이 버그 고치지 마라**

### 예외 (human partner 허가 필요)
- Throwaway 프로토타입
- 생성 코드
- 설정 파일

"이번만 TDD 건너뛰자" 생각? **Stop. 그게 rationalization.**

## The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

테스트 전에 코드 작성? **삭제. 처음부터 다시.**

**예외 없음**:
- "참고용으로 keep" 금지
- 테스트 쓰면서 "adapt" 금지
- 보지도 마라
- Delete means delete

테스트에서 새로 구현. Period.

## Red-Green-Refactor

### RED — Watch It Fail (MANDATORY, 절대 skip 금지)

```bash
<test command for your stack>   # npm test / ./gradlew test / pytest / cargo test
```

확인:
- 테스트가 **fail** (error 아님)
- Failure 메시지가 예상대로
- 기능 missing 때문 (typo 아님)

**테스트가 바로 통과?** 기존 동작을 테스트하는 중. 테스트 수정.
**테스트가 error?** error 고치고 fail이 제대로 날 때까지 재실행.

### GREEN — Minimal Code

통과할 최소 코드만.

```typescript
// GOOD: 딱 통과할 만큼
async function retryOperation<T>(fn: () => Promise<T>): Promise<T> {
  for (let i = 0; i < 3; i++) {
    try { return await fn(); }
    catch (e) { if (i === 2) throw e; }
  }
  throw new Error('unreachable');
}

// BAD: 과엔지니어링 (YAGNI 위반)
async function retryOperation<T>(
  fn: () => Promise<T>,
  options?: { maxRetries?: number; backoff?: 'linear' | 'exponential'; onRetry?: Function }
): Promise<T> { /* YAGNI */ }
```

기능 추가, 다른 코드 리팩토링, 테스트 범위 밖 "improve" 금지.

### Verify GREEN — Watch It Pass (MANDATORY)

확인:
- 테스트 pass
- 다른 테스트도 여전히 pass
- Output 청결 (error, warning 없음)

**테스트 fail?** 코드 수정 (테스트 아님).
**다른 테스트 fail?** 지금 당장 수정.

### REFACTOR — Clean Up (green 이후에만)

- 중복 제거
- 이름 개선
- 헬퍼 추출

**green 유지**. 동작 추가 금지.

## Good Tests

| 품질 | Good | Bad |
|---|---|---|
| **Minimal** | 한 가지. 이름에 "and"? 쪼개라 | `test('validates email and domain and whitespace')` |
| **Clear** | 이름이 동작 설명 | `test('test1')` |
| **Shows intent** | 원하는 API 시연 | 코드가 뭘 해야 하는지 흐림 |

## Why Order Matters

### "I'll write tests after to verify it works"
사후 작성 테스트는 바로 통과. 통과는 증명하는 게 없음:
- 엉뚱한 걸 테스트 중일 수 있음
- 동작이 아닌 구현을 테스트
- 에지케이스 누락
- 버그 잡는 걸 본 적 없음

Test-first가 테스트 실패를 보게 강제 → 실제로 뭔가 테스트한다는 증거.

### "I already manually tested all the edge cases"
수동 테스트는 ad-hoc:
- 뭘 테스트했는지 기록 없음
- 코드 변경 시 재실행 불가
- 압박 속에서 쉽게 놓침
- "내가 해봤을 때는 됨" ≠ 포괄적

자동 테스트는 체계적. 매번 똑같이 실행.

### "Deleting X hours of work is wasteful"
Sunk cost fallacy. 시간은 이미 갔음. 지금 선택:
- 삭제 후 TDD로 재작성 (+X시간, 높은 신뢰)
- 남겨두고 사후 테스트 (30분, 낮은 신뢰, 버그 ↑)

"낭비"는 신뢰 못 하는 코드를 **유지**하는 것. 진짜 테스트 없는 working code = 기술 부채.

### "Tests after achieve the same goals — it's spirit not ritual"
**No.** Tests-after는 "What does this do?" 답변. Tests-first는 "What SHOULD this do?" 답변.

사후 테스트는 구현에 편향 → 요구사항이 아닌 만든 것을 테스트. 기억한 에지케이스만 검증 (발견된 것 아님).

## Common Rationalizations

| Excuse | Reality |
|---|---|
| "Too simple to test" | Simple code breaks. Test takes 30 seconds. |
| "I'll test after" | Tests passing immediately prove nothing. |
| "Tests after achieve same goals" | Tests-after = "what does this do?" Tests-first = "what should this do?" |
| "Already manually tested" | Ad-hoc ≠ systematic. No record, can't re-run. |
| "Deleting X hours is wasteful" | Sunk cost fallacy. Keeping unverified code is technical debt. |
| "Keep as reference, write tests first" | You'll adapt it. That's testing after. Delete means delete. |
| "Need to explore first" | Fine. Throw away exploration, start with TDD. |
| "Test hard = design unclear" | Listen to test. Hard to test = hard to use. |
| "TDD will slow me down" | TDD faster than debugging. Pragmatic = test-first. |
| "Manual test faster" | Manual doesn't prove edge cases. You'll re-test every change. |
| "Existing code has no tests" | You're improving it. Add tests for existing code. |

## Red Flags — STOP and Start Over

- Code before test
- Test after implementation
- Test passes immediately
- Can't explain why test failed
- Tests added "later"
- Rationalizing "just this once"
- "I already manually tested it"
- "Tests after achieve the same purpose"
- "It's about spirit not ritual"
- "Keep as reference" or "adapt existing code"
- "Already spent X hours, deleting is wasteful"
- "TDD is dogmatic, I'm being pragmatic"
- "This is different because..."

**전부 의미하는 것: 코드 삭제. TDD로 다시 시작.**

## When Stuck

| 문제 | 해결 |
|---|---|
| 테스트 쓰는 법 모름 | Wished-for API를 써라. Assertion 먼저. 사용자에게 질문 |
| 테스트 너무 복잡 | 설계 너무 복잡. 인터페이스 단순화 |
| 다 mock 해야 함 | 코드 결합도 과다. Dependency injection |
| Setup 거대 | Helper 추출. 여전히 복잡? 설계 단순화 |

## Verification Checklist (작업 완료 선언 전)

- [ ] 모든 새 함수/메서드에 테스트 있음
- [ ] 구현 전에 각 테스트 fail을 봤음
- [ ] 각 테스트가 예상된 이유로 fail (기능 missing, typo 아님)
- [ ] 통과할 최소 코드만 작성
- [ ] 모든 테스트 pass
- [ ] Output 청결 (error, warning 없음)
- [ ] 실제 코드 사용 (mock은 불가피할 때만)
- [ ] Edge case + error 커버

체크 못 하는 항목? **TDD 건너뛴 것. 처음부터 다시.**

## 관련 스킬

- **Mock 작성·변경 시**: `testing-anti-patterns.md` 참조 (5 anti-patterns + gate functions)
- **완료 선언 전**: `verification-before-completion.md` (fresh evidence 요구)
- **회사 Kotlin 백엔드 컨벤션**: `java/springboot-3.2/testing.md` (E2E→Unit 순서, `doAnswer` ID 주입 등)

## 프로젝트 확장

프로젝트 고유 TDD 규칙은 `<project>/.claude/skills/project-tdd.md`에 추가. 이 스킬을 수정하지 않고 덮어씀.

## Gotchas

- **"Spirit not ritual"은 거의 항상 위반의 신호**: test-first의 spirit은 바로 "절차 지킴". 쇼트컷 하려는 자기 합리화.
- **사후 작성 테스트가 "커버리지 %"를 올려도 TDD 아님**: 원래 버그를 잡을 수 있었는지는 증명 안 됨.
- **Human partner 허가 없이 "예외"**: 건너뛴 이유를 commit 메시지에 남기더라도, 허가는 사전에.

## Final Rule

```
Production code → test exists and failed first
Otherwise → not TDD
```

Human partner 명시적 허가 없이 예외 없음.

## Related (신규 그래프 cross-ref)

TDD가 적용되거나 보강되는 신규 노드:
- `java/lang/testcontainers-junit-integration.md` — `@Testcontainers` + `@Container static` lifecycle, Spring `@ServiceConnection`, JaCoCo Report Aggregation. integration test의 TDD 형태
- `kotlin/android/paparazzi-screenshot-tests.md` — JVM screenshot test (record/verify), AGP lockstep, RTL pseudolocale. UI 회귀의 TDD 변종
- `kotlin/android/circuit-unidirectional-architecture.md` — `Presenter.test { awaitItem() }` distinct-until-changed, FakeNavigator
- `_common/experimentation-and-ab-testing.md` — production 통계 검증 (TDD가 deterministic이라면 이건 production stochastic)
- `_common/durable-execution.md` — Temporal activity test는 deterministic replay 보장 (workflow 코드 안 `Date.now()` 금지)
