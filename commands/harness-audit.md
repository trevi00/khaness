---
description: "하네스 감사 — IMPACT 프레임워크 기반 전체 하네스 완성도 평가 및 개선 로드맵"
user-invocable: true
category: review
mutates: no
long-running: yes
external-deps: none
---

당신은 Claude Code 하네스 감사 전문가입니다. IMPACT 프레임워크와 Claude Code 내부 아키텍처 지식을 기반으로 사용자의 전체 하네스를 평가합니다.

## IMPACT 프레임워크 (swyx, AI Engineer Summit 2025)

| 축 | 의미 | Claude Code 대응 |
|----|------|-----------------|
| **I**ntent | 목표가 명확하고 검증 가능한가 | CLAUDE.md, 프로젝트 설정, 테스트 스위트 |
| **M**emory | 세션 간 지식이 유지되는가 | Memory 시스템, 세션 저장, 스킬 상태 |
| **P**lanning | 계획을 세우고 수정할 수 있는가 | Plan 모드, /compact, 태스크 분해 |
| **A**uthority | 적절한 신뢰 경계가 있는가 | 권한 규칙, auto-mode, 훅 게이트 |
| **C**ontrol Flow | 동적 실행 경로인가 | 도구 선택, 서브에이전트, 조건부 훅 |
| **T**ools | 필요한 도구가 갖춰져 있는가 | MCP 서버, 내장 도구, 스킬 |

## Guide/Sensor 매트릭스 (Fowler/Boeckeler)

| 유형 | Computational (결정적) | Inferential (AI 기반) |
|------|----------------------|---------------------|
| **Guide** (사전) | CLAUDE.md, 린터 설정, 스키마 | AI 스킬 매칭, PreToolUse 훅 |
| **Sensor** (사후) | 테스트, 타입 체크, git diff | PostToolUse 리뷰, auto-mode 분류기 |

## 감사 절차

### Phase 1: 데이터 수집

다음 파일들을 읽고 분석합니다:

**설정 파일**:
- `~/.claude.json` — MCP 서버, 기본 설정
- `~/.claude/settings.json` — 권한 규칙, 모드, 도구 허용
- `~/.claude/settings.local.json` — 로컬 오버라이드
- 프로젝트 루트의 `.claude/settings.json` — 프로젝트 설정

**컨텍스트 파일**:
- 모든 CLAUDE.md 파일 (user, project, local)
- `.claude/rules/*.md` — 규칙 파일

**확장 기능**:
- `~/.claude/commands/*.md` — 사용자 스킬
- `.claude/commands/*.md` — 프로젝트 스킬
- 훅 설정 (settings.json의 hooks 섹션)
- MCP 서버 목록과 상태

**메모리**:
- `~/.claude/projects/*/memory/` — 프로젝트 메모리

### Phase 2: 각 IMPACT 축 평가

**먼저 결정론적 evidence 수집** (점수를 인상이 아닌 측정값에 근거시킴 — closes the
"checklist는 pseudo-code, 미배선" 갭):
```bash
python -m lib.harness_audit   # 6축별 deterministic facts (commands_count, brain_l1_lines,
                              # validators_count, allow/deny_rules, hook_events_registered, …)
```
각 축에 대해 1-5점으로 평가하되, **위 evidence의 구체 수치를 근거로 인용**합니다 (예:
"Control 3/5 — hook_events_registered=6, validators_count=37이나 X 미흡"). evidence는
read-only이며 LLM 판단을 대체하지 않고 grounding합니다.

**I — Intent (의도 명확성)**
- [ ] CLAUDE.md에 프로젝트 목표가 명시되어 있는가?
- [ ] 성공 기준이 코드로 검증 가능한가? (테스트, 린터)
- [ ] "IMPORTANT", "NEVER", "ALWAYS" 키워드로 핵심 규칙이 명확한가?
- [ ] 불필요한 내용이 토큰을 낭비하고 있지 않은가?

**M — Memory (기억 지속성)**
- [ ] 메모리 파일이 체계적으로 관리되는가?
- [ ] MEMORY.md 인덱스가 200줄 이내인가? (초과 시 절단됨)
- [ ] 세션 간 컨텍스트 손실 없이 작업이 이어지는가?
- [ ] 오래되거나 잘못된 메모리가 정리되고 있는가?

**P — Planning (계획 능력)**
- [ ] 복잡한 작업에 Plan 모드를 활용하고 있는가?
- [ ] /compact 전략이 수립되어 있는가?
- [ ] 서브에이전트 활용 패턴이 있는가?
- [ ] 작업 분해 가이드가 CLAUDE.md에 있는가?

**A — Authority (권한 경계)**
- [ ] 불필요한 와일드카드 allow가 없는가? (cmd.exe:*, bash:* 등)
- [ ] 위험 작업에 적절한 ask 규칙이 있는가?
- [ ] auto-mode 사용 시 커스텀 allow/deny 규칙이 있는가?
- [ ] MCP 서버의 destructiveHint가 적절히 설정되어 있는가?

**C — Control Flow (실행 흐름)**
- [ ] 훅으로 동적 행동 제어를 하고 있는가?
- [ ] PreToolUse 훅으로 위험 작업을 사전 검토하는가?
- [ ] UserPromptSubmit 훅으로 컨텍스트를 동적 주입하는가?
- [ ] 조건부 스킬 활성화가 구현되어 있는가?

**T — Tools (도구 완비)**
- [ ] 프로젝트에 필요한 MCP 서버가 모두 설치되어 있는가?
- [ ] 반복 작업이 스킬로 자동화되어 있는가?
- [ ] MCP 서버 안정성이 확보되어 있는가? (캐시 영향 최소화)
- [ ] 불필요한 MCP 서버가 비활성화되어 있는가?

### Phase 3: 결과 리포트

```
╔══════════════════════════════════════════╗
║        하네스 감사 결과 리포트            ║
╠══════════════════════════════════════════╣
║ Intent     [████░] 4/5  의도 명확        ║
║ Memory     [███░░] 3/5  정리 필요        ║
║ Planning   [██░░░] 2/5  Plan 모드 미활용  ║
║ Authority  [████░] 4/5  양호             ║
║ Control    [█░░░░] 1/5  훅 미사용        ║
║ Tools      [███░░] 3/5  MCP 2개 불안정    ║
╠══════════════════════════════════════════╣
║ 종합 점수: 17/30                         ║
║ Guide 커버리지: 60%                      ║
║ Sensor 커버리지: 20%                     ║
╚════════════════════════════════��═════════╝
```

### Phase 4: 개선 로드맵

우선순위별로 구체적 액션을 제시합니다:

**즉시 (10분 이내)**:
- 위험 권한 규칙 제거
- 불필요한 MCP 서버 비활성화

**단기 (1시간 이내)**:
- CLAUDE.md 정리 및 최적화
- 핵심 훅 1-2개 추가

**중기 (1일 이내)**:
- 스킬 세트 구축
- 메모리 체계 정비

**장기 (1주 이내)**:
- 전체 Guide/Sensor 매트릭스 구축
- 커스텀 MCP 서버 개발
- auto-mode 커스텀 규칙 튜닝

### Phase 5: Trigger Evaluation (수동 invoke 전용)

> 이 섹션은 `~/.claude/state/decisions/triggers.yaml` 의 재평가 트리거를 집계해 발화 여부를 판정합니다. 자동 cron 없음 — 사용자가 `/harness-audit` 명시 호출 시에만 실행. (Gen3 debate 결정: 섀도우 모드 정책과 일관, Windows cron 신뢰성 회피.)

#### 5-1. triggers.yaml 로드

```python
import yaml
from pathlib import Path

triggers_path = Path.home() / ".claude/state/decisions/triggers.yaml"
if not triggers_path.is_file():
    print("[skip] triggers.yaml 없음 — Phase 5 건너뜀")
else:
    triggers = yaml.safe_load(triggers_path.read_text(encoding="utf-8"))["triggers"]
```

#### 5-2. Telemetry 집계

각 트리거의 `conditions[].source` 를 `~/.claude/telemetry/*.jsonl` 에서 읽고 임계 비교:

| Trigger | 신호 | 임계 | 윈도우 |
|---|---|---|---|
| `rust_rewrite.hook_latency_p95_high` | hook-latency.jsonl P95 duration_ms | ≥ 200ms | 7일 |
| `category_model_routing.weekly_routing_calls_at_least_10` | hook-latency.jsonl `name="model_router.*"` count | ≥ 10 | 7일 |
| `validator_expansion.value_gaps_count_high` | value-gaps.jsonl count | ≥ 5 | 14일 |

`anthropic_native_plugin_api`, `callers_at_least_2`, `registered_categories_at_least_5` 는 `check: manual` / `codebase_grep` 이라 사람 판단 필요.

#### 5-3. 발화 판정

각 트리거의 `fire_when` (`any` / `all`) 으로 conditions 조합:

```python
for name, trig in triggers.items():
    fired = []
    for cond in trig["conditions"]:
        if evaluate_condition(cond):  # telemetry 비교 또는 manual 체크
            fired.append(cond["id"])
    if trig["fire_when"] == "all":
        triggered = len(fired) == len(trig["conditions"])
    else:  # any
        triggered = len(fired) > 0
    if triggered:
        report_section.append({"trigger": name, "fired_conditions": fired})
```

#### 5-4. 보고

발화 트리거가 있으면 audit 보고서 마지막에 `[TRIGGER FIRED]` 섹션 추가:

```markdown
## [TRIGGER FIRED] 재평가 권고

### rust_rewrite (signal: latency)
- ✅ hook_latency_p95_high — 7일 P95 = 247ms (임계 200ms)
- ❌ anthropic_native_plugin_api — 외부 사실, 미발화

→ 권고: `/harness-debate "rust rewrite revisit (P95=247ms)"` 호출
→ 참고: `~/.claude/state/research/openagent.md` Anti-Spec 섹션
```

발화 트리거가 없으면 단일 라인:

```
[TRIGGER OK] 모든 재평가 트리거 미발화 (Gen3 결정 유효)
```

#### 5-5. Cross-references

- `~/.claude/state/decisions/triggers.yaml` — 트리거 정의 (signal_dominant, conditions, fire_when)
- `~/.claude/state/research/openagent.md` — 트리거가 가리키는 원본 결정 + Anti-Spec
- `~/.claude/scripts/lib/logging.py` — `@timed` decorator (telemetry 생산자)
- `~/.claude/telemetry/hook-latency.jsonl`, `~/.claude/telemetry/value-gaps.jsonl` — 데이터 소스

## Output

- audit report (markdown to user, no file write by default):
  - IMPACT 6축 점수 (0-5 each) + Guide/Sensor 매트릭스 충족도
  - blocker list (priority-ordered, with file:line citations)
  - 개선 로드맵 (P0 즉시 / P1 strategic / P2 백로그)
- optional: `state/audits/audit-<unix_ts>.md` if `--save` flag passed by user.
- status: `audit_complete` (모든 6축 평가됨) | `partial` (일부 축 데이터 부족) | `aborted_no_harness` (CLAUDE_HOME 또는 skills/ 없음).

## Failure behavior

- **CLAUDE_HOME or skills/ missing**: abort with `aborted_no_harness` + path that's missing. Read-only operation so no rollback needed.
- **데이터 부족** (예: telemetry/ 비어있음, debate-triggers.jsonl 없음): 해당 축은 `partial` 표시 + 데이터 수집 방법 제안. 다른 축 평가는 계속.
- **잘못된 frontmatter** in skills/commands: 해당 항목을 skip + 카운트, 전체 audit는 계속.
- **trigger 집계는 별도 명령 위임** (Round-3 P0 #4): 상세 telemetry 분석은 `/harness-trigger-summary` 호출 권장 표시. audit 본 보고서에는 카운트만 요약.
- read-only 명령이므로 implementation/state 변경 없음. 사용자가 patch 제안 적용 시 별도 작업.

## Gate summary

- preflight: `CLAUDE_HOME/skills/`, `CLAUDE_HOME/commands/`, `CLAUDE_HOME/scripts/` 존재; 최소 하나의 telemetry 파일 또는 inventory.md 존재.
- success criteria: 6 IMPACT 축 모두 평가됨 + blocker 리스트 + 우선순위별 로드맵 제공.
- abort triggers: 하네스 디렉토리 자체가 없음; 사용자 인터럽트.

## Retry / Resume

- checkpoint: read-only audit이므로 명시적 checkpoint 없음. `state/audits/audit-<ts>.md` 저장 시 그 자체가 결과 스냅샷.
- resume command: 재실행하면 새 audit (현재 시점 기준). 비교 분석은 사용자가 두 보고서를 diff.
- idempotent: YES (동일 시점·동일 상태에서 동일 결과). LLM 비결정성 외 변동 없음.
- stall detection: 6축 평가가 monotonic — 진행 멈추면 사용자가 인터럽트.

## Boundary with other commands

- vs `harness-trigger-summary`: this는 6축 종합 평가; trigger-summary는 debate-triggers.jsonl 한 가지 telemetry만 집계.
- vs `harness-diagnose`: this는 정기 점검 (steady-state); diagnose는 증상 기반 RCA.
- vs `harness-optimize`: this는 정성/정량 평가; optimize는 비용/캐시/지연 튜닝 backlog 제안.
- vs `kha-audit-planning-health`: this는 하네스 자체 (~/.claude/); kha-audit-planning-health는 프로젝트의 .planning/.
