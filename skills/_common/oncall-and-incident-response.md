---
name: oncall-and-incident-response
description: Incident 역할 분리(IC/Ops/Comms), SEV 분류, blameless postmortem, multi-burn-rate alerts, toil 식별
keywords: oncall incident-commander postmortem severity slo error-budget burn-rate toil sre runbook
intent: assign-roles classify-severity write-postmortem set-burn-rate-alerts identify-toil
paths:
patterns: severity-level burn-rate error-budget runbook IC-handoff
requires: sre-operations monitoring
phase: plan implement review deploy debug
tech-stack: any
min_score: 2
quality_axes_enforced: true
---

# Oncall & Incident Response

> 핵심: incident 중 가장 흔한 실패는 기술이 아니라 **역할 혼재** — IC가 직접 디버깅하면 상황 인식이 무너진다. Google SRE/PagerDuty 표준은 IC/Ops/Comms 3역할 분리, blameless postmortem, multi-burn-rate alert 3종을 핵심으로 한다.

## 의사결정 트리

### IF incident 발생 (Implement)
1. 심각도 분류 — PagerDuty SEV1-5 적용 (아래 표)
2. SEV ≤ 2 또는 multi-team 영향 → **IC 지정 필수** (Ops Lead와 분리)
3. IC는 기술 작업 금지 — **상황 인식 + 문서화 + 의사결정**만 ("Avoid performing technical actions, remediation work, or log investigations" — PagerDuty)
4. Comms Lead는 외부/내부 stakeholder 정기 업데이트 (보통 30분 cadence)

### IF SLO/error budget 운영 (Plan)
1. SLI 정의 — 사용자 관점 메트릭 (success rate, latency p99). 인프라 메트릭(CPU)은 SLI 아님
2. SLO 결정 — 99.9% (3 nines) → monthly error budget 약 43.2분
3. Multi-window multi-burn-rate alert 3-tier 적용 (페이지 vs 티켓 분리):
   - **Page**: 1h+5m, burn 14.4× → 2% budget 소진 시
   - **Page**: 6h+30m, burn 6× → 5% budget 소진 시
   - **Ticket**: 3d+6h, burn 1× → 10% budget 소진 시
4. 단일 window alert는 alert fatigue 또는 slow MTTR — 항상 multi-window

### IF postmortem 작성 (Review)
1. 트리거 — Google SRE Book 명시: user-visible downtime, data loss, manual rollback/reroute, MTTR 초과, monitoring failure, stakeholder 요청 중 하나라도 충족 시 **mandatory**
2. **blameless 원칙 엄수** — "everyone involved in an incident had good intentions and did the right thing with the information they had" (Google SRE Book Ch.15)
3. action item 명시 — 각 항목에 owner + due date + tracking ticket
4. 시스템/프로세스 개선만 — 개인 책망 금지

### IF toil 식별 (Review)
toil = 6 특성 **모두 충족**:
- Manual / Repetitive / Automatable / Tactical / No enduring value / Scales linearly
부분 충족(예: 보안 감사 = manual + tactical) → toil 아닌 overhead. 잘못 분류 시 부적절한 자동화 비용.

## SEV 분류 표 (PagerDuty 표준)

| SEV | 정의 (verbatim) |
|---|---|
| 1 | "Critical issue that warrants public notification and liaison with executive teams." |
| 2 | "Critical system issue actively impacting many customers' ability to use the product." |
| 3 | "Stability or minor customer-impacting issues that require immediate attention." |
| 4 | "Minor issues requiring action, but not affecting customer ability to use the product." |
| 5 | "Cosmetic issues or bugs, not affecting customer ability to use the product." |

## 가이드

- IC는 "decisions are final" — consensus 추구 X, "강한 반대 있나?" 묻기 (PagerDuty 권장).
- 장기 incident → IC가 planning lead 위임하여 sub-incident 생성 (Google SRE Book).
- Runbook 표준: symptom → diagnosis → mitigation → root cause 분리. "actionable in 5 minutes" 기준.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | postmortem trigger 6 조건 명시 → 누락 incident 차단 |
| 성능 효율성 | multi-burn-rate alert로 fast (1h) + slow (3d) 신호 분리 → MTTR 단축 |
| 호환성 | PagerDuty/Atlassian/자체 ticketing 도구 무관 SEV 표준 적용 |
| 사용성 | IC 단일 책임 분리로 상황 인식 명확 |
| 신뢰성 | error budget burn rate 14.4× → 2시간 안에 page (early detection) |
| 보안 | postmortem에 PII/credential 마스킹 + 외부 공개 시 redaction |
| 유지보수성 | runbook 5분 actionable 기준 → 인지 부하 최소 |
| 이식성 | Google SRE 표준은 회사/스택 무관 |
| 확장성 | sub-incident delegation으로 long-running incident 관리 |

## Gotchas

### IC가 직접 디버깅에 빠짐
PagerDuty 명시 antipattern. 시니어 엔지니어가 IC인데 터미널에서 grep 시작하면 상황 인식 손실 → 다른 팀의 신호 놓침. IC는 화이트보드/문서/지휘에만.

### single-burn-rate alert만 운영
short window 단독 → false positive 폭증 (alert fatigue). long window 단독 → MTTR 길어짐. 1h+5m 단축 + 6h+30m 장기 + 3d+6h 티켓 3-tier 필수 (Google SRE Workbook).

### postmortem에 "휴먼 에러"로 결론
blameless 원칙 위반. "왜 그 사람이 그 결정을 내릴 수밖에 없는 시스템이었는가"로 framing. 명시 안 하면 다음 사고 시 정보 은폐 inducement.

### toil ≠ 모든 manual 작업
보안 감사처럼 manual+tactical만 충족하는 작업은 overhead. 잘못 toil 분류 후 자동화 → ROI 마이너스. 6 특성 모두 충족만 toil.

### IC와 Ops Lead가 동일인
역할 분리 정신 위반. 한 사람이 두 역할 겸하면 기술 작업 시작 = 상황 인식 손실. SEV 2+ 에서는 강제로 분리.

## Source

- https://sre.google/sre-book/managing-incidents/ — Google SRE Book Ch.14: IC "structure the incident response task force"; Ops Lead "the only group modifying the system during an incident"; Comms Lead "the public face of the incident response", 조회 2026-05-10
- https://sre.google/sre-book/postmortem-culture/ — "everyone involved in an incident had good intentions"; "You can't 'fix' people, but you can fix systems and processes"; 6 trigger conditions, 조회 2026-05-10
- https://sre.google/workbook/alerting-on-slos/ — multi-window multi-burn-rate formula, 99.9% SLO recommended params (14.4× / 6× / 1×), 조회 2026-05-10
- https://sre.google/sre-book/eliminating-toil/ — toil 6 characteristics: manual, repetitive, automatable, tactical, no enduring value, scales linearly, 조회 2026-05-10
- https://response.pagerduty.com/before/severity_levels/ — SEV1-5 verbatim 정의, 조회 2026-05-10
- https://response.pagerduty.com/training/incident_commander/ — "Keep the incident moving towards resolution"; "Avoid performing technical actions"; "strong objections" (not consensus), 조회 2026-05-10
