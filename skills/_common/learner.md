---
name: learner
description: Extract a REUSABLE learned skill from current conversation — non-Googleable, context-specific, actionable insights only.
keywords: [learner, extract-skill, learned, codify, insight, gotcha]
intent: [learn, extract, codify]
phase: review
min_score: 3
---

# Learner

세션에서 얻은 교훈을 **재사용 가능한 스킬**로 승격. 하네스 2-Strike 규칙의 우회로 (발견 2회 전이라도, 충분히 비자명하면 즉시 코드화).

> ⚠️ `handlers/stop/learner.py`는 자동 sensor, 이 스킬은 **수동 extraction**. 상보 관계.

## 핵심 원칙

재사용 가능 스킬 = 코드 스니펫 복사본 X, **원칙 + 의사결정 휴리스틱** O. Claude에게 이런 문제 부류를 **어떻게 사고할지** 가르침.

**차이**:
- BAD (mimic): "ConnectionResetError 보이면 이 try/except 블록 추가"
- GOOD (reusable): "비동기 네트워크 코드에서 I/O 연산은 클라이언트/서버 라이프사이클 불일치로 독립적으로 실패할 수 있다. 원칙: 각 I/O 연산을 개별 래핑 — 실패는 예외가 아니라 일반 케이스."

## 품질 게이트

추출 전 3가지 모두 참이어야:
- "누군가 5분 구글링으로 찾을 수 있나?" → NO
- "이 코드베이스에 특정적인가?" → YES
- "진짜 디버깅 노력이 들었나?" → YES

## 추출 타이밍 (sensor signals)

오직 다음 이후에만 추출:
- 깊은 조사가 필요한 트리키한 버그 해결
- 이 코드베이스 고유의 비자명한 우회책 발견
- 잊으면 시간 낭비하는 숨겨진 함정
- 이 프로젝트에 영향을 주는 문서화 안 된 동작 발견

## 유용한 스킬의 조건

1. **Non-Googleable**: 검색으로 쉽게 못 찾는 것
   - BAD: "TypeScript에서 파일 읽는 법" ❌
   - GOOD: "이 코드베이스는 ESM + 커스텀 path resolution — fileURLToPath + 특정 상대경로 필요" ✓

2. **Context-Specific**: 이 코드베이스의 실제 파일/에러 메시지/패턴 참조
   - BAD: "try/catch로 에러 처리" ❌
   - GOOD: "server.py:42 aiohttp 프록시는 ClientDisconnectedError에서 크래시 — StreamResponse를 try/except로 감싸라" ✓

3. **Actionable with Precision**: WHAT + WHERE 정확히
   - BAD: "엣지 케이스 처리" ❌
   - GOOD: "dist/에서 'Cannot find module' 시 tsconfig.json moduleResolution이 package.json type과 맞는지 확인" ✓

4. **Hard-Won**: 실제 노력 들어감
   - BAD: 제네릭 프로그래밍 패턴 ❌
   - GOOD: "worker.ts line 89 Promise.all에 await 빠짐 — race condition" ✓

## 안티 패턴 (추출 금지)

- 제네릭 프로그래밍 패턴 (공식 문서 참조로 충분)
- 리팩토링 기법 (universal)
- 라이브러리 사용 예제 (라이브러리 문서 사용)
- 타입 정의 / 보일러플레이트
- 주니어가 5분 구글링으로 찾는 것

## 워크플로우

### Step 1: 정보 수집
- **Problem Statement**: 구체적 에러/증상/혼동
  - 실제 에러 메시지, 파일 경로, 라인 번호
  - 예: "src/hooks/session.ts:45 TypeError when sessionId undefined after restart"
- **Solution**: 정확한 fix (제네릭 조언 X)
  - 코드 스니펫, 파일 경로, 설정 변경
  - 예: "session.user 접근 전 null 체크, 401에서 session regenerate"
- **Triggers**: 이 문제 재발 시 나올 키워드
  - 에러 메시지 조각, 파일명, 증상 설명
  - 예: ["sessionId undefined", "session.ts TypeError", "401 session"]
- **Scope**: project-level 기본, 진짜 portable insight만 user-level

### Step 2: Quality validation

시스템이 거부하는 스킬:
- 너무 제네릭 (파일 경로/라인/에러 메시지 없음)
- 쉽게 구글러블 (표준 패턴, 라이브러리 사용법)
- 모호한 솔루션 (코드 스니펫/정확한 지시 없음)
- 나쁜 triggers (모든 것에 매치되는 제네릭 단어)

### Step 3: 배치

- **User-level**: `~/.claude/skills/_common/<skill-name>.md` — 진짜 portable insight만 (드물게)
- **Project-level**: `<project>/.claude/skills/<skill-name>.md` — 기본값

### 필수 파일 형식

모든 learned 스킬은 YAML frontmatter 필수:

```yaml
---
name: <skill-name>
description: <한줄 설명>
keywords: [<트리거-1>, <트리거-2>]
intent: [<의도-1>]
phase: <plan|implement|review|debug|deploy>
min_score: 2
---
```

### 본문 템플릿

```markdown
# [Skill Name]

## The Insight
발견한 PRINCIPLE은 무엇인가? 코드가 아니라 멘탈 모델.

## Why This Matters
이걸 모르면 뭐가 잘못되나? 어떤 증상이 여기까지 이끌었나?

## Recognition Pattern
이 스킬이 적용될 때를 어떻게 아나? 징후는?

## The Approach
의사결정 휴리스틱. Claude가 이걸 어떻게 사고해야 하나?

## Example (선택)
코드가 도움되면 표시 — 단, 원칙의 illustration, 복사본이 아님.
```

**핵심**: 스킬이 재사용 가능하다 == Claude가 동일한 상황이 아니라 **새로운 상황**에 적용할 수 있다.

## Gotchas

- **너무 일찍 추출**: 1회 경험으로는 진짜 재사용 가능한지 검증 안 됨. 2-Strike 대기 권장.
- **코드만 저장**: 원칙 없이 코드 조각은 검색만도 못 함.
- **Triggers에 제네릭 단어**: `["error", "bug"]` 같은 건 전부에 매치. 구체적 에러 메시지/파일명.
- **Expertise vs Workflow 혼동**: 패턴/함정 = expertise, 단계 시퀀스 = workflow. 별도 저장이 안전한 업데이트에 유리.
