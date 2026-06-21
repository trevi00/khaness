---
name: testing-anti-patterns
description: 5 testing anti-patterns with gate functions — testing mock behavior, test-only methods in production, mocking without understanding, incomplete mocks, tests as afterthought.
keywords: [testing-anti-patterns, mock, test-only-methods, incomplete-mocks, 목, 테스트안티패턴, 목테스트, 부분목]
intent: [test-review, mock-review, avoid-anti-pattern]
phase: review
min_score: 2
---

# Testing Anti-Patterns

> 원본: superpowers (MIT, Jesse Vincent). Mock/test 작성·변경 시 **load as reference**.

## 의사결정 트리

### IF Mock 추가/변경 (Implement)
1. 진짜 method가 어떤 side effect를 가지는가? → 목록화
2. 테스트가 그 side effect에 의존하는가?
3. 의존하면 **낮은 레벨에서 mock** (실제 느린/외부 연산만)
4. 의존 안 하면 → higher-level mock 가능
5. 모르면 real 구현으로 먼저 실행 → 필요한 게 뭔지 관찰 → 그 다음 최소 mock

### IF Production 클래스에 메서드 추가 (Implement)
1. 이게 테스트에서만 쓰이는가?
2. YES → **추가 금지.** test utility로 이동
3. 이 클래스가 이 리소스의 lifecycle 소유자인가?
4. NO → **잘못된 클래스.** 올바른 owner로

### IF Mock response 만들기 (Implement)
1. 실제 API response에 어떤 필드가 있는가?
2. **모든 필드** 포함 (down-stream code가 쓰는 것까지)
3. 불확실하면 문서의 모든 필드 포함

## Core Principle

**Test what the code does, not what the mocks do.**

**Following strict TDD prevents these anti-patterns.**

## The Iron Laws

```
1. NEVER test mock behavior
2. NEVER add test-only methods to production classes
3. NEVER mock without understanding dependencies
```

## Anti-Pattern 1: Testing Mock Behavior

**Violation**:
```typescript
// ❌ Testing that the mock exists
test('renders sidebar', () => {
  render(<Page />);
  expect(screen.getByTestId('sidebar-mock')).toBeInTheDocument();
});
```

**Why wrong**: mock이 작동한다는 걸 검증 중 — 컴포넌트가 작동한다는 게 아님. Mock 있으면 pass, 없으면 fail. 실제 동작을 아무것도 안 알려줌.

**Human partner's correction**: "Are we testing the behavior of a mock?"

**Fix**:
```typescript
// ✅ 실제 컴포넌트 테스트 또는 mock 안 함
test('renders sidebar', () => {
  render(<Page />);  // sidebar mock 안 함
  expect(screen.getByRole('navigation')).toBeInTheDocument();
});
```

### Gate Function
```
BEFORE asserting on any mock element:
  Ask: "Am I testing real component behavior or just mock existence?"
  IF testing mock existence:
    STOP — Delete the assertion or unmock the component
  Test real behavior instead
```

## Anti-Pattern 2: Test-Only Methods in Production

**Violation**:
```typescript
// ❌ destroy()가 오직 테스트에서만 쓰임
class Session {
  async destroy() {  // production API처럼 보임!
    await this._workspaceManager?.destroyWorkspace(this.id);
  }
}
afterEach(() => session.destroy());
```

**Why wrong**: production 클래스가 test-only 코드로 오염. production에서 실수로 호출되면 위험. YAGNI + separation of concerns 위반. Object lifecycle과 entity lifecycle 혼동.

**Fix**:
```typescript
// ✅ test utility가 cleanup 처리
// Session은 destroy() 없음 — production에서는 stateless

// test-utils/
export async function cleanupSession(session: Session) {
  const workspace = session.getWorkspaceInfo();
  if (workspace) await workspaceManager.destroyWorkspace(workspace.id);
}
afterEach(() => cleanupSession(session));
```

### Gate Function
```
BEFORE adding any method to production class:
  Ask: "Is this only used by tests?"
  IF yes:
    STOP — Don't add it. Put it in test utilities instead
  Ask: "Does this class own this resource's lifecycle?"
  IF no:
    STOP — Wrong class for this method
```

## Anti-Pattern 3: Mocking Without Understanding

**Violation**:
```typescript
// ❌ Mock이 테스트 로직을 깨뜨림
test('detects duplicate server', () => {
  vi.mock('ToolCatalog', () => ({
    discoverAndCacheTools: vi.fn().mockResolvedValue(undefined)
    // ^ 테스트가 의존하는 config write를 막아버림!
  }));
  await addServer(config);
  await addServer(config);  // throw 해야 하지만 안 함!
});
```

**Why wrong**: mock된 method가 테스트가 의존하는 side effect를 가짐 (config 작성). "안전하게" over-mocking이 실제 동작을 깸. 엉뚱한 이유로 pass 또는 mysterious fail.

**Fix**:
```typescript
// ✅ 올바른 레벨에서 mock
test('detects duplicate server', () => {
  vi.mock('MCPServerManager');  // 느린 server startup만 mock
  await addServer(config);  // config 작성됨
  await addServer(config);  // 중복 감지 ✓
});
```

### Gate Function
```
BEFORE mocking any method:
  STOP — Don't mock yet

  1. "이 method의 real 구현이 어떤 side effect를 가지나?"
  2. "이 테스트가 그 side effect에 의존하나?"
  3. "이 테스트가 뭘 필요로 하는지 완전히 이해하는가?"

  IF depends on side effects:
    낮은 레벨(실제 slow/external 연산)에서 mock
    OR 필요한 behavior 보존하는 test double
    NOT the high-level method the test depends on

  IF unsure:
    Real 구현으로 먼저 실행 → 필요한 걸 관찰 → THEN minimal mock

  Red flags:
    - "안전하게 mock하자"
    - "이건 느릴 수도 있으니까 mock"
    - Dependency chain 이해 없이 mocking
```

## Anti-Pattern 4: Incomplete Mocks

**Violation**:
```typescript
// ❌ 필요한 것 같은 필드만 mock
const mockResponse = {
  status: 'success',
  data: { userId: '123', name: 'Alice' }
  // 빠짐: 하류 코드가 쓰는 metadata
};
// 나중: response.metadata.requestId 접근 시 터짐
```

**Why wrong**:
- **부분 mock은 구조 가정을 숨김** — 아는 필드만 mock함
- **하류 코드가 안 넣은 필드에 의존할 수 있음** — silent failure
- **테스트는 pass, 통합은 fail** — mock 불완전, real API 완전
- **거짓 자신감**

**The Iron Rule**: Mock 만들면 **전체 구조**를 reality 그대로 — 즉시 테스트가 쓰는 필드만이 아님.

**Fix**:
```typescript
// ✅ 실제 API의 완전성을 미러
const mockResponse = {
  status: 'success',
  data: { userId: '123', name: 'Alice' },
  metadata: { requestId: 'req-789', timestamp: 1234567890 }
  // 실제 API가 반환하는 모든 필드
};
```

### Gate Function
```
BEFORE creating mock responses:
  Check: "실제 API response의 필드는?"
  Actions:
    1. docs/examples에서 실제 response 확인
    2. 시스템이 하류에서 쓸 수 있는 모든 필드 포함
    3. Mock이 실제 response 스키마와 완전히 일치 검증

  Critical:
    Mock을 만들면 전체 구조를 이해해야 함
    부분 mock은 코드가 누락 필드에 의존할 때 silent fail

  불확실: 문서화된 모든 필드 포함
```

## Anti-Pattern 5: Tests as Afterthought

**Violation**:
```
✅ 구현 완료
❌ 테스트 없음
"Ready for testing"
```

**Why wrong**: 테스트는 구현의 **일부**, optional follow-up 아님. TDD 했으면 잡혔을 것. 테스트 없이 complete 주장 불가.

**Fix**: TDD cycle 준수 — RED → GREEN → REFACTOR → THEN claim complete.

## When Mocks Become Too Complex

**Warning signs**:
- Mock setup > test logic 길이
- 테스트 통과시키려고 전부 mock
- Mock이 실제 컴포넌트의 method 누락
- Mock 바뀌면 테스트 깨짐

**Human partner's question**: "Do we need to be using a mock here?"

**Consider**: real component 통합 테스트가 복잡한 mock보다 종종 더 간단.

## Quick Reference

| Anti-Pattern | Fix |
|---|---|
| Mock element에 assert | 실제 컴포넌트 테스트 또는 unmock |
| Production 클래스에 test-only method | test utility로 이동 |
| 이해 없이 mock | 의존성 먼저 이해, 최소 mock |
| 부분 mock | 실제 API 완전히 미러 |
| Afterthought 테스트 | TDD — 테스트 먼저 |
| 과복잡 mock | 통합 테스트 고려 |

## Red Flags

- `*-mock` test ID에 assertion
- Test 파일에서만 호출되는 method
- Mock setup이 테스트의 >50%
- Mock 제거하면 테스트 fail
- Mock이 왜 필요한지 설명 못함
- "안전하게 mock"

## 관련 스킬

- **TDD 본 skill**: `test-driven-development.md` — Iron Law, Red-Green-Refactor, rationalization table
- **Mock 기피 회사 관례**: memory `feedback_avoid_mock.md` — Mock 최대한 피하고 실제 구현 대기 or 통합 테스트로 대체

## The Bottom Line

**Mocks are tools to isolate, not things to test.**

TDD 중 mock behavior를 테스트 중이라면 잘못 간 것.

Fix: 실제 동작 테스트 OR 왜 mocking 하는지부터 재검토.
