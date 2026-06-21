---
name: autoresearch
description: Stateful single-mission improvement loop — evaluator-driven iteration with durable decision logs, bounded by max-runtime stop.
keywords: [autoresearch, iterate, improvement-loop, evaluator, mission]
intent: [research, iterate, optimize, benchmark]
phase: implement
min_score: 3
---

# Autoresearch

Bounded, evaluator-driven iterative improvement. Owns ONE mission at a time. Keeps iterating through non-passing results, records each evaluation + decision as durable artifact, stops only at explicit terminal condition (max-runtime default).

## 언제 쓰는가

- 이미 mission + evaluator가 있음 (interview-grade context crystallization 완료)
- 한 mission에 대한 지속적 개선 루프 필요
- `<project>/.harness/autoresearch/` 아래 durable 실험 로그 원함
- 주기 재실행 가능한 launch surface 보유 (스케줄러 / 수동 / scripted — 아래 호환성 섹션 참조)

## 언제 안 쓰는가

- Evaluator가 아직 없음 → 먼저 interview-style context crystallization으로 생성
- 여러 mission을 동시 orchestration → v1 금지
- Stateless 단발 실행 → ralph-style verify-fix loop 또는 autopilot-style design-execute-verify cycle

## 계약

- v1: **single-mission only**
- Evaluator 출력은 필수 JSON: `{"pass": bool, "score"?: number}`
- Non-passing iteration은 루프를 **멈추지 않음**
- Stop 조건은 explicit + bounded (max-runtime 우선)

## 필수 아티팩트

`<project>/.harness/autoresearch/<mission-slug>/`

```
mission.md               — 미션 스펙
evaluator.json           — evaluator 스크립트/명령 참조
runs/<run-id>/
  evaluations/
    iteration-0001.json  — 머신 판독 evaluator 결과
    iteration-0002.json
  decision-log.md        — 사람 판독 결정 로그
```

## 워크플로우

1. **확인**: 단일 mission + evaluator 존재.
2. **State 활성화**:
   - mission slug/dir
   - evaluator 참조
   - iteration 카운트
   - started/updated timestamps
   - 명시적 max-runtime / deadline
3. **매 iteration**:
   - 실험/변경 cycle 1회 실행
   - evaluator 실행
   - 머신 판독 evaluation JSON 저장
   - 사람 판독 decision log entry 추가
   - **evaluation fail이어도 계속**
4. **Stop when**:
   - max-runtime 도달
   - 사용자 명시 취소
   - runtime이 기록한 explicit terminal condition

## Scheduler/Runtime compatibility

본 스킬은 **특정 cron 구현에 하드 의존하지 않는다**. 주기 재실행이 필요할
때는 다음 launch surface 중 하나를 선택:

| Launch surface | 적합 케이스 | 제약 |
|---|---|---|
| Manual re-invocation | one-off / 짧은 미션 (10 iteration 이내) | 사용자 가용성 의존 |
| Claude Code native cron (있을 때) | 주기 재실행 지원 환경 | 도구 가용 여부에 따름 |
| OS cron / launchd / systemd timer | 인프라 통제 가능 시 | shell-launch 정책 사용자 책임 |
| External scheduler (GitHub Actions / Airflow) | CI 환경 속 mission | secret/credential 별도 관리 |
| 수동 스크립트 + watchdog | 환경 제약 큰 경우 | 수동 재시작 정책 명시 |

공통 invariant (어느 surface든 지켜야 함):
- 스케줄 단위당 1 mission (multi-mission 동시 실행 금지)
- 동일 mission/evaluator 계약 유지
- 이전 실험 덮어쓰지 말고 새 run 아티팩트 append

## 실행 정책

- 로그는 사람에게도 유용하게 (머신-only 금지)
- mission 재정의 없이 실행 반환 금지

## Gotchas

- **Evaluator가 non-JSON 반환**: 스킬 전체가 깨짐. 반드시 `{pass, score?}` 계약 지켜라.
- **Multi-mission 유혹**: v1은 단일 mission. 여러 개 필요하면 스킬 여러 번 호출.
- **Max-runtime 없이 시작**: 무한 루프 리스크. 항상 explicit bound 설정.
- **Iteration 로그 누락**: decision-log.md 안 쓰면 재현 불가. 매 iteration 기록 필수.
