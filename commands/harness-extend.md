---
description: "하네스 확장 설계 — 훅, MCP, 스킬을 내부 아키텍처에 맞게 설계하고 구현합니다"
user-invocable: true
argument-hint: "원하는 기능을 설명하세요"
category: build
mutates: yes
long-running: yes
external-deps: git
---

당신은 Claude Code 하네스 확장 전문가입니다. 사용자가 원하는 기능을 **내부 아키텍처에 가장 적합한 방식**으로 설계하고 구현합니다.

## 확장 포인트 아키텍처 (소스코드 기반)

### 1. Hook 시스템 — 가장 강력한 행동 수정 메커니즘

**이벤트 종류와 활용법**:

| 이벤트 | 시점 | 핵심 활용 | 응답 가능 필드 |
|--------|------|----------|---------------|
| PreToolUse | 도구 실행 전 | 입력 수정, 차단, 컨텍스트 주입 | decision, updatedInput, additionalContext |
| PostToolUse | 도구 실행 후 | 결과 수정, 리뷰 주입, 기록 | updatedMCPToolOutput, additionalContext |
| UserPromptSubmit | 사용자 입력 시 | 프레이밍, 스킬 매칭, 컨텍스트 로딩 | additionalContext |
| Notification | 알림 발생 | 외부 전달 (Slack, Discord) | - |
| SessionStart | 세션 시작 | 초기화, 환경 세팅 | additionalContext |

**Hook 응답 JSON 스키마**:
```json
{
  "continue": true,
  "decision": "allow | deny",
  "stopReason": "중단 사유",
  "additionalContext": "모델에게 주입할 텍스트",
  "updatedInput": { "수정된": "입력값" },
  "updatedMCPToolOutput": "수정된 MCP 결과",
  "permissionDecision": "allow | deny | ask"
}
```

**additionalContext 주입 메커니즘** (핵심!):
- `<system-reminder>` 태그로 감싸져 대화에 주입됨
- 모델은 이를 시스템 지시로 인식
- 여러 훅의 additionalContext는 배열로 합산 → 모두 주입
- **Guide(피드포워드)로서 가장 유연한 확장 포인트**

### 2. MCP 서버 — 외부 도구/리소스 제공

**도구 등록 구조**:
- 자동 네이밍: `mcp__서버명__도구명`
- 설명 2,048자 제한 (초과 시 자동 절단)
- 어노테이션: `readOnlyHint`, `destructiveHint`, `openWorldHint`
- 권한: 기본 passthrough → 사용자 승인 필요

**프로토콜 지원**: stdio (로컬), SSE, HTTP, WebSocket, SDK (인프로세스)

**캐시 영향 주의**: MCP 서버 연결/해제 시 도구 목록 변경 → 캐시 무효화
→ 안정적인 서버만 항상 연결, 나머지는 필요 시 연결

### 3. Skill (Commands) — 재사용 프롬프트 패턴

**실행 모드**:
- `inline`: 프롬프트를 대화에 주입 → 기존 도구로 실행 (가벼움)
- `fork`: 서브에이전트로 격리 실행 → 결과만 반환 (무거움, 안전)

**프론트매터 필드**:
```yaml
allowed-tools: [Bash, Read, Edit]  # fork 모드에서 허용 도구
description: "설명"
model: "claude-sonnet-4-5-20250514"  # 모델 오버라이드
context: fork  # inline(기본) 또는 fork
user-invocable: true  # /명령어로 직접 호출 가능
disable-model-invocation: false  # 모델이 자동 호출 가능 여부
argument-hint: "인자 힌트"
effort: low  # thinking effort
```

### 4. CLAUDE.md — 가장 기본적인 Guide

**로딩 순서** (마지막이 최우선):
managed → user → project → local

**효과적인 CLAUDE.md 작성 원칙** (소스 분석 기반):
- 모든 내용은 시스템 프롬프트에 매 턴 포함됨 → 간결하게
- "IMPORTANT:", "NEVER:", "ALWAYS:" 패턴이 모델 준수율 높음
- 조건부 지시: "IF ... THEN ..." 패턴으로 상황별 분기
- 도구 사용 가이드: 소스의 anti-pattern 패턴 따라 "X하지 마세요, 대신 Y하세요"

## 확장 설계 의사결정 트리

```
원하는 기능이...

도구 실행을 수정/차단해야 하나?
  ├─ Yes → PreToolUse Hook
  │   ├─ 입력값 변경 필요 → updatedInput 반환
  │   ├─ 차단 필요 → decision: "deny"
  │   └─ 맥락 추가 → additionalContext
  └─ No ↓

도구 실행 후 결과를 활용해야 하나?
  ├─ Yes → PostToolUse Hook
  │   ├─ 결과 수정 → updatedMCPToolOutput
  │   ├─ 추가 정보 주입 → additionalContext
  │   └─ 외부 기록 → 사이드 이펙트만
  └─ No ↓

사용자 입력에 컨텍스트를 더해야 하나?
  ├─ Yes → UserPromptSubmit Hook
  │   └─ 매칭 조건에 따라 additionalContext 주입
  └─ No ↓

외부 시스템에 접근해야 하나?
  ├─ Yes → MCP 서버
  │   ├─ 읽기 전용 → readOnlyHint: true
  │   ├─ 위험 작업 → destructiveHint: true
  │   └─ 네트워크 접근 → openWorldHint: true
  └─ No ↓

재사용 가능한 워크플로우인가?
  ├─ Yes → Skill (.claude/commands/)
  │   ├─ 대화 내에서 → context: inline
  │   └─ 격리 필요 → context: fork
  └─ No ↓

항상 적용되는 규칙인가?
  └─ Yes → CLAUDE.md
```

## 실행 절차

1. 사용자의 요구사항을 정확히 파악합니다
2. 위 의사결정 트리로 최적 확장 포인트를 결정합니다
3. Guide(사전 제어)인지 Sensor(사후 제어)인지 분류합니다
4. 구현 코드를 생성합니다
5. 테스트 방법을 안내합니다
6. 캐시/성능 영향을 평가합니다

사용자가 인자로 원하는 기능을 설명했다면, 바로 설계에 들어가세요.
인자가 없다면 "어떤 기능을 만들고 싶으신가요?"라고 물어보세요.

## Output

- design doc: surfaced inline (extension type chosen, hook event / MCP server / skill subtree, integration plan, rollback plan).
- patch artifacts: per-file diffs (settings.json hook entry, scripts/handlers/<sub>/<name>.py, skills/.../SKILL.md, etc.).
- tests: unit tests under scripts/tests/ + acceptance criteria.
- status: `design_only` (sketch produced, no patch) | `implemented` (files written + tests pass) | `aborted_unsupported` | `aborted_user_reject`.

## Failure behavior

- **request maps to no recognized extension type**: list supported types (hook / MCP / skill / validator / handler / lib) + abort with `aborted_unsupported`.
- **design rejected by user at gate** (after design surface, before write): abort with `aborted_user_reject`. Nothing written.
- **implementation step fails** (test failures, frontmatter validator block): rollback the partial write — `git restore` modified files, leave new files staged for user review. Surface failure reason + suggest `/harness-ralph` to recover.
- **design-first gate**: ALWAYS surface design + ask for explicit approval BEFORE patches. No silent implementation.
- **MCP server config requires user action** (network endpoint, API key): produce design + `.mcp.json` template; halt at `design_only` status until user provides config.

## Gate summary

- preflight: request resolves to one of {hook, mcp, skill, validator, handler, lib}; existing harness state has compatible ABI (e.g., new hook needs settings.json schema match); git working tree clean OR user accepts dirty state.
- success criteria: design surfaced + user approves + patches applied + relevant validator/test passes.
- abort triggers: unsupported extension type; user rejects design; test gate fails after implementation; user interrupt.

## Retry / Resume

- checkpoint: design surfaced inline (markdown text); patch files staged before commit. Both can be replayed manually.
- resume command: not first-class — re-run with refined description. Existing partial work in git working tree must be cleaned (`git restore` or commit) first.
- idempotent: NO — extension synthesis is LLM-driven; same description may produce different valid designs.
- stall detection: design phase is bounded by user interaction; implementation phase tracks per-file write progress; user-visible advisory if any write hangs >60s.

## Boundary with other commands

- vs `harness-skill`: extend creates NEW extension mechanisms (hook/MCP/lib); skill manages EXISTING skill files (list/edit/remove).
- vs `harness-debate`: debate decides; extend designs+implements after the decision is clear. extend may CALL debate internally for ambiguous design choices.
- vs `harness-autopilot`: autopilot is goal-driven (any feature); extend is harness-mechanism-driven (specifically hooks/MCP/skills/validators).
- vs `kha-plan-phase`: kha-plan-phase produces PLAN.md for application code; extend produces design + patch for HARNESS code (~/.claude/scripts).
