---
name: skill-lint-workflow
description: 신규 스킬 추가/수정/삭제 시 frontmatter 품질 + matcher 트리거 정확도 + R002 size 위반을 검증하는 운영 워크플로우. skill_lint_report, skill_trigger_eval, debate_doubts CLI 도구 사용 시점과 PR 검토 게이트 명시. 스킬 작성자와 리뷰어가 매번 따라야 하는 절차서.
keywords: skill-lint workflow audit trigger-eval grandfather R002 R003 frontmatter 검증 매처 정확도 회귀방지 스킬리뷰 quality-gate skill-quality matcher-quality 스킬추가 스킬수정
intent: skill추가해 skill리뷰해 trigger확인해 frontmatter검증해 matcher정확도 quality확인해
paths: skills/_common skills/java skills/flutter skills/typescript
patterns: skill_lint skill_trigger_eval debate_doubts
phase: review implement
min_score: 3
---

# Skill Lint Workflow — 운영 절차서

> Reference: debate sessions `833f75770125` (P0), `603933922d9c` (R002), `42b4a343e390` (R003 redesign).
> 도구 위치: `~/.claude/scripts/cli/`

## 의사결정 트리

### IF 신규 스킬 추가 (Implement)
1. **frontmatter 작성**: `_template.md` 참조, **whitespace-separated** 토큰 권장 (`a b c`). YAML list `[a, b, c]`도 허용 (`lib/frontmatter_norm.split_list_field`가 정규화)
2. **자체 lint**: skill .md 저장 시 PostToolUse hook이 telemetry 자동 기록 (`telemetry/skill_lint.jsonl`)
3. **trigger eval 작성**: should-trigger 7+ / should-NOT-trigger 5+ JSON 파일 작성
4. **trigger eval 실행**: `python -m cli.skill_trigger_eval <skill.md> --queries <queries.json> --candidates _common`
5. **PASS 기준**: recall ≥ 60% AND precision = 100%
6. **FAIL 시 조정**: keyword 추가/min_score 조정 후 재실행
7. **lock-in test 추가**: trigger eval 결과를 회귀 방지 테스트로 lock

### IF 스킬 수정 (Implement)
1. 변경 전 `python -m cli.skill_trigger_eval <skill.md> --queries <기존 queries.json>` baseline 측정
2. frontmatter 수정
3. 같은 queries로 재측정 → recall/precision 회귀 없는지 확인
4. lock-in test 통과 확인 (`python -m tests.test_skill_trigger_eval`)

### IF 스킬 삭제 (Plan)
1. 다른 스킬의 `requires:` 필드에서 참조 검색 (`grep -r "requires:.*<skill>" skills/`)
2. 참조하는 스킬들의 `requires` 업데이트
3. test_skill_lint.py의 GRANDFATHERED_PATHS lock-in test 확인 (해당 스킬이 grandfather라면 entry 제거)
4. `_common/skill-lint-workflow.md` (이 파일)의 `paths`/`patterns`도 영향 없는지 확인

### IF lint 위반 발견 (Review)
**R002 (file size > 30KB)**:
- 분리 가능 → 도메인별 파일 split (`security-auth.md`, `security-api.md` 등)
- 분리 부적정 (cross-ref 비용 큼) → `cli/skill_lint_report.py`의 `GRANDFATHERED_PATHS` frozenset에 명시 등록 + `tests/test_skill_lint.py::test_grandfathered_paths_contains_known_outliers` 업데이트 (PR 리뷰 강제)

**R003 trigger fired**:
- `python -m cli.skill_lint_report --lint --json` 실행 → 어느 clause fired 확인
- `short_desc_drift_ge_5pp_over_baseline` fired → conv_trees 중 description <40자 비율 갑자기 증가. 새 debate session으로 R003 design 진입 (snapshot ref `42b4a343e390`)

### IF Architect self_doubt 누적 검토 (Review/Periodic)
1. SessionStart `<harness-status>` block의 `[debate-doubts] N pending` 라인에서 카운트 확인 (Wave 18 통합 advisory)
2. `python -m cli.debate_doubts` 전체 목록 확인
3. 검토 후 `python -m cli.debate_doubts --acknowledge <session_id>` ack (또는 통합 alias `python -m cli.advisory_ack debate_doubts <sid>` — Wave 19부터)
4. 7일 누적 시: `python -m cli.debate_doubts --since 7d` 최근만 보기

### IF strict-design intent 누적 검토 (Wave 18+19부터)
1. SessionStart `<harness-status>` block의 `[strict-design] N unreviewed` 라인 확인
2. `/harness-trigger-summary` 또는 `python -m engine.trigger_summary` 카테고리 분류
3. 일괄 ack: `python -m engine.trigger_summary --acknowledge-all` (또는 `--acknowledge-up-to <ts>` / `--ack-ts <ts>`)
4. 통합 alias: `python -m cli.advisory_ack strict_design <ts>` — Wave 19부터 동일 효과

**Wave 19 통합 (`lib/advisory_ack.py` REGISTRY)**: 두 advisory 모두 `class AdvisoryAck`의 인스턴스로 통합. 새 advisory 추가 시 `REGISTRY` dict에 entry 1줄만. snapshot hash `89f6af6e...`로 lock된 invariant.

## 도구 매트릭스 (시점별)

| 시점 | 도구 | 무엇 |
|---|---|---|
| 매 세션 시작 | (자동 SessionStart hook) | skill-lint-summary + debate-doubts advisory + handoff |
| 매 skill .md 저장 | (자동 PostToolUse hook) | telemetry/skill_lint.jsonl 기록 (advisory 발동 안 함) |
| 신규/수정 스킬 검토 | `cli.skill_trigger_eval` | trigger 정확도 측정 (recall/precision/F1) |
| baseline 분석 | `cli.skill_lint_report` | 트리별 분포, R003 trigger 상태, R002 violation |
| `--p1-check` 게이트 | `cli.skill_lint_report --p1-check` | exit 0 if P1 ready (per-tree dominance ≥80%) |
| 의도된 long file 등록 | code PR → `cli/skill_lint_report.py::GRANDFATHERED_PATHS` | 명시적 등록 + lock-in test 갱신 |
| Architect 회고 | `cli.debate_doubts` | self_doubt 누적 확인 |

## Locked invariants (PR 리뷰 시 확인)

debate-locked invariants는 **새 debate 없이 변경 금지**:

| Invariant | 보호 대상 |
|---|---|
| `telemetry_only_no_advisory` | PostToolUse 채널 (skill_lint.py public 함수가 advisory 문자열 반환 금지) |
| `reviewer_py_diff_lines = 0` | reviewer.py 핵심 dispatch (lint은 lazy import + try/except로 통합) |
| `shape_classifier_enum 5-way` | has_upstream_schema / has_harness_schema / harness_extended / mixed / none |
| `telemetry_schema 7 fields` | ts/session_id/path/shape/name_present/description_present/file_size_bytes |
| `BASELINE_SHORT_DESCRIPTION_RATIO_CONV = 0.0070` | R003 baseline freeze (snapshot `debate-1777970195-6b152b`) |
| `baseline_snapshot_ref` | 새 R003 debate에서만 갱신 가능 |
| `ack_module_location = lib_advisory_ack_generic` (Wave 19) | `lib/advisory_ack.py` 단일 store, snapshot `89f6af6e...` |
| `cli_alias = argv_rewrite_no_argparse_surface` (Wave 19) | `cli/advisory_ack.py`는 argparse import 0건 (AST-locked) |
| `migration_strategy = read_union_no_migrate` (Wave 19) | sunset/copy-forward 금지, union이 영속 |
| `walk_up_caps` (Wave 19.1) | tempfile-based 테스트는 `max_levels=1` 명시 (Windows USERPROFILE walk-up 회피) |

## Convention (논의 기반)

- frontmatter `keywords` 등 list 필드: **whitespace-separated 권장**, YAML list 허용 (자동 정규화)
- 새 skill 도입 시 `requires`로 의존 스킬 명시 (cross-ref 자동 안내)
- description은 64+자 권장 (한 줄 트리거 의도 명확화)
- intent 토큰은 동사 어간 (한국어 verb-stem 매칭 활용)
- 향후 Architect verdict 로깅 시 **`self_doubt_note` payload 포함** (debate_doubts CLI 추적 활성화)

## Gotchas

### grandfather 추가가 silent waiver로 변하는 경우
`GRANDFATHERED_PATHS`에 path만 추가하고 `test_grandfathered_paths_contains_known_outliers`는 갱신 안 하면 lock-in test가 즉시 catch. PR 리뷰 단계에서 "이 path를 정말 grandfather할 가치 있는가" 토론 강제.

### YAML list syntax 사용 시 score 0 (해결됨)
2026-05-05 fix 후 `lib/frontmatter_norm.split_list_field`가 자동 정규화. 그러나 작성자에게는 여전히 whitespace-separated 권장 — 가독성 + 실수 회피.

### qa-boundary같은 boundary 스킬은 messaging-governance와 도메인 overlap
kafka schema 같은 쿼리는 messaging-governance 우세. trigger eval에서 일부 MISS 정상. recall floor 60% 통과면 OK.

### debate_doubts ack 안 하고 무시
`--acknowledge` 없이 무시하면 SessionStart 매번 동일 advisory. ack 파일은 `state/debate_doubts_acknowledged.txt`.

### 새 trigger eval 도구 자체가 자기 스킬 PASS하는지 self-consistency 확인
도구 도입 직후 자기 ecosystem의 핵심 스킬(qa-boundary 등)을 자기 도구로 측정. FAIL 시 즉시 fix.

## 도구 사용 패턴 (Harness)
- 신규 skill PR: `python -m cli.skill_trigger_eval <new>.md --queries <queries>.json` 결과를 PR description에 첨부
- 정기 audit: `python -m cli.skill_lint_report` 출력을 매주 1회 사람 검토
- session 정리: SessionStart advisory에서 actionable signal 보이면 그 자리에서 `--acknowledge`
- debate 후속: 새 debate 종료 시 verdict event payload에 `self_doubt_note` 명시 포함
