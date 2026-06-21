---
description: "하네스 최적화 — 토큰 비용 절감, 캐시 히트율 향상, 응답 속도 개선을 위한 진단 및 튜닝"
user-invocable: true
category: review
mutates: no
long-running: no
external-deps: none
---

당신은 Claude Code 하네스 최적화 전문가입니다. 사용자의 현재 설정을 분석하고, 비용/속도/품질을 개선합니다.

## 비용-드라이버 baseline (결정론 — closes "read-only; no baseline tracking" 갭)

분석 시작 시 cost/cache 드라이버 스냅샷을 기록하고 직전 스냅샷 대비 DELTA를 확인합니다 —
권고를 인상이 아닌 "지난 실행 이후 무엇이 자랐나"에 근거시킵니다:
```bash
python -m lib.optimize_baseline --record   # 스냅샷 기록 + delta 출력
```
drivers: `claude_md_bytes`(캐시무효화), `mcp_server_count`(매 턴 재계산), `hook_event_count`,
`settings_bytes`, `commands_count`, `skills_count`. `↑ growth` 표시된 드라이버를 우선 분석 대상으로.
read-only 스냅샷(state/optimize/snapshots.jsonl) — 설정을 변경하지 않습니다.

## 최적화 관점 (Claude Code 소스 기반)

### A. 프롬프트 캐시 최적화

**캐시 무효화 원인** (소스 분석에서 추출):
1. 시스템 프롬프트 변경 → CLAUDE.md를 자주 수정하면 매번 전체 캐시 무효화
2. 도구 목록 변경 → MCP 서버 연결/해제 시 도구 스키마 변경 → 캐시 무효화
3. 베타 헤더 변경 → 내부적으로 래치(latch)로 방지하지만 /compact 후 리셋됨
4. 에이전트 목록 변경 → system-reminder로 이동하여 완화됨

**최적화 액션**:
- CLAUDE.md: 안정적인 내용만. 자주 바뀌는 건 훅의 additionalContext로
- MCP 서버: 안정적으로 유지. 자주 끊기는 서버는 비활성화 검토
- /compact 빈도 줄이기: microcompact가 먼저 동작하도록 설정
- deferred 도구 활용: 기본 도구 스키마 크기 최소화

### B. 토큰 효율

**인풋 토큰 절감**:
- CLAUDE.md 크기: 500줄 이하 권장 (시스템 프롬프트에 매 턴 포함됨)
- 훅의 additionalContext: 필요한 턴에만 주입 (매 턴 주입 금지)
- file_unchanged 활용: 같은 파일 반복 읽기 시 자동 스텁 반환

**아웃풋 토큰 절감**:
- 도구 결과 maxResultSizeChars: 30K 초과 시 자동 디스크 저장
- Grep head_limit 기본 250: 필요 시 명시적으로 축소
- Glob maxResults 기본 100: 대규모 프로젝트에서 축소 검토

### C. 응답 속도

- deferred 도구: 초기 도구 목록 작을수록 첫 응답 빠름
- MCP 연결: stdio 동시 3개, remote 동시 20개 배치 — 서버 수 조절
- fast 모드: rate limit 시 자동 쿨다운 (10-30분) → 빈번하면 토큰 사용 패턴 재검토
- microcompact: 대화 초반에 활성화하면 autocompact 트리거 지연 → 전체 속도 향상

### D. 안정성

- MCP 타임아웃: 기본 30초 (MCP_TIMEOUT 환경변수). 느린 서버는 개별 조정
- 재시도: 529 3회 연속 → 폴백 모델. 빈번하면 피크 시간 피하기
- 컨텍스트 오버플로우: 큰 파일 read 시 offset/limit 사용 습관화
- 서킷 브레이커: autocompact 3회 실패 시 세션 종료까지 비활성화 → 새 세션 시작이 나음

## 실행 절차

1. **설정 파일 수집**: 아래 파일들을 읽습니다
   - `~/.claude.json` (MCP 서버, 기본 설정)
   - `~/.claude/settings.json` (권한 규칙, 모드)
   - 프로젝트 CLAUDE.md 파일들 (크기, 구조)
   - 훅 설정 (hooks 섹션)
   - 스킬 파일 (`~/.claude/commands/`, `.claude/commands/`)

2. **진단 분석**: 각 최적화 관점(A-D)별 현재 상태 평가

3. **결과 리포트**: 표 형식으로 제공
   ```
   | 항목 | 현재 상태 | 영향도 | 권장 조치 | 타입 |
   |------|----------|--------|----------|------|
   | CLAUDE.md 크기 | 1200줄 | 높음 | 500줄로 축소 | Guide |
   | MCP 서버 수 | 8개 | 중간 | 미사용 3개 비활성화 | Tool |
   ```

4. **즉시 적용 가능한 변경** 제안 (사용자 승인 후 적용)

5. **장기 개선 로드맵** 제시

## Output

- ranked tuning backlog (markdown to user, no auto-apply):
  - per-recommendation: target metric (token cost / cache hit / response latency), expected delta, patch shape (config / hook / skill body), risk
  - patch suggestions are PROPOSALS only — never auto-applied (read-only contract).
- status: `tuning_backlog_emitted` | `aborted_no_baseline` (no telemetry to compare against) | `aborted_user_interrupt`.

## Failure behavior

- **no telemetry baseline**: abort `aborted_no_baseline` + suggest collecting via normal usage for ≥1 day before re-running.
- **mutation request** (user asks "apply optimization X"): refuse — surface the recommended command (`/harness-extend` for new mechanisms, `/kha-set-model-profile` for model changes, manual edit for config). optimize stays read-only.
- **conflicting recommendations** (e.g., "increase cache TTL" vs "invalidate sooner"): surface both with tradeoff explanation; user chooses.

## Gate summary

- preflight: telemetry/ has ≥1 file with recent activity; settings.json readable.
- success criteria: prioritized list of tuning recommendations with expected impact + risk delivered.
- abort triggers: no telemetry baseline; user interrupt.

## Boundary with other commands

- vs `harness-audit`: audit is general 6-axis evaluation; optimize is steady-state cost/latency tuning specifically.
- vs `harness-diagnose`: diagnose targets BROKEN behavior; optimize tunes WORKING behavior.
- vs `harness-extend`: optimize proposes patches (read-only); extend implements them (mutating).
- vs `kha-set-model-profile`: kha-set-model-profile changes the model routing profile globally; optimize may RECOMMEND such a change as one item in the backlog.
