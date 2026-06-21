---
name: finops
description: Cloud cost as a governance surface — budgets, unit cost, anomalies, and commitment coverage made reviewable before they become incidents.
keywords: finops cost 비용 budget 예산 unit-cost 단위원가 anomaly 이상징후 commitment savings-plan reserved-instance RI showback chargeback rightsizing tagging allocation forecast burn-rate cap guardrail blast-radius shared-cost denominator coverage utilization expiry on-demand fallback
intent: 비용분석해 예산설정해 비용추적해 비용리뷰해 finops해 cost최적화해 commitment검토해 anomaly대응해 비용오너십정해 unit-cost계산해 chargeback해
paths: finops/ cost/ billing/ infra/cost/ docs/finops/ .claude/finops/ tag-policy.yaml
patterns: budget-alert anomaly-detector savings-plan reserved-instance commitment-coverage tagging-policy chargeback showback unit-economics burn-rate forecast
requires: monitoring devops sre-operations
phase: plan review deploy
tech-stack: any
min_score: 2
---

# FinOps Governance

비용은 청구 데이터가 아니라 아키텍처와 운영 결정의 출력. 이 스킬은 비용을 **운영 거버넌스**로 다룬다 — 예산/단위원가/이상징후/commitment 4축이 모두 "누가, 언제, 무엇을, 얼마까지" 결정하는지가 명시되어야 한다.

## 의사결정 트리

### IF 새 워크로드/서비스 시작 (Plan)
1. 태그 정책 먼저 정의 — `service`, `env`, `owner`, `cost-center` 4개는 필수
2. 예산 owner 지정 (개인 X, 팀/소유 그룹 O) + 1차/2차 임계값(80%/100%)과 escalation 채널
3. 단위원가(unit cost)의 분모 결정 — 요청 수 / MAU / 주문 수 / 처리 GB 중 하나
4. 공유 비용(shared cost) 배분 정책 명시 — equal split / weighted by usage / pinned to platform team
5. **→ monitoring 스킬: 비용 메트릭을 일반 대시보드와 함께 노출**

### IF 비용 이상징후(anomaly) 감지 (Review)
1. blast radius 먼저 — 어느 서비스/계정/리전에서, 일/주 비용이 평소 대비 몇 % 변동인가
2. 가설 분기 — (a) 정상 트래픽 증가 (b) 누수/유휴 자원 (c) 가격 모델 변경 (d) 잘못된 배포
3. 응답 posture — spending cap 발동? rollback? 통보 후 monitor only?
4. 응답 owner와 24h ETA를 anomaly 티켓에 기록
5. 종결 기준 — 일 비용이 baseline ±N% 안으로 N일 연속 복귀

### IF Commitment(Savings Plan / RI / 약정) 검토 (Plan)
1. coverage target — 정상 트래픽의 60-80% 정도, 100% 약정 금지 (탄력성 손실)
2. utilization 추적 — 약정한 만큼 실제 사용 중인가? 미달은 손실
3. expiry window — 만료 30/60/90일 전 review 일정 사전 등록
4. on-demand fallback posture — 약정 초과 시 어느 가격으로, 누구 승인으로 spillover
5. overcommit 위험 — 워크로드 축소/이전 시 lock-in 손실 시뮬레이션

### IF 비용 회고 / 분기 리뷰 (Review)
- [ ] 단위원가 추세 — 사용자 또는 트래픽 단위당 비용이 줄고 있는가, 늘고 있는가
- [ ] ownerless 비용 — 태그 누락된 자원의 % (목표: <5%)
- [ ] anomaly 응답 latency — 감지~조치까지 시간
- [ ] commitment utilization — 약정 대비 실 사용률(%)
- [ ] 잠자는 자원 — 30일 무사용 인스턴스/볼륨/스냅샷 목록

## Budget · Unit cost · Anomaly · Commitment 4축 체크리스트

```
[Budget]
□ 예산마다 owner(팀)와 escalation 경로 명시 — 개인 단일 owner 금지
□ 임계값 2단계 이상 (80% 경고 / 100% 차단/승인 필요)
□ 예외 윈도우(이벤트/마이그레이션) 사전 정의 + 종료 일자

[Unit Cost]
□ 분모(allocation key) 명시 — 요청·사용자·주문·GB 중 하나
□ shared cost 배분 정책 문서화 — denominator 침묵 금지
□ baseline 추세 추적 — 월별 unit cost가 product KPI와 함께 노출

[Anomaly]
□ blast radius framing 의무 — 서비스/계정/리전 차원의 변동
□ rollback 또는 spending cap posture 사전 정의
□ customer 통보 / 내부 통보 결정 분기

[Commitment]
□ coverage target과 max overcommit 한도 문서화
□ utilization 주간 리뷰 — 미달은 손실로 회계
□ expiry 일정 — 만료 60일 전 자동 알림
□ on-demand fallback이 작동함을 검증 (drill)
```

## 가이드

### Showback vs Chargeback — 운영 차이
- **Showback**: 비용을 "보여주기만" 함. 거버넌스 신호이지만 행동 강제력은 약함.
- **Chargeback**: 팀별 회계 계정에 실제 청구. 행동을 강하게 바꾸지만 정치적 마찰 큼.
- 처음 도입 시: showback → 6개월 후 부분 chargeback (인프라 공통은 본사 부담, 도메인 자원은 팀 부담) 단계적 진행.

### Rightsizing 함정
- 단순 "CPU 평균 < 30% → 다운사이즈" 규칙은 burst 워크로드를 깨뜨림. p95/p99과 함께 봐야 함.
- 메모리는 OOM이 비용보다 비싸다 — 25% 헤드룸 유지.
- DB는 다운사이즈 후 다시 키울 때 다운타임 비용을 계산에 포함.

### 단위원가가 의미를 가지려면
- Product 한 명 / 주문 한 건 같은 **운영적으로 의미 있는 단위**여야 함. CPU 시간당 비용은 거의 무용.
- 단위원가가 **올라가는 것** 자체보다 **갑자기 올라간 시점**과 그 원인이 명확해야 함.

## Gotchas

### 예산 알림 와도 owner가 없어 응답 없음
"이 알림 누구한테 가는지 모르겠다"가 가장 흔한 finops 실패. 예산을 만들 때 반드시 팀 + 2차 escalation까지 지정. 개인 owner는 휴가/이직으로 무력화됨.

### 단위원가가 노이즈 — denominator가 implicit
"요청당 비용"이라고 말하면서 정작 어떤 요청(헬스체크 포함? 실패 포함? 내부 호출 포함?)인지 합의가 없으면 매번 다른 숫자가 나와서 신뢰 잃음. denominator를 코드 레벨로 정의하고 commit.

### Anomaly 알림에 cap이 없어 감지만 하고 출혈 지속
이상징후를 감지만 하고 spending cap이나 rollback posture가 없으면 24h+ 동안 비용이 계속 새어나감. 임계값마다 "감지 시 즉시 차단" / "알림만" 둘 중 하나로 명시.

### Commitment 100% 커버리지 욕심
"할인 최대화"라며 100% 약정하면 워크로드가 줄거나 이전될 때 lock-in 손실 발생. 60-80%만 약정하고 나머지는 on-demand로 flexibility 유지.

### 만료된 RI/Savings Plan 모름
expiry 30일 전 review 일정이 없으면 자동 만료 후 갑자기 on-demand 비용으로 전환되어 다음 청구서에서 폭탄. expiry calendar를 finops dashboard 1면에.

### Tag policy를 enforce 안 함 — ownerless 비용 누적
태그 강제(missing tag → 생성 거부 / 격리 계정으로 회수)가 없으면 6개월 후 30%+가 ownerless. CI/IaC에서 태그 검증 게이트 필수.

### 공유 비용을 한 팀에 몰빵
NAT gateway, observability stack, control plane을 사용량 가장 큰 한 팀에 다 부과하면 "이상한 spike"로 noise. weighted allocation 또는 platform team 부담으로 분리.

### 비용을 incident 후에야 봄
finops를 분기 리포트로 운영하면 incident 발생 후에 손실을 발견. 일일/주간 burn rate 검토 + 대시보드를 monitoring 옆에 같이 두기.

## 도구 사용 패턴 (Harness)
- 태그 정책 검증: `Grep`으로 IaC(`terraform`, `cloudformation`) 파일에서 `tags`/`labels` 누락 검색
- 비용 데이터 분석은 외부 도구 (Cost Explorer, GCP Billing) — Harness에서는 결과 마크다운 리뷰
- `.claude/finops/RULES.md`에 예산 owner와 임계값 캐싱 (release.md 패턴 참고)

## 에러 복구 패턴 (Harness)
- 갑작스런 비용 spike → `Grep`으로 최근 배포/IaC 변경 추적, anomaly window의 deploy log 확인
- 태그 누락 자원 발견 → IaC PR로 일괄 패치, 운영 중 자원은 owner 추적 후 회수
- commitment 미달 → utilization 리포트로 분기, 다음 갱신 시 coverage target 하향

## Related (신규 그래프 cross-ref)

finops가 결합되는 신규 노드:
- `_common/distributed-cache-decisions.md` — Cassandra/EVCache/Redis/DynamoDB cost model (managed RCU/WCU vs self-host infra)
- `infra/k8s-runtime-titus-style.md` — Karpenter spot consolidation, instance type 다양화로 비용 ↓
- `data/kafka-compaction-and-retention.md` — Tiered Storage로 hot tier (disk) 비용 ↓
- `data/iceberg-table-format.md` — `expire_snapshots` + `remove_orphan_files` 정기로 storage 비용 통제
- `_common/load-shedding-prioritized.md` — capacity 비용 vs 성공 트래픽 트레이드오프 (tier 4 drop으로 over-provision 회피)
- `ml/llm-serving-gpu-batching.md` — vLLM / TensorRT-LLM FP8 quantization으로 GPU 비용 ~50% 감소
