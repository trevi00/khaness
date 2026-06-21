---
description: Aggregate ~/.claude/telemetry/debate-triggers.jsonl — total prompts, strict-design matches, top phases/cwds, recent samples. Manual invoke only (no auto cron).
user-invocable: true
allowed-tools: Bash
category: report
mutates: no
long-running: no
external-deps: python-cli
---

당신은 사용자의 **`/harness-trigger-summary`** 호출에 응답해 strict-design intent telemetry를 집계합니다.

## 동작

1. `~/.claude/scripts/engine/trigger_summary.py` 를 실행:

   ```bash
   python ~/.claude/scripts/engine/trigger_summary.py
   ```

2. 출력된 markdown 보고서를 사용자에게 그대로 보여줍니다 (가공 없음).

   > **구조화 출력 (체이닝용)**: `python ~/.claude/scripts/engine/trigger_summary.py --json` 은
   > 동일 데이터를 schema-stable JSON(`{schema_version, total_prompts, strict_design_matched,
   > pending, top_phases:[{phase,count}], top_cwds, recent_strict}`)으로 emit합니다. 다른
   > 스크립트/커맨드가 임계 비교·이상 감지에 소비할 때 사용 (markdown 파싱 대신).

3. 발화 트리거 (예: P95 latency 임계 초과, gap 누적) 가 보고서에 포함되어 있으면 사용자에게 `/harness-debate <topic>` 또는 `/harness-audit` 후속 호출 권고.

## Non-Goals (자동 cron 없음)

- 본 커맨드는 **수동 invoke 전용**. SessionStart 훅은 advisory 1줄 ("N개 미점검 트리거")만 제공.
- 트리거 발화 시 자동 토론 엔진 기동 금지 (CLAUDE.md "엔진 기동은 명시 호출 시에만" 정신 일관).

## 데이터 소스

- `~/.claude/telemetry/debate-triggers.jsonl` (`handlers/prompt/debate_trigger.py` 가 매 prompt 마다 append).
- `~/.claude/state/decisions/triggers.yaml` (재평가 trigger 정의 — `/harness-audit` Phase 5가 이쪽 평가 담당).

## 관련

- `~/.claude/scripts/handlers/prompt/debate_trigger.py` (생산자)
- `~/.claude/scripts/handlers/session/init.py` (SessionStart advisory)
- `~/.claude/state/research/openagent.md` Anti-Spec §8 (동일 카테고리 거부 정책)

## Output

- summary report (markdown to user, no file write):
  - total prompts logged + strict-design matches + match ratio
  - top N phases (plan / implement / review / debug) by count
  - top N cwds where strict-design intent fired
  - 5-10 recent sample prompts (preview-trimmed)
- status: `summary_emitted` | `aborted_no_telemetry` (debate-triggers.jsonl missing or empty).

## Failure behavior

- **telemetry file missing**: abort `aborted_no_telemetry` + suggest enabling `handlers/prompt/debate_trigger.py` OR using harness for ≥1 day to populate.
- **malformed JSONL line**: skip and count toward `parse_errors` total; continue aggregation.
- **truncated final line** (still being written): treat as malformed; skip.
- read-only command — no state mutation.

## Gate summary

- preflight: `~/.claude/telemetry/debate-triggers.jsonl` exists AND is non-empty.
- success criteria: aggregated counts + top-N tables + recent samples printed.
- abort triggers: telemetry file missing/empty.

## Boundary with other commands

- vs `harness-audit`: trigger-summary aggregates ONE telemetry file; audit evaluates 6-axis IMPACT across the whole harness. (Round-3 P0 #4: audit was previously inlining trigger summary; now delegated here.)
- vs `harness-diagnose`: trigger-summary is steady-state stats; diagnose targets a specific symptom.
- vs `harness-optimize`: trigger-summary feeds optimize as one input signal.
- vs `kha-session-report`: trigger-summary covers the harness telemetry ring; kha-session-report covers a single session's token/work breakdown.
