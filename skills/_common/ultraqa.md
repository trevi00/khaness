---
name: ultraqa
description: QA cycling loop — run tests/build/lint/typecheck, diagnose failures with harness-architect, fix with executor, repeat until goal met or max cycles.
keywords: [ultraqa, qa, test-loop, build-fix, typecheck, lint-loop, cycle]
intent: [qa, verify, test, fix-cycle]
phase: review
min_score: 3
---

# UltraQA

자율 QA 사이클. 목표 달성까지 test → verify → fix 루프.

**루프**: runner → (fail) → harness-architect 진단 → executor 수정 → 재시도.

## Goal 파싱

```
/ultraqa --tests          # 테스트 통과
/ultraqa --build          # 빌드 exit 0
/ultraqa --lint           # lint 에러 0
/ultraqa --typecheck      # TS/타입 에러 0
/ultraqa --custom "pattern"  # 출력에 패턴 매치
/ultraqa --interactive    # harness-qa-tester로 CLI/서비스 테스트
```

구조화 goal 없으면 인자를 custom goal로 해석.

## 사이클 워크플로우

### Cycle N (최대 5)

1. **RUN QA**: goal 타입에 따라 검증 실행
   - `--tests`: 프로젝트 test 명령 (`npm test`, `./gradlew test`, `pytest` 등)
   - `--build`: 빌드 명령
   - `--lint`: lint 명령
   - `--typecheck`: 타입 체크 명령
   - `--custom`: 적절한 명령 + 패턴 매칭
   - `--interactive`: `Agent(subagent_type="harness-qa-tester")` 호출

2. **CHECK RESULT**: goal pass?
   - **YES** → 성공 종료
   - **NO** → Step 3

3. **ARCHITECT 진단**:
   ```
   Agent(subagent_type="harness-architect",
         prompt="DIAGNOSE FAILURE:
         Goal: <goal type>
         Output: <test/build output>
         Provide root cause and specific fix recommendations.")
   ```

4. **FIX**: Architect 권고 적용
   ```
   Agent(subagent_type="kha-executor",
         prompt="FIX:
         Issue: <architect diagnosis>
         Files: <affected files>
         Apply the fix precisely as recommended.")
   ```

5. **REPEAT**: Step 1 복귀

## 종료 조건

| 조건 | 액션 |
|------|------|
| **Goal 달성** | 성공 종료: "ULTRAQA COMPLETE: N cycles 후 goal 달성" |
| **Cycle 5 도달** | 진단과 함께 종료: "ULTRAQA STOPPED: Max cycles. Diagnosis: ..." |
| **같은 실패 3회** | 조기 종료: "ULTRAQA STOPPED: 같은 실패 3회 감지. Root cause: ..." |
| **환경 에러** | 종료: "ULTRAQA ERROR: [psmux/port/dependency 이슈]" |

## 관찰성

사이클마다 progress:
```
[ULTRAQA Cycle 1/5] Running tests...
[ULTRAQA Cycle 1/5] FAILED - 3 tests failing
[ULTRAQA Cycle 1/5] Architect 진단 중...
[ULTRAQA Cycle 1/5] Fix: auth.test.ts - missing mock
[ULTRAQA Cycle 2/5] Running tests...
[ULTRAQA Cycle 2/5] PASSED - 47/47 tests pass
[ULTRAQA COMPLETE] 2 cycles 후 goal 달성
```

## State 추적

`<project>/.harness/ultraqa-state.json`:
```json
{
  "active": true,
  "goal_type": "tests",
  "goal_pattern": null,
  "cycle": 1,
  "max_cycles": 5,
  "failures": ["3 tests failing: auth.test.ts"],
  "started_at": "<ISO timestamp>",
  "session_id": "<uuid>"
}
```

## 중요 규칙

1. **가능하면 PARALLEL**: 진단 중에도 가능한 fix 준비.
2. **TRACK failures**: 패턴 감지용으로 각 실패 기록.
3. **패턴 발견 시 조기 종료**: 같은 실패 3회 → 중단 + 사용자에게 노출.
4. **명확한 출력**: 사용자가 현재 사이클/상태를 항상 알 수 있어야.
5. **CLEAN UP**: 완료/취소 시 state 파일 삭제 (active: false 방치 금지).

## State 정리 (완료 시)

**중요: 완료 시 state 파일 삭제 — `active: false`로 두지 마라**

goal 달성 OR max cycles OR early exit 시:
```bash
rm -f <project>/.harness/ultraqa-state.json
```

## Gotchas

- **`--tests`로 실행하지만 test 명령 모름**: `package.json.scripts.test` / `Makefile` / `pyproject.toml.tool.pytest` 등에서 자동 감지. 감지 실패 시 사용자에게 묻기.
- **같은 실패 반복인데 무한 루프**: 3회 규칙 엄수. Architect 진단이 패턴을 만들어야.
- **환경 이슈 (port busy, missing dep)를 코드 문제로 오진**: Cycle 1 실패 시 Architect가 먼저 환경 체크.
- **`--interactive` 없이 UI 테스트**: CLI 서비스면 `--interactive`로 `harness-qa-tester` 호출.
- **State 덮어쓰기**: active ultraqa 있는데 새로 시작 → 기존 state 덮어써서 진행 상황 상실. 시작 전 active 체크.
